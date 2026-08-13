"""UAP runtime envelopes: observe, invoke, result, verify, events.

Specification: the observation, typed-action, results and events sections.

These are the messages that cross the bridge once discovery has happened. Three
properties shape every one of them.

**Bounded, always.** An observation is a *query result*, never a dump of the DOM,
the accessibility tree, or every object in the document (spec §Observation). Every list
carries how many items were withheld, so the host can tell the model "47 more not
shown" and let it narrow the query — rather than letting it assume it saw
everything. This is context economy applied to a protocol boundary.

**Never optimistic about success.** :class:`ActionResult` separates *dispatched*
from *done*: ``ACCEPTED`` means the provider took the command, and nothing more.
"Observe, act, verify" (product principle 5) only works if the envelope refuses to
conflate the two — an action is not successful because input was sent.

**Ordered, gap-detectable.** Events carry a monotonic sequence so the host can
notice it missed one, drop what arrived out of order, and re-observe (spec §Events)
instead of acting on a state it silently mis-assembled.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from uap_core.errors import InvalidCallExpectation, UapError, UapErrorCode
from uap_core.references import (
    MAX_REFERENCE_BASIS_CHARS,
    MAX_REFERENCE_ID_CHARS,
    MAX_REFERENCE_KIND_CHARS,
    EpochSet,
    Reference,
    ReferenceLifetime,
)

#: Payload bounds. Both directions are untrusted: a provider can be compromised or
#: simply buggy, and an oversized frame is a context-flooding and memory-pressure
#: primitive. Enforced by the host bridge, not by politeness.
MAX_OBSERVED_OBJECTS = 20
MAX_ARGUMENT_CHARS = 8_000
MAX_ARGUMENT_KEYS = 20
#: Maximum nested container depth inside ``ActionCall.arguments``. The root arguments map is
#: depth zero. This is a wire/safety bound, not a model-prompt suggestion: deeply recursive
#: JSON can exhaust parsers long before it reaches the encoded-size cap.
MAX_ARGUMENT_DEPTH = 16
#: Bounds for the ActionCall control plane. These are Unicode-scalar counts, matching
#: Python ``len`` and the published TypeScript/Dart/Go implementations. They are deliberately
#: separate from argument JSON size: identifiers reach routing, audit, and replay tables even
#: when the provider never executes the action.
MAX_ACTION_CHARS = 132
MAX_COMMAND_ID_CHARS = 128
MAX_PROVIDER_CHARS = 200
MAX_REVISION_CHARS = 128
MAX_PROPERTY_CHARS = 400
#: An action's output payload is the one part of a result that reaches model context at full
#: width, so it carries the host's read-a-file context cap rather than a protocol-shaped
#: number. A read that returned a whole document would bill the user for it on the spot.
MAX_RESULT_DATA_CHARS = 2_000
MAX_RESULT_DATA_KEYS = 20
#: Per-object key/action count. `MAX_OBSERVED_OBJECTS` bounds how many objects arrive, not how
#: fat each one is; without this a conforming-looking snapshot could still be megabytes.
MAX_OBJECT_KEYS = 32

_MISSING = object()


class ActionCallDecodeError(ValueError):
    """A malformed ActionCall field, with the exact repair envelope for the wire.

    Keeping diagnostics in the canonical parser prevents each transport from guessing why
    parsing failed. The exception carries no provider prose and is safe to convert directly
    to ``invalid_call``; callers must reject the entire call and must not invoke a provider.
    """

    def __init__(
        self,
        field_path: str,
        expected: InvalidCallExpectation,
        got: str,
        *,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(f"invalid ActionCall field {field_path}: got {got}")
        self.field_path = field_path
        self.expected = expected
        self.got = got
        self.suggestion = suggestion

    def to_uap_error(self) -> UapError:
        """Return the closed, machine-repairable error shape used on every transport."""
        return UapError(
            UapErrorCode.INVALID_CALL,
            "the action call does not match the wire contract",
            field_path=self.field_path,
            expected=self.expected,
            got=self.got,
            suggestion=self.suggestion,
        )


class ObservationScope(StrEnum):
    """Which slices of state a query wants. Asking for less costs less."""

    VIEW = "view"
    """Where the user is: route/page/screen and its short title."""

    FOCUS = "focus"
    """What has keyboard focus, and what kind of thing it is."""

    SELECTION = "selection"
    """What is selected or where the cursor sits."""

    DOCUMENT = "document"
    """The open document's identity, revision, and dirty state — not its contents."""

    OBJECTS = "objects"
    """Semantic objects addressable in the current view."""


