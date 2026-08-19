"""UAP canonical error taxonomy.

A UAP failure is a **typed, closed-set code** — never prose the host has to parse.
The set is deliberately small: it exists so the host can decide *what to do next*
(re-observe, clarify, re-authorise, retry, give up) without reading a message the
provider wrote. Prose lives in :attr:`UapError.message` for the user/audit trail
and is never load-bearing.

The two codes that carry the most design weight:

``STALE_REFERENCE``
    The single most important error in the protocol. The bridge must **never**
    silently retarget a stale reference to a different object (spec §References), so a
    reference whose epoch/revision has moved on fails closed with this code and
    the host re-observes or clarifies. Guessing "the nearest note" is how an
    agent edits the wrong document.

``UNSUPPORTED``
    An action the provider does not implement is **absent from discovery**, not a
    no-op (spec §Manifest and capability discovery). This code exists for the race —
    discovery said yes, the
    capability went away before the call landed — and for a host that invoked
    without discovering.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# Bounds every provider-supplied string that reaches an LLM or an audit row. A
# provider is untrusted input (spec "Safety" §), so its prose cannot be allowed to
# flood model context or a log line.
MAX_MESSAGE_CHARS = 200
MAX_REPAIR_FIELD_CHARS = 160
MAX_EXPECTED_ENUM_VALUES = 20


class InvalidCallExpectedKind(StrEnum):
    """The three constraint shapes an invalid call can repair against."""

    TYPE = "type"
    ENUM = "enum"
    RANGE = "range"


@dataclass(frozen=True, slots=True)
class InvalidCallExpectation:
    """A machine-actionable description of what one call field accepts.

    Exactly one variant is valid on the wire:

    - ``type`` carries ``type``;
    - ``enum`` carries ``values``;
    - ``range`` carries at least one of ``minimum`` / ``maximum`` and an optional
      unit.

    Keeping the variants explicit lets a host repair without parsing provider
    prose, while the tight bounds stop a malicious descriptor from turning an
    error into a context dump.
    """

    kind: InvalidCallExpectedKind
    type_name: str | None = None
    values: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    unit: str | None = None

    def __post_init__(self) -> None:
        if self.kind is InvalidCallExpectedKind.TYPE:
            valid = bool(self.type_name) and not self.values
            valid = valid and self.minimum is None and self.maximum is None and self.unit is None
        elif self.kind is InvalidCallExpectedKind.ENUM:
            valid = bool(self.values) and self.type_name is None
            valid = valid and self.minimum is None and self.maximum is None and self.unit is None
        else:
            valid = self.type_name is None and not self.values
            valid = valid and (self.minimum is not None or self.maximum is not None)
        if not valid:
            raise ValueError(f"invalid {self.kind.value} expectation")
        if self.minimum is not None and not math.isfinite(self.minimum):
            raise ValueError("invalid minimum")
        if self.maximum is not None and not math.isfinite(self.maximum):
            raise ValueError("invalid maximum")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum exceeds maximum")
        if len(self.values) > MAX_EXPECTED_ENUM_VALUES:
            raise ValueError("too many expected enum values")

        for field_name in ("type_name", "unit"):
            value = getattr(self, field_name)
            if value is not None and len(value) > MAX_REPAIR_FIELD_CHARS:
                object.__setattr__(self, field_name, value[:MAX_REPAIR_FIELD_CHARS])
        if self.values:
            object.__setattr__(
                self,
                "values",
                tuple(value[:MAX_REPAIR_FIELD_CHARS] for value in self.values),
            )
            if len(set(self.values)) != len(self.values):
                raise ValueError("expected enum values must be unique")

    @classmethod
    def type(cls, type_name: str) -> InvalidCallExpectation:
        return cls(InvalidCallExpectedKind.TYPE, type_name=type_name)

    @classmethod
    def enum(cls, values: tuple[str, ...]) -> InvalidCallExpectation:
        return cls(InvalidCallExpectedKind.ENUM, values=values)

    @classmethod
    def range(
        cls,
        *,
        minimum: float | None = None,
        maximum: float | None = None,
        unit: str | None = None,
    ) -> InvalidCallExpectation:
        return cls(
            InvalidCallExpectedKind.RANGE,
            minimum=minimum,
            maximum=maximum,
            unit=unit,
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"kind": self.kind.value}
        if self.kind is InvalidCallExpectedKind.TYPE:
            result["type"] = self.type_name
        elif self.kind is InvalidCallExpectedKind.ENUM:
            result["values"] = list(self.values)
        else:
            if self.minimum is not None:
                result["minimum"] = self.minimum
            if self.maximum is not None:
                result["maximum"] = self.maximum
            if self.unit is not None:
                result["unit"] = self.unit
        return result

    @classmethod
    def from_dict(cls, value: Any) -> InvalidCallExpectation:
        if not isinstance(value, dict):
            raise ValueError("expected constraint must be an object")
        try:
            kind = InvalidCallExpectedKind(str(value.get("kind", "")))
        except ValueError as exc:
            raise ValueError("unknown expected constraint kind") from exc

        if kind is InvalidCallExpectedKind.TYPE:
            type_name = value.get("type")
            if not isinstance(type_name, str):
                raise ValueError("type expectation is missing type")
            return cls.type(type_name)
        if kind is InvalidCallExpectedKind.ENUM:
            raw_values = value.get("values")
            if not isinstance(raw_values, list) or not all(
                isinstance(item, str) for item in raw_values
            ):
                raise ValueError("enum expectation is missing string values")
            return cls.enum(tuple(raw_values))

        raw_minimum = value.get("minimum")
        raw_maximum = value.get("maximum")
        minimum = _finite_number(raw_minimum, "minimum")
        maximum = _finite_number(raw_maximum, "maximum")
        unit = value.get("unit")
        if unit is not None and not isinstance(unit, str):
            raise ValueError("range unit must be a string")
        return cls.range(minimum=minimum, maximum=maximum, unit=unit)


class UapErrorCode(StrEnum):
    """The closed set of UAP failure codes. Providers may not invent codes."""

    # -- addressing / lifetime --------------------------------------------
    STALE_REFERENCE = "stale_reference"
    """A reference outlived its declared lifetime (epoch, revision, or scope moved)."""
    UNKNOWN_REFERENCE = "unknown_reference"
    """A well-formed reference was never issued by, or no longer belongs to, this binding."""

    # -- capability --------------------------------------------------------
    UNSUPPORTED = "unsupported"
    """No such action or capability is declared by this binding."""
    AMBIGUOUS = "ambiguous"
    """More than one provider offers this action at equal assurance — ask which."""
    PRECONDITION_FAILED = "precondition_failed"
    """A declared precondition did not hold (nothing focused, no note open, ...)."""
    INVALID_CALL = "invalid_call"
    """The action envelope is malformed; structured fields say how to repair it."""
    INVALID_ARGUMENT = "invalid_argument"
    """A well-formed call failed the provider's domain validation."""

    # -- authority ---------------------------------------------------------
    PERMISSION_DENIED = "permission_denied"
    """Host policy, tenancy, OS permission, or the user denied it.

    See :class:`DeniedScope` for how far the refusal reaches — the difference between
    "not this record" and "not at all", which the code alone cannot carry.
    """
    CONFIRMATION_REQUIRED = "confirmation_required"
    """A consequential action reached the provider without the host's approval basis."""

    # -- execution ---------------------------------------------------------
    CONFLICT = "conflict"
    """An optimistic revision check lost — someone else wrote first."""
    CANCELLED = "cancelled"
    """The user, an emergency stop, or the host cancelled it at a safe boundary."""
    TIMEOUT = "timeout"
    """No result from the provider within the host's bound."""
    UNAVAILABLE = "unavailable"
    """The provider/client is not reachable or not bound to this session.

    See :class:`UnavailableScope` for how much of the target is gone — "the editor is not
    running" and "that window closed, the editor is still open" are one code today and have
    different recoveries.
    """
    INTERNAL = "internal"
    """The provider failed in a way it could not classify."""


