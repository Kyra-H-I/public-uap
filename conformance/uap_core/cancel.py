"""Stopping an action in flight (spec §5, product principle 7).

"Stop!" is the one command a user must never doubt. Before this, a barge-in stopped the agent
*listening* while the write it had already dispatched carried on — the host simply stopped
waiting for it. The user watched their note change after being told it had stopped, which is
worse than never offering to stop at all.

The honest model has four outcomes, and the ones that matter are the two in the middle:

``STOPPED``
    The action never ran. The command was cancelled before the provider began it.
``TOO_LATE``
    It had already started or finished. Nothing was undone — cancelling is not undoing, and
    conflating them would have the host claim a revert it never performed.
``NOTHING_CHANGED``
    It had already finished, and it left nothing behind. Separated from ``TOO_LATE`` because
    that answer offers to undo what it warns about, and there is nothing here to undo — a
    command refused for a stale reference, or a read that already returned, changed nothing
    whatever else is true of it.
``UNSUPPORTED``
    This provider cannot stop anything. Said plainly, so the host can tell the user rather
    than letting silence imply success.

The asymmetry is deliberate: a provider may only report ``STOPPED`` when it can *prove* the
work never began. Anything else is ``TOO_LATE``, because "I think I stopped it" spoken aloud
becomes "I stopped it" in the user's memory. ``NOTHING_CHANGED`` does not soften that rule —
it makes no claim about stopping at all, only about what the world looks like afterwards.
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

    NOTHING_CHANGED = "nothing_changed"
    """Already finished, and nothing changed. Nothing to stop, and nothing to undo.

    The name states what is true of the world rather than of the request, deliberately. Every
    phrasing centred on the request — "no effect", "did nothing" — reads just as naturally as
    *the cancellation* having achieved nothing, which is true of a command still running and
    still writing. A member whose plausible misreading is a reassurance about a live write does
    not belong in this taxonomy, however convenient it is to say.
    """

    UNSUPPORTED = "unsupported"
    """This provider cannot stop work. Not a failure — an honest capability answer."""


@dataclass(frozen=True, slots=True)
class CancelOutcome:
    """The result of asking a provider to stop one command."""

    command_id: str
    state: CancelState
    detail: str = ""

    undoable: bool | None = None
    """Whether the host can actually offer to undo what finished. HOST-SIDE ONLY.

    Deliberately absent from :meth:`to_dict` and :meth:`from_dict`, so it is not wire
    vocabulary and no client restates it. It is not a provider's answer to give: the host
    already holds the finished action's declared effects, and reversibility is exactly what
    it trusts them for when deriving confirmation. Asking a provider to self-report
    undoability would be inviting the same claim the conformance suite refuses to take on
    faith.

    ``None`` means the host could not establish it, and reads the same as ``False`` when
    spoken. That is the direction that fails safely: withholding an offer costs the user one
    follow-up question, whereas offering an undo that does not exist is a promise broken at
    the moment they accept it.
    """

    @property
    def stopped(self) -> bool:
        return self.state is CancelState.STOPPED

    def to_dict(self) -> dict[str, Any]:
        return {"command_id": self.command_id, "state": self.state.value, "detail": self.detail}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CancelOutcome:
        """Parse a client's answer, failing CLOSED on anything unrecognised.

        An unparseable state becomes ``TOO_LATE``, never ``STOPPED``: the strict reading is
        the one that does not promise the user something did not happen. Note what that costs
        a word this host does not yet know — before ``NOTHING_CHANGED`` was declared here, a
        provider saying it was downgraded into the offer-to-undo it was reaching for a way to
        avoid. Fail-closed is right, and it is why a new member has to land in every copy.
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
    """What to say to someone who just said "stop".

    The one line that carries no offer is the point of it. A user who says "stop" and hears
    "I can undo it if you want" has been told something happened; making that offer when the
    command changed nothing sends them after a revert that has no subject. Here the answer is
    already complete, so it ends.

    ``TOO_LATE`` has two lines for the same reason, chosen by
    :attr:`CancelOutcome.undoable`. The offer used to be unconditional, which made it false in
    two ordinary cases: a completed read has nothing to undo, and a write whose effects declare
    no operation-bound way back — saving under a new name, for one — cannot be taken back at
    all. Both told the user a revert was available and then had to withdraw it, which spends
    the credibility that "stop" depends on. The offer is now made only when the finished
    action's own declaration backs it.
    """
    if outcome.state is CancelState.TOO_LATE:
        return (
            "that had already gone through — I can undo it if you want."
            if outcome.undoable
            else "that had already gone through, and I can't undo it."
        )
    return {
        CancelState.STOPPED: "stopped.",
        CancelState.NOTHING_CHANGED: "that one had already finished, and nothing changed.",
        CancelState.UNSUPPORTED: "I couldn't stop that one.",
    }[outcome.state]