@dataclass(frozen=True, slots=True)
class ObservationQuery:
    """A bounded request for state. Unscoped queries are not allowed to mean 'everything'."""

    scopes: tuple[ObservationScope, ...] = (ObservationScope.VIEW,)
    ref: Reference | None = None
    """Narrow to one object's subtree/detail, when the provider supports it."""

    limit: int = MAX_OBSERVED_OBJECTS

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "scopes": [s.value for s in self.scopes],
            "limit": min(self.limit, MAX_OBSERVED_OBJECTS),
        }
        if self.ref is not None:
            d["ref"] = self.ref.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ObservationQuery:
        scopes: list[ObservationScope] = []
        for raw in d.get("scopes", []) if isinstance(d.get("scopes"), list) else []:
            try:
                scopes.append(ObservationScope(str(raw)))
            except ValueError:
                continue  # an unknown scope is ignored, never treated as "all"
        raw_ref = d.get("ref")
        return cls(
            scopes=tuple(scopes) or (ObservationScope.VIEW,),
            ref=Reference.from_dict(raw_ref) if isinstance(raw_ref, dict) else None,
            limit=min(int(d.get("limit", MAX_OBSERVED_OBJECTS)), MAX_OBSERVED_OBJECTS),
        )


@dataclass(frozen=True, slots=True)
class ObservedObject:
    """One addressable thing, as a reference plus a few facts — never its contents."""

    ref: Reference
    type: str
    """Domain type, e.g. ``portal.page``, ``note.document``, ``device.calendar_event``."""

    title: str = ""
    properties: dict[str, str] = field(default_factory=dict)
    """Small scalar facts only. Bodies, blobs and images stay behind the reference."""

    actions: tuple[str, ...] = ()
    """Action names currently available ON this object."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref.to_dict(),
            "type": self.type,
            "title": self.title,
            "properties": dict(self.properties),
            "actions": list(self.actions),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ObservedObject:
        raw_props = d.get("properties")
        props = dict(raw_props) if isinstance(raw_props, dict) else {}
        raw_actions = d.get("actions")
        raw_ref = d.get("ref")
        return cls(
            ref=Reference.from_dict(raw_ref if isinstance(raw_ref, dict) else {}),
            type=str(d.get("type", ""))[:64],
            title=str(d.get("title", ""))[:120],
            # Per-value AND per-count: bounding the value alone left 20 objects x N properties
            # unbounded in aggregate, so "bounded, always" was not true for this field.
            properties={
                str(k): str(v)[:MAX_PROPERTY_CHARS]
                for k, v in list(props.items())[:MAX_OBJECT_KEYS]
            },
            actions=(
                tuple(str(a)[:64] for a in raw_actions[:MAX_OBJECT_KEYS])
                if isinstance(raw_actions, list)
                else ()
            ),
        )


@dataclass(frozen=True, slots=True)
class Observation:
    """A coherent, bounded snapshot: what is on screen, and what can be done to it."""

    provider: str
    epochs: EpochSet
    """The bases every reference in this observation was minted against."""

    view_key: str | None = None
    """The provider's key for the current view. None = the user is somewhere undrivable."""

    view_title: str | None = None
    focus_kind: str | None = None
    """What has focus, coarsely (``text_field``, ``editor``, ``none``)."""

    objects: tuple[ObservedObject, ...] = ()
    omitted: int = 0
    """How many objects the limit withheld. Non-zero means "narrow the query"."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "epochs": self.epochs.to_dict(),
            "view_key": self.view_key,
            "view_title": self.view_title,
            "focus_kind": self.focus_kind,
            "objects": [o.to_dict() for o in self.objects],
            "omitted": self.omitted,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Observation:
        raw_objects = d.get("objects")
        objects = raw_objects if isinstance(raw_objects, list) else []
        kept = objects[:MAX_OBSERVED_OBJECTS]
        # A provider that over-sends is truncated HERE and the overflow is counted,
        # so an over-eager client cannot flood model context by ignoring the limit.
        dropped = len(objects) - len(kept)

        # One unparseable object must not cost the whole snapshot: it is dropped and
        # counted as omitted. Losing every reference because a single note has an
        # awkward path would take the user's whole surface offline over one row.
        parsed: list[ObservedObject] = []
        for raw in kept:
            if not isinstance(raw, dict):
                dropped += 1
                continue
            try:
                parsed.append(ObservedObject.from_dict(raw))
            except (ValueError, TypeError):
                dropped += 1

        raw_epochs = d.get("epochs")
        return cls(
            provider=str(d.get("provider", "")),
            epochs=EpochSet.from_dict(raw_epochs if isinstance(raw_epochs, dict) else {}),
            view_key=_opt_str(d.get("view_key"), 64),
            view_title=_opt_str(d.get("view_title"), 120),
            focus_kind=_opt_str(d.get("focus_kind"), 32),
            objects=tuple(parsed),
            omitted=max(int(d.get("omitted", 0)), 0) + dropped,
        )


@dataclass(frozen=True, slots=True)
class ActionCall:
    """One invocation: what to do, to which object, under which basis."""

    action: str
    command_id: str
    """Unique per attempt. The idempotency and audit key; replayed only for a retry."""

    ref: Reference | None = None
    arguments: dict[str, Any] = field(default_factory=dict)

    expect_revision: str | None = None
    """Optimistic precondition. The provider rejects with CONFLICT if state moved on."""

    dry_run: bool = False
    """Ask for a preview instead of a commit. Only meaningful if the provider declares it."""

    provider: str | None = None
    """Pin the action to one provider, answering an ``AMBIGUOUS`` clarification.

    Standardising action names to ``<noun>.<verb>`` is what makes the protocol interfaceable —
    and it also makes `note.undo` mean the same thing on the phone and in the browser, so the
    host can no longer assume one candidate. When the user says "on my phone", that answer
    travels here rather than the router guessing."""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "action": self.action,
            "command_id": self.command_id,
            "arguments": dict(self.arguments),
            "dry_run": self.dry_run,
        }
        if self.provider is not None:
            d["provider"] = self.provider
        if self.ref is not None:
            d["ref"] = self.ref.to_dict()
        if self.expect_revision is not None:
            d["expect_revision"] = self.expect_revision
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ActionCall:
        # Decode in one canonical order shared by Python, TypeScript and Dart. When more than
        # one field is malformed, every transport must name the same first repair rather than
        # sending a model into a cross-language repair loop.
        action = _required_call_string(d, "action", MAX_ACTION_CHARS)
        command_id = _required_call_string(d, "command_id", MAX_COMMAND_ID_CHARS)
        arguments = parse_action_arguments(d.get("arguments", _MISSING))
        provider = _optional_call_string(d, "provider", MAX_PROVIDER_CHARS)
        expect_revision = _optional_call_string(d, "expect_revision", MAX_REVISION_CHARS)
        dry_run = _parse_dry_run(d)
        ref = _parse_action_reference(d)
        return cls(
            action=action,
            command_id=command_id,
            ref=ref,
            # Action inputs are rejected atomically when they exceed the contract. Truncating
            # an output is safe when it carries an explicit marker; truncating an input can
            # silently remove a recipient, range, or option and execute a different command.
            arguments=arguments,
            expect_revision=expect_revision,
            dry_run=dry_run,
            provider=provider,
        )


class ActionStatus(StrEnum):
    """What actually happened. ``ACCEPTED`` is not ``COMPLETED``."""

    ACCEPTED = "accepted"
    """Taken for execution. Says nothing about the outcome — verify before claiming success."""

    COMPLETED = "completed"
    """Finished, and the provider observed the intended effect."""

    PREVIEWED = "previewed"
    """A dry run produced a result; nothing was committed."""

    REJECTED = "rejected"
    """Refused before doing anything. ``error`` says why. Nothing changed."""

    FAILED = "failed"
    """Started and did not finish. State may be partially changed — re-observe."""

    CANCELLED = "cancelled"
    """Stopped at a safe boundary, by the user or the host."""


#: Statuses that guarantee nothing changed. Anything outside this set must be
#: re-observed before the host tells the user what the world looks like.
_NO_EFFECT: frozenset[ActionStatus] = frozenset({ActionStatus.REJECTED, ActionStatus.PREVIEWED})


@dataclass(frozen=True, slots=True)
class ActionResult:
    """The structured outcome of one invocation."""

    command_id: str
    status: ActionStatus
    error: UapError | None = None
    ref: Reference | None = None
    """The object actually acted on, re-issued at its post-action basis."""

    revision_before: str | None = None
    revision_after: str | None = None
    undo_token: str | None = None
    """Opaque, operation-bound. Present only when this exact command can be undone."""

    detail: str = ""
    """One short line for the user/audit. Never the document body."""

    data: dict[str, Any] = field(default_factory=dict)
    """The action's typed OUTPUT — what a read actually returns.

    (Spec: typed actions, "typed inputs and output".) Bounded by
    :data:`MAX_RESULT_DATA_CHARS`, because this is the one part of a
    result that reaches model context at full width; a read that returns a whole document
    would bill the user for it on the spot. Oversized payloads are truncated with a
    ``_truncated`` marker so the model knows to narrow rather than assume it saw everything."""

    @property
    def changed_nothing(self) -> bool:
        """True only when the provider guarantees the world is untouched."""
        return self.status in _NO_EFFECT

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "command_id": self.command_id,
            "status": self.status.value,
            "detail": self.detail,
        }
        if self.data:
            d["data"] = dict(self.data)
        if self.error is not None:
            d["error"] = self.error.to_dict()
        if self.ref is not None:
            d["ref"] = self.ref.to_dict()
        for key, value in (
            ("revision_before", self.revision_before),
            ("revision_after", self.revision_after),
            ("undo_token", self.undo_token),
        ):
            if value is not None:
                d[key] = value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ActionResult:
        """Parse a provider result, failing CLOSED on an unrecognised status.

        An unknown status becomes ``FAILED``, not ``COMPLETED``: the host must
        never report success because a client sent a word it did not understand.
        """
        try:
            status = ActionStatus(str(d.get("status", "")))
        except ValueError:
            status = ActionStatus.FAILED
        raw_error = d.get("error")
        raw_ref = d.get("ref")
        return cls(
            command_id=str(d.get("command_id", "")),
            status=status,
            error=UapError.from_dict(raw_error) if isinstance(raw_error, dict) else None,
            ref=Reference.from_dict(raw_ref) if isinstance(raw_ref, dict) else None,
            revision_before=_opt_str(d.get("revision_before"), 128),
            revision_after=_opt_str(d.get("revision_after"), 128),
            undo_token=_opt_str(d.get("undo_token"), 256),
            detail=str(d.get("detail", ""))[:200],
            data=_bounded_data(d.get("data")),
        )


@dataclass(frozen=True, slots=True)
class Expectation:
    """What the host believes should now be true, for the provider to check.

    Deliberately narrow: a revision and a handful of scalar properties. Verifying
    by diffing whole documents would put the document into model context, which is
    exactly what the two-plane rule forbids: bulk content stays in the local tool
    plane, and only the facts needed for the current decision reach the model.
    """

    ref: Reference | None = None
    revision: str | None = None
    properties: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"properties": dict(self.properties)}
        if self.ref is not None:
            d["ref"] = self.ref.to_dict()
        if self.revision is not None:
            d["revision"] = self.revision
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Expectation:
        raw_ref = d.get("ref")
        raw_props = d.get("properties")
        return cls(
            ref=Reference.from_dict(raw_ref) if isinstance(raw_ref, dict) else None,
            revision=_opt_str(d.get("revision"), 128),
            properties=(
                {str(k): str(v)[:MAX_PROPERTY_CHARS] for k, v in raw_props.items()}
                if isinstance(raw_props, dict)
                else {}
            ),
        )


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Did the world actually end up the way the action claimed? (principle 5)"""

    verified: bool
    observation: Observation | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"verified": self.verified, "detail": self.detail}
        if self.observation is not None:
            d["observation"] = self.observation.to_dict()
        return d