class DeniedScope(StrEnum):
    """How far a ``PERMISSION_DENIED`` reaches (spec §Manifest and capability discovery).

    Two refusals wear the same code and mean opposite things. "You may not void
    *this* invoice" is a row-level rule about one record and says nothing about the
    capability. "You may not void invoices" is authority the manifest claimed and no
    longer has. Without this field a host must either ignore the second — leaving a
    stale capability it will keep offering for the binding — or act on the first and
    disable invoicing because one protected record said no.

    Absent means :attr:`TARGET`. That is the direction that fails safely: a provider
    that forgets to classify its refusal costs one wasted retry, never a capability
    the user still has.
    """

    TARGET = "target"
    """This record/object/document only. Discovery is untouched; try another target."""

    CAPABILITY = "capability"
    """The whole capability for this binding. Its manifest is stale — stop offering it."""


class UnavailableScope(StrEnum):
    """How much of the target an ``UNAVAILABLE`` reaches — the HOST's own derivation.

    Three failures used to be one sentence to the user. Two of them are this code, and they are
    not the same situation: *no binding of this application is attached* means the editor is not
    running, while *this binding is gone and a sibling is alive* means one window closed and the
    editor is still there. The second is the more actionable of the two — it is the only one with
    an alternative to offer — and it was the one that could not be said.

    **Not wire vocabulary, and deliberately so.** A provider never sends this: it knows about
    itself and nothing about the other windows of its own application, so only the host — which
    holds the registry — can tell the two apart. It is therefore derived rather than declared, it
    is absent from :meth:`UapError.to_dict`, and :meth:`UapError.from_dict` ignores it if a
    provider sends one anyway. The vocabulary that is restated in six client implementations and
    gated by the cross-client parity suite stays untouched.

    Absent means the host derived nothing — a provider-authored ``unavailable``, or a failure
    that happened before anything was routed. It reads as NEITHER value, because claiming "that
    app is not running" about a refusal we did not derive is a guess, and the guess would be
    spoken aloud.
    """

    PROVIDER = "provider"
    """No binding of this application is attached at all. Today's meaning, made explicit."""

    BINDING = "binding"
    """Only this attachment is gone; siblings of the same application are live and listed."""


