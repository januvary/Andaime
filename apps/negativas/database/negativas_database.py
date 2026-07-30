"""Database do Sistema de Negativas"""

import sqlite3
import json
from typing import Optional, List
from pathlib import Path

from andaime.database import BaseDatabase, db_op
from andaime.error_handler import ErrorHandler, ErrorLevel
from andaime.text import to_upper_normalized
from andaime.paths import resolve_db_path

from negativas.models import Medicamento, ModeloTexto

# Caminho para o arquivo de modelos
_MODELOS_PATH = Path(__file__).resolve().parent / "modelos.json"


class NegativasDatabase(BaseDatabase):
    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path is None:
            db_path = resolve_db_path("database.db", create_dir=True)
        super().__init__(db_path=db_path, entity_name="negativas")
        self._modelos_cache: dict[str, ModeloTexto] = {}
        self._cache_modelos()

    def _create_schema(self) -> None:
        try:
            with self._cursor() as cur:
                cur.executescript("""
                    CREATE TABLE IF NOT EXISTS medicamentos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        nome TEXT NOT NULL,
                        categoria TEXT NOT NULL CHECK(categoria IN ('CEAF', 'USAFA', 'CAPS II')),
                        cids TEXT NOT NULL DEFAULT '[]',
                        disponivel INTEGER NOT NULL DEFAULT 1
                    );
                    
                    CREATE TABLE IF NOT EXISTS modelos_texto (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tipo TEXT NOT NULL UNIQUE,
                        texto TEXT NOT NULL
                    );
                    
                    CREATE INDEX IF NOT EXISTS idx_medicamentos_nome ON medicamentos(nome COLLATE NOCASE);
                    CREATE INDEX IF NOT EXISTS idx_medicamentos_categoria ON medicamentos(categoria);
                """)
                self._commit()
                
                # Insere modelos de texto se a tabela estiver vazia
                if self._fetch_count("modelos_texto") == 0:
                    self._insert_modelos_texto()
                    
        except Exception as e:
            ErrorHandler.handle_database_error(e, operation="criar schema do banco Negativas")
            raise

    def _insert_modelos_texto(self) -> None:
        """Insere os modelos de texto padrão a partir do arquivo JSON."""
        try:
            with open(_MODELOS_PATH, 'r', encoding='utf-8') as f:
                modelos_data = json.load(f)
            
            modelos = modelos_data.get('modelos', [])
            
            for modelo in modelos:
                tipo = modelo.get('tipo')
                texto = modelo.get('texto')
                if tipo and texto:
                    self._insert_row("modelos_texto", tipo=tipo, texto=texto)
                    
        except FileNotFoundError:
            ErrorHandler.log(
                f"Arquivo de modelos não encontrado: {_MODELOS_PATH}",
                level=ErrorLevel.WARNING,
                context="Database"
            )
        except json.JSONDecodeError as e:
            ErrorHandler.log(
                f"Erro ao ler arquivo de modelos: {e}",
                level=ErrorLevel.ERROR,
                context="Database"
            )

    def _log_initialization_success(self) -> None:
        try:
            medicamentos_count = self._fetch_count("medicamentos")
            modelos_count = self._fetch_count("modelos_texto")

            ErrorHandler.log(
                f"NegativasDatabase inicializado: {medicamentos_count} medicamentos, "
                f"{modelos_count} modelos de texto",
                level=ErrorLevel.INFO,
                context="Database",
            )
        except Exception:
            super()._log_initialization_success()

    # ========== MEDICAMENTOS ==========

    @db_op("read")
    def get_medicamento_por_id(self, medicamento_id: int) -> Optional[Medicamento]:
        row = self._fetch_by_id("medicamentos", medicamento_id)
        return Medicamento.from_row(row) if row else None

    @db_op("read")
    def buscar_medicamentos(self, query: str) -> List[Medicamento]:
        """Busca medicamentos por nome (case insensitive, accent insensitive)."""
        if not query:
            return []
        
        normalized_query = to_upper_normalized(query)
        rows = self._fetch_all(
            "SELECT * FROM medicamentos WHERE nome LIKE ? ORDER BY nome COLLATE NOCASE",
            (f"%{normalized_query}%",)
        )
        return [Medicamento.from_row(r) for r in rows]

    @db_op("read")
    def get_todos_medicamentos(self) -> List[Medicamento]:
        """Retorna todos os medicamentos ordenados por nome."""
        rows = self._fetch_all_table("medicamentos", order_by="nome COLLATE NOCASE")
        return [Medicamento.from_row(r) for r in rows]

    @db_op("read")
    def get_medicamento_por_nome(self, nome: str) -> Optional[Medicamento]:
        """Busca medicamento por nome exato (case insensitive)."""
        normalized_nome = to_upper_normalized(nome)
        row = self._fetch_one(
            "SELECT * FROM medicamentos WHERE nome = ? LIMIT 1",
            (normalized_nome,),
        )
        return Medicamento.from_row(row) if row else None

    @db_op("read")
    def get_medicamentos_por_categoria(self, categoria: str) -> List[Medicamento]:
        """Retorna medicamentos de uma categoria específica."""
        rows = self._fetch_all(
            "SELECT * FROM medicamentos WHERE categoria = ? ORDER BY nome COLLATE NOCASE",
            (categoria,)
        )
        return [Medicamento.from_row(r) for r in rows]

    @db_op("write")
    def atualizar_disponibilidade(self, medicamento_id: int, disponivel: bool) -> bool:
        """Atualiza a disponibilidade de um medicamento."""
        return self._update_row("medicamentos", medicamento_id, disponivel=1 if disponivel else 0)

    # ========== MODELOS DE TEXTO ==========

    def _cache_modelos(self) -> None:
        """Carrega todos os modelos em cache."""
        try:
            modelos = self.get_todos_modelos()
            self._modelos_cache = {m.tipo: m for m in modelos}
        except Exception as e:
            ErrorHandler.log(
                f"Erro ao cachear modelos: {e}",
                level=ErrorLevel.WARNING,
                context="Database"
            )
            self._modelos_cache = {}

    @db_op("read")
    def get_modelo_por_tipo(self, tipo: str) -> Optional[ModeloTexto]:
        return self._modelos_cache.get(tipo)

    @db_op("read")
    def get_todos_modelos(self) -> List[ModeloTexto]:
        """Retorna todos os modelos de texto."""
        rows = self._fetch_all_table("modelos_texto")
        return [ModeloTexto.from_row(r) for r in rows]