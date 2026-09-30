"""Unit tests for the local Discord forum-post plugin."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from discord_forum_posts.tools import DiscordApiError, DiscordForumPostsClient
from discord_forum_posts import _wire_discord_component_actions


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


class FakeResponse:
    def __init__(self) -> None:
        self.messages: list[tuple[str, bool]] = []

    async def send_message(self, content: str, *, ephemeral: bool) -> None:
        self.messages.append((content, ephemeral))


class FakeContext:
    def __init__(self) -> None:
        self.injected: list[tuple[str, str]] = []

    def inject_message(self, content: str, *, session_key: str) -> bool:
        self.injected.append((content, session_key))
        return True


class FakeBot:
    def __init__(self) -> None:
        self.user = type("User", (), {"id": 999})()
        self.listeners: list[object] = []

    def add_listener(self, listener: object, event_name: str) -> None:
        self.listeners.append(listener)
        self.event_name = event_name


def fake_interaction(*, actor_id: int = 123) -> object:
    button = type(
        "Button",
        (), {"custom_id": "hermes-forum-posts:v1:shorter", "label": "Plus courte"},
    )()
    row = type("ActionRow", (), {"children": [button]})()
    author = type("Author", (), {"id": 999})()
    message = type("Message", (), {"author": author, "components": [row]})()
    user = type("User", (), {"id": actor_id, "display_name": "Ame"})()
    return type(
        "Interaction",
        (),
        {
            "data": {"custom_id": "hermes-forum-posts:v1:shorter"},
            "message": message,
            "user": user,
            "channel_id": 456,
            "response": FakeResponse(),
        },
    )()


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

    def test_create_post_sends_initial_message_tag_and_actions(self) -> None:
        client = FakeClient()

        result = client.create_forum_post(
            "100",
            "Review: Siham",
            "Draft reply",
            ["1"],
            actions=[
                {"id": "shorter", "label": "Plus courte", "emoji": "➖"},
                {"id": "ignore", "label": "Ignorer"},
            ],
        )

        self.assertEqual(result["post_id"], "300")
        self.assertEqual(
            result["actions"],
            [
                {"id": "shorter", "label": "Plus courte", "emoji": "➖"},
                {"id": "ignore", "label": "Ignorer"},
            ],
        )
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
                        "components": [
                            {
                                "type": 1,
                                "components": [
                                    {
                                        "type": 2,
                                        "style": 2,
                                        "custom_id": "hermes-forum-posts:v1:shorter",
                                        "label": "Plus courte",
                                        "emoji": {"name": "➖"},
                                    },
                                    {
                                        "type": 2,
                                        "style": 2,
                                        "custom_id": "hermes-forum-posts:v1:ignore",
                                        "label": "Ignorer",
                                    },
                                ],
                            }
                        ],
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

        result = client.send_post_message(
            "200", "Follow-up", actions=[{"id": "shorter", "label": "Plus courte"}]
        )

        self.assertEqual(
            result,
            {
                "forum_id": "100",
                "post_id": "200",
                "message_id": "400",
                "actions": [{"id": "shorter", "label": "Plus courte"}],
            },
        )
        self.assertEqual(
            client.requests[-1],
            (
                "POST",
                "/channels/200/messages",
                {
                    "content": "Follow-up",
                    "allowed_mentions": {"parse": []},
                    "components": [
                        {
                            "type": 1,
                            "components": [
                                {
                                    "type": 2,
                                    "style": 2,
                                    "custom_id": "hermes-forum-posts:v1:shorter",
                                    "label": "Plus courte",
                                }
                            ],
                        }
                    ],
                },
            ),
        )

    def test_rejects_duplicate_action_ids(self) -> None:
        client = FakeClient()

        with self.assertRaisesRegex(DiscordApiError, "Duplicate action id: shorter"):
            client.create_forum_post(
                "100",
                "Review",
                "Draft reply",
                ["1"],
                actions=[
                    {"id": "shorter", "label": "Plus courte"},
                    {"id": "shorter", "label": "Encore plus courte"},
                ],
            )

    def test_button_click_injects_a_descriptive_action_event(self) -> None:
        context = FakeContext()
        bot = FakeBot()
        interaction = fake_interaction()

        with patch.dict("os.environ", {"DISCORD_ALLOWED_USERS": "123"}, clear=False), patch(
            "discord_forum_posts._session_key_for_forum_post", return_value="test-session"
        ):
            _wire_discord_component_actions(context, bot, object())
            asyncio.run(bot.listeners[0](interaction))

        self.assertEqual(bot.event_name, "on_interaction")
        self.assertEqual(
            context.injected,
            [
                (
                    "[DISCORD_COMPONENT_ACTION]\n"
                    "action_id=shorter\n"
                    "action_label=Plus courte\n"
                    "thread_id=456\n"
                    "actor_id=123",
                    "test-session",
                )
            ],
        )
        self.assertEqual(interaction.response.messages, [("Action received.", True)])


if __name__ == "__main__":
    unittest.main()