#: How many surviving siblings ride along with a binding-scoped unavailability. This feeds an
#: OFFER ("you've another one open"), not a listing, so it is bounded near one rather than near
#: the number of windows a person can have open.
MAX_ALTERNATIVE_BINDINGS = 3


@dataclass(frozen=True, slots=True)
class AlternativeBinding:
    """One live sibling of a dead binding: what the host may OFFER, never what it may use.

    ``same_machine`` is carried because the two offers are not equally safe to accept — "your
    other window" and "a window on your desktop" invite different answers — and the user cannot
    tell them apart from the handle. It is derivable from the handle
    but is resolved once, at mint time, against the
    binding that actually failed: nothing downstream still knows which one that was.
    """

    binding: str
    """The routing handle to re-issue against, IF the user says so. Never a provider id."""

    same_machine: bool
    """Whether this sibling is on the machine the dead binding was on."""


#: Codes a host should answer by re-observing rather than by asking the user.
#: Re-observation is cheap and usually resolves the race that produced them.
REOBSERVABLE: frozenset[UapErrorCode] = frozenset(
    {
        UapErrorCode.STALE_REFERENCE,
        UapErrorCode.UNKNOWN_REFERENCE,
        UapErrorCode.CONFLICT,
    }
)

#: Error codes for which re-observation can make a second attempt meaningful.
#:
#: This is eligibility, not permission to retry. The error code is only one necessary
#: condition: the reference runtime also requires a declared, non-empty, all-``read`` effect
#: set; no generic descriptor preconditions or ``expect_revision``; a fresh object that still
#: advertises the action; plus its unchanged-outcome, identity, routing, focus, confirmation,
#: and retry-count guards. A view transition or mutation is re-observed and then returns to
#: policy/the user without redispatch, because the host cannot yet prove that its preconditions
#: and the scope of continuing consent still hold.
#:
#: ``CONFLICT`` is deliberately excluded despite being re-observable. A conflict means someone
#: else's edit landed first; re-observing tells you what it says now, and retrying against the
#: fresh revision would overwrite it. That is precisely what the optimistic check exists to
#: prevent, so a conflict has to reach a decision-maker rather than a retry loop.
AUTOMATIC_RETRY_ELIGIBLE_CODES: frozenset[UapErrorCode] = frozenset(
    {
        UapErrorCode.STALE_REFERENCE,
        UapErrorCode.UNKNOWN_REFERENCE,
    }
)

