"""Gmail through the API (spec docs/superpowers/specs/2026-09-28-gmail-api-taxonomy-design.md).

No real Gmail call: every test uses `FakeGmail`, an in-memory stand-in for the `service` object
returned by `googleapiclient.discovery.build("gmail", "v1", ...)`.
"""

import base64
import email
from datetime import date, datetime

import httplib2
import pytest
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

from mailtag.archive import run_archive
from mailtag.config import FastParseConfig, GmailConfig
from mailtag.gmail_api import (
    PROMOTIONS,
    GmailApiService,
    GmailLabelClient,
    criteria_query,
    move_changes,
    selection,
)
from mailtag.pending_archive import PendingArchive
from mailtag.routing import RoutedMail, route_to_action_folders

# --------------------------------------------------------------------------------------------------
# FakeGmail: minimal in-memory stand-in for the Gmail API `service` object.
# --------------------------------------------------------------------------------------------------


def http_error(status: int = 500, content: bytes = b"boom") -> HttpError:
    return HttpError(httplib2.Response({"status": status}), content)


RATE_LIMITED = b'{"error": {"errors": [{"reason": "rateLimitExceeded"}]}}'


@pytest.fixture(autouse=True)
def no_sleep(mocker):
    return mocker.patch("mailtag.gmail_api.time.sleep")


class _Req:
    def __init__(self, fn):
        self._fn = fn

    def execute(self, **kwargs):
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
            stored = msg.get("headers", {}).get("Message-ID", "").strip("<>")
            if stored != token[len("rfc822msgid:") :]:
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
        self.errors_by_id: dict[str, Exception] = {}
        self.errors_once: dict[str, Exception] = {}  # raised on the first get of that id only
        self.batch_error: Exception | None = None  # raised by the whole batch request
        self.batch_sizes: list[int] = []

    def new_batch_http_request(self, callback=None):
        return _FakeBatch(self, callback)

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


class _FakeBatch:
    """googleapiclient's BatchHttpRequest: one callback per sub-request, errors passed, not raised."""

    def __init__(self, gmail: FakeGmail, callback):
        self.gmail = gmail
        self.callback = callback
        self.requests: list[tuple[str, _Req]] = []

    def add(self, request, callback=None, request_id=None):
        self.requests.append((request_id, request))

    def execute(self, http=None):
        if self.gmail.batch_error:
            err, self.gmail.batch_error = self.gmail.batch_error, None
            raise err
        self.gmail.batch_sizes.append(len(self.requests))
        for request_id, request in self.requests:
            try:
                response, exception = request.execute(), None
            except HttpError as e:
                response, exception = None, e
            self.callback(request_id, response, exception)


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

    def list(self, userId="me", labelIds=None, q="", includeSpamTrash=False, pageToken=None, maxResults=None):
        def call():
            self.gmail._raise_if_needed()
            self.gmail.list_calls.append(
                {"labelIds": labelIds, "q": q, "includeSpamTrash": includeSpamTrash, "maxResults": maxResults}
            )
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
            if id in self.gmail.errors_by_id:
                raise self.gmail.errors_by_id[id]
            if id in self.gmail.errors_once:
                raise self.gmail.errors_once.pop(id)
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
        assert criteria_query(["HEADER", "Message-ID", "<a@b>"]) == "rfc822msgid:a@b"

    def test_header_message_id_without_angle_brackets(self):
        assert criteria_query(["HEADER", "Message-ID", "a@b"]) == "rfc822msgid:a@b"

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

    def test_promotions_to_category_leaves_inbox(self):
        # Leaving INBOX is archiving (spec): a mail filed from Promotions to a category folder
        # must lose INBOX too, or it stays visible in the inbox.
        assert move_changes("Promotions", "Archive/Achats", {"Archive/Achats": "L3"}, "SPAM") == (
            ["L3"],
            ["INBOX"],
        )

    def test_spam_to_action_folder(self):
        assert move_changes("SPAM", "4-Pour info", {"4-Pour info": "L4"}, "SPAM") == (["L4"], ["SPAM"])

    def test_spam_to_promotions_adds_inbox(self):
        # A source other than INBOX/Promotions moving to Promotions must add INBOX back,
        # else the mail vanishes into All Mail (selection() requires INBOX + CATEGORY_PROMOTIONS).
        assert move_changes("SPAM", "Promotions", {}, "SPAM") == (
            ["CATEGORY_PROMOTIONS", "INBOX"],
            ["CATEGORY_PERSONAL", "CATEGORY_SOCIAL", "CATEGORY_UPDATES", "CATEGORY_FORUMS", "SPAM"],
        )

    def test_user_label_to_promotions_adds_inbox(self):
        label_ids = {"github": "Label_github"}
        assert move_changes("github", "Promotions", label_ids, "SPAM") == (
            ["CATEGORY_PROMOTIONS", "INBOX"],
            ["CATEGORY_PERSONAL", "CATEGORY_SOCIAL", "CATEGORY_UPDATES", "CATEGORY_FORUMS", "Label_github"],
        )


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

    def test_http_error_400_becomes_connection_error(self):
        client, fake = make_client()
        fake.error = http_error(400)
        with pytest.raises(ConnectionError):
            client.list_folders()

    def test_network_error_becomes_connection_error(self):
        client, fake = make_client()
        fake.error = TimeoutError("timed out")
        with pytest.raises(ConnectionError):
            client.list_folders()

    def test_httplib2_error_becomes_connection_error(self):
        client, fake = make_client()
        fake.error = httplib2.ServerNotFoundError("dns lookup failed")
        with pytest.raises(ConnectionError):
            client.list_folders()

    def test_folder_exists_is_case_insensitive(self):
        client, _ = make_client(labels={"Domaines/Santé": "L2"})
        assert client.folder_exists("domaines/santé") is True

    def test_create_folder_skips_existing_casefold_match(self):
        client, fake = make_client(labels={"Domaines/Santé": "L2"})
        client.create_folder("domaines/SANTÉ")
        assert fake.label_ids == {"Domaines/Santé": "L2"}


