#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Collection snapshot provider — pulls encrypted snapshots from a GitHub
collection branch and decrypts them with the admin private key.

Used by the GitHub Action (and local testing) to aggregate all USAFAs.
Only depends on ``cryptography`` + stdlib — no andaime, no PySide6, no DB.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from rac.sync.asymmetric import decrypt_with_private_key
from rac.sync.types import Snapshot

_API_BASE = "https://api.github.com/repos"


def _github_get_json(url: str, token: str | None) -> Any:
    headers = {
        "User-Agent": "RAC-Panel",
        "Accept": "application/vnd.github+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _github_get_text(url: str, token: str | None) -> str:
    headers = {
        "User-Agent": "RAC-Panel",
        "Accept": "application/vnd.github+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


class CollectionSnapshotProvider:
    """Pull + decrypt snapshots from a GitHub collection branch."""

    def __init__(
        self,
        repo: str,
        branch: str,
        private_key_pem: str,
        token: str | None = None,
    ) -> None:
        self._repo = repo
        self._branch = branch
        self._private_key_pem = private_key_pem
        self._token = (
            token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        )

    def snapshots(self) -> list[Snapshot]:
        entries = self._list_files()
        results: list[Snapshot] = []
        for entry in entries:
            name = entry.get("name", "")
            if not name.endswith(".json.enc"):
                continue
            try:
                blob = json.loads(_github_get_text(entry["download_url"], self._token))
                plaintext = decrypt_with_private_key(blob, self._private_key_pem)
                results.append(json.loads(plaintext))
            except (urllib.error.URLError, KeyError, ValueError) as exc:
                print(f"[collection] skipping {name}: {exc}")
        return results

    def _list_files(self) -> list[dict]:
        url = f"{_API_BASE}/{self._repo}/contents/data?ref={self._branch}"
        try:
            data = _github_get_json(url, self._token)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return []
            raise
        if not isinstance(data, list):
            return []
        return data
