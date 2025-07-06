from __future__ import annotations

import base64
import builtins
from typing import Any


class MockGmailService:
    """A mock Gmail service that simulates the Google API service."""

    def __init__(self):
        self.labels_data = {
            "labels": [
                {"id": "IMPORTANT", "name": "MyLabel"},
                {"id": "INBOX", "name": "Inbox"},
            ]
        }
        self.messages_data: dict[str, dict[str, Any]] = {}

    def users(self):
        return self

    def labels(self):
        return self

    def messages(self):
        return self

    def list(self, **kwargs):
        if "userId" in kwargs and kwargs["userId"] == "me":
            if self.messages_data and "q" in kwargs:
                return self.MockRequest({"messages": [{"id": msg_id} for msg_id in self.messages_data]})
            return self.MockRequest(self.labels_data)
        return self

    def get(self, **kwargs):
        msg_id = kwargs.get("id")
        if msg_id and msg_id in self.messages_data:
            return self.MockRequest(self.messages_data[msg_id])
        return self

    def execute(self):
        # This is a simplified mock. In a real scenario, you would inspect
        # the method calls leading to `execute` to return the correct data.
        if self.messages_data:
            return {"messages": [{"id": msg_id} for msg_id in self.messages_data]}
        return self.labels_data

    class MockRequest:
        def __init__(self, data):
            self.data = data

        def execute(self):
            return self.data

    def add_message(self, msg_id: str, label_ids: builtins.list[str], subject: str, body: str):
        encoded_body = base64.urlsafe_b64encode(body.encode("utf-8")).decode("utf-8")
        self.messages_data[msg_id] = {
            "id": msg_id,
            "labelIds": label_ids,
            "payload": {
                "headers": [{"name": "Subject", "value": subject}],
                "parts": [{"mimeType": "text/plain", "body": {"data": encoded_body}}],
            },
        }

    def get_message(self, msg_id: str) -> dict[str, Any] | None:
        return self.messages_data.get(msg_id)
