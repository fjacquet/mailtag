"""Gmail through the API (spec docs/superpowers/specs/2026-09-28-gmail-api-taxonomy-design.md).

No real Gmail call: every test uses `FakeGmail`, an in-memory stand-in for the `service` object
returned by `googleapiclient.discovery.build("gmail", "v1", ...)`.
"""

import base64
import email
from datetime import date, datetime

import httplib2
import pytest
from googleapiclient.errors import HttpError

from mailtag.gmail_api import (
    PROMOTIONS,
    GmailLabelClient,
    criteria_query,
    move_changes,
    selection,
)

# --------------------------------------------------------------------------------------------------
# FakeGmail: minimal in-memory stand-in for the Gmail API `service` object.
# --------------------------------------------------------------------------------------------------


def http_error(status: int = 500) -> HttpError:
    return HttpError(httplib2.Response({"status": status}), b"boom")


class _Req:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


def _query_matches(msg: dict, q: str) -> bool:
    if not q:
        return True
    for token in q.split():
        if token == "-category:promotions":
            if "CATEGORY_PROMOTIONS" in msg["labelIds"]:
                return False
        elif token == "-is:unread":
            if "UNREAD" in msg["labelIds"]:
                return False
        elif token == "-is:starred":
            if "STARRED" in msg["labelIds"]:
                return False
        elif token.startswith("before:"):
            cutoff = datetime.strptime(token[len("before:") :], "%Y/%m/%d").date()
            if msg.get("date") is None or msg["date"] >= cutoff:
                return False
        elif token.startswith("rfc822msgid:"):
            if msg.get("headers", {}).get("Message-ID") != token[len("rfc822msgid:") :]:
                return False
        else:
            raise ValueError(f"FakeGmail cannot interpret query token: {token!r}")
    return True


class FakeGmail:
    """Labels (name -> id, user labels only) and messages (id -> {labelIds, raw, headers, date})."""

    def __init__(self, labels=None, messages=None, page_size=1000):
        self.label_ids = dict(labels or {})
        self.by_id = messages or {}
        self.page_size = page_size
        self._next_id = 1
        self.list_calls: list[dict] = []
        self.batch_modify_calls: list[dict] = []
        self.error: Exception | None = None

    def users(self):
        return self

    def labels(self):
        return _LabelsResource(self)

    def messages(self):
        return _MessagesResource(self)

    def _raise_if_needed(self):
        if self.error:
            err, self.error = self.error, None
            raise err

    def _new_label_id(self) -> str:
        label_id = f"Label_{self._next_id}"
        self._next_id += 1
        return label_id


class _LabelsResource:
    def __init__(self, gmail: FakeGmail):
        self.gmail = gmail

    def list(self, userId="me"):
        def call():
            self.gmail._raise_if_needed()
            return {"labels": [{"id": i, "name": n, "type": "user"} for n, i in self.gmail.label_ids.items()]}

        return _Req(call)

    def create(self, userId="me", body=None):
        def call():
            self.gmail._raise_if_needed()
            name = body["name"]
            label_id = self.gmail._new_label_id()
            self.gmail.label_ids[name] = label_id
            return {"id": label_id, "name": name}

        return _Req(call)


class _MessagesResource:
    def __init__(self, gmail: FakeGmail):
        self.gmail = gmail

    def list(self, userId="me", labelIds=None, q="", includeSpamTrash=False, pageToken=None):
        def call():
            self.gmail._raise_if_needed()
            self.gmail.list_calls.append({"labelIds": labelIds, "q": q, "includeSpamTrash": includeSpamTrash})
            wanted = set(labelIds or [])
            matches = [
                mid
                for mid, msg in self.gmail.by_id.items()
                if wanted.issubset(msg["labelIds"])
                and (includeSpamTrash or "SPAM" not in msg["labelIds"])
                and _query_matches(msg, q)
            ]
            matches.sort()
            start = int(pageToken) if pageToken else 0
            page = matches[start : start + self.gmail.page_size]
            resp = {"messages": [{"id": mid} for mid in page]}
            if start + self.gmail.page_size < len(matches):
                resp["nextPageToken"] = str(start + self.gmail.page_size)
            return resp

        return _Req(call)

    def get(self, userId="me", id=None, format="metadata", metadataHeaders=None):
        def call():
            self.gmail._raise_if_needed()
            msg = self.gmail.by_id[id]
            if format == "raw":
                return {"id": id, "raw": base64.urlsafe_b64encode(msg["raw"]).decode()}
            wanted = {n.upper() for n in (metadataHeaders or [])}
            headers = [
                {"name": n, "value": v}
                for n, v in msg.get("headers", {}).items()
                if not wanted or n.upper() in wanted
            ]
            return {"id": id, "payload": {"headers": headers}}

        return _Req(call)

    def batchModify(self, userId="me", body=None):
        def call():
            self.gmail._raise_if_needed()
            self.gmail.batch_modify_calls.append(dict(body))
            add = set(body.get("addLabelIds") or [])
            remove = set(body.get("removeLabelIds") or [])
            for mid in body["ids"]:
                labels = self.gmail.by_id[mid]["labelIds"]
                labels |= add
                labels -= remove
            return {}

        return _Req(call)


