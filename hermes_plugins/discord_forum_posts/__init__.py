"""Hermes plugin exposing safe Discord forum-post operations."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from .component_actions import ComponentActionStatuses
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


async def _session_key_for_forum_post(adapter: Any, interaction: Any) -> str:
    """Create or reuse this forum post's session using the live gateway configuration."""

    gateway_runner = getattr(adapter, "gateway_runner", None)
    if gateway_runner is None:
        raise RuntimeError("The Hermes gateway runner is unavailable.")
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
    session = await gateway_runner.async_session_store.get_or_create_session(
        source,
        touch_activity=False,
    )
    return str(session.session_key)


def _component_action_event(
    action_id: str,
    action_label: str,
    interaction_ref: str,
    thread_id: str,
    actor_id: str,
) -> str:
    return "\n".join(
        [
            "[DISCORD_COMPONENT_ACTION]",
            f"action_id={action_id}",
            f"action_label={action_label}",
            f"interaction_ref={interaction_ref}",
            f"thread_id={thread_id}",
            f"actor_id={actor_id}",
        ]
    )


def _wire_discord_component_actions(
    ctx: Any, bot: Any, adapter: Any, statuses: ComponentActionStatuses | None = None
) -> ComponentActionStatuses:
    """Register one scoped native Discord listener for this plugin's buttons."""

    statuses = statuses or ComponentActionStatuses()

    async def on_interaction(interaction: Any) -> None:
        data = getattr(interaction, "data", None) or {}
        custom_id = data.get("custom_id")
        if not isinstance(custom_id, str) or not custom_id.startswith(ACTION_CUSTOM_ID_PREFIX):
            return

        action_id = custom_id.removeprefix(ACTION_CUSTOM_ID_PREFIX)
        action_label = _action_label(interaction, custom_id) or action_id
        acknowledgement_started = time.perf_counter()
        try:
            interaction_ref = await statuses.acknowledge(interaction, action_label)
        except Exception:
            logger.exception(
                "Failed to acknowledge Discord forum action %s after %.3fs",
                action_id,
                time.perf_counter() - acknowledgement_started,
            )
            return
        logger.info(
            "Acknowledged Discord forum action %s in %.3fs",
            action_id,
            time.perf_counter() - acknowledgement_started,
        )

        try:
            message_author = getattr(getattr(interaction, "message", None), "author", None)
            if (
                message_author is None
                or getattr(bot, "user", None) is None
                or getattr(message_author, "id", None) != getattr(bot.user, "id", None)
            ):
                await statuses.complete(interaction_ref, success=False)
                return

            actor_id = str(interaction.user.id)
            if actor_id not in _allowed_user_ids():
                await statuses.complete(interaction_ref, success=False)
                return

            session_lookup_started = time.perf_counter()
            try:
                session_key = await _session_key_for_forum_post(adapter, interaction)
            except Exception:
                logger.exception(
                    "Failed to find a Hermes session for Discord forum action %s after %.3fs",
                    action_id,
                    time.perf_counter() - session_lookup_started,
                )
                await statuses.complete(interaction_ref, success=False)
                return
            logger.info(
                "Found Hermes session for Discord forum action %s in %.3fs",
                action_id,
                time.perf_counter() - session_lookup_started,
            )

            injection_started = time.perf_counter()
            try:
                accepted = ctx.inject_message(
                    _component_action_event(
                        action_id=action_id,
                        action_label=action_label,
                        interaction_ref=interaction_ref,
                        thread_id=str(interaction.channel_id),
                        actor_id=actor_id,
                    ),
                    session_key=session_key,
                )
            except Exception:
                logger.exception(
                    "Failed to inject Discord forum action %s after %.3fs",
                    action_id,
                    time.perf_counter() - injection_started,
                )
                accepted = False
            else:
                logger.info(
                    "Injected Discord forum action %s in %.3fs (accepted=%s)",
                    action_id,
                    time.perf_counter() - injection_started,
                    accepted,
                )
            if not accepted:
                await statuses.complete(interaction_ref, success=False)
        except Exception:
            logger.exception("Unexpected Discord forum action failure %s", action_id)
            await statuses.complete(interaction_ref, success=False)

    bot.add_listener(on_interaction, "on_interaction")
    return statuses


