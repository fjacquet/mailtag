"""Taxonomy rules: validated senders, learned senders and domains (spec sections 2 to 5)."""

import contextlib
import fcntl
import json
import os
import tempfile
import threading
from pathlib import Path

from loguru import logger

from .utils.domain_utils import extract_domain, is_non_commercial_domain_cached

_FILES = ("validated", "senders", "domains", "folder_overrides")


def write_json_files(files: dict[Path, object]) -> None:
    """Write several JSON files all or nothing: every temp file first, then the renames."""
    staged: list[tuple[str, Path]] = []
    try:
        for path, data in files.items():
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
            staged.append((tmp, path))
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
    except BaseException:
        for tmp, _ in staged:
            Path(tmp).unlink(missing_ok=True)
        raise
    for tmp, path in staged:
        os.replace(tmp, path)


def write_json_atomic(path: Path, data) -> None:
    """Write JSON through a temp file in the same folder, then rename it over the target."""
    write_json_files({Path(path): data})


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
    changes as a list of operations; `save` takes an exclusive file lock and, if another process
    wrote since, reloads the files and replays the operations, then writes every changed file
    all or nothing. Lookups reload, under a shared lock, the files another process has saved.
    The lock is flock(2): it does not cross a Docker Desktop VM boundary (see CLAUDE.md).
    """

    def __init__(self, directory: Path, min_agreements: int = 2, read_only: bool = False):
        self.directory = Path(directory)
        self.min_agreements = min_agreements
        self.read_only = read_only
        self._ops: list[tuple] = []
        self._touched: set[str] = set()
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
        return (stat.st_ino, stat.st_mtime_ns, stat.st_size)

    def _disk_changed(self) -> bool:
        return any(self._stamp(name) != self._stamps.get(name) for name in _FILES)

    @contextlib.contextmanager
    def _file_lock(self, exclusive: bool):
        lock_path = self.directory / ".lock"
        if not exclusive and not lock_path.exists():
            yield  # nobody has saved with a lock yet; do not create files just to read
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            try:
                yield
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)

    def _reload(self) -> None:
        for name in _FILES:
            self._stamps[name] = self._stamp(name)
            setattr(self, name, _load(self._path(name)))

    def _replay(self) -> set[str]:
        """Reload the files and apply this store's unsaved operations on top."""
        self._reload()
        changed: set[str] = set()
        for op in self._ops:
            changed |= self._apply(op)
        return changed

    def _refresh(self) -> None:
        """Pick up what another process saved, keeping this store's unsaved operations."""
        if self._disk_changed():
            with self._file_lock(exclusive=False):
                self._replay()

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
            changed = self._apply(op)
            if not self.read_only:  # a dry run applies in memory and never saves
                self._ops.append(op)
                self._touched |= changed

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
            with self._file_lock(exclusive=True):
                changed = self._replay() if self._disk_changed() else set(self._touched)
                write_json_files({self._path(name): getattr(self, name) for name in changed})
                for name in changed:
                    self._stamps[name] = self._stamp(name)
                self._ops.clear()
                self._touched.clear()
