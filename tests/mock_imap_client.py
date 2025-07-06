from __future__ import annotations

import email
from typing import Any


class MockImapClient:
    """A mock IMAP client that simulates `imapclient.IMAPClient`."""

    def __init__(self, host: str, port: int | None = None, ssl: bool = True):
        self.host = host
        self.port = port
        self.ssl = ssl
        self._is_login = False
        self.mailboxes: dict[str, dict[int, dict[bytes, Any]]] = {
            "INBOX": {
                1: {
                    b"BODY[]": email.message_from_string(
                        "From: test@example.com\nSubject: Test\n\nTest body"
                    ).as_bytes(),
                    b"X-GM-LABELS": [b"\\Inbox", b"MyLabel"],
                }
            }
        }
        self.selected_folder: str | None = None

    def login(self, user, password):
        if not user or not password:
            raise Exception("Login failed")
        self._is_login = True

    def logout(self):
        self._is_login = False

    def is_login(self) -> bool:
        return self._is_login

    def select_folder(self, folder: str, readonly: bool = False):
        if folder not in self.mailboxes:
            raise Exception("Folder not found")
        self.selected_folder = folder

    def search(self, criteria: list[str]) -> list[int]:
        return list(self.mailboxes.get(self.selected_folder, {}).keys())

    def fetch(self, messages: list[int], data: list[bytes]) -> dict[int, dict[bytes, Any]]:
        if not self.selected_folder:
            return {}
        
        response = {}
        for msg_id in messages:
            if msg_id in self.mailboxes[self.selected_folder]:
                response[msg_id] = self.mailboxes[self.selected_folder][msg_id]
        return response

    def folder_exists(self, folder: str) -> bool:
        return folder in self.mailboxes

    def create_folder(self, folder: str):
        if not self.folder_exists(folder):
            self.mailboxes[folder] = {}

    def move(self, messages: list[int], destination: str):
        if not self.selected_folder or not self.folder_exists(destination):
            return

        for msg_id in messages:
            if msg_id in self.mailboxes[self.selected_folder]:
                self.mailboxes[destination][msg_id] = self.mailboxes[self.selected_folder].pop(msg_id)