@dataclass(frozen=True, slots=True)
class ProviderEvent:
    """One ordered lifecycle event. Carries references and routing facts, never content."""

    provider: str
    type: str
    """e.g. ``view.changed``, ``focus.changed``, ``document.changed``, ``reference.invalidated``."""

    seq: int
    """Monotonic per provider session. A gap means the host must re-observe."""

    ref: Reference | None = None
    epochs: EpochSet | None = None
    """The new bases, when this event moved one. Lets the host invalidate without a round trip."""

    def to_dict(self) -> dict[str, Any]:
        # `event` carries the SEMANTIC type; the envelope's own `type` is transport routing
        # (``uap.event``) and is stamped by the sender. Two fields because one cannot be both:
        # reusing `type` made every event arrive as "uap.event", which is a routing label, not
        # something a host can react to.
        d: dict[str, Any] = {"provider": self.provider, "event": self.type, "seq": self.seq}
        if self.ref is not None:
            d["ref"] = self.ref.to_dict()
        if self.epochs is not None:
            d["epochs"] = self.epochs.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ProviderEvent:
        raw_ref = d.get("ref")
        raw_epochs = d.get("epochs")
        return cls(
            provider=str(d.get("provider", "")),
            type=str(d.get("event", ""))[:64],
            seq=int(d.get("seq", 0)),
            ref=Reference.from_dict(raw_ref) if isinstance(raw_ref, dict) else None,
            epochs=EpochSet.from_dict(raw_epochs) if isinstance(raw_epochs, dict) else None,
        )


