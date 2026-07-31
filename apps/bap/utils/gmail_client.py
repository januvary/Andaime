"""Cliente Gmail para criação de rascunhos (drafts) da remessa DRS.

Usa OAuth de aplicativo desktop (client ID do tipo "Desktop app"). Na
primeira execução abre o navegador para consentimento; o token é armazenado
localmente e reutilizado/renovado nas execuções seguintes.

Os anexos são enviados via Google Drive (chip de anexo do Gmail), o que
contorna o limite de ~25 MB da mensagem ``raw``: o PDF é carregado no Drive e
referenciado no rascunho, sem trafegar os bytes pela Gmail API.

Escopos:
- ``gmail.compose``  -> criar rascunhos
- ``gmail.metadata`` -> ler rótulos (labels) da mensagem para detectar envio
- ``gmail.readonly`` -> varredura de mensagens DRS
- ``drive.file``     -> criar/ler apenas os arquivos que o app cria no Drive
"""

from __future__ import annotations

import base64
import glob
import json
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid
from pathlib import Path

from bap.utils.config import bap_data_dir

SCOPES = [
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.metadata",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.file",
]


class GmailError(Exception):
    """Erro de configuração ou comunicação com o Gmail."""


class GmailAuthRequired(GmailError):
    """O token atual não tem escopos suficientes (ex.: falta ``drive.file``).

    Deve ser tratado como "token ausente": apagar o ``gmail_token.json`` e
    disparar novamente o fluxo de consentimento interativo.
    """


@dataclass
class DraftResult:
    draft_id: str
    message_id: str
    rfc822_msgid: str


def resolve_credentials_path(configured: str = "") -> Path | None:
    """Resolve o caminho do ``credentials.json``.

    Ordem: caminho configurado -> ``data/credentials.json`` ->
    primeiro ``data/client_secret_*.json`` encontrado.
    """
    if configured:
        p = Path(configured)
        return p if p.exists() else None

    data_dir = bap_data_dir()
    default = data_dir / "credentials.json"
    if default.exists():
        return default

    matches = sorted(glob.glob(str(data_dir / "client_secret_*.json")))
    return Path(matches[0]) if matches else None


def resolve_token_path(configured: str = "") -> Path:
    if configured:
        return Path(configured)
    return bap_data_dir() / "gmail_token.json"