# --------------------------------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------------------------------


class TestSelection:
    def test_inbox_excludes_promotions(self):
        assert selection("INBOX", {}, "SPAM") == (["INBOX"], "-category:promotions")

    def test_promotions_is_inbox_plus_category(self):
        assert selection(PROMOTIONS, {}, "SPAM") == (["INBOX", "CATEGORY_PROMOTIONS"], "")

    def test_junk_is_spam(self):
        assert selection("SPAM", {}, "SPAM") == (["SPAM"], "")

    def test_user_label_with_accents_and_punctuation(self):
        label_ids = {"Domaines/Énergie & Télécom": "Label_9"}
        assert selection("Domaines/Énergie & Télécom", label_ids, "SPAM") == (["Label_9"], "")

    def test_unknown_folder_raises_key_error(self):
        with pytest.raises(KeyError):
            selection("Nonexistent", {}, "SPAM")


class TestCriteriaQuery:
    def test_none_is_empty(self):
        assert criteria_query(None) == ""

    def test_all_is_empty(self):
        assert criteria_query(["ALL"]) == ""

    def test_seen_unflagged_before(self):
        assert criteria_query(["SEEN", "UNFLAGGED", "BEFORE", date(2026, 9, 21)]) == (
            "-is:unread -is:starred before:2026/09/21"
        )

    def test_header_message_id(self):
        assert criteria_query(["HEADER", "Message-ID", "<a@b>"]) == "rfc822msgid:<a@b>"

    def test_unsupported_criteria_raises(self):
        with pytest.raises(ValueError):
            criteria_query(["FLAGGED"])


class TestMoveChanges:
    def test_inbox_to_action_folder(self):
        assert move_changes("INBOX", "1-A traiter", {"1-A traiter": "L1"}, "SPAM") == (["L1"], ["INBOX"])

    def test_action_folder_to_category(self):
        label_ids = {"1-A traiter": "L1", "Domaines/Santé": "L2"}
        assert move_changes("1-A traiter", "Domaines/Santé", label_ids, "SPAM") == (["L2"], ["L1"])

    def test_inbox_to_promotions_keeps_inbox(self):
        assert move_changes("INBOX", "Promotions", {}, "SPAM") == (
            ["CATEGORY_PROMOTIONS"],
            ["CATEGORY_PERSONAL", "CATEGORY_SOCIAL", "CATEGORY_UPDATES", "CATEGORY_FORUMS"],
        )

    def test_promotions_to_category(self):
        assert move_changes("Promotions", "Archive/Achats", {"Archive/Achats": "L3"}, "SPAM") == (
            ["L3"],
            [],
        )

    def test_spam_to_action_folder(self):
        assert move_changes("SPAM", "4-Pour info", {"4-Pour info": "L4"}, "SPAM") == (["L4"], ["SPAM"])


# --------------------------------------------------------------------------------------------------
# GmailLabelClient
# --------------------------------------------------------------------------------------------------


def make_client(**fake_kwargs) -> tuple[GmailLabelClient, FakeGmail]:
    fake = FakeGmail(**fake_kwargs)
    return GmailLabelClient(fake), fake


class TestGmailLabelClientFolders:
    def test_list_folders_shape(self):
        client, _ = make_client(labels={"github": "Label_1", "TRAVELS": "Label_2"})
        folders = client.list_folders()
        names = [f[2] for f in folders]
        assert set(names) == {"github", "TRAVELS", "INBOX"}
        assert all(f[1] == b"/" for f in folders)

    def test_folder_exists_for_system_and_user_labels(self):
        client, _ = make_client(labels={"github": "Label_1"})
        assert client.folder_exists("INBOX") is True
        assert client.folder_exists("Promotions") is True
        assert client.folder_exists("SPAM") is True
        assert client.folder_exists("github") is True
        assert client.folder_exists("Domaines/Santé") is False

    def test_create_folder_caches_new_label(self):
        client, fake = make_client()
        client.create_folder("Domaines/Santé")
        assert client.folder_exists("Domaines/Santé") is True
        assert fake.label_ids["Domaines/Santé"].startswith("Label_")

    def test_select_unknown_folder_raises_key_error(self):
        client, _ = make_client()
        with pytest.raises(KeyError):
            client.select_folder("Nope")

    def test_http_error_becomes_connection_error(self):
        client, fake = make_client()
        fake.error = http_error()
        with pytest.raises(ConnectionError):
            client.list_folders()


