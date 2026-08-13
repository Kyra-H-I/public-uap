"""What an action DOES to the world, as declared by its provider (spec §Typed actions, §Results).

This module is only the vocabulary. The rule that makes it safe lives in the host's
policy engine: **a provider describes effects; it never chooses its own
confirmation class.** A provider — and especially an adapter generated from vendor
documentation, or a page whose content is attacker-controlled — must not be able to
mark "email the customer" as a quiet local edit and skip the approval path.

Two declarations do the work:

``EffectKind``
    What kind of change escapes: nothing, something local and forgettable, something
    the user's own durable state, or something that leaves the machine entirely.

``Reversibility``
    Whether there is an **operation-bound** way back. The spec is explicit that a
    generic Undo menu is not a transaction protocol (§5): if the provider cannot
    hand back a token bound to *this* command, the action is irreversible for
    policy purposes, no matter what the application's Edit menu offers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class EffectKind(StrEnum):
    """The escape radius of an action, ordered from smallest to largest."""

    READ = "read"
    """Observes only. Changes nothing the user could notice afterwards."""

    VIEW = "view"
    """Moves the user's view — navigation, scroll, focus. No data changes."""

    DRAFT = "draft"
    """Changes unsaved, in-memory state (an editor buffer, an unsaved form)."""

    PERSIST = "persist"
    """Writes the user's own durable state (saves a note, updates a record)."""

    DEVICE = "device"
    """Acts on the device outside the app (clipboard, camera, launching an app)."""

    EXTERNAL = "external"
    """Leaves the user's control: sends, calls, publishes, shares, pays."""


#: Effects that can never be quietly auto-executed regardless of reversibility,
#: because the damage is *the escape itself* — an email that was un-sent was still
#: read, a call that was hung up still rang someone at 3am.
_ALWAYS_CONSEQUENTIAL: frozenset[EffectKind] = frozenset({EffectKind.EXTERNAL})


class Reversibility(StrEnum):
    """Whether this exact operation can be taken back."""

    NONE = "none"
    """No operation-bound way back. The default, and the honest answer for most apps."""

    CHECKPOINT = "checkpoint"
    """The provider took a restore point covering this operation."""

    OPERATION_UNDO = "operation_undo"
    """The provider returns a token that undoes THIS command specifically."""


class ActionTerminality(StrEnum):
    """Whether an action's final outcome is observable from this provider at all.

    Three classes of action end differently, and collapsing them is how a host either
    fabricates success or fabricates failure:

    - **observable** (the default): the outcome can be checked — a revision moves, a
      record exists. COMPLETED must verify; an ACCEPTED that never resolves is an
      ambiguous failure, because a receiver COULD have observed it and none did.
    - **handoff**: the action verifiably LEAVES this provider (a dialer intent, a posted
      notification) and its final outcome is intrinsically unobservable on this
      transport — there is nothing a receiver could ever watch. ACCEPTED is then the
      terminal truth: "sent it, cannot confirm it finished" spoken honestly, never
      converted into a failure the user can see is false while the dialer is ringing.

    Declared on the descriptor, once, at discovery — never asserted per result, so a
    provider cannot upgrade a lie mid-flight, and conformance can test the claim.
    """

    OBSERVABLE = "observable"
    HANDOFF = "handoff"


@dataclass(frozen=True, slots=True)
class Effect:
    """One declared consequence of an action, with the scope it touches."""

    kind: EffectKind

    scope: str = ""
    """What it touches, in the provider's own vocabulary ("the open note", "calendar").
    Free text bounded by the envelope validator; shown in approvals, never parsed."""

    reversibility: Reversibility = Reversibility.NONE
    """Operation-bound reversal, if any. NONE is the safe default."""

    @property
    def consequential(self) -> bool:
        """True when this effect alone forces the confirmation path.

        An effect is consequential when it escapes the user's control, or when it
        changes durable/device state with no operation-bound way back. A DRAFT edit
        or a VIEW move is never consequential on its own — insisting the user
        approve every cursor insertion is how a voice agent becomes unusable.
        """
        if self.kind in _ALWAYS_CONSEQUENTIAL:
            return True
        if self.kind in (EffectKind.PERSIST, EffectKind.DEVICE):
            return self.reversibility is Reversibility.NONE
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "scope": self.scope,
            "reversibility": self.reversibility.value,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Effect:
        """Parse a declared effect, failing CLOSED on anything unrecognised.

        An unknown effect kind becomes ``EXTERNAL`` and an unknown reversibility
        becomes ``NONE`` — i.e. a provider that garbles its declaration gets the
        *strictest* treatment, never the most permissive. A provider on an old or
        malicious build must not be able to downgrade its own risk class by
        emitting a value the host has never heard of.
        """
        try:
            kind = EffectKind(str(d.get("kind", "")))
        except ValueError:
            kind = EffectKind.EXTERNAL
        try:
            reversibility = Reversibility(str(d.get("reversibility", "")))
        except ValueError:
            reversibility = Reversibility.NONE
        return cls(kind=kind, scope=str(d.get("scope", ""))[:120], reversibility=reversibility)
