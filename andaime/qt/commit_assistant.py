"""Commit Assistant — draft and commit a one-line message from the working tree.

Given a git repository, this module:
  1. Collects ``git status``, ``git diff`` (unstaged + staged), and a stat summary.
  2. Asks a small OpenRouter model to draft a single conventional-commit line.
  3. Presents a dialog with the diff and an editable message box.
  4. On confirm, runs ``git commit -m <message>`` (local only — no push).

The message is always a *suggestion*: the human approves/edits it before commit.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from andaime.qt.theme import colors, make_button

# Small, cheap model used only for drafting the one-line commit message.
COMMIT_MODEL = "poolside/laguna-s-2.1:free"
_DEFAULT_MAX_SUMMARY = 4000  # trim huge diffs before sending to the model


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _run_git(repo: Path, *args: str) -> str:
    """Run a git command in *repo*, returning stdout stripped."""
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


class CommitInfo:
    """Collected working-tree state for a repository."""

    def __init__(
        self,
        repo: Path,
        status: str,
        diff: str,
        staged_diff: str,
        stat: str,
    ) -> None:
        self.repo = repo
        self.status = status or "(clean)"
        self.diff = diff
        self.staged_diff = staged_diff
        self.stat = stat or "(no changes)"

    @property
    def has_changes(self) -> bool:
        return bool(self.diff or self.staged_diff)

    @property
    def model_prompt(self) -> str:
        """Trimmed prompt for the drafting model."""
        combined = "\n".join(
            part for part in (self.staged_diff, self.diff) if part
        )
        if len(combined) > _DEFAULT_MAX_SUMMARY:
            combined = combined[-_DEFAULT_MAX_SUMMARY:]
        return (
            "You are a git commit assistant. Read the diff below and write ONE\n"
            "concise conventional-commit line describing the change: type(scope): summary\n"
            "Use a real, honest summary of what actually changed (e.g. fix, feat, refactor, test).\n"
            "Reply with only the single line — no explanation, no quotes, no prefix.\n\n"
            f"--- git status ---\n{self.status}\n\n"
            f"--- diff ---\n{combined}\n"
        )


def collect_commit_info(repo: Path) -> CommitInfo:
    """Gather the working-tree state of *repo* for a commit draft."""
    return CommitInfo(
        repo=repo,
        status=_run_git(repo, "status", "--short"),
        diff=_run_git(repo, "diff"),
        staged_diff=_run_git(repo, "diff", "--staged"),
        stat=_run_git(repo, "diff", "--stat"),
    )


def find_repo_root(path: Path) -> Path | None:
    """Return the git work-tree root containing *path*, or None."""
    proc = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return Path(proc.stdout.strip())


# ---------------------------------------------------------------------------
# Model call (single OpenRouter HTTP request)
# ---------------------------------------------------------------------------

def openrouter_api_key() -> str | None:
    """Return the OpenRouter key from opencode's auth store (never printed)."""
    db_path = os.path.expanduser(
        "~/.local/share/opencode/auth.json"
    )
    try:
        with open(db_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return _find_sk(data)


def _find_sk(node) -> str | None:
    if isinstance(node, dict):
        key = node.get("key", "")
        if isinstance(key, str) and key.startswith("sk-or-v1"):
            return key
        for value in node.values():
            found = _find_sk(value)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_sk(item)
            if found:
                return found
    return None


def draft_commit_message(info: CommitInfo, api_key: str) -> str:
    """Call OpenRouter to draft a one-line commit message."""
    import urllib.request

    body = json.dumps(
        {
            "model": COMMIT_MODEL,
            "messages": [{"role": "user", "content": info.model_prompt}],
            "max_tokens": 80,
            "temperature": 0.2,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Commit dialog
# ---------------------------------------------------------------------------

class CommitDialog(QDialog):
    """Show the diff and an editable commit-message draft, then commit."""

    def __init__(self, name: str, info: CommitInfo, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.info = info
        self.setWindowTitle(f"Commit — {name}")
        self.resize(860, 560)

        layout = QVBoxLayout(self)

        # Status + stat line
        status_line = QLabel(f"{info.status}\n\n{info.stat}")
        status_line.setWordWrap(True)
        status_line.setStyleSheet(f"color: {colors()['text_dim']};")
        layout.addWidget(status_line)

        # Diff pane
        self.diff_edit = QTextEdit()
        self.diff_edit.setReadOnly(True)
        self.diff_edit.setPlainText(
            (info.staged_diff + "\n" + info.diff).strip() or "(no changes to show)"
        )
        self.diff_edit.setStyleSheet(
            f"QTextEdit {{ background: {colors()['box_bg']}; color: {colors()['text']}; "
            "font-family: monospace; }}"
        )

        # Splitter: diff on top, message below
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.diff_edit)

        msg_widget = QWidget()
        msg_layout = QVBoxLayout(msg_widget)
        msg_layout.addWidget(QLabel("Commit message (edit as needed):"))
        self.msg_edit = QTextEdit()
        self.msg_edit.setPlaceholderText("type(scope): summary")
        self.msg_edit.setFixedHeight(90)
        self.msg_edit.setStyleSheet(
            f"QTextEdit {{ background: {colors()['box_bg']}; color: {colors()['text']}; }}"
        )
        msg_layout.addWidget(self.msg_edit)
        splitter.addWidget(msg_widget)

        layout.addWidget(splitter, 1)

        # Buttons
        btn_row = QHBoxLayout()
        self.btn_cancel = make_button("Cancel", role="flat", parent=self)
        self.btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addStretch()
        self.btn_commit = make_button("Commit", role="primary", parent=self)
        self.btn_commit.setEnabled(False)
        self.btn_commit.clicked.connect(self._commit)
        btn_row.addWidget(self.btn_commit)
        layout.addLayout(btn_row)

    def set_message(self, message: str) -> None:
        self.msg_edit.setPlainText(message)
        self.btn_commit.setEnabled(bool(message.strip()))

    def _commit(self) -> None:
        message = self.msg_edit.toPlainText().strip()
        if not message:
            return
        # Stage all working-tree changes (tracked mods + untracked) so the commit
        # actually captures them. `git commit` on a repo with only unstaged changes
        # commits nothing but still exits 0, so we must add first.
        proc = subprocess.run(
            ["git", "-C", str(self.info.repo), "add", "-A"],
            capture_output=True,
            text=True,
        )
        proc = subprocess.run(
            ["git", "-C", str(self.info.repo), "commit", "-m", message],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0 and "nothing to commit" not in proc.stdout:
            self.result_message = proc.stdout.strip()
            self.accept()
        else:
            self.result_message = proc.stdout.strip() or proc.stderr.strip()
            self.msg_edit.setPlainText(
                self.msg_edit.toPlainText()
                + "\n\n[commit failed]\n"
                + (proc.stdout + proc.stderr).strip()
            )


def present_commit(name: str, repo: Path, parent: QWidget | None = None) -> tuple[bool, str]:
    """Gather info, draft a message, and run the commit dialog.

    Returns ``(committed, detail)``.
    """
    info = collect_commit_info(repo)
    if not info.has_changes:
        return False, "No changes to commit."

    dialog = CommitDialog(name, info, parent)
    try:
        api_key = openrouter_api_key()
        draft = draft_commit_message(info, api_key) if api_key else ""
        dialog.set_message(draft)
        dialog.btn_commit.setEnabled(bool(draft.strip()))
    except Exception as exc:  # noqa: BLE001 — show a friendly status on model failure
        dialog.set_message("")
        dialog.msg_edit.setPlainText(f"Could not draft a message: {exc}")

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False, "Cancelled by user."
    return True, getattr(dialog, "result_message", "committed.")