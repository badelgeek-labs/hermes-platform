"""Minimal Discord REST client for safe forum-post operations."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DISCORD_API_BASE_URL = "https://discord.com/api/v10"
FORUM_CHANNEL_TYPE = 15
MAX_APPLIED_TAGS = 5
MAX_POST_TITLE_LENGTH = 100
MAX_MESSAGE_LENGTH = 2_000


class DiscordApiError(RuntimeError):
    """A safe, user-visible error from the Discord API."""


@dataclass(frozen=True)
class DiscordForumPostsClient:
    token: str

    @classmethod
    def from_environment(cls) -> "DiscordForumPostsClient":
        token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
        if not token:
            raise DiscordApiError("DISCORD_BOT_TOKEN is not configured.")
        return cls(token=token)

    def get_forum(self, forum_id: str) -> dict[str, Any]:
        forum = self._request("GET", f"/channels/{self._snowflake(forum_id, 'forum_id')}")
        if forum.get("type") != FORUM_CHANNEL_TYPE:
            raise DiscordApiError("forum_id must identify a Discord forum channel.")
        return forum

    def update_post_tags(
        self, post_id: str, tag_ids: list[str], operation: str
    ) -> dict[str, Any]:
        post, forum = self._get_forum_post(post_id)
        parent_id = str(post["parent_id"])
        allowed_tags = {
            str(tag["id"]): tag for tag in forum.get("available_tags", []) if "id" in tag
        }
        requested_tags = self._tag_ids(tag_ids)
        unknown_tags = [tag_id for tag_id in requested_tags if tag_id not in allowed_tags]
        if unknown_tags:
            raise DiscordApiError(
                "Every tag_id must already be configured on the parent forum. "
                f"Unknown tag IDs: {', '.join(unknown_tags)}."
            )

        current_tags = self._tag_ids(post.get("applied_tags", []), allow_empty=True)
        if operation == "replace":
            next_tags = requested_tags
        elif operation == "add":
            next_tags = self._tag_ids(current_tags + requested_tags)
        elif operation == "remove":
            next_tags = [tag_id for tag_id in current_tags if tag_id not in requested_tags]
        else:
            raise DiscordApiError("operation must be replace, add, or remove.")

        if len(next_tags) > MAX_APPLIED_TAGS:
            raise DiscordApiError("A Discord forum post can have at most five tags.")

        updated_post = self._request(
            "PATCH",
            f"/channels/{self._snowflake(post_id, 'post_id')}",
            {"applied_tags": next_tags},
        )
        return {
            "forum_id": str(parent_id),
            "post_id": updated_post["id"],
            "operation": operation,
            "applied_tags": updated_post.get("applied_tags", []),
            "tags": [
                {"id": tag_id, "name": allowed_tags[tag_id].get("name")}
                for tag_id in updated_post.get("applied_tags", [])
                if tag_id in allowed_tags
            ],
        }

    def create_forum_post(
        self, forum_id: str, title: str, content: str, tag_ids: list[str]
    ) -> dict[str, Any]:
        forum = self.get_forum(forum_id)
        requested_tags = self._validate_forum_tags(forum, tag_ids)
        created_post = self._request(
            "POST",
            f"/channels/{self._snowflake(forum_id, 'forum_id')}/threads",
            {
                "name": self._text(title, "title", MAX_POST_TITLE_LENGTH),
                "message": {
                    "content": self._text(content, "content", MAX_MESSAGE_LENGTH),
                    "allowed_mentions": {"parse": []},
                },
                "applied_tags": requested_tags,
            },
        )
        allowed_tags = {
            str(tag["id"]): tag
            for tag in forum.get("available_tags", [])
            if "id" in tag
        }
        return {
            "forum_id": str(forum["id"]),
            "post_id": str(created_post["id"]),
            "applied_tags": created_post.get("applied_tags", requested_tags),
            "tags": [
                {"id": tag_id, "name": allowed_tags[tag_id].get("name")}
                for tag_id in created_post.get("applied_tags", requested_tags)
                if tag_id in allowed_tags
            ],
        }

    def send_post_message(self, post_id: str, content: str) -> dict[str, Any]:
        post, forum = self._get_forum_post(post_id)
        message = self._request(
            "POST",
            f"/channels/{self._snowflake(post_id, 'post_id')}/messages",
            {
                "content": self._text(content, "content", MAX_MESSAGE_LENGTH),
                "allowed_mentions": {"parse": []},
            },
        )
        return {
            "forum_id": str(forum["id"]),
            "post_id": str(post["id"]),
            "message_id": str(message["id"]),
        }

    def _get_forum_post(self, post_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        post = self._request("GET", f"/channels/{self._snowflake(post_id, 'post_id')}")
        parent_id = post.get("parent_id")
        if not parent_id:
            raise DiscordApiError("post_id must identify a forum post with a parent forum.")
        return post, self.get_forum(str(parent_id))

    def _validate_forum_tags(
        self, forum: dict[str, Any], tag_ids: list[str]
    ) -> list[str]:
        requested_tags = self._tag_ids(tag_ids)
        allowed_tags = {
            str(tag["id"]) for tag in forum.get("available_tags", []) if "id" in tag
        }
        unknown_tags = [tag_id for tag_id in requested_tags if tag_id not in allowed_tags]
        if unknown_tags:
            raise DiscordApiError(
                "Every tag_id must already be configured on the forum. "
                f"Unknown tag IDs: {', '.join(unknown_tags)}."
            )
        return requested_tags

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{DISCORD_API_BASE_URL}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bot {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "hermes-platform-discord-forum-posts/1.1",
            },
        )
        try:
            with urlopen(request, timeout=15) as response:  # nosec B310
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise DiscordApiError(
                f"Discord API request failed ({error.code}). Check the bot's forum permissions."
            ) from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise DiscordApiError("Discord API request failed.") from error

    @staticmethod
    def _snowflake(value: str, field_name: str) -> str:
        value = str(value).strip()
        if not value.isdigit():
            raise DiscordApiError(f"{field_name} must be a Discord numeric ID.")
        return value

    @staticmethod
    def _tag_ids(values: list[str], allow_empty: bool = False) -> list[str]:
        normalized = []
        for value in values:
            tag_id = DiscordForumPostsClient._snowflake(value, "tag_ids entry")
            if tag_id not in normalized:
                normalized.append(tag_id)
        if not normalized and not allow_empty:
            raise DiscordApiError("tag_ids must contain at least one Discord tag ID.")
        if len(normalized) > MAX_APPLIED_TAGS:
            raise DiscordApiError("A Discord forum post can have at most five tags.")
        return normalized

    @staticmethod
    def _text(value: str, field_name: str, maximum_length: int) -> str:
        if not isinstance(value, str):
            raise DiscordApiError(f"{field_name} must be text.")
        text = value.strip()
        if not text:
            raise DiscordApiError(f"{field_name} must not be empty.")
        if len(text) > maximum_length:
            raise DiscordApiError(
                f"{field_name} must not exceed {maximum_length} characters."
            )
        return text
