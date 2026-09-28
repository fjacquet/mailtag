"""Taxonomy rules: validated senders, learned senders and domains (spec sections 2 to 5)."""

import fcntl
import json
import os
import tempfile
import threading
from pathlib import Path

from loguru import logger

from .utils.domain_utils import extract_domain, is_non_commercial_domain_cached

_FILES = ("validated", "senders", "domains", "folder_overrides")


def write_json_atomic(path: Path, data) -> None:
    """Write JSON through a temp file in the same folder, then rename it over the target."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def normalize_address(address: str) -> str:
    return (address or "").strip().lower()


def _load(path: Path) -> dict:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.error(f"Could not parse {path}, starting empty")
        return {}
    return data if isinstance(data, dict) else {}


class TaxonomyStore:
    """Signals 1, 3 and 4 of the taxonomy mode, and learning from nomic/Gemma agreements.

    Several processes share these files (the webhook API and a `run`). Each store keeps its
    changes as a list of operations; `save` takes a file lock, reloads the files, replays the
    operations and writes, so no process overwrites another's rules. Lookups reload the files
    when another process has saved since.
    """

    def __init__(self, directory: Path, min_agreements: int = 2, read_only: bool = False):
        self.directory = Path(directory)
        self.min_agreements = min_agreements
        self.read_only = read_only
        self._ops: list[tuple] = []
        self._stamps: dict[str, tuple | None] = {}
        # One store is shared by the webhook API's thread pool
        self._lock = threading.RLock()
        self._reload()

    def _path(self, name: str) -> Path:
        return self.directory / f"{name}.json"

    def _stamp(self, name: str) -> tuple | None:
        try:
            stat = self._path(name).stat()
        except FileNotFoundError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def _reload(self) -> None:
        for name in _FILES:
            self._stamps[name] = self._stamp(name)
            setattr(self, name, _load(self._path(name)))

    def _refresh(self) -> None:
        """Pick up what another process saved, keeping this store's unsaved operations."""
        if any(self._stamp(name) != self._stamps.get(name) for name in _FILES):
            self._reload()
            for op in self._ops:
                self._apply(op)

    def _apply(self, op: tuple) -> set[str]:
        """Apply one operation to the in-memory rules; return the files it changed."""
        kind, *args = op
        if kind == "agree":
            sender, category = args
            if sender in self.validated:
                return set()
            entry = self.senders.get(sender)
            if entry is None:
                self.senders[sender] = {"category": category, "agreements": 1}
            elif entry["category"] == category:
                entry["agreements"] += 1
            else:
                logger.info(f"Contradiction for {sender}: {entry['category']} vs {category}, entry removed")
                del self.senders[sender]
            return {"senders"}
        if kind == "validate":
            sender, category = args
            self.validated[sender] = category
            if self.senders.pop(sender, None) is not None:
                return {"validated", "senders"}
            return {"validated"}
        if kind == "folder":
            folder, category = args
            self.folder_overrides[folder] = category
            return {"folder_overrides"}
        learned, domains = args  # "replace"
        self.senders = {**self.senders, **{s: dict(e) for s, e in learned.items()}}
        self.domains = dict(domains)
        return {"senders", "domains"}

    def _record(self, op: tuple) -> None:
        with self._lock:
            self._refresh()
            self._apply(op)
            self._ops.append(op)

    def category_for(self, sender_address: str) -> str | None:
        sender = normalize_address(sender_address)
        with self._lock:
            self._refresh()
            return self._category_for(sender)

    def _category_for(self, sender: str) -> str | None:
        if sender in self.validated:
            return self.validated[sender]
        entry = self.senders.get(sender)
        if entry and entry["agreements"] >= self.min_agreements:
            return entry["category"]
        domain = extract_domain(sender)
        if domain and not is_non_commercial_domain_cached(domain):
            return self.domains.get(domain)
        return None

    def record_agreement(self, sender_address: str, category: str) -> None:
        sender = normalize_address(sender_address)
        if sender:
            self._record(("agree", sender, category))

    def set_validated(self, sender_address: str, category: str) -> None:
        self._record(("validate", normalize_address(sender_address), category))

    def set_folder_category(self, folder: str, category: str | None) -> None:
        """Audit decision for an old folder; None means the folder holds no category."""
        self._record(("folder", folder, category))

    def replace_rules(self, learned: dict[str, dict], domains: dict[str, str]) -> None:
        """Install rules from `build`; runtime entries for senders `build` does not know are kept."""
        self._record(("replace", {s: dict(e) for s, e in learned.items()}, dict(domains)))

    def save(self) -> None:
        if self.read_only:
            return
        with self._lock:
            if not self._ops:
                return
            self.directory.mkdir(parents=True, exist_ok=True)
            with (self.directory / ".lock").open("w") as lock_file:
                fcntl.flock(lock_file, fcntl.LOCK_EX)
                try:
                    self._reload()
                    changed: set[str] = set()
                    for op in self._ops:
                        changed |= self._apply(op)
                    for name in changed:
                        write_json_atomic(self._path(name), getattr(self, name))
                        self._stamps[name] = self._stamp(name)
                    self._ops.clear()
                finally:
                    fcntl.flock(lock_file, fcntl.LOCK_UN)
