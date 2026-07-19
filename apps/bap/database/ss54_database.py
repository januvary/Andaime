import hashlib
import sqlite3
import json
from pathlib import Path
from typing import Optional
from datetime import datetime

from andaime.database import BaseDatabase, db_op
from andaime.error_handler import ErrorHandler, ErrorContext, ErrorLevel
from bap.utils.config import bap_data_dir
from andaime.text import to_upper_normalized
from bap.utils.text_utils import (
    generate_initials,
    generate_protocolo,
    normalize_phone,
    _digits,
)
from bap.models import Paciente, Lote, Processo, Arquivo
from bap.constants import Status

_MISSING = object()


class SS54Database(BaseDatabase):

    # Alias do banco anexado que armazena os BLOBs dos arquivos.
    ARQUIVOS_DB_ALIAS = "arqdb"

    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path is None:
            db_path = str(bap_data_dir() / "ss54.db")
        # Banco separado (anexado) para os conteúdos dos arquivos, mantendo o
        # banco principal pequeno e barato de copiar/backupear. Apenas o banco
        # principal é copiado nos backups; os BLOBs (grandes) ficam de fora.
        self._arquivos_db_path = self._compute_arquivos_db_path(db_path)
        super().__init__(db_path=db_path, entity_name="ss54")
        self._backup_retention = 2

    @staticmethod
    def _compute_arquivos_db_path(db_path: str) -> str:
        if db_path == ":memory:":
            return ":memory:"
        return str(Path(db_path).with_name("ss54_arquivos.db"))

    def _resolve_default_db_path(self) -> str:
        return str(bap_data_dir() / "ss54.db")

    def _apply_pragmas(self, cur: sqlite3.Cursor) -> None:
        super()._apply_pragmas(cur)
        # Anexa o banco de conteúdos a esta conexão (reexecutado a cada
        # (re)conexão, pois o ATTACH é por conexão).
        cur.execute(
            f"ATTACH DATABASE ? AS {self.ARQUIVOS_DB_ALIAS}",
            (self._arquivos_db_path,),
        )

    def _create_schema(self) -> None:
        try:
            with self._cursor() as cur:
                cur.executescript("""
                    CREATE TABLE IF NOT EXISTS pacientes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        nome TEXT NOT NULL UNIQUE,
                        telefone TEXT DEFAULT '',
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS lotes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        date TEXT NOT NULL UNIQUE,
                        sent_at TEXT
                    );

                    CREATE TABLE IF NOT EXISTS processos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        protocolo TEXT UNIQUE,
                        paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
                        lote_id INTEGER NOT NULL REFERENCES lotes(id),
                        tipo TEXT NOT NULL CHECK(tipo IN ('medicamento', 'nutricao', 'bomba')),
                        solicitacao TEXT NOT NULL CHECK(solicitacao IN ('primeira', 'renovacao')),
                        descricao TEXT DEFAULT '',
                        protocolo_drs TEXT DEFAULT '',
                        status TEXT DEFAULT 'em_analise'
                            CHECK(status IS NULL OR status IN ('preparando', 'em_analise', 'incompleto', 'completo', 'enviado', 'correcao', 'autorizado', 'expirado', 'negado', 'encerrado')),
                        observacoes TEXT DEFAULT '',
                        pdf_sig TEXT,
                        created_at TEXT NOT NULL,
                        sent_at TEXT,
                        result_at TEXT
                    );

                    CREATE TABLE IF NOT EXISTS arquivos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        processo_id INTEGER NOT NULL REFERENCES processos(id) ON DELETE CASCADE,
                        tipo_documento TEXT NOT NULL
                            CHECK(tipo_documento IN ('formulario', 'declaracao', 'receita', 'relatorio', 'exame', 'documento_pessoal', 'outro')),
                        arquivo_original TEXT DEFAULT '',
                        caminho TEXT,
                        ordem INTEGER NOT NULL DEFAULT 0,
                        validado INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS status_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        processo_id INTEGER NOT NULL REFERENCES processos(id) ON DELETE CASCADE,
                        old_status TEXT DEFAULT '',
                        new_status TEXT NOT NULL,
                        observacoes TEXT DEFAULT '',
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS pending_sends (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        lote_id INTEGER NOT NULL REFERENCES lotes(id) ON DELETE CASCADE,
                        grupo TEXT NOT NULL CHECK(grupo IN ('renovacao', 'primeira')),
                        draft_id TEXT,
                        message_id TEXT,
                        rfc822_msgid TEXT,
                        processo_ids TEXT NOT NULL DEFAULT '[]',
                        to_email TEXT DEFAULT '',
                        subject TEXT DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'pending'
                            CHECK(status IN ('pending', 'sent', 'discarded')),
                        created_at TEXT NOT NULL,
                        resolved_at TEXT
                    );

                    CREATE TABLE IF NOT EXISTS drs_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
                        message_id TEXT NOT NULL,
                        thread_id TEXT DEFAULT '',
                        from_email TEXT DEFAULT '',
                        subject TEXT DEFAULT '',
                        snippet TEXT DEFAULT '',
                        body TEXT DEFAULT '',
                        message_date TEXT,
                        inferred_status TEXT,
                        seen INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_pacientes_nome ON pacientes(nome COLLATE NOCASE);
                    CREATE INDEX IF NOT EXISTS idx_lotes_date ON lotes(date);
                    CREATE INDEX IF NOT EXISTS idx_processos_paciente ON processos(paciente_id);
                    CREATE INDEX IF NOT EXISTS idx_processos_lote ON processos(lote_id);
                    CREATE INDEX IF NOT EXISTS idx_processos_status ON processos(status);
                    CREATE INDEX IF NOT EXISTS idx_processos_tipo ON processos(tipo);
                    CREATE INDEX IF NOT EXISTS idx_processos_protocolo ON processos(protocolo);
                    CREATE INDEX IF NOT EXISTS idx_arquivos_processo ON arquivos(processo_id);
                    CREATE INDEX IF NOT EXISTS idx_arquivos_ordem ON arquivos(processo_id, ordem);
                    CREATE INDEX IF NOT EXISTS idx_status_logs_processo ON status_logs(processo_id, created_at);
                    CREATE INDEX IF NOT EXISTS idx_pending_sends_status ON pending_sends(status);
                    CREATE INDEX IF NOT EXISTS idx_lotes_sent_at ON lotes(sent_at, date);
                    CREATE INDEX IF NOT EXISTS idx_pending_sends_status_created ON pending_sends(status, created_at);
                    CREATE INDEX IF NOT EXISTS idx_processos_lote_status ON processos(lote_id, status);
                    CREATE INDEX IF NOT EXISTS idx_drs_messages_paciente ON drs_messages(paciente_id);
                    CREATE INDEX IF NOT EXISTS idx_drs_messages_seen ON drs_messages(seen);
                    CREATE INDEX IF NOT EXISTS idx_drs_messages_date ON drs_messages(message_date);
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_drs_messages_paciente_msg
                        ON drs_messages(paciente_id, message_id);
                    """)
                # Conteúdos (BLOBs) vivem no banco anexado ``ss54_arquivos.db``.
                # Sem FK entre bancos (SQLite não suporta); a integridade é
                # mantida na aplicação (ver ``delete_arquivo``/``delete_processo``).
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.ARQUIVOS_DB_ALIAS}.arquivo_conteudos (
                        arquivo_id INTEGER PRIMARY KEY,
                        conteudo BLOB NOT NULL
                    )
                    """
                )
                self._commit()
                self._run_migrations()
        except Exception as e:
            ErrorHandler.handle_database_error(e, operation="criar schema do banco SS54")
            raise

    def _run_migrations(self) -> None:
        """Migrações leves para bancos já existentes (idempotentes)."""
        try:
            with self._cursor() as cur:
                cols = {r["name"] for r in cur.execute("PRAGMA table_info(processos)")}
                if "pdf_sig" not in cols:
                    cur.execute("ALTER TABLE processos ADD COLUMN pdf_sig TEXT")

                arq_cols = {r["name"] for r in cur.execute("PRAGMA table_info(arquivos)")}
                if "content_sha256" not in arq_cols:
                    cur.execute("ALTER TABLE arquivos ADD COLUMN content_sha256 TEXT")
            self._commit()
            self._backfill_content_sha256()
        except Exception as e:
            ErrorHandler.handle_database_error(e, operation="migrar schema do banco SS54")
            raise

    def _backfill_content_sha256(self) -> None:
        """Calcula o ``content_sha256`` de arquivos pré-migração (uma única vez).

        Lê cada BLOB individualmente (pico de memória de um BLOB, não todos)
        para popular a coluna. Depois disso a assinatura do processo deriva
        só de metadados — sem ler BLOBs na decisão de regenerar o PDF.
        Idempotente: só processa linhas com ``content_sha256 IS NULL``.
        """
        with self._cursor() as cur:
            unhashed = [
                r["id"]
                for r in cur.execute(
                    "SELECT id FROM arquivos WHERE content_sha256 IS NULL"
                )
            ]
        for aid in unhashed:
            blob = self.get_arquivo_conteudo(aid)
            digest = hashlib.sha256(blob).hexdigest() if blob is not None else ""
            self._update_row("arquivos", aid, content_sha256=digest)

    def _log_initialization_success(self) -> None:
        try:
            pacientes_count = self._fetch_count("pacientes")
            lotes_count = self._fetch_count("lotes")
            processos_count = self._fetch_count("processos")

            ErrorHandler.log(
                f"SS54Database inicializado: {pacientes_count} pacientes, "
                f"{lotes_count} lotes, {processos_count} processos",
                level=ErrorLevel.INFO,
                context=ErrorContext.DATABASE,
            )
        except Exception:
            super()._log_initialization_success()

    # ========== PACIENTE ==========

    @db_op("write")
    def create_paciente(self, nome: str, telefone: str = "") -> Paciente:
        normalized = to_upper_normalized(nome.strip())
        telefone = normalize_phone(telefone)
        now = datetime.now().isoformat()
        last_id = self._insert_row(
            "pacientes",
            nome=normalized,
            telefone=telefone,
            created_at=now,
        )
        return Paciente(id=last_id, nome=normalized, telefone=telefone, created_at=now)

    @db_op("read")
    def get_paciente_by_id(self, paciente_id: int) -> Optional[Paciente]:
        row = self._fetch_by_id("pacientes", paciente_id)
        return Paciente.from_row(row) if row else None

    @db_op("read")
    def find_paciente_by_name(self, nome: str) -> Optional[Paciente]:
        row = self._fetch_one(
            "SELECT * FROM pacientes WHERE nome = ? LIMIT 1",
            (to_upper_normalized(nome),),
        )
        return Paciente.from_row(row) if row else None

    @db_op("read")
    def get_all_pacientes(self) -> list[Paciente]:
        rows = self._fetch_all_table("pacientes", order_by="nome COLLATE NOCASE")
        return [Paciente.from_row(r) for r in rows]

    @db_op("read")
    def get_distinct_descricoes(self) -> list[str]:
        """Descrições não-vazias já utilizadas, das mais recentes às mais antigas.

        Usado para alimentar o autocomplete do campo de descrição do cabeçalho.
        """
        rows = self._fetch_all(
            "SELECT descricao FROM processos "
            "WHERE descricao IS NOT NULL AND TRIM(descricao) != '' "
            "GROUP BY descricao ORDER BY MAX(created_at) DESC, MAX(id) DESC"
        )
        return [r["descricao"] for r in rows]

    @db_op("write")
    def update_paciente(self, paciente_id: int, nome: str = None, telefone: str = None) -> bool:
        updates = {}
        if nome is not None:
            updates["nome"] = to_upper_normalized(nome.strip())
        if telefone is not None:
            updates["telefone"] = normalize_phone(telefone)
        if not updates:
            return False
        return self._update_row("pacientes", paciente_id, **updates)

    # ========== LOTE ==========

    @db_op("write")
    def create_lote(self, date: str, sent_at: Optional[str] = None) -> Lote:
        last_id = self._insert_row("lotes", date=date, sent_at=sent_at)
        return Lote(id=last_id, date=date, sent_at=sent_at)

    @db_op("write")
    def move_incompletos_to_lote(self, lote_id: int) -> int:
        """Move processos ``incompleto`` ou ``em_analise`` para a remessa informada.

        Reassocia cada processo (com regeneração de protocolo) e retorna
        o número de processos movidos.
        """
        rows = self._fetch_all(
            "SELECT id FROM processos "
            "WHERE status IN (?, ?) AND lote_id != ?",
            (Status.INCOMPLETO, Status.EM_ANALISE, lote_id),
        )
        count = 0
        for row in rows:
            if self.reassign_processo_lote(row["id"], lote_id) is not None:
                count += 1
        return count

    @db_op("read")
    def get_lote_by_id(self, lote_id: int) -> Optional[Lote]:
        row = self._fetch_by_id("lotes", lote_id)
        return Lote.from_row(row) if row else None

    @db_op("read")
    def get_active_lote(self) -> Optional[Lote]:
        row = self._fetch_one(
            "SELECT * FROM lotes WHERE sent_at IS NULL ORDER BY date ASC LIMIT 1"
        )
        return Lote.from_row(row) if row else None

    @db_op("read")
    def get_all_lotes(self) -> list[Lote]:
        rows = self._fetch_all_table("lotes", order_by="date DESC")
        return [Lote.from_row(r) for r in rows]

    @db_op("write")
    def mark_lote_sent(self, lote_id: int) -> bool:
        """Marca a remessa como enviada (define ``sent_at`` se ainda nulo)."""
        with self._cursor() as cur:
            cur.execute(
                "UPDATE lotes SET sent_at = COALESCE(sent_at, ?) WHERE id = ?",
                (datetime.now().isoformat(), lote_id),
            )
            self._commit()
            return cur.rowcount > 0

    @db_op("write")
    def update_lote_date(self, lote_id: int, date: str) -> bool:
        return self._update_row("lotes", lote_id, date=date)

    # ========== PROCESSO ==========

    @db_op("write")
    def create_processo(
        self,
        paciente_id: int,
        lote_id: int,
        tipo: str,
        solicitacao: str,
        descricao: str = "",
        observacoes: str = "",
        status: str | None = _MISSING,
        created_at: str | None = None,
        log_created_at: str | None = None,
    ) -> Processo:
        lote = self.get_lote_by_id(lote_id)
        paciente = self.get_paciente_by_id(paciente_id)
        if not lote or not paciente:
            raise ValueError("Lote or Paciente not found")

        initials = generate_initials(paciente.nome)
        seq = self._get_next_seq(lote_id, initials)

        protocolo = generate_protocolo(lote.date, initials, seq)

        status_val = Status.EM_ANALISE if status is _MISSING else status
        now = created_at or datetime.now().isoformat()
        last_id = self._insert_row(
            "processos",
            protocolo=protocolo,
            paciente_id=paciente_id,
            lote_id=lote_id,
            tipo=tipo,
            solicitacao=solicitacao,
            descricao=descricao.strip(),
            observacoes=observacoes.strip(),
            status=status_val,
            created_at=now,
        )
        log_ts = now if log_created_at is None else log_created_at
        self._execute_write(
            "INSERT INTO status_logs (processo_id, old_status, new_status, observacoes, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (last_id, "", status_val or "", observacoes.strip(), log_ts),
        )
        return Processo(
            id=last_id,
            protocolo=protocolo,
            paciente_id=paciente_id,
            lote_id=lote_id,
            tipo=tipo,
            solicitacao=solicitacao,
            descricao=descricao.strip(),
            observacoes=observacoes.strip(),
            status=status_val,
            created_at=now,
            paciente_nome=paciente.nome,
            paciente_telefone=paciente.telefone,
            lote_date=lote.date,
        )

    @db_op("read")
    def _get_next_seq(self, lote_id: int, initials: str) -> int:
        lote = self.get_lote_by_id(lote_id)
        if lote is None:
            return 1
        prefix = f"{lote.date}-{initials}-"
        row = self._fetch_one(
            "SELECT MAX(CAST(substr(protocolo, "
            "length(rtrim(protocolo, '0123456789')) + 1) AS INTEGER)) AS max_seq "
            "FROM processos WHERE lote_id = ? AND protocolo LIKE ?",
            (lote_id, f"{prefix}%"),
        )
        max_seq = row["max_seq"] if row and row["max_seq"] is not None else 0
        return max_seq + 1

    def _fetch_processos_joined(
        self, where: str = "", params: tuple = (), order_by: str = ""
    ) -> list[dict]:
        sql = (
            "SELECT p.*, pac.nome as paciente_nome, pac.telefone as paciente_telefone, l.date as lote_date, "
            "sl.observacoes AS last_obs, sl.created_at AS last_obs_at "
            "FROM processos p "
            "JOIN pacientes pac ON p.paciente_id = pac.id "
            "JOIN lotes l ON p.lote_id = l.id "
            "LEFT JOIN status_logs sl ON sl.id = "
            "(SELECT id FROM status_logs WHERE processo_id = p.id ORDER BY created_at DESC LIMIT 1)"
        )
        if where:
            sql += f" WHERE {where}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        return self._fetch_all(sql, params)

    @db_op("read")
    def get_processo_by_id(self, processo_id: int) -> Optional[Processo]:
        rows = self._fetch_processos_joined("p.id = ?", (processo_id,))
        row = rows[0] if rows else None
        return Processo.from_row(row) if row else None

    @db_op("read")
    def get_processos_by_context(
        self, paciente_id: int, lote_id: int, tipo: str, solicitacao: str
    ) -> list[Processo]:
        rows = self._fetch_all(
            "SELECT * FROM processos "
            "WHERE paciente_id = ? AND lote_id = ? "
            "AND tipo = ? AND solicitacao = ? "
            "ORDER BY id ASC",
            (paciente_id, lote_id, tipo, solicitacao),
        )
        return [Processo.from_row(r) for r in rows]

    @db_op("read")
    def count_processos_by_lote(self) -> dict[int, int]:
        rows = self._fetch_all(
            "SELECT lote_id, COUNT(*) AS cnt FROM processos "
            "WHERE status NOT IN ('em_analise', 'incompleto') "
            "GROUP BY lote_id"
        )
        return {r["lote_id"]: r["cnt"] for r in rows}

    @db_op("read")
    def get_processos_by_lote(self, lote_id: int) -> list[Processo]:
        rows = self._fetch_processos_joined(
            "p.lote_id = ?", (lote_id,), "pac.nome COLLATE NOCASE"
        )
        return [Processo.from_row(r) for r in rows]

    @db_op("read")
    def get_status_logs(self, processo_id: int) -> list[dict]:
        return self._fetch_all(
            "SELECT id, old_status, new_status, observacoes, created_at "
            "FROM status_logs WHERE processo_id = ? "
            "ORDER BY created_at DESC",
            (processo_id,),
        )

    @db_op("write")
    def update_processo_status(self, processo_id: int, status: str, observacoes: str = None) -> bool:
        current = self.get_processo_by_id(processo_id)
        if not current:
            return False

        # "" (ou None) representa "sem status" -> armazenado como NULL.
        status = status or None

        updates: dict = {"status": status}
        if status == Status.ENVIADO:
            updates["sent_at"] = datetime.now().isoformat()
        elif status in (Status.AUTORIZADO, Status.NEGADO):
            updates["result_at"] = datetime.now().isoformat()

        self._update_row("processos", processo_id, **updates)

        # ``observacoes`` é a nota da transição (registrada apenas no log,
        # sem sobrescrever a observação persistente do processo).
        now = datetime.now().isoformat()
        self._execute_write(
            "INSERT INTO status_logs (processo_id, old_status, new_status, observacoes, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (processo_id, current.status or "", status or "", observacoes or "", now),
        )
        return True

    @db_op("write")
    def update_status_log(self, log_id: int, observacoes: str) -> bool:
        return self._update_row("status_logs", log_id, observacoes=observacoes)

    @db_op("write")
    def add_status_observation(self, processo_id: int, observacoes: str) -> bool:
        current = self.get_processo_by_id(processo_id)
        if not current:
            return False
        now = datetime.now().isoformat()
        self._execute_write(
            "INSERT INTO status_logs (processo_id, old_status, new_status, observacoes, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (processo_id, current.status or "", current.status or "", observacoes or "", now),
        )
        return True

    @db_op("write")
    def update_processo(self, processo_id: int, **fields) -> bool:
        allowed = {"tipo", "solicitacao", "observacoes", "descricao", "protocolo_drs"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        return self._update_row("processos", processo_id, **updates)

    @db_op("write")
    def set_processo_pdf_sig(self, processo_id: int, pdf_sig: str) -> bool:
        """Registra a assinatura do PDF combinado atualmente gerado."""
        return self._update_row("processos", processo_id, pdf_sig=pdf_sig)

    @db_op("write")
    def reassign_processo_lote(
        self, processo_id: int, lote_id: int
    ) -> Optional[Processo]:
        """Move um processo para outra remessa, regerando o protocolo.

        O protocolo é reconstruído a partir da data da remessa de destino e de
        uma nova sequência (próxima disponível naquela remessa). Retorna o
        processo atualizado, ou ``None`` se processo/remessa/paciente não
        existirem.
        """
        processo = self.get_processo_by_id(processo_id)
        if processo is None:
            return None
        if processo.lote_id == lote_id:
            return processo
        lote = self.get_lote_by_id(lote_id)
        paciente = self.get_paciente_by_id(processo.paciente_id)
        if lote is None or paciente is None:
            return None

        initials = generate_initials(paciente.nome)
        seq = self._get_next_seq(lote_id, initials)
        protocolo = generate_protocolo(lote.date, initials, seq)
        self._update_row(
            "processos", processo_id, lote_id=lote_id, protocolo=protocolo
        )
        return self.get_processo_by_id(processo_id)

    @db_op("write")
    def delete_processo(self, processo_id: int) -> bool:
        with self.transaction():
            # O ON DELETE CASCADE remove os metadados em ``arquivos``, mas não
            # alcança o banco anexado — apaga os BLOBs órfãos explicitamente.
            rows = self._fetch_all(
                "SELECT id FROM arquivos WHERE processo_id = ?", (processo_id,)
            )
            if rows:
                ids = [r["id"] for r in rows]
                placeholders = ", ".join("?" for _ in ids)
                self._execute_write(
                    f"DELETE FROM {self.ARQUIVOS_DB_ALIAS}.arquivo_conteudos "
                    f"WHERE arquivo_id IN ({placeholders})",
                    tuple(ids),
                )
            return self._delete_row("processos", processo_id)

    @db_op("read")
    def search_processos(
        self,
        query: str = "",
        status: str = None,
        tipo: str = None,
        solicitacao: str = None,
        lote_id: int = None,
        active_lote_id: int = None,
        limit: int = 50,
    ) -> list[Processo]:
        conditions = []
        params: list = []

        if query:
            # Busca por nome (normalizado) OU por telefone. Telefones são
            # armazenados apenas com dígitos, então basta comparar dígitos.
            digits = _digits(query)
            if digits:
                conditions.append("(pac.nome LIKE ? OR pac.telefone LIKE ?)")
                params.append(f"%{to_upper_normalized(query)}%")
                params.append(f"%{digits}%")
            else:
                conditions.append("pac.nome LIKE ?")
                params.append(f"%{to_upper_normalized(query)}%")

        if status:
            conditions.append("p.status = ?")
            params.append(status)

        if tipo:
            conditions.append("p.tipo = ?")
            params.append(tipo)

        if solicitacao:
            conditions.append("p.solicitacao = ?")
            params.append(solicitacao)

        if lote_id:
            conditions.append("p.lote_id = ?")
            params.append(lote_id)

        where = " AND ".join(conditions) if conditions else "1=1"

        # Ordena a remessa ativa primeiro, depois por data (desc) e nome.
        order_by = ""
        order_params: list = []
        if active_lote_id:
            order_by += "CASE WHEN p.lote_id = ? THEN 0 ELSE 1 END, "
            order_params.append(active_lote_id)
        order_by += "l.date DESC, pac.nome COLLATE NOCASE LIMIT ?"

        rows = self._fetch_processos_joined(
            where, params + order_params + [limit], order_by
        )
        return [Processo.from_row(r) for r in rows]

    @db_op("read")
    def get_processos_by_status(self, status: str) -> list[Processo]:
        rows = self._fetch_processos_joined("p.status = ?", (status,))
        return [Processo.from_row(r) for r in rows]

    @db_op("read")
    def get_processos_for_export(self) -> list[dict]:
        """Linhas de processos (com paciente/lote) para exportação da planilha."""
        return self._fetch_processos_joined(
            order_by="l.date, p.solicitacao, pac.nome, p.id"
        )

    # ========== ARQUIVO ==========

    @db_op("write")
    def create_arquivo(
        self,
        processo_id: int,
        tipo_documento: str,
        conteudo: bytes,
        arquivo_original: str = "",
        ordem: int = 0,
        caminho: str | None = None,
    ) -> Arquivo:
        now = datetime.now().isoformat()
        content_sha256 = (
            hashlib.sha256(conteudo).hexdigest() if conteudo is not None else ""
        )
        with self.transaction():
            last_id = self._insert_row(
                "arquivos",
                processo_id=processo_id,
                tipo_documento=tipo_documento,
                arquivo_original=arquivo_original,
                caminho=caminho,
                ordem=ordem,
                content_sha256=content_sha256,
                created_at=now,
            )
            if conteudo is not None:
                self._execute_write(
                    f"INSERT INTO {self.ARQUIVOS_DB_ALIAS}.arquivo_conteudos "
                    "(arquivo_id, conteudo) VALUES (?, ?)",
                    (last_id, sqlite3.Binary(conteudo)),
                )
        return Arquivo(
            id=last_id,
            processo_id=processo_id,
            tipo_documento=tipo_documento,
            arquivo_original=arquivo_original,
            caminho=caminho,
            conteudo=conteudo,
            ordem=ordem,
            content_sha256=content_sha256,
            created_at=now,
        )

    @db_op("read")
    def get_arquivos_by_processo(self, processo_id: int) -> list[Arquivo]:
        # Metadados apenas (sem BLOB) — use ``get_arquivo_conteudo`` para o binário.
        rows = self._fetch_all(
            "SELECT id, processo_id, tipo_documento, arquivo_original, "
            "caminho, ordem, validado, content_sha256, created_at "
            "FROM arquivos WHERE processo_id = ? ORDER BY ordem",
            (processo_id,),
        )
        return [Arquivo.from_row(r) for r in rows]

    @db_op("read")
    def get_arquivo_conteudo(self, arquivo_id: int) -> bytes | None:
        row = self._fetch_one(
            f"SELECT conteudo FROM {self.ARQUIVOS_DB_ALIAS}.arquivo_conteudos "
            "WHERE arquivo_id = ?",
            (arquivo_id,),
        )
        if not row:
            return None
        blob = row["conteudo"]
        return bytes(blob) if blob is not None else None

    @db_op("write")
    def update_arquivo_conteudo(self, arquivo_id: int, conteudo: bytes) -> bool:
        # Hash regravado junto ao conteúdo, na mesma transação (ambas as DBs
        # ATTACHadas compartilham a conexão): conteúdo e hash nunca divergem,
        # então a assinatura do processo (só metadados) é sempre fiel.
        content_sha256 = (
            hashlib.sha256(conteudo).hexdigest() if conteudo is not None else ""
        )
        with self.transaction():
            self._execute_write(
                f"UPDATE {self.ARQUIVOS_DB_ALIAS}.arquivo_conteudos "
                "SET conteudo = ? WHERE arquivo_id = ?",
                (sqlite3.Binary(conteudo), arquivo_id),
            )
            self._update_row(
                "arquivos", arquivo_id, content_sha256=content_sha256,
            )
        return True

    @db_op("write")
    def update_arquivo(self, arquivo_id: int, **fields) -> bool:
        allowed = {"tipo_documento", "ordem", "validado", "caminho"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        if "validado" in updates:
            updates["validado"] = 1 if updates["validado"] else 0
        return self._update_row("arquivos", arquivo_id, **updates)

    @db_op("write")
    def delete_arquivo(self, arquivo_id: int) -> bool:
        with self.transaction():
            self._execute_write(
                f"DELETE FROM {self.ARQUIVOS_DB_ALIAS}.arquivo_conteudos "
                "WHERE arquivo_id = ?",
                (arquivo_id,),
            )
            return self._delete_row("arquivos", arquivo_id)

    # ========== STATS ==========

    # ========== STATUS LOGS ==========

    @db_op("read")
    def get_processos_by_lote_and_status(self, lote_id: int, status: str) -> list[Processo]:
        rows = self._fetch_processos_joined(
            "p.lote_id = ? AND p.status = ?",
            (lote_id, status),
            "pac.nome COLLATE NOCASE",
        )
        return [Processo.from_row(r) for r in rows]

    # ========== PENDING SENDS (rascunhos DRS aguardando envio) ==========

    @db_op("write")
    def create_pending_send(
        self,
        lote_id: int,
        grupo: str,
        processo_ids: list[int],
        draft_id: str = "",
        message_id: str = "",
        rfc822_msgid: str = "",
        to_email: str = "",
        subject: str = "",
    ) -> int:
        """Registra um rascunho DRS criado, aguardando confirmação de envio."""
        now = datetime.now().isoformat()
        return self._insert_row(
            "pending_sends",
            lote_id=lote_id,
            grupo=grupo,
            draft_id=draft_id,
            message_id=message_id,
            rfc822_msgid=rfc822_msgid,
            processo_ids=json.dumps(list(processo_ids)),
            to_email=to_email,
            subject=subject,
            status="pending",
            created_at=now,
        )

    @db_op("read")
    def get_pending_sends(self, status: str = "pending") -> list[dict]:
        """Retorna os envios com o status informado (default: pendentes)."""
        rows = self._fetch_all(
            "SELECT * FROM pending_sends WHERE status = ? ORDER BY created_at",
            (status,),
        )
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["processo_ids"] = json.loads(d.get("processo_ids") or "[]")
            except (ValueError, TypeError):
                d["processo_ids"] = []
            result.append(d)
        return result

    @db_op("write")
    def resolve_pending_send(self, pending_id: int, status: str) -> bool:
        """Marca um envio pendente como ``sent`` ou ``discarded``."""
        return self._update_row(
            "pending_sends",
            pending_id,
            status=status,
            resolved_at=datetime.now().isoformat(),
        )

    # ========== DRS MESSAGES (menções de pacientes em e-mails) ==========

    @db_op("write")
    def create_drs_message(
        self,
        paciente_id: int,
        message_id: str,
        thread_id: str = "",
        from_email: str = "",
        subject: str = "",
        snippet: str = "",
        body: str = "",
        message_date: str = "",
        inferred_status: str = "",
    ) -> bool:
        """Registra um e-mail que menciona um paciente (ignora duplicatas)."""
        now = datetime.now().isoformat()
        with self._cursor() as cur:
            cur.execute(
                "INSERT OR IGNORE INTO drs_messages "
                "(paciente_id, message_id, thread_id, from_email, subject, "
                "snippet, body, message_date, inferred_status, seen, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
                (
                    paciente_id, message_id, thread_id, from_email, subject,
                    snippet, body, message_date, inferred_status, now,
                ),
            )
            self._commit()
            return cur.rowcount > 0

    @db_op("read")
    def get_drs_messages(self, seen: int | None = None) -> list[dict]:
        where = "" if seen is None else "WHERE seen = ?"
        params = () if seen is None else (seen,)
        rows = self._fetch_all(
            f"SELECT dm.*, pac.nome as paciente_nome "
            f"FROM drs_messages dm "
            f"JOIN pacientes pac ON dm.paciente_id = pac.id "
            f"{where} ORDER BY dm.message_date DESC",
            params,
        )
        return [dict(r) for r in rows]

    @db_op("read")
    def get_unseen_drs_count(self) -> int:
        row = self._fetch_one("SELECT COUNT(*) AS cnt FROM drs_messages WHERE seen = 0")
        return row["cnt"] if row else 0

    @db_op("read")
    def get_scanned_message_ids(self) -> set[str]:
        rows = self._fetch_all("SELECT message_id FROM drs_messages")
        return {r["message_id"] for r in rows}

    @db_op("write")
    def mark_drs_message_seen(self, message_id: str) -> bool:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE drs_messages SET seen = 1 WHERE message_id = ?",
                (message_id,),
            )
            self._commit()
            return cur.rowcount > 0

    @db_op("read")
    def get_processos_by_paciente(self, paciente_id: int) -> list[Processo]:
        rows = self._fetch_processos_joined(
            "p.paciente_id = ?", (paciente_id,), "l.date DESC, p.id ASC"
        )
        return [Processo.from_row(r) for r in rows]

    @db_op("read")
    def count_processos_by_paciente(self, paciente_id: int) -> int:
        row = self._fetch_one(
            "SELECT COUNT(*) AS cnt FROM processos WHERE paciente_id = ?",
            (paciente_id,),
        )
        return row["cnt"] if row else 0
