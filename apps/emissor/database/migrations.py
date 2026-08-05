#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migrações de banco de dados do Emissor."""

import unicodedata
from typing import Any

from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel
from andaime.dates import parse_date
from emissor.database.definitive_catalog import DEFINITIVE_CATALOG


class DatabaseMigrator:
    """Gerencia migrações de banco de dados do Emissor."""

    @staticmethod
    def _normalize_description(desc: str) -> str:
        """Normaliza descrição (sem acentos, minúsculas) para comparação."""
        if not desc:
            return ""
        # Fast path para descrições apenas ASCII (sem acentos)
        if desc.isascii():
            return desc.lower().strip()
        # Slow path para caracteres com acentos
        # Normaliza para forma decomposta (NFD), remove caracteres de acentuação
        return (
            "".join(
                c
                for c in unicodedata.normalize("NFD", desc)
                if unicodedata.category(c) != "Mn"
            )
            .lower()
            .strip()
        )

    @staticmethod
    def sync_definitive_catalog(cursor: Any, conn: Any, db_path: str) -> None:
        """Sincroniza catálogo com DEFINITIVE_CATALOG (executa uma vez).

        Corrige ID/unidade por descrição; insere itens novos. Ignora conflitos.
        """
        # Skip for in-memory databases (test isolation)
        if db_path == ":memory:":
            return

        # Verificar se migration já foi aplicada
        cursor.execute("PRAGMA user_version")
        user_version = cursor.fetchone()[0]

        if user_version >= 1:
            # Migration já aplicada anteriormente
            return

        ErrorHandler.log(
            "Sincronizando catálogo com lista definitiva...",
            level=ErrorLevel.INFO,
            context=ErrorContext.DATABASE,
        )

        try:
            cursor.execute("BEGIN IMMEDIATE")

            # Construir lookup do catálogo definitivo
            # {normalized_desc: (item_id, unidade, descricao_original)}
            definitive_lookup = {}
            for descricao, item_id, unidade in DEFINITIVE_CATALOG:
                norm_desc = DatabaseMigrator._normalize_description(descricao)
                if norm_desc in definitive_lookup:
                    ErrorHandler.log(
                        f"  Descrição duplicada no catálogo definitivo: '{descricao}'",
                        level=ErrorLevel.WARNING,
                        context=ErrorContext.DATABASE,
                    )
                    continue
                definitive_lookup[norm_desc] = (item_id, unidade, descricao)

            # Buscar todos os itens atuais do banco
            cursor.execute("SELECT item_id, descricao, unidade FROM items_catalog")
            current_items = cursor.fetchall()

            # Estatísticas
            ids_corrected = 0
            units_corrected = 0
            items_inserted = 0
            items_skipped = 0

            # 1. Processar itens existentes (atualizar ID/unidade se necessário)
            for row in current_items:
                current_id = row[0]
                current_desc = row[1]
                current_unidade = row[2]

                norm_current_desc = DatabaseMigrator._normalize_description(
                    current_desc
                )

                # Verificar se descrição existe no catálogo definitivo
                if norm_current_desc in definitive_lookup:
                    definitive_id, definitive_unidade, definitive_desc = (
                        definitive_lookup[norm_current_desc]
                    )

                    # Verificar se ID atual corresponde ao definitivo
                    if current_id != definitive_id:
                        # Descrição corresponde, mas ID é diferente -> verificar se podemos atualizar
                        # Primeiro verificar se definitive_id já existe no banco
                        cursor.execute(
                            "SELECT item_id FROM items_catalog WHERE item_id = ?",
                            (definitive_id,),
                        )
                        if cursor.fetchone():
                            # ID definitivo já existe com outra descrição -> conflito, IGNORAR
                            items_skipped += 1
                            ErrorHandler.log(
                                f"  Ignorado: não é possível corrigir ID de '{current_desc}' "
                                f"(ID {definitive_id} já existe no banco)",
                                level=ErrorLevel.WARNING,
                                context=ErrorContext.DATABASE,
                            )
                            # Continuar para verificar unidade no item atual
                        else:
                            # ID definitivo está livre -> ATUALIZAR ID
                            cursor.execute(
                                "UPDATE items_catalog SET item_id = ? WHERE item_id = ?",
                                (definitive_id, current_id),
                            )
                            ids_corrected += 1
                            ErrorHandler.log(
                                f"  ID corrigido: '{current_desc}' ({current_id} -> {definitive_id})",
                                level=ErrorLevel.INFO,
                                context=ErrorContext.DATABASE,
                            )

                    # Verificar se unidade atual corresponde à definitiva
                    new_unidade = (
                        definitive_unidade
                        if current_unidade != definitive_unidade
                        else None
                    )
                    if new_unidade:
                        # Usar o ID atualizado (ou original se não mudou)
                        target_id = (
                            definitive_id if current_id != definitive_id else current_id
                        )
                        cursor.execute(
                            "UPDATE items_catalog SET unidade = ? WHERE item_id = ?",
                            (definitive_unidade, target_id),
                        )
                        units_corrected += 1
                        ErrorHandler.log(
                            f"  Unidade corrigida: '{current_desc}' ({current_unidade} -> {definitive_unidade})",
                            level=ErrorLevel.INFO,
                            context=ErrorContext.DATABASE,
                        )
                else:
                    # Descrição não existe no catálogo definitivo
                    # Verificar se ID existe no catálogo definitivo (com outra descrição)
                    id_exists_in_definitive = any(
                        item_id == current_id for item_id, _, _ in DEFINITIVE_CATALOG
                    )

                    if id_exists_in_definitive:
                        # ID conflita com descrição diferente -> IGNORAR
                        items_skipped += 1
                        ErrorHandler.log(
                            f"  Ignorado: ID {current_id} com descrição não catalogada ('{current_desc}')",
                            level=ErrorLevel.WARNING,
                            context=ErrorContext.DATABASE,
                        )

            # 2. Inserir itens do catálogo definitivo que não existem no banco
            cursor.execute("SELECT item_id FROM items_catalog")
            existing_ids = {row[0] for row in cursor.fetchall()}

            # Coletar itens para inserção em lote
            items_to_insert = [
                (item_id, descricao, unidade)
                for descricao, item_id, unidade in DEFINITIVE_CATALOG
                if item_id not in existing_ids
            ]

            # Inserção em lote para performance
            if items_to_insert:
                cursor.executemany(
                    "INSERT INTO items_catalog (item_id, descricao, unidade) VALUES (?, ?, ?)",
                    items_to_insert,
                )
                items_inserted = len(items_to_insert)

            # 3. Marcar migration como aplicada
            cursor.execute("PRAGMA user_version = 1")

            conn.commit()

            # Log resumo
            ErrorHandler.log(
                f"Catálogo definitivo sincronizado: {items_inserted} inseridos, "
                f"{ids_corrected} IDs corrigidos, {units_corrected} unidades corrigidas, "
                f"{items_skipped} ignorados",
                level=ErrorLevel.INFO,
                context=ErrorContext.DATABASE,
            )

        except Exception as e:
            conn.rollback()
            ErrorHandler.log(
                f"Erro na sincronização do catálogo: {e}",
                level=ErrorLevel.ERROR,
                context=ErrorContext.DATABASE,
            )
            raise

    @staticmethod
    def flatten_patient_data(cursor: Any, conn: Any, db_path: str) -> None:
        """Migra dados de patient_data para pacientes (v1 → v2)."""
        if db_path == ":memory:":
            return

        cursor.execute("PRAGMA user_version")
        user_version = cursor.fetchone()[0]

        if user_version >= 2:
            return

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='patient_data'"
        )
        if not cursor.fetchone():
            cursor.execute("PRAGMA user_version = 2")
            return

        ErrorHandler.log(
            "Migrando patient_data para pacientes...",
            level=ErrorLevel.INFO,
            context=ErrorContext.DATABASE,
        )

        try:
            cursor.execute("BEGIN IMMEDIATE")

            cursor.execute("PRAGMA table_info(pacientes)")
            existing_cols = {row[1] for row in cursor.fetchall()}

            cursor.execute("PRAGMA table_info(patient_data)")
            pd_cols = [row[1] for row in cursor.fetchall() if row[1] != "patient_id"]

            for col in pd_cols:
                if col not in existing_cols:
                    cursor.execute(f"ALTER TABLE pacientes ADD COLUMN {col} TEXT")

            set_clauses = ", ".join(
                f"{col} = (SELECT {col} FROM patient_data WHERE patient_id = pacientes.id)"
                for col in pd_cols
            )
            cursor.execute(
                f"UPDATE pacientes SET {set_clauses} "
                "WHERE EXISTS (SELECT 1 FROM patient_data WHERE patient_id = pacientes.id)"
            )

            cursor.execute("DROP TABLE patient_data")

            cursor.execute("PRAGMA user_version = 2")
            conn.commit()

            ErrorHandler.log(
                "Migração concluída: patient_data -> pacientes",
                level=ErrorLevel.INFO,
                context=ErrorContext.DATABASE,
            )

        except Exception as e:
            conn.rollback()
            ErrorHandler.log(
                f"Erro na migração: {e}",
                level=ErrorLevel.ERROR,
                context=ErrorContext.DATABASE,
            )
            raise

    @staticmethod
    def mark_superseded_retiradas(cursor: Any, conn: Any, db_path: str) -> None:
        """Marca retiradas antigas como substituídas (executa uma vez).

        Para cada paciente, marca retiradas cujo retorno estava no futuro
        quando uma mais recente com item em comum ocorreu.
        """
        if db_path == ":memory:":
            return

        cursor.execute("PRAGMA user_version")
        user_version = cursor.fetchone()[0]

        if user_version >= 3:
            return

        ErrorHandler.log(
            "Marcando retiradas substituídas...",
            level=ErrorLevel.INFO,
            context=ErrorContext.DATABASE,
        )

        try:
            cursor.execute("BEGIN IMMEDIATE")

            # Agrupar retiradas por paciente, ordenadas por data_retirada
            cursor.execute(
                "SELECT id, patient_id, data_retirada, data_proxima_retirada "
                "FROM retiradas ORDER BY patient_id, data_retirada"
            )
            all_retiradas = cursor.fetchall()

            # Construir conjuntos de itens por retirada
            cursor.execute("SELECT retirada_id, item_id FROM retirada_items")
            retirada_item_map: dict[int, set[str]] = {}
            for row in cursor.fetchall():
                rid = row[0]
                if rid not in retirada_item_map:
                    retirada_item_map[rid] = set()
                retirada_item_map[rid].add(row[1])

            # Agrupar por paciente (já ordenado por data_retirada)
            patient_groups: dict[int, list[tuple]] = {}
            for r in all_retiradas:
                pid = r[1]
                if pid not in patient_groups:
                    patient_groups[pid] = []
                patient_groups[pid].append(r)

            # Marcar retiradas substituídas
            marked = 0
            for pid, retiradas in patient_groups.items():
                for i, a in enumerate(retiradas):
                    a_id = a[0]
                    a_proxima = a[3]
                    a_items = retirada_item_map.get(a_id, set())
                    if not a_items:
                        continue
                    # Verificar retiradas mais recentes
                    for b in retiradas[i + 1 :]:
                        b_id = b[0]
                        b_data = b[2]
                        b_items = retirada_item_map.get(b_id, set())
                        # Retorno de A ainda no futuro quando B ocorreu?
                        if a_proxima >= b_data and (a_items & b_items):
                            cursor.execute(
                                "UPDATE retiradas SET substituida = 1 WHERE id = ?",
                                (a_id,),
                            )
                            marked += 1
                            break

            cursor.execute("PRAGMA user_version = 3")
            conn.commit()

            ErrorHandler.log(
                f"{marked} retirada(s) marcada(s) como substituída(s)",
                level=ErrorLevel.INFO,
                context=ErrorContext.DATABASE,
            )

        except Exception as e:
            conn.rollback()
            ErrorHandler.log(
                f"Erro ao marcar retiradas substituídas: {e}",
                level=ErrorLevel.ERROR,
                context=ErrorContext.DATABASE,
            )
            raise

    @staticmethod
    def normalize_ultima_receita(cursor: Any, conn: Any, db_path: str) -> None:
        """Normaliza ``ultima_receita`` para ISO YYYY-MM-DD (idempotente)."""
        if db_path == ":memory:":
            return

        cursor.execute("PRAGMA user_version")
        if cursor.fetchone()[0] >= 4:
            return

        try:
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute("SELECT id, ultima_receita FROM pacientes")
            for pid, value in cursor.fetchall():
                if not value:
                    continue
                parsed = parse_date(value)
                if not parsed:
                    continue
                iso = parsed.strftime("%Y-%m-%d")
                if iso != value:
                    cursor.execute(
                        "UPDATE pacientes SET ultima_receita = ? WHERE id = ?",
                        (iso, pid),
                    )
            cursor.execute("PRAGMA user_version = 4")
            conn.commit()
        except Exception as e:
            conn.rollback()
            ErrorHandler.log(
                f"Erro ao normalizar ultima_receita: {e}",
                level=ErrorLevel.ERROR,
                context=ErrorContext.DATABASE,
            )
            raise

    @staticmethod
    def normalize_profissionais(cursor: Any, conn: Any, db_path: str) -> None:
        """Normaliza profissionais para tabela mestre (v4 → v5).

        Cria ``profissionais``, extrai pares (nome, crm) de ``pacientes``,
        adiciona ``profissional_id`` (FK) e remove colunas antigas.
        Idempotente (user_version >= 5).
        """
        if db_path == ":memory:":
            return

        cursor.execute("PRAGMA user_version")
        if cursor.fetchone()[0] >= 5:
            return

        ErrorHandler.log(
            "Normalizando profissionais para tabela mestre...",
            level=ErrorLevel.INFO,
            context=ErrorContext.DATABASE,
        )

        try:
            cursor.execute("BEGIN IMMEDIATE")

            # Garantir tabela profissionais (idempotente em bancos novos).
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS profissionais ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "nome TEXT UNIQUE NOT NULL, "
                "crm TEXT"
                ")"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_profissionais_nome "
                "ON profissionais(nome)"
            )

            # Verificar se o banco antigo ainda tem as colunas profissional/crm.
            cursor.execute("PRAGMA table_info(pacientes)")
            pac_cols = {row[1] for row in cursor.fetchall()}

            if "profissional" in pac_cols or "crm" in pac_cols:
                # 1. Extrair pares distintos (profissional, crm), ignorando vazios.
                cursor.execute(
                    "SELECT profissional, crm FROM pacientes "
                    "WHERE (profissional IS NOT NULL AND profissional != '') "
                    "OR (crm IS NOT NULL AND crm != '')"
                )
                # nome -> primeiro crm não-vazio (ordem de inserção por id).
                prof_crm: dict[str, str] = {}
                for prof, crm in cursor.fetchall():
                    prof = (prof or "").strip().upper()
                    crm = (crm or "").strip().upper()
                    if not prof:
                        continue
                    existing = prof_crm.get(prof)
                    if existing is None:
                        prof_crm[prof] = crm
                    elif crm and existing != crm:
                        # Conflito: manter o primeiro, registrar o conflito.
                        ErrorHandler.log(
                            f"Conflito de CRM para profissional '{prof}': "
                            f"mantido '{existing}', ignorado '{crm}'",
                            level=ErrorLevel.WARNING,
                            context=ErrorContext.DATABASE,
                        )

                # 2. Inserir profissionais (nome UNIQUE cuida de duplicatas).
                for nome, crm in prof_crm.items():
                    cursor.execute(
                        "INSERT OR IGNORE INTO profissionais (nome, crm) "
                        "VALUES (?, ?)",
                        (nome, crm),
                    )

                # 3. Adicionar profissional_id e fazer backfill.
                cursor.execute("PRAGMA table_info(pacientes)")
                if "profissional_id" not in {r[1] for r in cursor.fetchall()}:
                    cursor.execute(
                        "ALTER TABLE pacientes ADD COLUMN profissional_id INTEGER "
                        "REFERENCES profissionais(id) ON DELETE SET NULL"
                    )
                cursor.execute(
                    "UPDATE pacientes SET profissional_id = ("
                    "SELECT id FROM profissionais "
                    "WHERE profissionais.nome = pacientes.profissional)"
                )

                # 4. Remover colunas antigas.
                cursor.execute("PRAGMA table_info(pacientes)")
                new_cols = [r[1] for r in cursor.fetchall()]
                for col in ("profissional", "crm"):
                    if col in new_cols:
                        cursor.execute(f"ALTER TABLE pacientes DROP COLUMN {col}")

            cursor.execute("PRAGMA user_version = 5")
            conn.commit()

            ErrorHandler.log(
                "Migração concluída: profissionais -> tabela mestre",
                level=ErrorLevel.INFO,
                context=ErrorContext.DATABASE,
            )
        except Exception as e:
            conn.rollback()
            ErrorHandler.log(
                f"Erro ao normalizar profissionais: {e}",
                level=ErrorLevel.ERROR,
                context=ErrorContext.DATABASE,
            )
            raise