class TestGmailLabelClientSearch:
    def test_search_paginates_across_all_pages(self):
        messages = {str(i): {"labelIds": {"L1"}} for i in range(5)}
        client, fake = make_client(labels={"1-A traiter": "L1"}, messages=messages, page_size=2)
        client.select_folder("1-A traiter")

        ids = client.search()

        assert sorted(ids) == [str(i) for i in range(5)]
        assert len(fake.list_calls) == 3  # 5 ids, page_size=2 -> 3 pages

    def test_numeric_looking_ids_round_trip(self):
        messages = {"123": {"labelIds": {"INBOX"}, "raw": b"From: a@b\r\n\r\nBody"}}
        client, _ = make_client(messages=messages)
        client.select_folder("INBOX")

        result = client.fetch([123], [b"BODY.PEEK[]"])

        assert 123 in result
        assert result[123][b"BODY[]"] == b"From: a@b\r\n\r\nBody"


class TestGmailLabelClientFetch:
    def test_fetch_header_fields(self):
        messages = {
            "123": {
                "labelIds": {"INBOX"},
                "headers": {
                    "From": "a@b.com",
                    "Subject": "Hi",
                    "Message-ID": "<x@y>",
                },
            },
            "124": {
                "labelIds": {"INBOX"},
                "headers": {"From": "c@d.com", "Subject": "Yo", "Message-ID": "<z@w>"},
            },
        }
        client, _ = make_client(messages=messages)
        client.select_folder("INBOX")

        field = b"BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID)]"
        result = client.fetch(["123", 124], [field])

        assert set(result.keys()) == {"123", 124}
        key = b"BODY[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID)]"
        parsed = email.message_from_bytes(result["123"][key])
        assert parsed["From"] == "a@b.com"
        assert parsed["Subject"] == "Hi"
        assert parsed["Message-ID"] == "<x@y>"
        parsed124 = email.message_from_bytes(result[124][key])
        assert parsed124["From"] == "c@d.com"

    def test_fetch_raw_body(self):
        raw = b"From: a@b\r\nSubject: Hi\r\n\r\nBody text"
        messages = {"1": {"labelIds": {"INBOX"}, "raw": raw}}
        client, _ = make_client(messages=messages)
        client.select_folder("INBOX")

        result = client.fetch(["1"], [b"BODY.PEEK[]"])

        assert result["1"][b"BODY[]"] == raw


class TestGmailLabelClientMove:
    def test_move_from_inbox_creates_label_and_removes_only_inbox(self):
        messages = {"m1": {"labelIds": {"INBOX", "Label_github"}}}
        client, fake = make_client(labels={"github": "Label_github"}, messages=messages)
        client.select_folder("INBOX")

        assert client.folder_exists("1-A traiter") is False
        client.create_folder("1-A traiter")
        client.move(["m1"], "1-A traiter")

        assert len(fake.batch_modify_calls) == 1
        call = fake.batch_modify_calls[0]
        assert call["removeLabelIds"] == ["INBOX"]
        new_label = fake.label_ids["1-A traiter"]
        assert call["addLabelIds"] == [new_label]
        assert messages["m1"]["labelIds"] == {"Label_github", new_label}

    def test_move_chunks_over_a_thousand_ids(self):
        messages = {str(i): {"labelIds": {"INBOX"}} for i in range(1500)}
        client, fake = make_client(labels={"4-Pour info": "L4"}, messages=messages)
        client.select_folder("INBOX")

        client.move([str(i) for i in range(1500)], "4-Pour info")

        assert len(fake.batch_modify_calls) == 2
        assert len(fake.batch_modify_calls[0]["ids"]) == 1000
        assert len(fake.batch_modify_calls[1]["ids"]) == 500

    def test_move_to_promotions_keeps_inbox_and_drops_categories(self):
        messages = {"m1": {"labelIds": {"INBOX", "CATEGORY_PERSONAL"}}}
        client, fake = make_client(messages=messages)
        client.select_folder("INBOX")

        client.move(["m1"], "Promotions")

        call = fake.batch_modify_calls[0]
        assert call["addLabelIds"] == ["CATEGORY_PROMOTIONS"]
        assert set(call["removeLabelIds"]) == {
            "CATEGORY_PERSONAL",
            "CATEGORY_SOCIAL",
            "CATEGORY_UPDATES",
            "CATEGORY_FORUMS",
        }
        assert messages["m1"]["labelIds"] == {"INBOX", "CATEGORY_PROMOTIONS"}