class TestGmailLabelClientSearch:
    def test_search_paginates_across_all_pages(self):
        messages = {str(i): {"labelIds": {"L1"}} for i in range(5)}
        client, fake = make_client(labels={"1-A traiter": "L1"}, messages=messages, page_size=2)
        client.select_folder("1-A traiter")

        ids = client.search()

        assert sorted(ids) == [str(i) for i in range(5)]
        assert len(fake.list_calls) == 3  # 5 ids, page_size=2 -> 3 pages
        assert fake.list_calls[0]["maxResults"] == 500

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

    def test_fetch_skips_message_missing_with_404(self):
        messages = {
            "1": {"labelIds": {"INBOX"}, "headers": {"Message-ID": "<a>"}},
            "2": {"labelIds": {"INBOX"}, "headers": {"Message-ID": "<b>"}},
        }
        client, fake = make_client(messages=messages)
        fake.errors_by_id = {"1": http_error(404)}
        client.select_folder("INBOX")

        field = b"BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]"
        result = client.fetch(["1", "2"], [field])

        assert "1" not in result
        assert "2" in result

    def test_fetch_reraises_non_404_http_error(self):
        messages = {"1": {"labelIds": {"INBOX"}, "headers": {"Message-ID": "<a>"}}}
        client, fake = make_client(messages=messages)
        fake.errors_by_id = {"1": http_error(500)}
        client.select_folder("INBOX")

        field = b"BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]"
        with pytest.raises(ConnectionError):
            client.fetch(["1"], [field])