def register(ctx: Any) -> None:
    """Register generic tools that only use tags defined on a parent forum."""

    statuses = ComponentActionStatuses()

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

    def edit_post_message(params: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        try:
            result = DiscordForumPostsClient.from_environment().edit_post_message(
                post_id=params["post_id"],
                message_id=params["message_id"],
                content=params["content"],
                actions=params.get("actions"),
            )
            return _json_result({"ok": True, **result})
        except (DiscordApiError, KeyError, TypeError, ValueError) as error:
            return _json_result({"ok": False, "error": str(error)})

    def delete_forum_post(params: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        try:
            result = DiscordForumPostsClient.from_environment().delete_forum_post(
                post_id=params["post_id"]
            )
            return _json_result({"ok": True, **result})
        except (DiscordApiError, KeyError, TypeError, ValueError) as error:
            return _json_result({"ok": False, "error": str(error)})

    def complete_component_action(params: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        interaction_ref = params.get("interaction_ref")
        success = params.get("success")
        if not isinstance(interaction_ref, str) or not isinstance(success, bool):
            return _json_result({"ok": False, "error": "interaction_ref and success are required."})
        completed = statuses.complete_from_tool(interaction_ref, success)
        return _json_result({"ok": completed, "completed": completed})

    ctx.register_tool(
        name="discord_complete_component_action",
        toolset="discord_forum_posts",
        schema={
            "name": "discord_complete_component_action",
            "description": (
                "Finalize the ephemeral status for a generic Discord component action. "
                "Use the interaction_ref supplied in its action event."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "interaction_ref": {
                        "type": "string",
                        "description": "Correlation reference from DISCORD_COMPONENT_ACTION.",
                    },
                    "success": {
                        "type": "boolean",
                        "description": "Whether the downstream action finished successfully.",
                    },
                },
                "required": ["interaction_ref", "success"],
            },
        },
        handler=complete_component_action,
    )
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
                                "interaction_ref": {
                                    "type": "string",
                                    "description": "Persistent discord-ui modal reference.",
                                },
                                "label": {
                                    "type": "string",
                                    "description": "Human-readable button label.",
                                },
                                "emoji": {
                                    "type": "string",
                                    "description": "Optional Unicode emoji.",
                                },
                                "style": {
                                    "type": "string",
                                    "enum": ["primary", "secondary", "success", "danger", "link"],
                                    "default": "secondary",
                                    "description": "Button style; link buttons require url.",
                                },
                                "url": {
                                    "type": "string",
                                    "description": "HTTP(S) URL for a link button only.",
                                },
                            },
                            "required": ["label"],
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
                                "interaction_ref": {"type": "string"},
                                "label": {"type": "string"},
                                "emoji": {"type": "string"},
                                "style": {
                                    "type": "string",
                                    "enum": ["primary", "secondary", "success", "danger", "link"],
                                    "default": "secondary",
                                },
                                "url": {"type": "string"},
                            },
                            "required": ["label"],
                        },
                    },
                },
                "required": ["post_id", "content"],
            },
        },
        handler=send_post_message,
    )
    ctx.register_tool(
        name="discord_edit_post_message",
        toolset="discord_forum_posts",
        schema={
            "name": "discord_edit_post_message",
            "description": (
                "Edit one existing message in a Discord forum post. Supplying actions "
                "replaces its buttons; use an empty array to remove all buttons."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "post_id": {
                        "type": "string",
                        "description": "Discord forum post (thread) ID.",
                    },
                    "message_id": {
                        "type": "string",
                        "description": "Message ID belonging to that forum post.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Replacement message content (1 to 2,000 characters).",
                    },
                    "actions": {
                        "type": "array",
                        "maxItems": 25,
                        "description": "Replacement generic Discord buttons; [] removes buttons.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "interaction_ref": {"type": "string"},
                                "label": {"type": "string"},
                                "emoji": {"type": "string"},
                                "style": {
                                    "type": "string",
                                    "enum": ["primary", "secondary", "success", "danger", "link"],
                                    "default": "secondary",
                                },
                                "url": {"type": "string"},
                            },
                            "required": ["label"],
                        },
                    },
                },
                "required": ["post_id", "message_id", "content"],
            },
        },
        handler=edit_post_message,
    )
    ctx.register_tool(
        name="discord_delete_forum_post",
        toolset="discord_forum_posts",
        schema={
            "name": "discord_delete_forum_post",
            "description": "Delete one existing Discord forum post (thread).",
            "parameters": {
                "type": "object",
                "properties": {
                    "post_id": {
                        "type": "string",
                        "description": "Discord forum post (thread) ID.",
                    }
                },
                "required": ["post_id"],
            },
        },
        handler=delete_forum_post,
    )
    ctx.register_platform_handler(
        "discord", lambda bot, adapter: _wire_discord_component_actions(ctx, bot, adapter, statuses)
    )
