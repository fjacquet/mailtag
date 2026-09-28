"""Gmail through the API: the small IMAPClient subset the taxonomy flow uses, translated to Gmail API
calls (spec docs/superpowers/specs/2026-09-28-gmail-api-taxonomy-design.md)."""

import base64
import re

from googleapiclient.errors import HttpError

PROMOTIONS = "Promotions"
_CATEGORIES = ("CATEGORY_PERSONAL", "CATEGORY_SOCIAL", "CATEGORY_UPDATES", "CATEGORY_FORUMS")

_HEADER_FIELDS_RE = re.compile(rb"HEADER\.FIELDS \(([^)]*)\)")
_MOVE_CHUNK = 1000


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
        return f"rfc822msgid:{criteria[2]}"
    raise ValueError(f"Unsupported search: {criteria}")


def move_changes(source: str, dest: str, label_ids: dict[str, str], junk: str) -> tuple[list[str], list[str]]:
    """Labels to add and remove when a mail moves from `source` to `dest`; nothing else is touched."""
    source_ids = {"INBOX": ["INBOX"], PROMOTIONS: [], junk: ["SPAM"]}.get(source, [label_ids.get(source)])
    if dest == PROMOTIONS:
        return ["CATEGORY_PROMOTIONS"], [*_CATEGORIES, *(i for i in source_ids if i not in ("INBOX", None))]
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
    def _execute(request):
        try:
            return request.execute()
        except HttpError as e:
            raise ConnectionError(str(e)) from e

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
        return name in self._labels

    def create_folder(self, name: str) -> None:
        self._ensure_labels()
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
            for field in fields:
                if b"BODY[]" in field or b"BODY.PEEK[]" in field:
                    resp = self._execute(
                        self.service.users().messages().get(userId="me", id=msg_id, format="raw")
                    )
                    entry[b"BODY[]"] = base64.urlsafe_b64decode(resp["raw"])
                elif b"HEADER.FIELDS (" in field:
                    names = _HEADER_FIELDS_RE.search(field).group(1).decode().split()
                    resp = self._execute(
                        self.service.users()
                        .messages()
                        .get(userId="me", id=msg_id, format="metadata", metadataHeaders=names)
                    )
                    headers = resp.get("payload", {}).get("headers", [])
                    text = "".join(f"{h['name']}: {h['value']}\r\n" for h in headers)
                    entry[field.replace(b".PEEK", b"")] = text.encode("utf-8")
                # else: ignore (e.g. X-GM-LABELS, not exposed by the Gmail API metadata call)
            if entry:
                result[uid] = entry
        return result

    def move(self, uids: list, dest: str) -> None:
        self._ensure_labels()
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
