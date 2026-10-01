"""Tests for the persistent, generic Discord modal registry."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from discord_ui.registry import ModalDefinitionError, ModalRegistry


class ModalRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.tempdir.name) / "discord-ui.sqlite3"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @staticmethod
    def _definition(**overrides: object) -> dict[str, object]:
        definition: dict[str, object] = {
            "key": "review-123-manual-edit",
            "title": "Modifier",
            "submit_action": "manual_edit",
            "fields": [
                {
                    "id": "text",
                    "label": "Texte",
                    "style": "paragraph",
                    "required": True,
                    "value": "Texte courant...",
                }
            ],
        }
        definition.update(overrides)
        return definition

    def test_upsert_returns_a_short_opaque_ref_and_persists_definition(self) -> None:
        registry = ModalRegistry(self.database_path)

        record = registry.upsert(self._definition())

        self.assertTrue(record["interaction_ref"].startswith("mui_"))
        self.assertLessEqual(len(record["interaction_ref"]), 79)
        self.assertEqual(record["definition"]["fields"][0]["value"], "Texte courant...")
        self.assertEqual(record["definition"]["fields"][0]["style"], "paragraph")

    def test_reload_after_simulated_restart_keeps_modal_and_ref(self) -> None:
        first_registry = ModalRegistry(self.database_path)
        record = first_registry.upsert(self._definition())

        reloaded_registry = ModalRegistry(self.database_path)
        restored = reloaded_registry.get(record["interaction_ref"])

        self.assertIsNotNone(restored)
        self.assertEqual(restored["interaction_ref"], record["interaction_ref"])
        self.assertEqual(restored["definition"]["submit_action"], "manual_edit")

    def test_upsert_by_key_preserves_interaction_ref(self) -> None:
        registry = ModalRegistry(self.database_path)
        initial = registry.upsert(self._definition())
        updated = registry.upsert(self._definition(title="Modifier la réponse"))

        self.assertEqual(updated["interaction_ref"], initial["interaction_ref"])
        self.assertEqual(updated["definition"]["title"], "Modifier la réponse")

    def test_delete_removes_modal(self) -> None:
        registry = ModalRegistry(self.database_path)
        record = registry.upsert(self._definition())

        self.assertTrue(registry.delete(record["interaction_ref"]))
        self.assertIsNone(registry.get(record["interaction_ref"]))
        self.assertFalse(registry.delete(record["interaction_ref"]))

    def test_short_field_and_lengths_are_retained(self) -> None:
        registry = ModalRegistry(self.database_path)
        record = registry.upsert(
            self._definition(
                fields=[
                    {
                        "id": "name",
                        "label": "Nom",
                        "style": "short",
                        "required": False,
                        "placeholder": "Votre nom",
                        "min_length": 2,
                        "max_length": 30,
                    }
                ]
            )
        )

        self.assertEqual(
            record["definition"]["fields"][0],
            {
                "id": "name",
                "label": "Nom",
                "style": "short",
                "required": False,
                "placeholder": "Votre nom",
                "min_length": 2,
                "max_length": 30,
            },
        )

    def test_rejects_more_than_five_fields(self) -> None:
        registry = ModalRegistry(self.database_path)
        fields = [
            {"id": f"field-{index}", "label": f"Field {index}"} for index in range(6)
        ]

        with self.assertRaisesRegex(ModalDefinitionError, "at most five"):
            registry.upsert(self._definition(fields=fields))


if __name__ == "__main__":
    unittest.main()