class TestBatchedFetch:
    @staticmethod
    def _messages(n):
        return {
            f"{i:03d}": {"labelIds": {"INBOX"}, "headers": {"Message-ID": f"<{i}>"}, "raw": b"x"}
            for i in range(n)
        }

    def test_headers_are_fetched_in_batches_of_50(self):
        client, fake = make_client(messages=self._messages(120))
        client.select_folder("INBOX")

        result = client.fetch(list(fake.by_id), [b"BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]"])

        assert fake.batch_sizes == [50, 50, 20]
        assert len(result) == 120

    def test_bodies_are_fetched_in_batches_of_10(self):
        client, fake = make_client(messages=self._messages(25))
        client.select_folder("INBOX")

        result = client.fetch(list(fake.by_id), [b"BODY.PEEK[]"])

        assert fake.batch_sizes == [10, 10, 5]
        assert result["000"][b"BODY[]"] == b"x"

    def test_rate_limited_messages_are_retried_after_the_pause(self, no_sleep):
        client, fake = make_client(messages=self._messages(3))
        fake.errors_once = {"001": http_error(403, RATE_LIMITED)}
        client.select_folder("INBOX")

        result = client.fetch(list(fake.by_id), [b"BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]"])

        assert sorted(result) == ["000", "001", "002"]
        assert fake.batch_sizes == [3, 1]
        no_sleep.assert_any_call(60)

    def test_batch_request_failure_becomes_connection_error(self):
        client, fake = make_client(messages=self._messages(2))
        fake.batch_error = httplib2.ServerNotFoundError("dns lookup failed")
        client.select_folder("INBOX")

        with pytest.raises(ConnectionError):
            client.fetch(list(fake.by_id), [b"BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]"])

    def test_batches_are_paced_under_the_per_user_quota(self, mocker, no_sleep):
        mocker.patch("mailtag.gmail_api.time.monotonic", return_value=100.0)
        client, fake = make_client(messages=self._messages(100))
        client.select_folder("INBOX")

        client.fetch(list(fake.by_id), [b"BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]"])

        assert pytest.approx(1.25) in [c.args[0] for c in no_sleep.call_args_list]


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

    def test_move_resolves_destination_label_case_insensitively(self):
        messages = {"m1": {"labelIds": {"INBOX"}}}
        client, fake = make_client(labels={"Domaines/Santé": "L2"}, messages=messages)
        client.select_folder("INBOX")

        client.move(["m1"], "domaines/santé")

        assert fake.batch_modify_calls[0]["addLabelIds"] == ["L2"]


class TestExecuteRetries:
    def test_execute_passes_num_retries(self, mocker):
        request = mocker.Mock()

        GmailLabelClient._execute(request)

        request.execute.assert_called_once_with(num_retries=5)

    def test_rate_limit_waits_out_the_minute_then_retries(self, mocker, no_sleep):
        request = mocker.Mock()
        request.execute.side_effect = [http_error(403, RATE_LIMITED), {"ok": 1}]

        assert GmailLabelClient._execute(request) == {"ok": 1}

        no_sleep.assert_any_call(60)

    def test_429_waits_then_retries(self, mocker, no_sleep):
        request = mocker.Mock()
        request.execute.side_effect = [http_error(429), {"ok": 1}]

        assert GmailLabelClient._execute(request) == {"ok": 1}

        no_sleep.assert_any_call(60)

    def test_rate_limit_gives_up_after_five_waits(self, mocker, no_sleep):
        request = mocker.Mock()
        request.execute.side_effect = http_error(403, RATE_LIMITED)

        with pytest.raises(ConnectionError):
            GmailLabelClient._execute(request)

        assert [c.args for c in no_sleep.call_args_list].count((60,)) == 5

    def test_other_403_is_not_retried(self, mocker, no_sleep):
        request = mocker.Mock()
        request.execute.side_effect = http_error(403, b'{"error": {"errors": [{"reason": "forbidden"}]}}')

        with pytest.raises(ConnectionError):
            GmailLabelClient._execute(request)

        assert request.execute.call_count == 1

    def test_calls_are_paced_under_the_per_user_quota(self, mocker, no_sleep):
        mocker.patch("mailtag.gmail_api.time.monotonic", return_value=100.0)
        request = mocker.Mock()

        GmailLabelClient._execute(request)
        GmailLabelClient._execute(request)

        waits = [c.args[0] for c in no_sleep.call_args_list]
        assert waits and 0 < waits[-1] <= 0.05


# --------------------------------------------------------------------------------------------------
# GmailApiService (Task 2)
# --------------------------------------------------------------------------------------------------

GMAIL_CONFIG = GmailConfig(credentials_file="creds.json", token_file="token.json")
FAST = FastParseConfig()


class TestGmailApiServiceConnect:
    def test_connect_yields_service_with_gmail_label_client(self, mocker):
        fake = FakeGmail()
        mocker.patch("mailtag.gmail_api.get_gmail_service", return_value=fake)

        service = GmailApiService(GMAIL_CONFIG, FAST)
        with service.connect() as provider:
            assert provider is service
            assert isinstance(provider.client, GmailLabelClient)
            assert provider.client.service is fake

    def test_connect_raises_connection_error_when_service_is_none(self, mocker):
        mocker.patch("mailtag.gmail_api.get_gmail_service", return_value=None)

        service = GmailApiService(GMAIL_CONFIG, FAST)
        with pytest.raises(ConnectionError):
            with service.connect():
                pass

    def test_connect_raises_connection_error_on_refresh_error(self, mocker):
        mocker.patch("mailtag.gmail_api.get_gmail_service", side_effect=RefreshError("expired"))

        service = GmailApiService(GMAIL_CONFIG, FAST)
        with pytest.raises(ConnectionError, match="token.json"):
            with service.connect():
                pass


