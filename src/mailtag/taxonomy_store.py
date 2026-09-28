"""Taxonomy rules: validated senders, learned senders and domains (spec sections 2 to 5)."""

import json
import os
import tempfile
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
    """Signals 1, 3 and 4 of the taxonomy mode, and learning from nomic/Gemma agreements."""

    def __init__(self, directory: Path, min_agreements: int = 2, read_only: bool = False):
        self.directory = Path(directory)
        self.min_agreements = min_agreements
        self.read_only = read_only
        self.validated: dict[str, str] = _load(self.directory / "validated.json")
        self.senders: dict[str, dict] = _load(self.directory / "senders.json")
        self.domains: dict[str, str] = _load(self.directory / "domains.json")
        self.folder_overrides: dict[str, str | None] = _load(self.directory / "folder_overrides.json")
        self._dirty: set[str] = set()

    def category_for(self, sender_address: str) -> str | None:
        sender = normalize_address(sender_address)
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
        if not sender or sender in self.validated:
            return
        entry = self.senders.get(sender)
        if entry is None:
            self.senders[sender] = {"category": category, "agreements": 1}
        elif entry["category"] == category:
            entry["agreements"] += 1
        else:
            logger.info(f"Contradiction for {sender}: {entry['category']} vs {category}, entry removed")
            del self.senders[sender]
        self._dirty.add("senders")

    def set_validated(self, sender_address: str, category: str) -> None:
        sender = normalize_address(sender_address)
        self.validated[sender] = category
        self._dirty.add("validated")
        if self.senders.pop(sender, None) is not None:
            self._dirty.add("senders")

    def set_folder_category(self, folder: str, category: str | None) -> None:
        """Audit decision for an old folder; None means the folder holds no category."""
        self.folder_overrides[folder] = category
        self._dirty.add("folder_overrides")

    def replace_rules(self, learned: dict[str, dict], domains: dict[str, str]) -> None:
        """Install rules from `build`; runtime entries for senders `build` does not know are kept."""
        self.senders = {**self.senders, **learned}
        self.domains = dict(domains)
        self._dirty.update({"senders", "domains"})

    def save(self) -> None:
        if self.read_only:
            return
        for name in _FILES:
            if name in self._dirty:
                write_json_atomic(self.directory / f"{name}.json", getattr(self, name))
        self._dirty.clear()
