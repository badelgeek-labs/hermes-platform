"""Persistent, validated definitions for generic Discord modals."""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_DATABASE_PATH = "/opt/data/discord-ui.sqlite3"
INTERACTION_REF_PREFIX = "mui_"
# The Discord custom_id prefix is 21 characters; Discord accepts at most 100.
MAX_INTERACTION_REF_LENGTH = 79
MAX_MODAL_TITLE_LENGTH = 45
MAX_FIELDS = 5
MAX_FIELD_ID_LENGTH = 100
MAX_FIELD_LABEL_LENGTH = 45
MAX_FIELD_PLACEHOLDER_LENGTH = 100
MAX_FIELD_VALUE_LENGTH = 4_000


class ModalDefinitionError(ValueError):
    """A modal definition that Discord cannot render safely."""


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ModalRegistry:
    """SQLite-backed modal registry that survives plugin and Hermes restarts."""

    def __init__(self, database_path: str | Path = DEFAULT_DATABASE_PATH) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS discord_ui_modals (
                    interaction_ref TEXT PRIMARY KEY,
                    modal_key TEXT NOT NULL UNIQUE,
                    definition_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def upsert(self, definition: dict[str, Any]) -> dict[str, Any]:
        normalized = validate_modal_definition(definition)
        now = _timestamp()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT interaction_ref, created_at FROM discord_ui_modals WHERE modal_key = ?",
                (normalized["key"],),
            ).fetchone()
            interaction_ref = (
                str(existing["interaction_ref"])
                if existing is not None
                else self._new_interaction_ref(connection)
            )
            created_at = str(existing["created_at"]) if existing is not None else now
            connection.execute(
                """
                INSERT INTO discord_ui_modals (
                    interaction_ref, modal_key, definition_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(modal_key) DO UPDATE SET
                    definition_json = excluded.definition_json,
                    updated_at = excluded.updated_at
                """,
                (
                    interaction_ref,
                    normalized["key"],
                    json.dumps(normalized, ensure_ascii=False, sort_keys=True),
                    created_at,
                    now,
                ),
            )
        return {
            "interaction_ref": interaction_ref,
            "definition": normalized,
            "created_at": created_at,
            "updated_at": now,
        }

    def get(self, interaction_ref: str) -> dict[str, Any] | None:
        normalized_ref = _interaction_ref(interaction_ref)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT interaction_ref, definition_json, created_at, updated_at
                FROM discord_ui_modals WHERE interaction_ref = ?
                """,
                (normalized_ref,),
            ).fetchone()
        if row is None:
            return None
        return {
            "interaction_ref": str(row["interaction_ref"]),
            "definition": json.loads(str(row["definition_json"])),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def delete(self, interaction_ref: str) -> bool:
        normalized_ref = _interaction_ref(interaction_ref)
        with self._connect() as connection:
            result = connection.execute(
                "DELETE FROM discord_ui_modals WHERE interaction_ref = ?", (normalized_ref,)
            )
        return result.rowcount > 0

    @staticmethod
    def _new_interaction_ref(connection: sqlite3.Connection) -> str:
        while True:
            interaction_ref = f"{INTERACTION_REF_PREFIX}{secrets.token_urlsafe(18)}"
            if connection.execute(
                "SELECT 1 FROM discord_ui_modals WHERE interaction_ref = ?", (interaction_ref,)
            ).fetchone() is None:
                return interaction_ref


def validate_modal_definition(definition: dict[str, Any]) -> dict[str, Any]:
    """Normalize the V1 definition and enforce Discord's modal constraints."""

    if not isinstance(definition, dict):
        raise ModalDefinitionError("modal definition must be an object.")
    key = _required_text(definition.get("key"), "key", 100)
    title = _required_text(definition.get("title"), "title", MAX_MODAL_TITLE_LENGTH)
    submit_action = _required_text(definition.get("submit_action"), "submit_action", 100)
    fields = definition.get("fields")
    if not isinstance(fields, list) or not fields:
        raise ModalDefinitionError("fields must contain between one and five fields.")
    if len(fields) > MAX_FIELDS:
        raise ModalDefinitionError("A Discord modal can contain at most five fields.")

    normalized_fields: list[dict[str, Any]] = []
    field_ids: set[str] = set()
    for field in fields:
        if not isinstance(field, dict):
            raise ModalDefinitionError("Every field must be an object.")
        field_id = _required_text(field.get("id"), "field id", MAX_FIELD_ID_LENGTH)
        if field_id in field_ids:
            raise ModalDefinitionError(f"Duplicate field id: {field_id}.")
        field_ids.add(field_id)
        style = field.get("style", "short")
        if style not in {"short", "paragraph"}:
            raise ModalDefinitionError("field style must be short or paragraph.")
        normalized_field: dict[str, Any] = {
            "id": field_id,
            "label": _required_text(field.get("label"), "field label", MAX_FIELD_LABEL_LENGTH),
            "style": style,
            "required": field.get("required", True),
        }
        if not isinstance(normalized_field["required"], bool):
            raise ModalDefinitionError("field required must be a boolean.")
        for name, maximum in (("value", MAX_FIELD_VALUE_LENGTH), ("placeholder", MAX_FIELD_PLACEHOLDER_LENGTH)):
            if name in field and field[name] is not None:
                if not isinstance(field[name], str):
                    raise ModalDefinitionError(f"field {name} must be text.")
                if len(field[name]) > maximum:
                    raise ModalDefinitionError(f"field {name} must not exceed {maximum} characters.")
                normalized_field[name] = field[name]
        min_length = _optional_length(field, "min_length")
        max_length = _optional_length(field, "max_length")
        if min_length is not None:
            normalized_field["min_length"] = min_length
        if max_length is not None:
            normalized_field["max_length"] = max_length
        if min_length is not None and max_length is not None and min_length > max_length:
            raise ModalDefinitionError("field min_length cannot exceed max_length.")
        if "value" in normalized_field and max_length is not None and len(normalized_field["value"]) > max_length:
            raise ModalDefinitionError("field value cannot exceed max_length.")
        normalized_fields.append(normalized_field)
    return {"key": key, "title": title, "submit_action": submit_action, "fields": normalized_fields}


def _required_text(value: Any, field_name: str, maximum_length: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModalDefinitionError(f"{field_name} must be non-empty text.")
    value = value.strip()
    if len(value) > maximum_length:
        raise ModalDefinitionError(f"{field_name} must not exceed {maximum_length} characters.")
    return value


def _optional_length(field: dict[str, Any], name: str) -> int | None:
    if name not in field or field[name] is None:
        return None
    value = field[name]
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_FIELD_VALUE_LENGTH:
        raise ModalDefinitionError(f"field {name} must be an integer from 0 to 4000.")
    return value


def _interaction_ref(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith(INTERACTION_REF_PREFIX):
        raise ModalDefinitionError("interaction_ref is invalid.")
    if len(value) > MAX_INTERACTION_REF_LENGTH or not value[len(INTERACTION_REF_PREFIX) :].replace("_", "").replace("-", "").isalnum():
        raise ModalDefinitionError("interaction_ref is invalid.")
    return value
