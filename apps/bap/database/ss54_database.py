import hashlib
import sqlite3
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional
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
        # VACUUM pendente: setado pelas deleções e executado só após o commit
        # da transação mais externa (VACUUM não roda dentro de transação).
        self._vacuum_pending = False

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
                        is_archived INTEGER NOT NULL DEFAULT 0,
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
                if "is_archived" not in cols:
                    cur.execute("ALTER TABLE processos ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0")

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

        Lê os BLOBs em lotes e aplica as atualizações dentro de uma única
        transação por lote, evitando um commit por arquivo. Em shares de rede
        (journal_mode=DELETE) cada commit é caro; o processamento em lote reduz
        drasticamente o tempo total. Idempotente: só processa linhas com
        ``content_sha256 IS NULL``.
        """
        BATCH_SIZE = 100

        with self._cursor() as cur:
            total = cur.execute(
                "SELECT COUNT(*) FROM arquivos WHERE content_sha256 IS NULL"
            ).fetchone()[0]
        if total == 0:
            return

        ErrorHandler.log(
            f"Iniciando backfill de content_sha256 para {total} arquivo(s)...",
            level=ErrorLevel.INFO,
            context=ErrorContext.DATABASE,
        )

        processed = 0
        while True:
            with self._cursor() as cur:
                cur.execute(
                    f"SELECT a.id, ac.conteudo FROM arquivos a "
                    f"JOIN {self.ARQUIVOS_DB_ALIAS}.arquivo_conteudos ac "
                    f"ON a.id = ac.arquivo_id "
                    f"WHERE a.content_sha256 IS NULL "
                    f"LIMIT {BATCH_SIZE}"
                )
                rows = cur.fetchall()
            if not rows:
                break

            updates = []
            for row in rows:
                blob = row["conteudo"]
                digest = hashlib.sha256(blob).hexdigest() if blob is not None else ""
                updates.append((digest, row["id"]))

            with self.transaction():
                with self._cursor() as cur:
                    cur.executemany(
                        "UPDATE arquivos SET content_sha256 = ? WHERE id = ?",
                        updates,
                    )

            processed += len(updates)
            ErrorHandler.log(
                f"Backfill content_sha256: {processed}/{total} arquivo(s) processado(s)",
                level=ErrorLevel.INFO,
                context=ErrorContext.DATABASE,
            )

        ErrorHandler.log(
            f"Backfill content_sha256 concluído: {processed} arquivo(s).",
            level=ErrorLevel.INFO,
            context=ErrorContext.DATABASE,
        )

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
            (to_upper_normalized(nome.strip()),),
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
    def update_paciente(self, paciente_id: int, nome: str | None = None, telefone: str | None = None) -> bool:
        updates = {}
        if nome is not None:
            updates["nome"] = to_upper_normalized(nome.strip())
        if telefone is not None:
            updates["telefone"] = normalize_phone(telefone)
        if not updates:
            return False
        return self._update_row("pacientes", paciente_id, **updates)

    @db_op("write")
    def merge_pacientes(self, from_id: int, to_id: int) -> bool:
        """Merges two patient records by moving all data from from_id to to_id.

        Moves processos and DRS messages to the target and keeps the source
        phone when the target has none (avoids silent data loss).
        """
        if from_id == to_id:
            return False
        from_pac = self.get_paciente_by_id(from_id)
        to_pac = self.get_paciente_by_id(to_id)
        if from_pac is None or to_pac is None:
            return False
        carry_telefone = bool(from_pac.telefone and not to_pac.telefone)
        with self.transaction():
            self._execute_write(
                "UPDATE processos SET paciente_id = ? WHERE paciente_id = ?",
                (to_id, from_id)
            )
            self._execute_write(
                "UPDATE drs_messages SET paciente_id = ? WHERE paciente_id = ?",
                (to_id, from_id)
            )
            if carry_telefone:
                self._execute_write(
                    "UPDATE pacientes SET telefone = ? WHERE id = ?",
                    (from_pac.telefone, to_id)
                )
            self._execute_write("DELETE FROM pacientes WHERE id = ?", (from_id,))
        return True

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
        # Uma única transação para toda a movimentação: atômica (tudo ou
        # nada) e um só commit — cada commit individual é caro em shares de
        # rede (journal_mode=DELETE).
        with self.transaction():
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

    @db_op("read")
    def get_lotes_with_counts(self) -> list[tuple[Lote, int]]:
        rows = self._fetch_all(
            "SELECT l.*, COUNT(p.id) AS cnt FROM lotes l "
            "LEFT JOIN processos p ON l.id = p.lote_id "
            "GROUP BY l.id ORDER BY l.date DESC"
        )
        return [(Lote.from_row(r), r["cnt"]) for r in rows]

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

    @db_op("write")
    def delete_lote(self, lote_id: int) -> bool:
        """Remove uma remessa, apenas se não houver processos associados.

        Guarda interna (defensiva) além da checagem da UI: lotes com
        processos não são apagados.
        """
        row = self._fetch_one(
            "SELECT COUNT(*) AS c FROM processos WHERE lote_id = ?", (lote_id,)
        )
        if row and row["c"]:
            return False
        deleted = self._delete_row("lotes", lote_id)
        if deleted:
            self._request_vacuum()
        return deleted

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
        status: str | None = None,
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

        status_val: str = status if status is not None else Status.EM_ANALISE
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
        # O último status_log de cada processo vem de uma derived table com
        # window function (um único scan de status_logs por query), em vez de
        # um subselect correlacionado por linha de processo. O desempate por
        # ``id DESC`` preserva a semântica de "mais recente" mesmo com
        # ``created_at`` iguais ou fora de ordem (imports com timestamps
        # customizados).
        sql = (
            "SELECT p.*, pac.nome as paciente_nome, pac.telefone as paciente_telefone, l.date as lote_date, "
            "sl.observacoes AS last_obs, sl.created_at AS last_obs_at "
            "FROM processos p "
            "JOIN pacientes pac ON p.paciente_id = pac.id "
            "JOIN lotes l ON p.lote_id = l.id "
            "LEFT JOIN ("
            "SELECT processo_id, observacoes, created_at, "
            "ROW_NUMBER() OVER ("
            "PARTITION BY processo_id ORDER BY created_at DESC, id DESC"
            ") AS rn "
            "FROM status_logs"
            ") sl ON sl.processo_id = p.id AND sl.rn = 1"
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
        rows = self._fetch_processos_joined(
            "p.paciente_id = ? AND p.lote_id = ? "
            "AND p.tipo = ? AND p.solicitacao = ?",
            (paciente_id, lote_id, tipo, solicitacao),
            "p.id ASC"
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
    def update_processo_status(self, processo_id: int, status: str, observacoes: str | None = None) -> bool:
        current = self.get_processo_by_id(processo_id)
        if not current:
            return False

        # "" (ou None) representa "sem status" -> armazenado como NULL.
        final_status: str | None = status or None

        updates: dict = {"status": final_status}
        if final_status == Status.ENVIADO:
            updates["sent_at"] = datetime.now().isoformat()
        elif final_status in (Status.AUTORIZADO, Status.NEGADO):
            updates["result_at"] = datetime.now().isoformat()

        self._update_row("processos", processo_id, **updates)

        # ``observacoes`` é a nota da transição (registrada apenas no log,
        # sem sobrescrever a observação persistente do processo).
        now = datetime.now().isoformat()
        self._execute_write(
            "INSERT INTO status_logs (processo_id, old_status, new_status, observacoes, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (processo_id, current.status or "", final_status or "", observacoes or "", now),
        )
        return True

    @db_op("write")
    def update_status_log(self, log_id: int, observacoes: str) -> bool:
        return self._update_row("status_logs", log_id, observacoes=observacoes)

    @db_op("write")
    def update_status_log_date(self, log_id: int, date_str: str) -> bool:
        """Atualiza a data de um status_log, preservando o horário do registro.

        Se a transição é ENVIADO, sincroniza ``processos.sent_at``; se é
        AUTORIZADO/NEGADO, sincroniza ``processos.result_at`` — para que o
        histórico e os marcos do processo concordem com a nova data.
        """
        rows = self._fetch_all(
            "SELECT processo_id, new_status, created_at "
            "FROM status_logs WHERE id = ?",
            (log_id,),
        )
        if not rows:
            return False
        row = rows[0]
        existing = row["created_at"] or ""
        new_created = date_str
        if "T" in existing:
            new_created = f"{date_str}T{existing.split('T', 1)[1]}"
        if not self._update_row("status_logs", log_id, created_at=new_created):
            return False

        st = row["new_status"] or ""
        if st == Status.ENVIADO:
            self._update_row("processos", row["processo_id"], sent_at=new_created)
        elif st in (Status.AUTORIZADO, Status.NEGADO):
            self._update_row("processos", row["processo_id"], result_at=new_created)
        return True

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
    def set_processo_archived(self, processo_id: int, archived: bool = True) -> bool:
        """Marca um processo como arquivado (PDF no disco, BLOBs removidos)."""
        return self._update_row(
            "processos", processo_id, is_archived=1 if archived else 0
        )

    def _request_vacuum(self) -> None:
        """Marca que os bancos precisam ser compactados após o commit."""
        self._vacuum_pending = True

    def _flush_pending_vacuum(self) -> None:
        """Executa o VACUUM pendente, fora de qualquer transação.

        Chamado automaticamente ao fim da transação mais externa (ver
        ``transaction``). Falhas são registradas, mas não derrubam a operação
        de escrita que originou a deleção.
        """
        if not self._vacuum_pending or self._in_transaction:
            return
        self._vacuum_pending = False
        try:
            with self._cursor() as cur:
                cur.execute(f"VACUUM {self.ARQUIVOS_DB_ALIAS}")
            with self._cursor() as cur:
                cur.execute("VACUUM")
        except Exception as e:
            ErrorHandler.handle_database_error(
                e, operation="compactar bancos de dados (VACUUM)"
            )

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Mesma semântica da base, mais a compactação adiada.

        Ao concluir a transação mais externa (committed), executa o VACUUM
        que ficou pendente nas deleções feitas dentro dela. Transações
        aninhadas apenas delegam à base.
        """
        with self._lock:
            already = self._in_transaction
        try:
            with super().transaction():
                yield
            if not already:
                self._flush_pending_vacuum()
        finally:
            pass

    @db_op("write")
    def delete_conteudos_for_processo(self, processo_id: int) -> int:
        """Remove os BLOBs de todos os arquivos de um processo (idempotente)."""
        with self.transaction():
            with self._cursor() as cur:
                cur.execute(
                    f"DELETE FROM {self.ARQUIVOS_DB_ALIAS}.arquivo_conteudos "
                    "WHERE arquivo_id IN (SELECT id FROM arquivos WHERE processo_id = ?)",
                    (processo_id,),
                )
                count = cur.rowcount
            if count > 0:
                self._request_vacuum()
        return count

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
        if processo.paciente_id is None:
            return None
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
            deleted = self._delete_row("processos", processo_id)
            if deleted:
                self._request_vacuum()
        return deleted

    @db_op("read")
    def search_processos(
        self,
        query: str = "",
        status: str | None = None,
        tipo: str | None = None,
        solicitacao: str | None = None,
        lote_id: int | None = None,
        active_lote_id: int | None = None,
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
            where, tuple(params + order_params + [limit]), order_by
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

    @db_op("read")
    def get_arquivos_conteudos(self, arquivo_ids: list[int]) -> dict[int, bytes]:
        """Busca os BLOBs de vários arquivos em uma única query.

        Retorna ``{arquivo_id: conteudo}`` apenas para ids encontrados.
        Em shares de rede, uma query ``IN (...)`` substitui N round-trips
        individuais de ``get_arquivo_conteudo``.
        """
        if not arquivo_ids:
            return {}
        placeholders = ", ".join("?" for _ in arquivo_ids)
        rows = self._fetch_all(
            f"SELECT arquivo_id, conteudo FROM {self.ARQUIVOS_DB_ALIAS}.arquivo_conteudos "
            f"WHERE arquivo_id IN ({placeholders})",
            tuple(arquivo_ids),
        )
        return {
            r["arquivo_id"]: bytes(r["conteudo"])
            for r in rows
            if r["conteudo"] is not None
        }

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
            deleted = self._delete_row("arquivos", arquivo_id)
            if deleted:
                self._request_vacuum()
        return deleted

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
