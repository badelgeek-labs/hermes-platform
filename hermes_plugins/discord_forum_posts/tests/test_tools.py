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
        self.message = {"id": "400", "channel_id": "200"}

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
        if path == "/channels/200/messages/400" and method == "GET":
            return self.message
        if path == "/channels/200/messages/400" and method == "PATCH":
            return {"id": "400", "channel_id": "200"}
        if path == "/channels/200" and method == "DELETE":
            return {}
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


class FakeAsyncSessionStore:
    def __init__(self) -> None:
        self.calls: list[tuple[object, bool]] = []

    async def get_or_create_session(
        self, source: object, *, touch_activity: bool
    ) -> object:
        self.calls.append((source, touch_activity))
        return type("Session", (), {"session_key": "test-session"})()


class FakeGatewayRunner:
    def __init__(self) -> None:
        self.async_session_store = FakeAsyncSessionStore()


class FakeAdapter:
    def __init__(self) -> None:
        self.gateway_runner = FakeGatewayRunner()
        self.source: dict[str, object] | None = None

    def build_source(self, **kwargs: object) -> object:
        self.source = kwargs
        return kwargs


class FakeBot:
    def __init__(self) -> None:
        self.user = type("User", (), {"id": 999})()
        self.listeners: list[object] = []

    def add_listener(self, listener: object, event_name: str) -> None:
        self.listeners.append(listener)
        self.event_name = event_name


def fake_interaction(*, actor_id: int = 123, custom_id: str | None = None) -> object:
    custom_id = "hermes-forum-posts:v1:shorter" if custom_id is None else custom_id
    button = type(
        "Button",
        (), {"custom_id": custom_id, "label": "Plus courte"},
    )()
    row = type("ActionRow", (), {"children": [button]})()
    author = type("Author", (), {"id": 999})()
    message = type("Message", (), {"author": author, "components": [row]})()
    user = type("User", (), {"id": actor_id, "display_name": "Ame"})()
    return type(
        "Interaction",
        (),
        {
            "data": {"custom_id": custom_id},
            "message": message,
            "user": user,
            "channel_id": 456,
            "channel": type("Channel", (), {"name": "Review", "parent_id": 789})(),
            "guild_id": 321,
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

    def test_create_post_maps_every_interactive_button_style(self) -> None:
        client = FakeClient()

        client.create_forum_post(
            "100",
            "Styles",
            "Draft reply",
            ["1"],
            actions=[
                {"id": "primary", "label": "Primary", "style": "primary"},
                {"id": "secondary", "label": "Secondary", "style": "secondary"},
                {"id": "success", "label": "Success", "style": "success"},
                {"id": "danger", "label": "Danger", "style": "danger"},
            ],
        )

        buttons = client.requests[-1][2]["message"]["components"][0]["components"]
        self.assertEqual([button["style"] for button in buttons], [1, 2, 3, 4])
        self.assertEqual(
            [button["custom_id"] for button in buttons],
            [
                "hermes-forum-posts:v1:primary",
                "hermes-forum-posts:v1:secondary",
                "hermes-forum-posts:v1:success",
                "hermes-forum-posts:v1:danger",
            ],
        )

    def test_link_button_has_url_and_no_custom_id(self) -> None:
        client = FakeClient()

        result = client.send_post_message(
            "200",
            "Follow-up",
            actions=[
                {
                    "label": "Voir l'avis",
                    "emoji": "🔗",
                    "style": "link",
                    "url": "https://example.com/review",
                }
            ],
        )

        self.assertEqual(result["actions"][0]["url"], "https://example.com/review")
        button = client.requests[-1][2]["components"][0]["components"][0]
        self.assertEqual(button["style"], 5)
        self.assertEqual(button["url"], "https://example.com/review")
        self.assertNotIn("custom_id", button)

    def test_rejects_invalid_link_url(self) -> None:
        with self.assertRaisesRegex(DiscordApiError, "HTTP or HTTPS url"):
            FakeClient().send_post_message(
                "200",
                "Follow-up",
                actions=[{"label": "Link", "style": "link", "url": "ftp://example.com"}],
            )

    def test_rejects_url_for_interactive_action(self) -> None:
        with self.assertRaisesRegex(DiscordApiError, "only allowed for link"):
            FakeClient().send_post_message(
                "200",
                "Follow-up",
                actions=[
                    {
                        "id": "publish",
                        "label": "Publish",
                        "url": "https://example.com/review",
                    }
                ],
            )

    def test_edit_message_replaces_content_and_actions(self) -> None:
        client = FakeClient()

        result = client.edit_post_message(
            "200",
            "400",
            "Replacement",
            actions=[{"id": "publish", "label": "Publier", "style": "success"}],
        )

        self.assertEqual(
            result,
            {
                "forum_id": "100",
                "post_id": "200",
                "message_id": "400",
                "actions": [{"id": "publish", "label": "Publier", "style": "success"}],
            },
        )
        self.assertEqual(
            client.requests[-1],
            (
                "PATCH",
                "/channels/200/messages/400",
                {
                    "content": "Replacement",
                    "allowed_mentions": {"parse": []},
                    "components": [
                        {
                            "type": 1,
                            "components": [
                                {
                                    "type": 2,
                                    "style": 3,
                                    "custom_id": "hermes-forum-posts:v1:publish",
                                    "label": "Publier",
                                }
                            ],
                        }
                    ],
                },
            ),
        )

    def test_edit_rejects_message_from_another_post(self) -> None:
        client = FakeClient()
        client.message["channel_id"] = "999"

        with self.assertRaisesRegex(DiscordApiError, "belonging to post_id"):
            client.edit_post_message("200", "400", "Replacement", actions=[])

    def test_delete_forum_post(self) -> None:
        client = FakeClient()

        self.assertEqual(
            client.delete_forum_post("200"),
            {"forum_id": "100", "post_id": "200", "deleted": True},
        )
        self.assertEqual(client.requests[-1], ("DELETE", "/channels/200", None))

    def test_button_click_injects_a_descriptive_action_event(self) -> None:
        context = FakeContext()
        bot = FakeBot()
        adapter = FakeAdapter()
        interaction = fake_interaction()

        with patch.dict("os.environ", {"DISCORD_ALLOWED_USERS": "123"}, clear=False):
            _wire_discord_component_actions(context, bot, adapter)
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
        self.assertEqual(adapter.source["chat_id"], "456")
        self.assertEqual(adapter.source["thread_id"], "456")
        self.assertEqual(adapter.source["parent_chat_id"], "789")
        self.assertEqual(
            adapter.gateway_runner.async_session_store.calls,
            [(adapter.source, False)],
        )

    def test_link_click_does_not_inject_an_hermes_event(self) -> None:
        context = FakeContext()
        bot = FakeBot()
        adapter = FakeAdapter()
        interaction = fake_interaction(custom_id="")

        _wire_discord_component_actions(context, bot, adapter)
        asyncio.run(bot.listeners[0](interaction))

        self.assertEqual(context.injected, [])
        self.assertEqual(adapter.gateway_runner.async_session_store.calls, [])
        self.assertEqual(interaction.response.messages, [])


if __name__ == "__main__":
    unittest.main()