def get_service(credentials_path: str = "", token_path: str = ""):
    """Retorna o serviço Gmail a partir do token local (não-interativo).

    Usa o token existente, renovando-o se possível. Levanta ``GmailError`` se
    as credenciais não estiverem disponíveis ou o consentimento for necessário
    (neste caso, o chamador deve iniciar o fluxo interativo via
    :func:`start_auth_flow`).
    """
    # Imports adiados: a dependência só é exigida quando o envio é usado.
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as e:  # pragma: no cover
        raise GmailError(
            "Bibliotecas do Google não instaladas (google-api-python-client, "
            "google-auth-oauthlib)."
        ) from e

    cred_path = resolve_credentials_path(credentials_path)
    if cred_path is None:
        raise GmailError(
            "credentials.json não encontrado. Baixe o OAuth client ID "
            "(Desktop app) e salve em data/credentials.json."
        )

    tok_path = resolve_token_path(token_path)
    creds = None
    if tok_path.exists():
        creds = Credentials.from_authorized_user_file(str(tok_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        if not creds:
            tok_path.unlink(missing_ok=True)
            raise GmailError("Autenticação do Gmail necessária.")
        tok_path.parent.mkdir(parents=True, exist_ok=True)
        tok_path.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def service_from_credentials(creds):
    """Constrói o serviço Gmail a partir de credenciais já obtidas."""
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def drive_service_from_credentials(creds):
    """Constrói o serviço Google Drive a partir de credenciais já obtidas."""
    from googleapiclient.discovery import build

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _get_http_error():
    """``HttpError`` do googleapiclient (ou ``Exception`` se a lib faltar)."""
    try:
        from googleapiclient.errors import HttpError
        return HttpError
    except ImportError:  # pragma: no cover
        return Exception


# Cache de ids de pastas do Drive por credencial, para não refazer a
# árvore ``REMESSAS/...`` a cada upload. Chave: id do token (ou objeto creds).
_FOLDER_CACHE: dict = {}


def _ensure_drive_folder(creds, relpath: str) -> str:
    """Garante a árvore de pastas ``relpath`` (POSIX, ex.: ``REMESSAS/2026/07-17/RENOVAÇÕES``)
    no Drive e retorna o ``fileId`` da pasta final.

    Cria as pastas conforme necessário (uma por segmento de caminho) e compartilha
    cada uma com o dono do token implicitamente (já é dono ao criar). Usa cache por
    ``creds`` para evitar repetir a resolução em múltiplos anexos do mesmo envio.
    """
    service = drive_service_from_credentials(creds)
    cache_key = getattr(creds, "token", None) or id(creds)
    cache = _FOLDER_CACHE.setdefault(cache_key, {})
    if relpath in cache:
        return cache[relpath]

    parent_id = "root"
    current = ""
    HttpError = _get_http_error()

    try:
        for seg in relpath.split("/"):
            if not seg:
                continue
            current = f"{current}/{seg}" if current else seg
            if current in cache:
                parent_id = cache[current]
                continue
            body = {
                "name": seg,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [parent_id],
            }
            try:
                folder = (
                    service.files().create(body=body, fields="id").execute()
                )
                folder_id = folder.get("id", "")
            except HttpError as he:
                # 409 = já existe sob esse parent: resolve o id por nome.
                if getattr(he, "status_code", None) == 409:
                    q = (
                        f"name = {json.dumps(seg)} and "
                        f"'{parent_id}' in parents"
                    )
                    resp = (
                        service.files()
                        .list(q=q, fields="files(id)", pageSize=1)
                        .execute()
                    )
                    files = resp.get("files") or []
                    folder_id = files[0].get("id", "") if files else ""
                else:
                    raise
            cache[current] = folder_id
            parent_id = folder_id
    except Exception as e:  # pragma: no cover - rede
        raise GmailError(
            f"Falha ao criar pasta no Drive ({relpath}): {_http_error_message(e)}"
        ) from e
    return parent_id


def _http_error_message(exc: Exception) -> str:
    """Extrai uma mensagem legível de um ``HttpError`` do Google.

    O ``str()`` padrão do ``HttpError`` despeja a URL, o corpo e o dict de
    ``Details`` inteiro numa única string ilegível. Aqui extraímos apenas a
    mensagem humana (campo ``message`` do JSON de erro, ou ``_get_reason``).
    """
    HttpError = _get_http_error()
    try:
        if isinstance(exc, HttpError):
            body = getattr(exc, "content", None)
            if isinstance(body, (bytes, bytearray)):
                body = body.decode("utf-8", "replace")
            if body:
                try:
                    data = json.loads(body)
                    msg = data.get("error", {}).get("message")
                    if msg:
                        return msg
                except (ValueError, AttributeError):
                    pass
            reason = exc._get_reason()
            if reason:
                return reason
    except Exception:
        pass
    return str(exc)


def _is_scope_error(exc: Exception) -> bool:
    """Detecta erro de escopo/permissão insuficiente do Google (403).

    O motivo real retornado pela API do Drive é ``insufficientPermissions``
    (não ``insufficientScopes``, que é do endpoint de autorização). Cobrimos
    ambos, além de ``invalid_scope`` e ``authError``.
    """
    HttpError = _get_http_error()
    try:
        if isinstance(exc, HttpError):
            content = getattr(exc, "content", None)
            if isinstance(content, (bytes, bytearray)):
                content = content.decode("utf-8", "replace")
            body = (content or "").lower()
            markers = (
                "insufficientpermissions",
                "insufficientscopes",
                "invalid_scope",
                "autherror",
                "required scopes",
            )
            if exc.status_code == 403 and any(m in body for m in markers):
                return True
    except Exception:
        pass
    return False


def _raise_if_scope_error(exc: Exception) -> None:
    if _is_scope_error(exc):
        raise GmailAuthRequired(
            "O acesso ao Drive não foi autorizado (escopo drive.file "
            "ausente). Será necessário autorizar novamente."
        ) from exc


def upload_drive_file(
    creds, path: str, name: str, parent_id: str | None = None
) -> tuple[str, str]:
    """Faz upload de ``path`` para o Google Drive (escopo ``drive.file``).

    Retorna ``(file_id, web_view_link)``. O ``web_view_link`` é o link
    compartilhável usado para montar o "chip" do anexo no corpo do e-mail.
    Se ``parent_id`` for informado, o arquivo é criado dentro dessa pasta.
    O app só pode ver/gerenciar os arquivos que ele mesmo cria (escopo mínimo).
    """
    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError as e:  # pragma: no cover
        raise GmailError("Bibliotecas do Google não instaladas.") from e

    service = drive_service_from_credentials(creds)
    file_metadata = {"name": name, "mimeType": "application/pdf"}
    if parent_id:
        file_metadata["parents"] = [parent_id]
    media = MediaFileUpload(path, mimetype="application/pdf", resumable=True)
    try:
        file = (
            service.files()
            .create(
                body=file_metadata,
                media_body=media,
                fields="id,webViewLink",
            )
            .execute()
        )
    except Exception as e:  # pragma: no cover - rede
        _raise_if_scope_error(e)
        msg = _http_error_message(e)
        if "accessNotConfigured" in msg or "has not been used" in msg:
            raise GmailError(
                "A Google Drive API não está habilitada neste projeto. "
                "Habilite-a em https://console.developers.google.com/apis/api/"
                "drive.googleapis.com/overview e tente novamente."
            ) from e
        raise GmailError(f"Falha ao enviar arquivo ao Drive: {msg}") from e
    file_id = file.get("id", "")
    web_link = file.get("webViewLink") or (
        f"https://drive.google.com/file/d/{file_id}/view?usp=drive_web"
    )
    return file_id, web_link


def share_drive_file_with(creds, file_id: str, email: str) -> None:
    """Concede acesso de leitura (reader) ao ``email`` para o arquivo do Drive."""
    service = drive_service_from_credentials(creds)
    permission = {"type": "user", "role": "reader", "emailAddress": email}
    try:
        service.permissions().create(
            fileId=file_id,
            body=permission,
            fields="id",
            sendNotificationEmail=False,
        ).execute()
    except Exception as e:  # pragma: no cover - rede
        _raise_if_scope_error(e)
        raise GmailError(
            f"Falha ao compartilhar arquivo no Drive: {_http_error_message(e)}"
        ) from e


_AUTH_SUCCESS_MESSAGE = (
    "Autorização concluída. Você já pode fechar esta aba e voltar ao BAP."
)


class AuthFlowHandle:
    """Fluxo OAuth em andamento.

    ``auth_url`` deve ser exibido ao usuário. ``wait()`` bloqueia aguardando o
    redirecionamento do navegador para o servidor local e, portanto, deve ser
    executado *fora* da thread da interface gráfica.
    """

    def __init__(self, flow, local_server, wsgi_app, auth_url: str, token_path: Path):
        self.flow = flow
        self._server = local_server
        self._wsgi = wsgi_app
        self.auth_url = auth_url
        self._token_path = token_path

    def wait(self, timeout_seconds: int | None = 300):
        """Aguarda o consentimento, troca o código pelo token e o persiste."""
        self._server.timeout = timeout_seconds
        try:
            self._server.handle_request()
            last_uri = getattr(self._wsgi, "last_request_uri", None)
            if not last_uri:
                raise GmailError(
                    "Tempo esgotado aguardando a autorização do Gmail."
                )
            authorization_response = last_uri.replace("http", "https")
            self.flow.fetch_token(authorization_response=authorization_response)
        except GmailError:
            raise
        except Exception as e:  # pragma: no cover - rede/entrada do usuário
            raise GmailError(f"Falha na autorização do Gmail: {e}") from e
        finally:
            try:
                self._server.server_close()
            except Exception:  # pragma: no cover - defensivo
                pass

        creds = self.flow.credentials
        self._token_path.parent.mkdir(parents=True, exist_ok=True)
        self._token_path.write_text(creds.to_json())
        return creds

    def cancel(self) -> None:
        """Encerra o servidor local (aborta ``wait()`` se estiver bloqueado)."""
        try:
            self._server.server_close()
        except Exception:  # pragma: no cover - defensivo
            pass


def start_auth_flow(credentials_path: str = "", token_path: str = "") -> AuthFlowHandle:
    """Inicia o fluxo OAuth de servidor local **sem** abrir o navegador.

    Retorna um :class:`AuthFlowHandle` com a URL de autorização a ser exibida.
    Diferente de ``flow.run_local_server``, isto não bloqueia nem tenta abrir
    o navegador automaticamente — evitando o congelamento da GUI e falhas de
    sandbox do navegador. Chame ``handle.wait()`` numa thread separada.
    """
    try:
        import wsgiref.simple_server

        from google_auth_oauthlib.flow import (  # type: ignore
            InstalledAppFlow,
            _RedirectWSGIApp,
            _WSGIRequestHandler,
        )
    except ImportError as e:  # pragma: no cover
        raise GmailError(
            "Bibliotecas do Google não instaladas (google-auth-oauthlib)."
        ) from e

    cred_path = resolve_credentials_path(credentials_path)
    if cred_path is None:
        raise GmailError(
            "credentials.json não encontrado. Baixe o OAuth client ID "
            "(Desktop app) e salve em data/credentials.json."
        )
    tok_path = resolve_token_path(token_path)

    flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), SCOPES)
    wsgi_app = _RedirectWSGIApp(_AUTH_SUCCESS_MESSAGE)
    wsgiref.simple_server.WSGIServer.allow_reuse_address = False
    try:
        local_server = wsgiref.simple_server.make_server(
            "localhost", 0, wsgi_app, handler_class=_WSGIRequestHandler
        )
    except OSError as e:  # pragma: no cover - porta ocupada
        raise GmailError(
            f"Não foi possível iniciar o servidor local de OAuth: {e}"
        ) from e

    flow.redirect_uri = f"http://localhost:{local_server.server_port}/"
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    return AuthFlowHandle(flow, local_server, wsgi_app, auth_url, tok_path)


