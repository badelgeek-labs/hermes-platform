"""Unit tests for the local Discord forum-tag plugin."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from discord_forum_posts.tools import DiscordApiError, DiscordForumPostsClient


class FakeClient(DiscordForumPostsClient):
    def __init__(self) -> None:
        super().__init__(token="test")
        self.requests: list[tuple[str, str, dict | None]] = []
        self.forum = {
            "id": "100",
            "type": 15,
            "available_tags": [
                {"id": "1", "name": "À valider"},
                {"id": "2", "name": "Publié"},
            ],
        }
        self.post = {"id": "200", "parent_id": "100", "applied_tags": ["1"]}

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        self.requests.append((method, path, payload))
        if path == "/channels/200" and method == "GET":
            return self.post
        if path == "/channels/100" and method == "GET":
            return self.forum
        if path == "/channels/200" and method == "PATCH":
            return {"id": "200", "applied_tags": payload["applied_tags"]}
        if path == "/channels/100/threads" and method == "POST":
            return {"id": "300", "applied_tags": payload["applied_tags"]}
        if path == "/channels/200/messages" and method == "POST":
            return {"id": "400", "channel_id": "200"}
        raise AssertionError(f"Unexpected request: {method} {path}")


class DiscordForumPostsClientTests(unittest.TestCase):
    def test_replace_uses_only_parent_forum_tags(self) -> None:
        result = FakeClient().update_post_tags("200", ["2"], "replace")

        self.assertEqual(result["applied_tags"], ["2"])
        self.assertEqual(result["tags"], [{"id": "2", "name": "Publié"}])

    def test_rejects_unknown_tag(self) -> None:
        with self.assertRaisesRegex(DiscordApiError, "Unknown tag IDs: 99"):
            FakeClient().update_post_tags("200", ["99"], "replace")

    def test_add_preserves_existing_tag(self) -> None:
        result = FakeClient().update_post_tags("200", ["2"], "add")

        self.assertEqual(result["applied_tags"], ["1", "2"])

    def test_create_post_sends_initial_message_and_existing_tag(self) -> None:
        client = FakeClient()

        result = client.create_forum_post("100", "Review: Siham", "Draft reply", ["1"])

        self.assertEqual(result["post_id"], "300")
        self.assertEqual(
            client.requests[-1],
            (
                "POST",
                "/channels/100/threads",
                {
                    "name": "Review: Siham",
                    "message": {
                        "content": "Draft reply",
                        "allowed_mentions": {"parse": []},
                    },
                    "applied_tags": ["1"],
                },
            ),
        )

    def test_create_post_rejects_unknown_tag_before_posting(self) -> None:
        client = FakeClient()

        with self.assertRaisesRegex(DiscordApiError, "Unknown tag IDs: 99"):
            client.create_forum_post("100", "Review", "Draft reply", ["99"])

        self.assertEqual(client.requests, [("GET", "/channels/100", None)])

    def test_send_message_verifies_post_belongs_to_a_forum(self) -> None:
        client = FakeClient()

        result = client.send_post_message("200", "Follow-up")

        self.assertEqual(
            result, {"forum_id": "100", "post_id": "200", "message_id": "400"}
        )
        self.assertEqual(
            client.requests[-1],
            (
                "POST",
                "/channels/200/messages",
                {"content": "Follow-up", "allowed_mentions": {"parse": []}},
            ),
        )


if __name__ == "__main__":
    unittest.main()
