"""Hermes plugin exposing safe Discord forum-post operations."""

from __future__ import annotations

import json
from typing import Any

from .tools import DiscordApiError, DiscordForumPostsClient


def _json_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


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
                },
                "required": ["post_id", "content"],
            },
        },
        handler=send_post_message,
    )
