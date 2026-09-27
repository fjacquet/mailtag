"""Category of each email waiting in an action folder, keyed by Message-ID (spec sections 2, 5, 6)."""

import json
import os
import tempfile
from pathlib import Path

from loguru import logger


class PendingArchive:
    """JSON store `Message-ID -> {category, sender, added}` with atomic saves."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._entries: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.error(f"Could not parse {self.path}, starting with an empty pending archive")
            return {}

    def add(self, message_id: str, category: str | None, sender: str, added: str) -> None:
        self._entries[message_id] = {"category": category, "sender": sender, "added": added}

    def get(self, message_id: str) -> dict | None:
        return self._entries.get(message_id)

    def remove(self, message_id: str) -> None:
        self._entries.pop(message_id, None)

    def items(self) -> list[tuple[str, dict]]:
        return list(self._entries.items())

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._entries, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
