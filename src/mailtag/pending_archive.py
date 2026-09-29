"""Category of each email waiting in an action folder, keyed by Message-ID (spec sections 2, 5, 6)."""

import fcntl
import json
import threading
from pathlib import Path

from loguru import logger

from .taxonomy_store import write_json_atomic


class PendingArchive:
    """JSON store `Message-ID -> {category, sender, added}`, shared by `run` and the webhook API.

    Each instance records its adds and removes as operations. `save` takes an exclusive flock on
    `<file>.lock`, reloads the file, replays the operations on top and writes it atomically, so
    concurrent instances (threads or processes) never overwrite each other's entries.
    The lock is flock(2): it does not cross a Docker Desktop VM boundary.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._ops: list[tuple] = []
        self._entries: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.error(f"Could not parse {self.path}, starting with an empty pending archive")
            return {}

    def _apply(self, op: tuple) -> None:
        if op[0] == "add":
            _, message_id, entry = op
            self._entries[message_id] = entry
        else:
            self._entries.pop(op[1], None)

    def add(self, message_id: str, category: str | None, sender: str, added: str) -> None:
        op = ("add", message_id, {"category": category, "sender": sender, "added": added})
        with self._lock:
            self._apply(op)
            self._ops.append(op)

    def get(self, message_id: str) -> dict | None:
        with self._lock:
            return self._entries.get(message_id)

    def remove(self, message_id: str) -> None:
        with self._lock:
            self._apply(("remove", message_id))
            self._ops.append(("remove", message_id))

    def items(self) -> list[tuple[str, dict]]:
        with self._lock:
            return list(self._entries.items())

    def save(self) -> None:
        with self._lock:
            if not self._ops:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.with_name(f"{self.path.name}.lock").open("a") as lock_file:
                fcntl.flock(lock_file, fcntl.LOCK_EX)
                try:
                    self._entries = self._load()
                    for op in self._ops:
                        self._apply(op)
                    write_json_atomic(self.path, self._entries)
                finally:
                    fcntl.flock(lock_file, fcntl.LOCK_UN)
            self._ops.clear()