class TestGmailApiServiceFlow:
    def test_get_email_headers_returns_routing_fields(self):
        messages = {
            "m1": {
                "labelIds": {"INBOX"},
                "headers": {
                    "From": "sender@example.com",
                    "Subject": "Hello",
                    "Message-ID": "<abc@example.com>",
                    "List-Unsubscribe": "<mailto:unsub@example.com>",
                },
            }
        }
        fake = FakeGmail(messages=messages)
        service = GmailApiService(GMAIL_CONFIG, FAST)
        service.client = GmailLabelClient(fake)

        headers = service.get_email_headers(["m1"])

        assert headers["m1"]["sender_address"] == "sender@example.com"
        assert headers["m1"]["subject"] == "Hello"
        assert headers["m1"]["message_id"] == "<abc@example.com>"
        assert headers["m1"]["has_unsubscribe"] is True
        assert headers["m1"]["is_bulk"] is True

    def test_batch_move_emails_creates_label_and_removes_inbox(self):
        messages = {"m1": {"labelIds": {"INBOX"}}}
        fake = FakeGmail(messages=messages)
        service = GmailApiService(GMAIL_CONFIG, FAST)
        service.client = GmailLabelClient(fake)
        service.client.select_folder("INBOX")

        service.batch_move_emails(["m1"], "1-A traiter")

        assert "1-A traiter" in fake.label_ids
        call = fake.batch_modify_calls[0]
        assert call["removeLabelIds"] == ["INBOX"]
        assert call["addLabelIds"] == [fake.label_ids["1-A traiter"]]


# --------------------------------------------------------------------------------------------------
# End-to-end flow on a fake Gmail (Task 3)
# --------------------------------------------------------------------------------------------------

TODAY = date(2026, 9, 27)


class TestArchiveSweep:
    def test_archives_to_category_and_learns_from_review(self, mocker, tmp_path):
        labels = {
            "4-Pour info": "L4",
            "5-A revoir": "L5",
            "Domaines/Santé": "L_dom_sante",
            "github": "L_github",
        }
        messages = {
            "a": {
                "labelIds": {"L4", "L_github"},
                "headers": {"Message-ID": "<a>"},
                "date": date(2026, 9, 1),
            },
            "b": {
                "labelIds": {"L_dom_sante"},
                "headers": {"Message-ID": "<b>"},
                "date": date(2026, 9, 1),
            },
        }
        fake = FakeGmail(labels=labels, messages=messages)
        service = GmailApiService(GMAIL_CONFIG, FAST)
        service.client = GmailLabelClient(fake)

        pending = PendingArchive(tmp_path / "pending.json")
        pending.add("<a>", "Santé", "sender-a@example.com", "2026-09-01")
        pending.add("<b>", None, "sender-b@example.com", "2026-09-01")
        rules = mocker.MagicMock()

        result = run_archive(service, pending, rules, days=7, today=TODAY)

        assert result == {"archived": 1, "learned": 1, "orphans": 0}
        # The mail moved to its category: the action label is gone, other labels (github) survive.
        assert messages["a"]["labelIds"] == {"L_github", "L_dom_sante"}
        rules.set_validated.assert_called_once_with("sender-b@example.com", "Santé")
        assert pending.items() == []


class TestRouteToActionFolders:
    def test_promotions_mail_keeps_inbox_and_gains_category(self, tmp_path):
        messages = {"m1": {"labelIds": {"INBOX"}}}
        fake = FakeGmail(messages=messages)
        service = GmailApiService(GMAIL_CONFIG, FAST)
        service.client = GmailLabelClient(fake)
        service.client.select_folder("INBOX")

        pending = PendingArchive(tmp_path / "pending.json")
        mail = RoutedMail(
            uid="m1",
            category="Achats",
            sender_address="shop@example.com",
            subject="Soldes -20%",
            message_id="<promo1>",
            has_unsubscribe=True,
            is_bulk=True,
        )

        moved = route_to_action_folders(service, pending, [mail], validate=False, today=TODAY)

        assert moved == 1
        assert messages["m1"]["labelIds"] == {"INBOX", "CATEGORY_PROMOTIONS"}
        assert pending.get("<promo1>") == {
            "category": "Achats",
            "sender": "shop@example.com",
            "added": TODAY.isoformat(),
        }
