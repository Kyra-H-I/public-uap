"""Stopping an action in flight (spec §5, product principle 7).

"Stop!" is the one command a user must never doubt. Before this, a barge-in stopped the agent
*listening* while the write it had already dispatched carried on — the host simply stopped
waiting for it. The user watched their note change after being told it had stopped, which is
worse than never offering to stop at all.

The honest model has three outcomes, and the third is the one that matters:

``STOPPED``
    The action never ran. The command was cancelled before the provider began it.
``TOO_LATE``
    It had already started or finished. Nothing was undone — cancelling is not undoing, and
    conflating them would have the host claim a revert it never performed.
``UNSUPPORTED``
    This provider cannot stop anything. Said plainly, so the host can tell the user rather
    than letting silence imply success.

The asymmetry is deliberate: a provider may only report ``STOPPED`` when it can *prove* the
work never began. Anything else is ``TOO_LATE``, because "I think I stopped it" spoken aloud
becomes "I stopped it" in the user's memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class CancelState(StrEnum):
    """What a cancellation actually achieved."""

    STOPPED = "stopped"
    """Proven not to have run. Safe to tell the user nothing happened."""

    TOO_LATE = "too_late"
    """Already started or finished. The world may have changed; nothing was undone."""

    UNSUPPORTED = "unsupported"
    """This provider cannot stop work. Not a failure — an honest capability answer."""


@dataclass(frozen=True, slots=True)
class CancelOutcome:
    """The result of asking a provider to stop one command."""

    command_id: str
    state: CancelState
    detail: str = ""

    @property
    def stopped(self) -> bool:
        return self.state is CancelState.STOPPED

    def to_dict(self) -> dict[str, Any]:
        return {"command_id": self.command_id, "state": self.state.value, "detail": self.detail}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CancelOutcome:
        """Parse a client's answer, failing CLOSED on anything unrecognised.

        An unparseable state becomes ``TOO_LATE``, never ``STOPPED``: the strict reading is
        the one that does not promise the user something did not happen.
        """
        try:
            state = CancelState(str(d.get("state", "")))
        except ValueError:
            state = CancelState.TOO_LATE
        return cls(
            command_id=str(d.get("command_id", "")),
            state=state,
            detail=str(d.get("detail", ""))[:200],
        )


def spoken(outcome: CancelOutcome) -> str:
    """What to say to someone who just said "stop"."""
    return {
        CancelState.STOPPED: "stopped.",
        CancelState.TOO_LATE: "that had already gone through — I can undo it if you want.",
        CancelState.UNSUPPORTED: "I couldn't stop that one.",
    }[outcome.state]
