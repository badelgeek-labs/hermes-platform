"""Hermes plugin exposing safe Discord forum-post operations."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from .tools import (
    ACTION_CUSTOM_ID_PREFIX,
    DiscordApiError,
    DiscordForumPostsClient,
)


logger = logging.getLogger(__name__)


def _json_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _allowed_user_ids() -> set[str]:
    """Return the explicit Discord user allow-list used by this deployment."""

    return {
        user_id.strip()
        for user_id in os.environ.get("DISCORD_ALLOWED_USERS", "").split(",")
        if user_id.strip().isdigit()
    }


def _action_label(interaction: Any, custom_id: str) -> str | None:
    """Read the label from the clicked component on the bot-authored message."""

    for row in getattr(getattr(interaction, "message", None), "components", []) or []:
        for component in getattr(row, "children", []) or []:
            if getattr(component, "custom_id", None) == custom_id:
                label = getattr(component, "label", None)
                if isinstance(label, str) and label.strip():
                    return " ".join(label.split())
    return None


def _session_key_for_forum_post(adapter: Any, interaction: Any) -> str:
    """Build the same default shared-thread key that Hermes uses for Discord messages."""

    from gateway.session import build_session_key

    channel = interaction.channel
    thread_id = str(interaction.channel_id)
    parent_id = str(
        getattr(channel, "parent_id", None)
        or getattr(getattr(channel, "parent", None), "id", "")
        or ""
    )
    source = adapter.build_source(
        chat_id=thread_id,
        chat_name=getattr(channel, "name", None),
        chat_type="thread",
        user_id=str(interaction.user.id),
        user_name=getattr(interaction.user, "display_name", None),
        thread_id=thread_id,
        guild_id=str(interaction.guild_id) if interaction.guild_id else None,
        parent_chat_id=parent_id or None,
    )
    return build_session_key(source)


def _component_action_event(
    action_id: str, action_label: str, thread_id: str, actor_id: str
) -> str:
    return "\n".join(
        [
            "[DISCORD_COMPONENT_ACTION]",
            f"action_id={action_id}",
            f"action_label={action_label}",
            f"thread_id={thread_id}",
            f"actor_id={actor_id}",
        ]
    )


def _wire_discord_component_actions(ctx: Any, bot: Any, adapter: Any) -> None:
    """Register one scoped native Discord listener for this plugin's buttons."""

    async def on_interaction(interaction: Any) -> None:
        data = getattr(interaction, "data", None) or {}
        custom_id = data.get("custom_id")
        if not isinstance(custom_id, str) or not custom_id.startswith(ACTION_CUSTOM_ID_PREFIX):
            return

        action_id = custom_id.removeprefix(ACTION_CUSTOM_ID_PREFIX)
        message_author = getattr(getattr(interaction, "message", None), "author", None)
        if (
            message_author is None
            or getattr(bot, "user", None) is None
            or getattr(message_author, "id", None) != getattr(bot.user, "id", None)
        ):
            await interaction.response.send_message(
                "This action is not managed by this Hermes bot.", ephemeral=True
            )
            return

        actor_id = str(interaction.user.id)
        if actor_id not in _allowed_user_ids():
            await interaction.response.send_message(
                "You are not authorized to use this action.", ephemeral=True
            )
            return

        action_label = _action_label(interaction, custom_id)
        if not action_label:
            await interaction.response.send_message(
                "The action label could not be read.", ephemeral=True
            )
            return

        try:
            session_key = _session_key_for_forum_post(adapter, interaction)
            accepted = ctx.inject_message(
                _component_action_event(
                    action_id=action_id,
                    action_label=action_label,
                    thread_id=str(interaction.channel_id),
                    actor_id=actor_id,
                ),
                session_key=session_key,
            )
        except Exception:
            logger.exception("Failed to inject Discord forum action %s", action_id)
            accepted = False

        await interaction.response.send_message(
            "Action received." if accepted else "The action could not be delivered.",
            ephemeral=True,
        )

    bot.add_listener(on_interaction, "on_interaction")


