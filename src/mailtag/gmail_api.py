"""Gmail through the API: the small IMAPClient subset the taxonomy flow uses, translated to Gmail API
calls (spec docs/superpowers/specs/2026-09-28-gmail-api-taxonomy-design.md)."""

import base64
import re
import time
from contextlib import contextmanager

import httplib2
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from loguru import logger

from mailtag.config import FastParseConfig, GmailConfig
from mailtag.gmail_auth import get_gmail_service
from mailtag.imap_service import ImapService

PROMOTIONS = "Promotions"
_CATEGORIES = ("CATEGORY_PERSONAL", "CATEGORY_SOCIAL", "CATEGORY_UPDATES", "CATEGORY_FORUMS")

_HEADER_FIELDS_RE = re.compile(rb"HEADER\.FIELDS \(([^)]*)\)")
_MOVE_CHUNK = 1000
# Gmail allows 250 quota units per second per user and messages.get costs 5: pace calls under 40 a second.
_MIN_INTERVAL = 0.025
# The quota is counted per minute: a rate-limited call waits the minute out, at most this many times.
_RATE_LIMIT_WAIT = 60
_RATE_LIMIT_TRIES = 5
_last_call = 0.0


def _rate_limited(e: HttpError) -> bool:
    return e.resp.status == 429 or (e.resp.status == 403 and "ratelimitexceeded" in str(e.content).lower())


def selection(folder: str, label_ids: dict[str, str], junk: str) -> tuple[list[str], str]:
    """Gmail labelIds and query of a MailTag folder."""
    if folder == "INBOX":
        return ["INBOX"], "-category:promotions"  # promos stay in the inbox, under their own tab
    if folder == PROMOTIONS:
        return ["INBOX", "CATEGORY_PROMOTIONS"], ""
    if folder == junk:
        return ["SPAM"], ""
    return [label_ids[folder]], ""  # KeyError for an unknown folder, like a failed IMAP select


def criteria_query(criteria: list | None) -> str:
    """The IMAP searches the taxonomy flow uses, as a Gmail query."""
    if not criteria or criteria == ["ALL"]:
        return ""
    if criteria[:3] == ["SEEN", "UNFLAGGED", "BEFORE"]:
        return f"-is:unread -is:starred before:{criteria[3]:%Y/%m/%d}"
    if criteria[:2] == ["HEADER", "Message-ID"]:
        return f"rfc822msgid:{criteria[2].strip('<>')}"
    raise ValueError(f"Unsupported search: {criteria}")


def move_changes(source: str, dest: str, label_ids: dict[str, str], junk: str) -> tuple[list[str], list[str]]:
    """Labels to add and remove when a mail moves from `source` to `dest`; nothing else is touched."""
    source_ids = {"INBOX": ["INBOX"], PROMOTIONS: ["INBOX"], junk: ["SPAM"]}.get(
        source, [label_ids.get(source)]
    )
    if dest == PROMOTIONS:
        # A source other than INBOX must get INBOX back, or the mail vanishes into All Mail.
        add = ["CATEGORY_PROMOTIONS"] if source == "INBOX" else ["CATEGORY_PROMOTIONS", "INBOX"]
        return add, [*_CATEGORIES, *(i for i in source_ids if i not in ("INBOX", None))]
    return [label_ids[dest]], [i for i in source_ids if i]