#: A malformed call may be repaired once from its structured constraint. This is
#: deliberately separate from the retry sets above: repair changes the call,
#: whereas re-observation refreshes the world around an otherwise valid call.
REPAIRABLE: frozenset[UapErrorCode] = frozenset({UapErrorCode.INVALID_CALL})

#: Codes that must never be retried automatically: retrying is either pointless
#: or is itself the abuse (hammering a denied permission, re-running a cancelled
#: action the user just stopped). ``AMBIGUOUS`` is deliberately in NEITHER set:
#: re-observing will not resolve it and it is not terminal — only the user can say
#: which one they meant, so it is a clarify signal, not a failure.
TERMINAL: frozenset[UapErrorCode] = frozenset(
    {
        UapErrorCode.PERMISSION_DENIED,
        UapErrorCode.CONFIRMATION_REQUIRED,
        UapErrorCode.CANCELLED,
        UapErrorCode.UNSUPPORTED,
        UapErrorCode.INVALID_ARGUMENT,
    }
)


@dataclass(frozen=True, slots=True)
class UapError:
    """One typed failure. ``code`` is for the host; ``message`` is for the human.

    ``INVALID_CALL`` additionally requires the repair fields. They live on the
    error object itself so every language sees one stable envelope rather than a
    prose convention hidden inside ``message``.
    """

    code: UapErrorCode
    message: str = ""
    field_path: str | None = None
    expected: InvalidCallExpectation | None = None
    got: str | None = None
    suggestion: str | None = None
    denied_scope: DeniedScope | None = None
    """Only meaningful on ``PERMISSION_DENIED``; absent reads as :attr:`DeniedScope.TARGET`."""

    unavailable_scope: UnavailableScope | None = None
    """Only meaningful on ``UNAVAILABLE``, and only ever set by the HOST. Absent reads as
    neither value — see :class:`UnavailableScope`."""

    alternatives: tuple[AlternativeBinding, ...] = ()
    """Live siblings of a dead binding, best offer first. Present only with
    :attr:`UnavailableScope.BINDING`, and an OFFER: nothing here may be routed to without the
    user agreeing and the action being planned again."""

    def __post_init__(self) -> None:
        # Truncate rather than reject: an over-long message is a provider bug, but
        # losing the whole error because of it would be worse for the user.
        if len(self.message) > MAX_MESSAGE_CHARS:
            object.__setattr__(self, "message", self.message[:MAX_MESSAGE_CHARS])
        if self.denied_scope is not None and self.code is not UapErrorCode.PERMISSION_DENIED:
            raise ValueError(f"denied_scope is meaningless on {self.code.value}")
        if self.unavailable_scope is not None and self.code is not UapErrorCode.UNAVAILABLE:
            raise ValueError(f"unavailable_scope is meaningless on {self.code.value}")
        # Both directions, because either half alone is a lie the user hears. Alternatives
        # without the scope would offer another window while the sentence still says the
        # application is gone; the scope without alternatives claims a sibling survived and then
        # names none, leaving "shall I use the other one" pointing at nothing.
        binding_scoped = self.unavailable_scope is UnavailableScope.BINDING
        if bool(self.alternatives) is not binding_scoped:
            raise ValueError("binding-scoped unavailability and its alternatives are one fact")
        if len(self.alternatives) > MAX_ALTERNATIVE_BINDINGS:
            # Trimmed, not rejected: a user with five windows open is not a bug, and the caller
            # has already put the offer it wants made first (see UapRuntime._unavailable).
            object.__setattr__(self, "alternatives", self.alternatives[:MAX_ALTERNATIVE_BINDINGS])
        if self.code is UapErrorCode.INVALID_CALL:
            if not self.field_path or self.expected is None or self.got is None:
                raise ValueError("invalid_call requires field_path, expected, and got")
            for field_name in ("field_path", "got", "suggestion"):
                value = getattr(self, field_name)
                if value is not None and len(value) > MAX_REPAIR_FIELD_CHARS:
                    object.__setattr__(self, field_name, value[:MAX_REPAIR_FIELD_CHARS])

    @property
    def reobservable(self) -> bool:
        """True when re-observing may resolve this without bothering the user."""
        return self.code in REOBSERVABLE

    @property
    def terminal(self) -> bool:
        """True when an automatic retry is pointless or abusive."""
        return self.code in TERMINAL

    @property
    def repairable(self) -> bool:
        """True when the host may make one structured correction attempt."""
        return self.code in REPAIRABLE

    @property
    def revokes_capability(self) -> bool:
        """True when this refusal means the manifest is stale, not that the target was wrong."""
        return (
            self.code is UapErrorCode.PERMISSION_DENIED
            and self.denied_scope is DeniedScope.CAPABILITY
        )

    def to_dict(self) -> dict[str, Any]:
        """The wire form. ``unavailable_scope`` and ``alternatives`` are deliberately absent.

        Unlike ``denied_scope``, which a provider emits and every client restates, those two are
        host-minted and host-consumed: serialising them would add words to a published schema
        that no peer can produce, and would hand one application the routing handles of another
        window it has no business knowing about.
        """
        result: dict[str, Any] = {"code": self.code.value, "message": self.message}
        if self.denied_scope is not None:
            result["denied_scope"] = self.denied_scope.value
        if self.code is UapErrorCode.INVALID_CALL:
            # Guarded by __post_init__; these casts merely narrow for type checkers.
            assert self.field_path is not None
            assert self.expected is not None
            assert self.got is not None
            result.update(
                {
                    "field_path": self.field_path,
                    "expected": self.expected.to_dict(),
                    "got": self.got,
                }
            )
            if self.suggestion is not None:
                result["suggestion"] = self.suggestion
        return result

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> UapError:
        """Parse a provider-supplied error, failing CLOSED on an unknown code.

        A provider that invents a code does not get to define new host behaviour:
        anything off the closed set becomes ``INTERNAL``, which is neither
        re-observable nor auto-retryable.
        """
        raw = str(d.get("code", ""))
        try:
            code = UapErrorCode(raw)
        except ValueError:
            code = UapErrorCode.INTERNAL
        message = str(d.get("message", ""))[:MAX_MESSAGE_CHARS]
        if code is UapErrorCode.PERMISSION_DENIED:
            # Unrecognised scope degrades to TARGET rather than raising: a refusal the
            # host cannot classify must still reach the user as a refusal, and the
            # narrow reading is the one that cannot lose a capability by accident.
            try:
                scope = DeniedScope(str(d.get("denied_scope", DeniedScope.TARGET.value)))
            except ValueError:
                scope = DeniedScope.TARGET
            return cls(code=code, message=message, denied_scope=scope)
        if code is not UapErrorCode.INVALID_CALL:
            # An `unavailable` arriving from a provider gets NO scope and NO alternatives, even
            # if it sent some. Only the host holds the registry, so a provider claiming "this
            # binding died, use that one instead" would be naming a target the host never derived
            # — a provider steering the host's offer toward a window of its choosing.
            return cls(code=code, message=message)
        try:
            field_path = d.get("field_path")
            got = d.get("got")
            suggestion = d.get("suggestion")
            if not isinstance(field_path, str) or not isinstance(got, str):
                raise ValueError("invalid_call is missing repair fields")
            if suggestion is not None and not isinstance(suggestion, str):
                raise ValueError("invalid_call suggestion must be a string")
            return cls(
                code=code,
                message=message,
                field_path=field_path,
                expected=InvalidCallExpectation.from_dict(d.get("expected")),
                got=got,
                suggestion=suggestion,
            )
        except ValueError:
            # A provider does not earn repair behaviour merely by spelling the
            # code correctly. A malformed repair shape is opaque INTERNAL input.
            return cls(UapErrorCode.INTERNAL, "malformed invalid_call")


def _finite_number(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number
