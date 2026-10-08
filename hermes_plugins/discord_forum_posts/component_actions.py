"""Track one ephemeral status response for each generic Discord component action."""

from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass
from typing import Any


logger = logging.getLogger(__name__)
DEFAULT_COMPONENT_ACTION_TIMEOUT_SECONDS = 300


@dataclass
class _PendingAction:
    interaction: Any
    action_label: str
    timeout_task: asyncio.Task[None]


class ComponentActionStatuses:
    """Correlate downstream action completion with its original interaction."""

    def __init__(self, timeout_seconds: int = DEFAULT_COMPONENT_ACTION_TIMEOUT_SECONDS) -> None:
        self._timeout_seconds = timeout_seconds
        self._pending: dict[str, _PendingAction] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    async def acknowledge(self, interaction: Any, action_label: str) -> str:
        """Create the sole ephemeral status response and return its correlation ID."""

        await interaction.response.send_message(
            f"⏳ Action: {action_label}", ephemeral=True
        )
        self._loop = asyncio.get_running_loop()
        interaction_ref = f"dca_{secrets.token_urlsafe(18)}"
        timeout_task = self._loop.create_task(self._expire(interaction_ref))
        self._pending[interaction_ref] = _PendingAction(
            interaction=interaction,
            action_label=action_label,
            timeout_task=timeout_task,
        )
        return interaction_ref

    async def complete(self, interaction_ref: str, success: bool) -> bool:
        """Finalize a pending action status from asynchronous Discord code."""

        pending = self._claim(interaction_ref)
        if pending is None:
            return False
        await self._edit(pending, success)
        return True

    def complete_from_tool(self, interaction_ref: str, success: bool) -> bool:
        """Schedule a completion requested by a synchronous downstream tool."""

        pending = self._claim(interaction_ref)
        if pending is None or self._loop is None or self._loop.is_closed():
            return False
        self._loop.call_soon_threadsafe(
            self._loop.create_task, self._edit(pending, success)
        )
        return True

    def _claim(self, interaction_ref: str) -> _PendingAction | None:
        pending = self._pending.pop(interaction_ref, None)
        if pending is not None and pending.timeout_task is not asyncio.current_task():
            pending.timeout_task.cancel()
        return pending

    async def _expire(self, interaction_ref: str) -> None:
        try:
            await asyncio.sleep(self._timeout_seconds)
            await self.complete(interaction_ref, success=False)
        except asyncio.CancelledError:
            pass

    @staticmethod
    async def _edit(pending: _PendingAction, success: bool) -> None:
        marker = "✅" if success else "❌"
        try:
            await pending.interaction.edit_original_response(
                content=f"{marker} Action: {pending.action_label}"
            )
        except Exception:
            logger.exception("Failed to finalize Discord component action status")
