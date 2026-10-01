"""Hermes plugin for persistent, generic Discord modal interactions."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from .registry import DEFAULT_DATABASE_PATH, ModalDefinitionError, ModalRegistry


logger = logging.getLogger(__name__)
MODAL_CUSTOM_ID_PREFIX = "hermes-discord-ui:v1:"


def _json_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _allowed_user_ids() -> set[str]:
    return {
        user_id.strip()
        for user_id in os.environ.get("DISCORD_ALLOWED_USERS", "").split(",")
        if user_id.strip().isdigit()
    }


async def _session_key_for_interaction(adapter: Any, interaction: Any) -> str:
    """Use the same gateway session identity as forum-post component actions."""

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
        source, touch_activity=False
    )
    return str(session.session_key)


def _modal_submit_event(
    submit_action: str, thread_id: str, actor_id: str, fields: dict[str, str]
) -> str:
    return "\n".join(
        [
            "[DISCORD_MODAL_SUBMIT]",
            f"action_id={submit_action}",
            f"thread_id={thread_id}",
            f"actor_id={actor_id}",
            f"fields={json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}",
        ]
    )


def _is_bot_message(interaction: Any, bot: Any) -> bool:
    """Buttons must originate from this bot; modal submissions have no message."""

    message = getattr(interaction, "message", None)
    if message is None:
        return True
    message_author = getattr(message, "author", None)
    return (
        message_author is not None
        and getattr(bot, "user", None) is not None
        and getattr(message_author, "id", None) == getattr(bot.user, "id", None)
    )


def _build_modal(
    definition: dict[str, Any], interaction_ref: str, submit_handler: Any
) -> Any:
    """Create a discord.py Modal only after Hermes has loaded the Discord adapter."""

    import discord  # type: ignore[import-not-found]

    class HermesModal(discord.ui.Modal):
        def __init__(self) -> None:
            super().__init__(
                title=definition["title"],
                custom_id=f"{MODAL_CUSTOM_ID_PREFIX}{interaction_ref}",
            )
            for field in definition["fields"]:
                self.add_item(
                    discord.ui.TextInput(
                        custom_id=field["id"],
                        label=field["label"],
                        style=(
                            discord.TextStyle.paragraph
                            if field["style"] == "paragraph"
                            else discord.TextStyle.short
                        ),
                        required=field["required"],
                        default=field.get("value"),
                        placeholder=field.get("placeholder"),
                        min_length=field.get("min_length"),
                        max_length=field.get("max_length"),
                    )
                )

        async def on_submit(self, modal_interaction: Any) -> None:
            await submit_handler(modal_interaction, definition, self.children)

    return HermesModal()


def _wire_discord_modals(ctx: Any, bot: Any, adapter: Any, registry: ModalRegistry) -> None:
    """Install the scoped component listener; no unrelated Discord interaction is touched."""

    async def submit_modal(
        interaction: Any, definition: dict[str, Any], inputs: list[Any]
    ) -> None:
        actor_id = str(interaction.user.id)
        if actor_id not in _allowed_user_ids():
            await interaction.response.send_message(
                "You are not authorized to use this action.", ephemeral=True
            )
            return
        fields = {str(item.custom_id): str(item.value) for item in inputs}
        try:
            session_key = await _session_key_for_interaction(adapter, interaction)
            accepted = ctx.inject_message(
                _modal_submit_event(
                    definition["submit_action"], str(interaction.channel_id), actor_id, fields
                ),
                session_key=session_key,
            )
        except Exception:
            logger.exception("Failed to inject Discord modal submit %s", definition["submit_action"])
            accepted = False
        await interaction.response.send_message(
            "Submitted." if accepted else "The submission could not be delivered.", ephemeral=True
        )

    async def on_interaction(interaction: Any) -> None:
        data = getattr(interaction, "data", None) or {}
        custom_id = data.get("custom_id")
        if not isinstance(custom_id, str) or not custom_id.startswith(MODAL_CUSTOM_ID_PREFIX):
            return
        # discord.py dispatches this submit to the Modal.on_submit callback above.
        # Do not interpret it as a second request to open the modal.
        if data.get("components"):
            return
        if not _is_bot_message(interaction, bot):
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
        interaction_ref = custom_id.removeprefix(MODAL_CUSTOM_ID_PREFIX)
        try:
            record = registry.get(interaction_ref)
        except ModalDefinitionError:
            record = None
        if record is None:
            await interaction.response.send_message("This action is no longer available.", ephemeral=True)
            return
        try:
            modal = _build_modal(record["definition"], interaction_ref, submit_modal)
            await interaction.response.send_modal(modal)
        except Exception:
            logger.exception("Failed to open Discord modal %s", interaction_ref)
            if not getattr(interaction.response, "is_done", lambda: False)():
                await interaction.response.send_message(
                    "The form could not be opened.", ephemeral=True
                )

    bot.add_listener(on_interaction, "on_interaction")


def _modal_definition_schema() -> dict[str, Any]:
    field_properties = {
        "id": {"type": "string", "maxLength": 100},
        "label": {"type": "string", "maxLength": 45},
        "style": {"type": "string", "enum": ["short", "paragraph"], "default": "short"},
        "required": {"type": "boolean", "default": True},
        "value": {"type": "string", "maxLength": 4000},
        "placeholder": {"type": "string", "maxLength": 100},
        "min_length": {"type": "integer", "minimum": 0, "maximum": 4000},
        "max_length": {"type": "integer", "minimum": 0, "maximum": 4000},
    }
    return {
        "type": "object",
        "properties": {
            "key": {"type": "string", "maxLength": 100},
            "title": {"type": "string", "maxLength": 45},
            "submit_action": {"type": "string", "maxLength": 100},
            "fields": {
                "type": "array",
                "minItems": 1,
                "maxItems": 5,
                "items": {"type": "object", "properties": field_properties, "required": ["id", "label"]},
            },
        },
        "required": ["key", "title", "submit_action", "fields"],
    }


def register(ctx: Any) -> None:
    """Expose generic modal tools and register their native Discord handler."""

    registry = ModalRegistry(os.environ.get("DISCORD_UI_DB_PATH", DEFAULT_DATABASE_PATH))

    def upsert_modal(params: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        try:
            record = registry.upsert(params)
            return _json_result({"ok": True, **record})
        except (ModalDefinitionError, TypeError, ValueError) as error:
            return _json_result({"ok": False, "error": str(error)})

    def get_modal(params: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        try:
            record = registry.get(params["interaction_ref"])
            return _json_result({"ok": True, "found": record is not None, **({"modal": record} if record else {})})
        except (ModalDefinitionError, KeyError, TypeError, ValueError) as error:
            return _json_result({"ok": False, "error": str(error)})

    def delete_modal(params: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        try:
            return _json_result({"ok": True, "deleted": registry.delete(params["interaction_ref"])})
        except (ModalDefinitionError, KeyError, TypeError, ValueError) as error:
            return _json_result({"ok": False, "error": str(error)})

    ctx.register_tool(
        name="discord_ui_upsert_modal",
        toolset="discord_ui",
        schema={
            "name": "discord_ui_upsert_modal",
            "description": "Create or update a persistent, generic Discord modal definition.",
            "parameters": _modal_definition_schema(),
        },
        handler=upsert_modal,
    )
    ctx.register_tool(
        name="discord_ui_get_modal",
        toolset="discord_ui",
        schema={
            "name": "discord_ui_get_modal",
            "description": "Read a persistent Discord modal definition by interaction_ref.",
            "parameters": {
                "type": "object",
                "properties": {"interaction_ref": {"type": "string"}},
                "required": ["interaction_ref"],
            },
        },
        handler=get_modal,
    )
    ctx.register_tool(
        name="discord_ui_delete_modal",
        toolset="discord_ui",
        schema={
            "name": "discord_ui_delete_modal",
            "description": "Delete a persistent Discord modal definition by interaction_ref.",
            "parameters": {
                "type": "object",
                "properties": {"interaction_ref": {"type": "string"}},
                "required": ["interaction_ref"],
            },
        },
        handler=delete_modal,
    )
    ctx.register_platform_handler(
        "discord", lambda bot, adapter: _wire_discord_modals(ctx, bot, adapter, registry)
    )