class GmailLabelClient:
    """The small IMAPClient subset the taxonomy flow uses (`select_folder`, `search`, `fetch`, `move`,
    `folder_exists`, `create_folder`, `list_folders`, `logout`), implemented on top of the Gmail API."""

    def __init__(self, service, junk: str = "SPAM"):
        self.service = service
        self._junk = junk
        self._labels: dict[str, str] = {}
        self._labels_loaded = False
        self._selected: str | None = None

    @staticmethod
    def _execute(request, ignore_status: int | None = None):
        global _last_call
        waits = 0
        while True:
            pause = _last_call + _MIN_INTERVAL - time.monotonic()
            if pause > 0:
                time.sleep(pause)
            _last_call = time.monotonic()
            try:
                return request.execute(num_retries=5)
            except HttpError as e:
                if ignore_status is not None and e.resp.status == ignore_status:
                    return None
                if _rate_limited(e) and waits < _RATE_LIMIT_TRIES:
                    waits += 1
                    logger.warning(f"Gmail quota reached, pausing {_RATE_LIMIT_WAIT}s ({waits})")
                    time.sleep(_RATE_LIMIT_WAIT)
                    continue
                raise ConnectionError(str(e)) from e
            except (httplib2.HttpLib2Error, OSError) as e:
                raise ConnectionError(str(e)) from e

    def _canonical(self, name: str) -> str:
        """Existing label name matching `name` case-insensitively, else `name` unchanged."""
        for existing in self._labels:
            if existing.casefold() == name.casefold():
                return existing
        return name

    def _ensure_labels(self) -> None:
        if self._labels_loaded:
            return
        resp = self._execute(self.service.users().labels().list(userId="me"))
        self._labels = {
            label["name"]: label["id"] for label in resp.get("labels", []) if label.get("type") == "user"
        }
        self._labels_loaded = True

    def list_folders(self):
        self._ensure_labels()
        return [((), b"/", name) for name in self._labels] + [((), b"/", "INBOX")]

    def folder_exists(self, name: str) -> bool:
        if name in ("INBOX", PROMOTIONS, self._junk):
            return True
        self._ensure_labels()
        return any(existing.casefold() == name.casefold() for existing in self._labels)

    def create_folder(self, name: str) -> None:
        self._ensure_labels()
        if any(existing.casefold() == name.casefold() for existing in self._labels):
            return
        resp = self._execute(
            self.service.users()
            .labels()
            .create(
                userId="me",
                body={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
            )
        )
        self._labels[name] = resp["id"]

    def select_folder(self, name: str, readonly: bool = False) -> None:
        self._ensure_labels()
        name = self._canonical(name)
        selection(name, self._labels, self._junk)  # KeyError for an unknown folder, like a failed IMAP select
        self._selected = name

    def search(self, criteria: list | None = None) -> list[str]:
        self._ensure_labels()
        label_ids, base_q = selection(self._selected, self._labels, self._junk)
        q = " ".join(part for part in (base_q, criteria_query(criteria)) if part)
        ids: list[str] = []
        page_token = None
        while True:
            kwargs = {
                "userId": "me",
                "labelIds": label_ids,
                "includeSpamTrash": self._selected == self._junk,
                "maxResults": 500,
            }
            if q:
                kwargs["q"] = q
            if page_token:
                kwargs["pageToken"] = page_token
            resp = self._execute(self.service.users().messages().list(**kwargs))
            ids.extend(message["id"] for message in resp.get("messages", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return ids

    def fetch(self, uids: list, fields: list[bytes]) -> dict:
        result = {}
        for uid in uids:
            msg_id = str(uid)
            entry: dict[bytes, bytes] = {}
            not_found = False
            for field in fields:
                if b"BODY[]" in field or b"BODY.PEEK[]" in field:
                    resp = self._execute(
                        self.service.users().messages().get(userId="me", id=msg_id, format="raw"),
                        ignore_status=404,
                    )
                    if resp is None:
                        not_found = True
                        break
                    entry[b"BODY[]"] = base64.urlsafe_b64decode(resp["raw"])
                elif b"HEADER.FIELDS (" in field:
                    names = _HEADER_FIELDS_RE.search(field).group(1).decode().split()
                    resp = self._execute(
                        self.service.users()
                        .messages()
                        .get(userId="me", id=msg_id, format="metadata", metadataHeaders=names),
                        ignore_status=404,
                    )
                    if resp is None:
                        not_found = True
                        break
                    headers = resp.get("payload", {}).get("headers", [])
                    text = "".join(f"{h['name']}: {h['value']}\r\n" for h in headers)
                    entry[field.replace(b".PEEK", b"")] = text.encode("utf-8")
                # else: ignore (e.g. X-GM-LABELS, not exposed by the Gmail API metadata call)
            if not_found:
                logger.warning(f"Gmail message {msg_id} not found (404); skipping, like a missing IMAP UID.")
                continue
            if entry:
                result[uid] = entry
        return result

    def move(self, uids: list, dest: str) -> None:
        self._ensure_labels()
        dest = self._canonical(dest)
        add, remove = move_changes(self._selected, dest, self._labels, self._junk)
        str_uids = [str(uid) for uid in uids]
        for i in range(0, len(str_uids), _MOVE_CHUNK):
            chunk = str_uids[i : i + _MOVE_CHUNK]
            self._execute(
                self.service.users()
                .messages()
                .batchModify(userId="me", body={"ids": chunk, "addLabelIds": add, "removeLabelIds": remove})
            )

    def logout(self) -> None:
        pass

    def is_login(self) -> bool:
        return True


class GmailApiService(ImapService):
    """The Gmail inbox through the Gmail API, using the same taxonomy flow as `ImapService`
    (`get_email_headers`, `get_full_emails`, `batch_move_emails` are inherited
    unchanged; only `connect()` is replaced)."""

    def __init__(self, config: GmailConfig, fast_parse_config: FastParseConfig):
        super().__init__(config, fast_parse_config)

    @contextmanager
    def connect(self):
        try:
            service = get_gmail_service(self.config.credentials_file, self.config.token_file)
        except RefreshError as e:
            raise ConnectionError(
                "Gmail credentials could not be refreshed; delete token.json and re-authorize."
            ) from e
        if service is None:
            raise ConnectionError("Could not authenticate with the Gmail API.")
        self.client = GmailLabelClient(service, junk=self.config.junk_folder_name or "SPAM")
        try:
            yield self
        finally:
            self._stop_metrics_thread()
            self.client.logout()