def _drive_chip_html(name: str, link: str) -> str:
    """Monta o "chip" de anexo do Drive no mesmo formato que o Gmail usa.

    O chip é um ``<div class="gmail_chip gmail_drive_chip">`` com um link para
    o arquivo no Drive. É assim que o Gmail reconhece e renderiza anexos do
    Drive (não é um anexo MIME comum, nem o ``drive-api-payload.json``).
    """
    safe_name = (
        name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    safe_link = link.replace("&", "&amp;").replace('"', "&quot;")
    return (
        '<div dir="ltr">'
        '<div contenteditable="false" class="gmail_chip gmail_drive_chip" '
        'style="width:386px;height:20px;max-height:20px;background-color:'
        'rgb(245,245,245);margin:6px 0px;padding:10px;color:rgb(34,34,34);'
        'font:14px/20px &quot;Google Sans&quot;,sans-serif;border:1px solid '
        'rgb(221,221,221)">'
        f'<a href="{safe_link}" target="_blank" style="color:#202124;display:'
        'inline-block;max-width:356px;overflow:hidden;text-overflow:ellipsis;'
        'white-space:nowrap;text-decoration:none;border:none" '
        f'aria-label="{safe_name}">'
        '<img style="vertical-align:text-bottom;border:none;padding-right:10px;'
        'height:20px;" alt="" src="https://ssl.gstatic.com/docs/doclist/images/'
        'icon_10_generic_list.png">&nbsp;'
        f'<span dir="ltr" style="vertical-align:bottom;text-decoration:none">'
        f"{safe_name}</span></a></div></div>"
    )


def _build_mime(
    to: str,
    subject: str,
    html_body: str,
    drive_attachments: list[tuple[str, str]],
    sender: str = "",
) -> tuple[str, str]:
    """Monta a mensagem MIME e retorna ``(raw_base64url, rfc822_msgid)``.

    Os anexos do Drive são incorporados ao corpo como "chips" (mesmo formato
    que o Gmail produz ao anexar um arquivo do Drive pela interface), e não
    como partes MIME ``application/json`` (que o Gmail não reconhece).
    """
    message = MIMEMultipart("alternative")
    message["To"] = to
    message["Subject"] = subject
    if sender:
        message["From"] = sender
    rfc822_msgid = make_msgid()
    message["Message-ID"] = rfc822_msgid

    chips_html = "".join(
        _drive_chip_html(name, link) for name, link in drive_attachments
    )
    full_html = html_body
    if chips_html:
        full_html = f"{html_body}<br>{chips_html}"

    text_lines = [html_body]
    for name, link in drive_attachments:
        text_lines.append(f"{name}\n{link}")
    text_body = "\n\n".join(text_lines)

    message.attach(MIMEText(text_body, "plain", "utf-8"))
    message.attach(MIMEText(full_html, "html", "utf-8"))

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return raw, rfc822_msgid



def create_draft(
    service,
    to: str,
    subject: str,
    html_body: str,
    attachments: list[tuple[str, str]],
    sender: str = "",
    creds=None,
    drive_folder: str = "",
) -> DraftResult:
    """Cria um rascunho no Gmail e retorna seus identificadores.

    Os anexos são enviados via Google Drive: cada ``(path, name)`` em
    ``attachments`` é carregado no Drive (escopo ``drive.file``), compartilhado
    com o destinatário (``to``) e referenciado no rascunho como um chip de
    anexo do Drive. O rascunho em si permanece pequeno, independentemente do
    tamanho dos PDFs.

    ``creds`` (credenciais OAuth já obtidas) é necessário para o upload/share.
    ``drive_folder`` é o caminho relativo (estilo POSIX, ex.:
    ``REMESSAS/2026/07-17/RENOVAÇÕES``) onde os arquivos são armazenados no
    Drive, espelhando a estrutura de pastas local.
    """
    if creds is None:
        raise GmailError(
            "Credenciais OAuth necessárias para anexar arquivos via Drive."
        )

    parent_id = None
    if drive_folder:
        parent_id = _ensure_drive_folder(creds, drive_folder)

    drive_attachments: list[tuple[str, str]] = []
    for path, name in attachments:
        file_id, web_link = upload_drive_file(creds, path, name, parent_id)
        share_drive_file_with(creds, file_id, to)
        drive_attachments.append((name, web_link))

    raw, rfc822_msgid = _build_mime(
        to, subject, html_body, drive_attachments, sender
    )
    try:
        draft = (
            service.users()
            .drafts()
            .create(userId="me", body={"message": {"raw": raw}})
            .execute()
        )
    except Exception as e:  # pragma: no cover - rede
        raise GmailError(f"Falha ao criar rascunho no Gmail: {e}") from e

    message = draft.get("message", {})
    return DraftResult(
        draft_id=draft.get("id", ""),
        message_id=message.get("id", ""),
        rfc822_msgid=rfc822_msgid,
    )


def get_draft_message_labels(service, draft_id: str) -> list[str] | None:
    """Retorna os rótulos da mensagem associada ao rascunho.

    Usa o ``draft_id`` (estável) para resolver o ``message_id`` atual —
    quando um rascunho é enviado pelo Gmail, o ``message_id`` original muda,
    mas o ``draft_id`` permanece e passa a apontar para a nova mensagem.

    Retorna ``None`` se o rascunho não existe mais (descartado/removido).
    """
    HttpError = _get_http_error()

    try:
        draft = (
            service.users().drafts().get(userId="me", id=draft_id).execute()
        )
    except HttpError as e:
        if getattr(e, "status_code", None) == 404:
            return None
        raise GmailError(f"Falha ao consultar rascunho no Gmail: {e}") from e

    message_id = draft.get("message", {}).get("id", "")
    if not message_id:
        return []

    try:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="metadata")
            .execute()
        )
    except HttpError as e:
        if getattr(e, "status_code", None) == 404:
            return None
        raise GmailError(f"Falha ao consultar mensagem no Gmail: {e}") from e
    return msg.get("labelIds", [])


def draft_web_url(message_id: str, account_index: int = 0) -> str:
    """URL para abrir o rascunho no Gmail (web) em modo de composição."""
    return (
        f"https://mail.google.com/mail/u/{account_index}/#drafts"
        f"?compose={message_id}"
    )