def register(ctx: Any) -> None:
    """Register generic tools that only use tags defined on a parent forum."""

    def list_forum_tags(params: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        try:
            forum = DiscordForumPostsClient.from_environment().get_forum(
                params["forum_id"]
            )
            return _json_result(
                {
                    "ok": True,
                    "forum_id": forum["id"],
                    "forum_name": forum.get("name"),
                    "tags": [
                        {
                            "id": tag["id"],
                            "name": tag["name"],
                            "moderated": tag.get("moderated", False),
                        }
                        for tag in forum.get("available_tags", [])
                    ],
                }
            )
        except (DiscordApiError, KeyError, TypeError, ValueError) as error:
            return _json_result({"ok": False, "error": str(error)})

    def update_forum_post_tags(params: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        try:
            result = DiscordForumPostsClient.from_environment().update_post_tags(
                post_id=params["post_id"],
                tag_ids=params["tag_ids"],
                operation=params.get("operation", "replace"),
            )
            return _json_result({"ok": True, **result})
        except (DiscordApiError, KeyError, TypeError, ValueError) as error:
            return _json_result({"ok": False, "error": str(error)})

    def create_forum_post(params: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        try:
            result = DiscordForumPostsClient.from_environment().create_forum_post(
                forum_id=params["forum_id"],
                title=params["title"],
                content=params["content"],
                tag_ids=params["tag_ids"],
                actions=params.get("actions"),
            )
            return _json_result({"ok": True, **result})
        except (DiscordApiError, KeyError, TypeError, ValueError) as error:
            return _json_result({"ok": False, "error": str(error)})

    def send_post_message(params: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        try:
            result = DiscordForumPostsClient.from_environment().send_post_message(
                post_id=params["post_id"],
                content=params["content"],
                actions=params.get("actions"),
            )
            return _json_result({"ok": True, **result})
        except (DiscordApiError, KeyError, TypeError, ValueError) as error:
            return _json_result({"ok": False, "error": str(error)})

    ctx.register_tool(
        name="discord_list_forum_tags",
        toolset="discord_forum_posts",
        schema={
            "name": "discord_list_forum_tags",
            "description": (
                "List the tag IDs and names configured on a Discord forum. "
                "Use this before changing a forum post's tags."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "forum_id": {
                        "type": "string",
                        "description": "Discord forum channel ID.",
                    }
                },
                "required": ["forum_id"],
            },
        },
        handler=list_forum_tags,
    )
    ctx.register_tool(
        name="discord_update_forum_post_tags",
        toolset="discord_forum_posts",
        schema={
            "name": "discord_update_forum_post_tags",
            "description": (
                "Apply only tags already configured on the parent Discord forum to "
                "one forum post. This cannot create, rename, or delete forum tags."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "post_id": {
                        "type": "string",
                        "description": "Discord forum post (thread) ID.",
                    },
                    "tag_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 5,
                        "description": "Existing tag IDs from the parent forum.",
                    },
                    "operation": {
                        "type": "string",
                        "enum": ["replace", "add", "remove"],
                        "default": "replace",
                        "description": "Replace, add, or remove the specified tags.",
                    },
                },
                "required": ["post_id", "tag_ids"],
            },
        },
        handler=update_forum_post_tags,
    )
    ctx.register_tool(
        name="discord_create_forum_post",
        toolset="discord_forum_posts",
        schema={
            "name": "discord_create_forum_post",
            "description": (
                "Create one Discord forum post with its required initial message and "
                "existing parent-forum tags. This cannot create, rename, or delete tags."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "forum_id": {
                        "type": "string",
                        "description": "Discord forum channel ID.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Forum post title (1 to 100 characters).",
                    },
                    "content": {
                        "type": "string",
                        "description": "Initial forum post message (1 to 2,000 characters).",
                    },
                    "tag_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 5,
                        "description": "Existing tag IDs from the parent forum.",
                    },
                    "actions": {
                        "type": "array",
                        "maxItems": 25,
                        "description": (
                            "Optional generic Discord buttons. Their clicks are injected into "
                            "an existing Hermes session as structured action events."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "string",
                                    "description": "Stable action ID, such as shorter.",
                                },
                                "label": {
                                    "type": "string",
                                    "description": "Human-readable button label.",
                                },
                                "emoji": {
                                    "type": "string",
                                    "description": "Optional Unicode emoji.",
                                },
                            },
                            "required": ["id", "label"],
                        },
                    },
                },
                "required": ["forum_id", "title", "content", "tag_ids"],
            },
        },
        handler=create_forum_post,
    )
    ctx.register_tool(
        name="discord_send_post_message",
        toolset="discord_forum_posts",
        schema={
            "name": "discord_send_post_message",
            "description": "Send a message to an existing Discord forum post.",
            "parameters": {
                "type": "object",
                "properties": {
                    "post_id": {
                        "type": "string",
                        "description": "Discord forum post (thread) ID.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Message content (1 to 2,000 characters).",
                    },
                    "actions": {
                        "type": "array",
                        "maxItems": 25,
                        "description": "Optional generic Discord buttons.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "label": {"type": "string"},
                                "emoji": {"type": "string"},
                            },
                            "required": ["id", "label"],
                        },
                    },
                },
                "required": ["post_id", "content"],
            },
        },
        handler=send_post_message,
    )
    ctx.register_platform_handler(
        "discord",
        lambda bot, adapter: _wire_discord_component_actions(ctx, bot, adapter),
    )
