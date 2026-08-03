#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from rac.database.rac_database import RACDatabase
from rac.models import ItemCatalog


class ItemCatalogService:
    def __init__(self, db: RACDatabase) -> None:
        self._db = db

    def create(self, name: str, unidade: str = "un", quantidade: int = 0) -> ItemCatalog:
        return self._db.create_item(name, unidade, quantidade)

    def all(self) -> list[ItemCatalog]:
        return self._db.get_all_items()

    def update(self, item_id: int, name: str) -> bool:
        return self._db.update_item(item_id, name)

    def update_cids(self, item_id: int, cids: str) -> bool:
        return self._db.update_item_cids(item_id, cids)

    def update_quantidade(self, item_id: int, quantidade: int) -> bool:
        return self._db.update_item_quantidade(item_id, quantidade)

    def update_unidade(self, item_id: int, unidade: str) -> bool:
        return self._db.update_item_unidade(item_id, unidade)

    def delete(self, item_id: int) -> bool:
        return self._db.delete_item(item_id)
