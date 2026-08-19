"""UAP references and their lifetimes (spec §References).

A reference names *a thing inside an application* — a page, a focused field, a
note, a calendar event. It is deliberately **not** a coordinate, a CSS selector,
or an accessibility node path: those address pixels and re-point themselves
silently when the application moves on.

The load-bearing idea here is the **basis**. Every reference carries the epoch or
revision it was minted against, and the host re-checks that basis at invoke time.
When the basis has moved — the user navigated, left the field, or the note gained
a revision — the reference is stale and the call fails closed with
``STALE_REFERENCE``. The bridge never retargets: "insert at the cursor" issued
against a field the user has since left must not land in whatever field is
focused *now*.

Lifetimes are declared, not inferred. An adapter must not claim a durability its
underlying application cannot provide (spec §References), so ``PERSISTENT`` means the
provider can genuinely re-resolve the reference after a restart — nothing weaker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from uap_core.errors import UapError, UapErrorCode

#: A reference id is provider-opaque but must stay bounded and printable: it ends
#: up in audit rows and (rarely) in model context, and an unbounded id is both a
#: log-flooding primitive and a way to smuggle prose past the typed boundary.
#: ``%`` is allowed so a provider can percent-encode a path or name that would
#: otherwise need base64 — an audit row reading ``notes/my%20plan.md`` is worth
#: more to a human than an opaque blob.
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/:@+%]{0,255}$")
_KIND_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}(\.[a-z][a-z0-9_]{0,31}){0,3}$")
MAX_REFERENCE_KIND_CHARS = 131
MAX_REFERENCE_ID_CHARS = 256
MAX_REFERENCE_BASIS_CHARS = 128


class ReferenceLifetime(StrEnum):
    """How long a reference stays valid, and therefore what invalidates it."""

    VIEW = "view"
    """Valid while the current view/route stands. Invalidated by navigation."""

    FOCUS = "focus"
    """Valid while the current focus epoch stands. Invalidated by any focus change."""

    DOCUMENT = "document"
    """Valid while the document is at the basis revision. Invalidated by any write."""

    SESSION = "session"
    """Valid for this live binding. Invalidated by disconnect/rebind."""

    PERSISTENT = "persistent"
    """Durable identity the provider can re-resolve later. Needs no basis."""


#: Lifetimes whose reference MUST carry a basis. ``PERSISTENT`` is the only kind
#: that may omit one — everything else is scoped to something that can move.
_BASIS_REQUIRED: frozenset[ReferenceLifetime] = frozenset(
    {
        ReferenceLifetime.VIEW,
        ReferenceLifetime.FOCUS,
        ReferenceLifetime.DOCUMENT,
        ReferenceLifetime.SESSION,
    }
)


@dataclass(frozen=True, slots=True)
class Reference:
    """A typed handle to one application object, scoped by lifetime + basis."""

    kind: str
    """Dotted domain type, e.g. ``portal.page``, ``note.document``, ``device.contact``."""

    id: str
    """Provider-opaque identity within ``kind``."""

    lifetime: ReferenceLifetime
    """What this reference is scoped to, and therefore what invalidates it."""

    basis: str | None = None
    """The epoch/revision this was minted against. Required unless PERSISTENT."""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or not _KIND_RE.match(self.kind):
            raise ValueError(f"invalid reference kind: {self.kind!r}")
        if not isinstance(self.id, str) or not _ID_RE.match(self.id):
            raise ValueError(f"invalid reference id: {self.id!r}")
        if self.basis is not None and (
            not isinstance(self.basis, str)
            or not self.basis
            or len(self.basis) > MAX_REFERENCE_BASIS_CHARS
        ):
            raise ValueError("invalid reference basis")
        if self.lifetime in _BASIS_REQUIRED and not self.basis:
            raise ValueError(f"{self.lifetime.value} reference requires a basis")

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind, "id": self.id, "lifetime": self.lifetime.value}
        if self.basis is not None:
            d["basis"] = self.basis
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Reference:
        """Parse a wire reference. Raises ``ValueError`` on anything malformed.

        Callers on the untrusted side (a provider's result) must catch that and
        turn it into ``UNKNOWN_REFERENCE`` rather than letting a bad reference
        through — a reference that cannot be validated must not be usable.
        """
        raw_lifetime = str(d.get("lifetime", ""))
        try:
            lifetime = ReferenceLifetime(raw_lifetime)
        except ValueError as exc:
            raise ValueError(f"invalid reference lifetime: {raw_lifetime!r}") from exc
        basis = d.get("basis")
        return cls(
            kind=str(d.get("kind", "")),
            id=str(d.get("id", "")),
            lifetime=lifetime,
            basis=None if basis is None else str(basis),
        )


@dataclass(frozen=True, slots=True)
class EpochSet:
    """The provider's CURRENT basis for each scoped lifetime.

    Published with every observation and re-read at invoke time. ``None`` means
    "this scope does not currently exist" — no view, nothing focused, no document
    open — which invalidates every reference scoped to it. That is deliberate:
    "no field is focused" must not be treated as "any field will do".
    """

    view: str | None = None
    focus: str | None = None
    document: str | None = None
    session: str | None = None

    def current(self, lifetime: ReferenceLifetime) -> str | None:
        return {
            ReferenceLifetime.VIEW: self.view,
            ReferenceLifetime.FOCUS: self.focus,
            ReferenceLifetime.DOCUMENT: self.document,
            ReferenceLifetime.SESSION: self.session,
            ReferenceLifetime.PERSISTENT: None,
        }[lifetime]

    def to_dict(self) -> dict[str, Any]:
        return {
            k: v
            for k, v in (
                ("view", self.view),
                ("focus", self.focus),
                ("document", self.document),
                ("session", self.session),
            )
            if v is not None
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EpochSet:
        def opt(key: str) -> str | None:
            v = d.get(key)
            return None if v is None else str(v)

        return cls(
            view=opt("view"), focus=opt("focus"), document=opt("document"), session=opt("session")
        )


def check_reference(ref: Reference, epochs: EpochSet) -> UapError | None:
    """Validate ``ref`` against the provider's current epochs. ``None`` = usable.

    This is the fail-closed gate. It is intentionally the *only* place staleness
    is decided, so no call site can be clever and "just use the current one".
    """
    if ref.lifetime is ReferenceLifetime.PERSISTENT:
        return None
    current = epochs.current(ref.lifetime)
    if current is None:
        return UapError(
            UapErrorCode.STALE_REFERENCE,
            f"no current {ref.lifetime.value} to resolve {ref.kind} against",
        )
    if current != ref.basis:
        return UapError(
            UapErrorCode.STALE_REFERENCE,
            f"{ref.kind} reference is from an earlier {ref.lifetime.value}",
        )
    return None
