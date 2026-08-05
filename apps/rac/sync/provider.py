#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Snapshot providers — the seam between the management panel and its data source.

A provider yields the list of per-USAFA snapshots the panel renders.
``LocalSnapshotProvider`` exports the current instance's database (used today,
while only one USAFA exists). A future ``GitHubSnapshotProvider`` will pull and
decrypt snapshots published by every USAFA over the wire.
"""

from __future__ import annotations

from typing import Protocol

from rac.database.rac_database import RACDatabase
from rac.sync.snapshot import export_snapshot
from rac.sync.types import Snapshot


class SnapshotProvider(Protocol):
    def snapshots(self) -> list[Snapshot]: ...


class LocalSnapshotProvider:
    def __init__(self, db: RACDatabase, usafa_id: str, usafa_name: str) -> None:
        self._db = db
        self._usafa_id = usafa_id
        self._usafa_name = usafa_name

    def snapshots(self) -> list[Snapshot]:
        return [export_snapshot(self._db, self._usafa_id, self._usafa_name)]