def _opt_str(value: Any, limit: int) -> str | None:
    return None if value is None else str(value)[:limit]


def _required_call_string(d: dict[str, Any], key: str, maximum: int) -> str:
    value = d.get(key, _MISSING)
    return _bounded_call_string(value, path=f"/{key}", maximum=maximum)


def _optional_call_string(d: dict[str, Any], key: str, maximum: int) -> str | None:
    if key not in d:
        return None
    return _bounded_call_string(d[key], path=f"/{key}", maximum=maximum)


def _bounded_call_string(value: Any, *, path: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ActionCallDecodeError(
            path,
            InvalidCallExpectation.type("string"),
            _json_kind(value),
        )
    length = len(value)
    if length < 1 or length > maximum:
        raise ActionCallDecodeError(
            path,
            InvalidCallExpectation.range(
                minimum=1,
                maximum=maximum,
                unit="unicode_scalars",
            ),
            f"{length} unicode_scalars",
        )
    return value


def _parse_dry_run(d: dict[str, Any]) -> bool:
    if "dry_run" not in d:
        return False
    value = d["dry_run"]
    if not isinstance(value, bool):
        raise ActionCallDecodeError(
            "/dry_run",
            InvalidCallExpectation.type("boolean"),
            _json_kind(value),
        )
    return value


def _parse_action_reference(d: dict[str, Any]) -> Reference | None:
    if "ref" not in d:
        return None
    raw = d["ref"]
    if not isinstance(raw, dict):
        raise ActionCallDecodeError(
            "/ref",
            InvalidCallExpectation.type("object"),
            _json_kind(raw),
        )

    allowed = {"kind", "id", "lifetime", "basis"}
    extra = next((key for key in raw if not isinstance(key, str) or key not in allowed), None)
    if extra is not None:
        segment = _pointer_segment(str(extra))
        raise ActionCallDecodeError(
            f"/ref/{segment}",
            InvalidCallExpectation.type("no additional property"),
            "unexpected property",
        )

    kind = _bounded_call_string(
        raw.get("kind", _MISSING),
        path="/ref/kind",
        maximum=MAX_REFERENCE_KIND_CHARS,
    )
    identifier = _bounded_call_string(
        raw.get("id", _MISSING),
        path="/ref/id",
        maximum=MAX_REFERENCE_ID_CHARS,
    )
    raw_lifetime = raw.get("lifetime", _MISSING)
    lifetimes = tuple(value.value for value in ReferenceLifetime)
    if not isinstance(raw_lifetime, str) or raw_lifetime not in lifetimes:
        raise ActionCallDecodeError(
            "/ref/lifetime",
            InvalidCallExpectation.enum(lifetimes),
            _json_kind(raw_lifetime) if not isinstance(raw_lifetime, str) else "unknown value",
        )
    lifetime = ReferenceLifetime(raw_lifetime)

    basis: str | None = None
    if "basis" in raw:
        basis = _bounded_call_string(
            raw["basis"],
            path="/ref/basis",
            maximum=MAX_REFERENCE_BASIS_CHARS,
        )
    elif lifetime is not ReferenceLifetime.PERSISTENT:
        raise ActionCallDecodeError(
            "/ref/basis",
            InvalidCallExpectation.type("string"),
            "missing",
        )

    try:
        return Reference(kind=kind, id=identifier, lifetime=lifetime, basis=basis)
    except ValueError as exc:
        field = "kind" if "kind" in str(exc) else "id"
        raise ActionCallDecodeError(
            f"/ref/{field}",
            InvalidCallExpectation.type(f"valid reference {field}"),
            "invalid string",
        ) from exc


def action_arguments_valid(value: Any) -> bool:
    """Whether an argument map can cross the wire without changing its meaning.

    The size is measured on the compact JSON representation that will actually be sent. Values
    must therefore be JSON-native too; accepting ``default=str`` here would make a local Python
    object turn into a different wire value behind the caller's back.
    """
    try:
        parse_action_arguments(value)
    except ActionCallDecodeError:
        return False
    return True


def parse_action_arguments(value: Any) -> dict[str, Any]:
    """Parse actionable input without ever returning a partial command."""
    if not isinstance(value, dict):
        raise ActionCallDecodeError(
            "/arguments",
            InvalidCallExpectation.type("object"),
            _json_kind(value),
        )
    if len(value) > MAX_ARGUMENT_KEYS:
        raise ActionCallDecodeError(
            "/arguments",
            InvalidCallExpectation.range(maximum=MAX_ARGUMENT_KEYS, unit="properties"),
            f"{len(value)} properties",
        )
    shape_error = _action_argument_shape_error(value, path="/arguments", depth=0, active=set())
    if shape_error is not None:
        raise shape_error
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise ActionCallDecodeError(
            "/arguments",
            InvalidCallExpectation.type("finite acyclic JSON"),
            "unencodable",
        ) from exc
    encoded_chars = len(encoded)
    if encoded_chars > MAX_ARGUMENT_CHARS:
        raise ActionCallDecodeError(
            "/arguments",
            InvalidCallExpectation.range(
                maximum=MAX_ARGUMENT_CHARS,
                unit="encoded_chars",
            ),
            f"{encoded_chars} encoded_chars",
        )
    return dict(value)


def _action_argument_shape_error(
    value: Any,
    *,
    path: str,
    depth: int,
    active: set[int],
) -> ActionCallDecodeError | None:
    if value is None or isinstance(value, (str, bool, int)):
        return None
    if isinstance(value, float):
        if math.isfinite(value):
            return None
        return ActionCallDecodeError(
            path,
            InvalidCallExpectation.type("finite number"),
            "non-finite number",
        )
    if not isinstance(value, (dict, list)):
        return ActionCallDecodeError(
            path,
            InvalidCallExpectation.type("JSON value"),
            _json_kind(value),
        )
    if depth > MAX_ARGUMENT_DEPTH:
        return ActionCallDecodeError(
            path,
            InvalidCallExpectation.range(
                maximum=MAX_ARGUMENT_DEPTH,
                unit="nesting_depth",
            ),
            f"{depth} nesting_depth",
        )

    identity = id(value)
    if identity in active:
        return ActionCallDecodeError(
            path,
            InvalidCallExpectation.type("acyclic JSON"),
            "cycle",
        )
    active.add(identity)
    try:
        items = value.items() if isinstance(value, dict) else enumerate(value)
        for key, item in items:
            if isinstance(value, dict) and not isinstance(key, str):
                return ActionCallDecodeError(
                    path,
                    InvalidCallExpectation.type("string keys"),
                    "non-string key",
                )
            segment = _pointer_segment(str(key))
            failure = _action_argument_shape_error(
                item,
                path=f"{path}/{segment}",
                depth=depth + 1,
                active=active,
            )
            if failure is not None:
                return failure
        return None
    finally:
        active.remove(identity)


def _json_kind(value: Any) -> str:
    if value is _MISSING:
        return "missing"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def _pointer_segment(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _bounded_data(value: Any) -> dict[str, Any]:
    """Bound an action's output payload before it can reach model context.

    Keys are truncated individually, longest first, until the whole payload fits. Truncating
    the biggest value rather than dropping the last key keeps the *shape* of the output
    intact — a caller reading ``data["text"]`` still gets text, just less of it — and the
    ``_truncated`` marker tells the model it is looking at a prefix rather than the whole
    thing — say so, so the model narrows the query instead of assuming.
    """
    if not isinstance(value, dict):
        return {}
    data: dict[str, Any] = {str(k): v for k, v in list(value.items())[:MAX_RESULT_DATA_KEYS]}
    if _data_size(data) <= MAX_RESULT_DATA_CHARS:
        return data

    truncated = False
    while _data_size(data) > MAX_RESULT_DATA_CHARS:
        widest = max(data, key=lambda k: len(str(data[k])))
        text = str(data[widest])
        if len(text) <= 32:
            # Everything left is small; the payload is wide rather than deep. Drop the last
            # key instead of shaving strings into uselessness.
            data.pop(widest)
        else:
            data[widest] = text[: len(text) // 2]
        truncated = True
    if truncated:
        data["_truncated"] = True
    return data


def _data_size(data: dict[str, Any]) -> int:
    return sum(len(str(k)) + len(str(v)) for k, v in data.items())
