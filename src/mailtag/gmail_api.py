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
# Reads go in batch requests: one HTTP round trip for many messages (each still costs its own quota).
_HEADER_BATCH = 50
_BODY_BATCH = 10  # raw bodies can be large
_PROGRESS_EVERY = 500  # messages between two progress lines of a long fetch
_last_call = 0.0


def _pace(calls: int = 1) -> None:
    """Wait until `calls` more calls fit under the per-user quota, counting from the previous call."""
    global _last_call
    pause = _last_call + calls * _MIN_INTERVAL - time.monotonic()
    if pause > 0:
        time.sleep(pause)
    _last_call = time.monotonic()


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
        waits = 0
        while True:
            _pace()
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

    def _batch_get(self, ids: list[str], build, size: int) -> dict[str, dict]:
        """messages.get for every id, `size` per batch request; a missing (404) message is left out."""
        found: dict[str, dict] = {}
        began = time.monotonic()
        for start in range(0, len(ids), size):
            todo, waits = ids[start : start + size], 0
            while todo:
                limited: list[str] = []
                failed: list[Exception] = []

                def on_reply(request_id, response, exception, limited=limited, failed=failed):
                    if exception is None:
                        found[request_id] = response
                    elif isinstance(exception, HttpError) and exception.resp.status == 404:
                        logger.warning(
                            f"Gmail message {request_id} not found (404); skipping, like a missing UID."
                        )
                    elif isinstance(exception, HttpError) and _rate_limited(exception):
                        limited.append(request_id)
                    else:
                        failed.append(exception)

                batch = self.service.new_batch_http_request(callback=on_reply)
                for msg_id in todo:
                    batch.add(build(msg_id), request_id=msg_id)
                _pace(len(todo))
                try:
                    batch.execute()
                except (HttpError, httplib2.HttpLib2Error, OSError) as e:
                    raise ConnectionError(str(e)) from e
                if failed:
                    raise ConnectionError(str(failed[0])) from failed[0]
                if limited and waits >= _RATE_LIMIT_TRIES:
                    raise ConnectionError(f"Gmail quota still exceeded for {len(limited)} messages")
                if limited:
                    waits += 1
                    logger.warning(f"Gmail quota reached, pausing {_RATE_LIMIT_WAIT}s ({waits})")
                    time.sleep(_RATE_LIMIT_WAIT)
                todo = limited
            done = min(start + size, len(ids))
            if len(ids) > _PROGRESS_EVERY and (done % _PROGRESS_EVERY < size or done == len(ids)):
                rate = done / max(time.monotonic() - began, 1e-6)
                logger.info(f"Gmail: {done}/{len(ids)} messages read ({rate:.0f}/s)")
        return found

    def fetch(self, uids: list, fields: list[bytes]) -> dict:
        messages = self.service.users().messages()
        ids = list(dict.fromkeys(str(uid) for uid in uids))  # a batch refuses a repeated request id
        replies: list[tuple[bytes, dict[str, dict]]] = []
        for field in fields:
            if b"BODY[]" in field or b"BODY.PEEK[]" in field:
                got = self._batch_get(
                    ids, lambda msg_id: messages.get(userId="me", id=msg_id, format="raw"), _BODY_BATCH
                )
                replies.append((b"BODY[]", got))
            elif b"HEADER.FIELDS (" in field:
                names = _HEADER_FIELDS_RE.search(field).group(1).decode().split()
                got = self._batch_get(
                    ids,
                    lambda msg_id, names=names: messages.get(
                        userId="me", id=msg_id, format="metadata", metadataHeaders=names
                    ),
                    _HEADER_BATCH,
                )
                replies.append((field.replace(b".PEEK", b""), got))
            # else: ignore (e.g. X-GM-LABELS, not exposed by the Gmail API metadata call)

        result = {}
        for uid in uids:
            msg_id = str(uid)
            if any(msg_id not in got for _, got in replies):
                continue  # missing (404) for one of the fields
            entry: dict[bytes, bytes] = {}
            for key, got in replies:
                resp = got[msg_id]
                if key == b"BODY[]":
                    entry[key] = base64.urlsafe_b64decode(resp["raw"])
                else:
                    headers = resp.get("payload", {}).get("headers", [])
                    entry[key] = "".join(f"{h['name']}: {h['value']}\r\n" for h in headers).encode("utf-8")
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
            self.client.logout()
