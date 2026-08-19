"""UAP discovery: manifests, capabilities, and action descriptors.

Specification: the manifest/capability-discovery and typed-action sections.

Discovery is split in two on purpose, and the split is a cost decision as much as
a design one.

A **manifest** is discovery metadata: the stable provider integration, its
provenance, which capability *ids* exist, and what safety features it supports. It
is small, cacheable by digest, and cheap enough to fetch on every session bind. The
live binding is retained separately by the host and transport.

An **action descriptor** is the expensive part — typed arguments, preconditions,
declared effects, usage guidance — and it is fetched **per capability, on demand**.
The economics are the host's schema-cost rule: a schema advertised to the model
is billed on every turn for the life of the session, so a provider with forty
actions must not put forty schemas in front of a user who asked to open a note.

The other rule discovery enforces: **a capability is absent only for a
binding-stable, target-independent reason** (spec §Manifest and capability
discovery). A build that omits a feature, an account without the entitlement, or an
ungranted platform permission shapes the bound manifest. Transient state and
target-specific permission are typed invocation results instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from uap_core.effects import ActionTerminality, Effect
from uap_core.references import ReferenceLifetime

#: The semantic model version this host implements. Bumped when the *core*
#: envelopes change shape; domain capabilities version independently.
UAP_VERSION = "1.0-draft"


def protocol_major(version: str) -> str:
    """The major of a declared core version, or ``""`` when there is nothing to read."""
    return version.split(".", 1)[0].strip()


def protocol_compatible(declared: str) -> bool:
    """Whether a client's declared core version may be bound at all.

    The draft's stated compatibility backstop (spec: "hosts fail closed on a major
    mismatch"), and the reason a breaking draft change is considered survivable at all: a
    client on another major is not slightly wrong, it is speaking a different protocol, and
    interpreting its envelopes with these semantics is exactly the silent misreading the
    version field exists to prevent.

    An **absent** version is incompatible too. It used to read as "the host's own version",
    which made the one field the backstop rests on fail open — the vocabulary lists ``uap``
    as always present, so silence is a malformed manifest, not consent to be assumed current.
    """
    return bool(declared) and protocol_major(declared) == protocol_major(UAP_VERSION)


_ACTION_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}(\.[a-z][a-z0-9_]{0,31}){1,3}$")
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}(\.[a-z][a-z0-9_]{0,31}){0,3}$")
#: One argument name — deliberately a single ``_ACTION_RE`` segment.
#:
#: Constrained rather than merely bounded, because an argument name is emitted into a
#: refusal's ``field_path`` as a JSON Pointer (``/arguments/<name>``), and a pointer is
#: something the repairing host *walks*. RFC 6901 gives ``/`` and ``~`` meaning inside a
#: token, so an argument named ``a/b`` would silently address a nested member that does not
#: exist and a repair would land in the wrong place. Escaping at emission time was the other
#: option; forbidding the characters is better, because a name needing an escape is a name no
#: provider should be declaring, and the constraint holds at the one place descriptors are
#: built instead of at every place a path is written.
_ARGUMENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
#: Reverse-DNS provider id (``org.example.editor``). Bounded because it is logged on
#: every routed action and shown in permission prompts.
_PROVIDER_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}(\.[a-z][a-z0-9_]{0,31}){1,5}$")


def is_valid_provider_id(value: str) -> bool:
    """Whether a string may be used as a provider id.

    This validates syntax only: the semantic id is stable across machines, windows,
    and sessions. Live-instance qualification belongs to binding context, not this
    id; its transport representation remains pending (F-004).
    """
    return bool(_PROVIDER_RE.match(value))


#: Discovery bounds. A manifest is fetched on every bind and its capability list
#: can reach model context, so it is capped rather than trusted to be sensible.
MAX_CAPABILITIES = 64
MAX_ACTIONS_PER_CAPABILITY = 32
#: The application label is rendered verbatim into every ``look_at_app`` result, so it is
#: bounded like every other provider-authored string here (``platform`` 32, ``title`` 80).
#: Uncapped it was ~128k tokens of attacker-chosen prose per look, billed to the user.
MAX_APPLICATION_CHARS = 120
#: Per-descriptor collection bounds. A descriptor is provider-authored input that lands in
#: model context whole, so "bounded, always" has to hold per COUNT as well as per value —
#: 5 000 one-line arguments render to ~99k characters without breaking any single cap.
MAX_ACTION_ARGUMENTS = 32
MAX_PRECONDITIONS = 16
MAX_EFFECTS = 16
#: Upper bound on a *declared* (not listed) action count. Deliberately far above
#: MAX_ACTIONS_PER_CAPABILITY — that cap bounds what a manifest may inline, and
#: declaring a large group is the sanctioned way past it. This bound only rejects
#: values that cannot describe a real application.
MAX_DECLARED_ACTIONS = 10_000


class ProviderOrigin(StrEnum):
    """How the UAP contract is implemented — provenance, NOT an assurance level.

    Kept separate from :class:`AssuranceLevel` because origin alone earns nothing
    (spec §Conformance and assurance): a native implementation that fails
    conformance is worse than an adapter that passes it.
    """

    NATIVE = "native"
    """The application implements UAP directly."""

    ADAPTER = "adapter"
    """Typed code maps the application's own documented API into UAP."""

    ACCESSIBILITY = "accessibility"
    """Normalised OS/browser accessibility semantics."""

    VISION_HID = "vision_hid"
    """Screenshots plus synthetic pointer/keyboard input. Inferred, never verified."""


class AssuranceLevel(StrEnum):
    """How much the host may trust this provider's semantics (spec §Conformance and assurance).

    Earned by conformance evidence, never self-declared: :func:`ProviderManifest.
    from_dict` deliberately does not read a level off the wire.
    """

    A_CONTROL_READY = "A"
    B_API_CONNECTED = "B"
    C_ACCESSIBLE = "C"
    D_VISUAL_LEGACY = "D"


class ManifestScope(StrEnum):
    """Whether a manifest describes one session or the whole deployment.

    Specification: the manifest and capability-discovery section.

    The same schema serves both, on purpose — a separately specified public format would
    drift against the bound one inside two releases, and this repository already runs
    cross-language parity gates because copies drift.
    """

    SESSION = "session"
    """What this binding can attempt from binding-stable, target-independent facts."""

    PUBLIC = "public"
    """The deployment's curated pre-binding projection, served pre-auth.

    Deliberately allowed to advertise *less* than a binding offers (publication is
    opt-in per capability), so no containment holds in either direction: a bound
    capability may be unadvertised, an advertised one absent at bind. The bound
    manifest is authoritative; this can never be read as a grant of anything.
    (The former ``bound ⊆ public`` invariant is withdrawn — spec F-013.)
    """


#: Routing preference. The router picks the highest-assurance provider that can
#: actually serve the requested action, per action — not per application.
_ASSURANCE_RANK: dict[AssuranceLevel, int] = {
    AssuranceLevel.A_CONTROL_READY: 0,
    AssuranceLevel.B_API_CONNECTED: 1,
    AssuranceLevel.C_ACCESSIBLE: 2,
    AssuranceLevel.D_VISUAL_LEGACY: 3,
}


def assurance_rank(level: AssuranceLevel) -> int:
    """Sort key for routing: lower is better."""
    return _ASSURANCE_RANK[level]


@dataclass(frozen=True, slots=True)
class ProviderFeatures:
    """Safety machinery this provider actually implements.

    Every field defaults to *absent*. A provider gets no credit for a feature it
    forgot to declare, which is the right direction to fail: the host then asks
    for confirmation it might not have needed, rather than skipping one it did.
    """

    events: bool = False
    """Emits ordered state invalidations per binding, so the host need not poll."""

    preview: bool = False
    """Can render or compute a dry-run before committing."""

    transactions: bool = False
    """Can commit a batch atomically."""

    cancellation: bool = False
    """Can stop an in-flight action at a safe boundary."""

    capability_query: bool = False
    """Its own registry can be asked whether an action exists, so nothing need be listed.

    The escape hatch for applications too large to enumerate (spec §Large surfaces).
    An IDE or ERP has more actions than any manifest may carry — and the cap is a
    context budget, not an opinion about how capable an application may be — so the
    manifest declares that the question can be *asked* instead of answered up front.

    Declared but not yet executed by the host: Phase 0 implements enumerated discovery
    only. The field is frozen here so independent implementations cannot fork the
    grammar while the execution semantics are still being settled — the same reason the
    query algebra shipped as schema ahead of its runtime.
    """

    def to_dict(self) -> dict[str, Any]:
        return {
            "events": self.events,
            "preview": self.preview,
            "transactions": self.transactions,
            "cancellation": self.cancellation,
            "capability_query": self.capability_query,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ProviderFeatures:
        return cls(
            events=_flag(d.get("events")),
            preview=_flag(d.get("preview")),
            transactions=_flag(d.get("transactions")),
            cancellation=_flag(d.get("cancellation")),
            capability_query=_flag(d.get("capability_query")),
        )


@dataclass(frozen=True, slots=True)
class ActionDescriptor:
    """The full description of one typed action. Fetched on demand, per capability."""

    name: str
    """Namespaced action name, e.g. ``portal.navigate``, ``note.insert_at_cursor``."""

    summary: str
    """One line the model reads while choosing. This IS the routing signal."""

    effects: tuple[Effect, ...] = ()
    """Everything this action does. Empty is undeclared reach, not an implicit read."""

    target: ReferenceLifetime | None = None
    """The reference class this action must be given, or None if it takes no target."""

    arguments: dict[str, str] = field(default_factory=dict)
    """Argument name → short type/units description. Kept prose-light on purpose."""

    required_arguments: tuple[str, ...] = ()
    """Which of :attr:`arguments` the action cannot run without.

    This is where a modal dialog goes. An application collects a mid-action value — a
    filename, a rename target — by popping a box, but a popup is that application's
    *rendering* of a missing parameter, not a protocol primitive: the host's conversation
    is the input dialog, and the model fills the value from context or asks at plan time.
    A provider that opens a dialog to collect a value has mis-declared the action.

    Declaring it is what lets the host ask BEFORE invoking rather than discovering the gap
    from a refusal. A call that omits one is refused ``invalid_call`` naming
    ``/arguments/<name>`` — repairable, because the host can supply what it forgot, unlike
    the terminal ``invalid_argument`` a domain-validation failure earns.

    Every name must also appear in :attr:`arguments`; a descriptor that requires something
    it never described tells the host two different stories about its own call shape, the
    same way a capability whose ``action_count`` disagrees with its list does."""

    preconditions: tuple[str, ...] = ()
    """What must hold before this can run ("a note is open", "a field is focused")."""

    verification: str = ""
    """How the host can confirm it worked ("re-read the note revision")."""

    idempotent: bool = False
    """Safe to re-issue with the same command id after an ambiguous timeout."""

    terminality: ActionTerminality = ActionTerminality.OBSERVABLE
    """Whether this action's final outcome is observable at all — see the enum.

    Only ``handoff`` lets an ACCEPTED result stand as terminal for a consequential
    action; every observable action must still resolve to a verified COMPLETED or an
    honest failure. The conservative default means a provider gets the relief only by
    declaring it."""

    undo_of: str | None = None
    """Names the action this one REVERSES, if it is a reversal.

    Undoing is the user correcting a mistake, and a correction must never cost more agreement
    than the mistake did — being made to re-confirm "no, take that back" is how a user learns
    that undo is not worth reaching for, which is exactly backwards when reversibility is the
    safety mechanism.

    Not self-certifying: the host's policy engine only grants the relief when the
    host can see the named action, that action declares an operation-bound undo, and it was not
    outward-facing. Otherwise any provider could dodge confirmation by claiming everything
    undoes something."""

    def __post_init__(self) -> None:
        if not _ACTION_RE.match(self.name):
            raise ValueError(f"invalid action name: {self.name!r}")
        # Bounded by COUNT as well as by value. Every string in a descriptor is already capped,
        # but a descriptor lands in model context whole, and 5 000 individually-legal one-line
        # arguments render to ~99k characters without breaking a single per-value cap.
        if len(self.arguments) > MAX_ACTION_ARGUMENTS:
            raise ValueError(f"action {self.name} declares too many arguments")
        for argument in self.arguments:
            if not _ARGUMENT_RE.match(argument):
                # Truncated in the message for the same reason the name is bounded at all:
                # this string came from a provider and ends up in a log line.
                raise ValueError(f"action {self.name} has invalid argument {argument[:32]!r}")
        if len(self.preconditions) > MAX_PRECONDITIONS:
            raise ValueError(f"action {self.name} declares too many preconditions")
        if len(self.effects) > MAX_EFFECTS:
            raise ValueError(f"action {self.name} declares too many effects")
        # Not trimmed to the cap the way `arguments` is, for the reason `effects` is not
        # trimmed either: dropping a required name makes the action read as less demanding
        # than it is, so the host sends a call the provider must refuse. Over the cap is a
        # malformed descriptor, and rejecting it is the fail-closed direction.
        if len(self.required_arguments) > MAX_ACTION_ARGUMENTS:
            raise ValueError(f"action {self.name} requires too many arguments")
        if len(set(self.required_arguments)) != len(self.required_arguments):
            raise ValueError(f"action {self.name} names a required argument twice")
        # Runs after `from_dict` has already trimmed `arguments`, which is the point: a
        # required name that fell off the end of that trim fails loudly here rather than
        # surviving as a requirement for an argument the descriptor no longer describes.
        undeclared = [name for name in self.required_arguments if name not in self.arguments]
        if undeclared:
            raise ValueError(
                f"action {self.name} requires undeclared arguments: {', '.join(undeclared)}"
            )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "summary": self.summary,
            "effects": [e.to_dict() for e in self.effects],
            "arguments": dict(self.arguments),
            "preconditions": list(self.preconditions),
            "verification": self.verification,
            "idempotent": self.idempotent,
        }
        # Emitted only when it says something, like `action_count` below and for the same
        # reason: a descriptor rides in the cached prompt prefix on every turn, so an empty
        # list per action is the waste the caps exist to prevent, multiplied by the surface.
        if self.required_arguments:
            d["required_arguments"] = list(self.required_arguments)
        if self.undo_of is not None:
            d["undo_of"] = self.undo_of
        if self.target is not None:
            d["target"] = self.target.value
        if self.terminality is not ActionTerminality.OBSERVABLE:
            d["terminality"] = self.terminality.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ActionDescriptor:
        raw_target = d.get("target")
        target: ReferenceLifetime | None = None
        if raw_target is not None:
            try:
                target = ReferenceLifetime(str(raw_target))
            except ValueError as exc:
                raise ValueError(f"invalid action target: {raw_target!r}") from exc
        raw_terminality = d.get("terminality")
        terminality = ActionTerminality.OBSERVABLE
        if raw_terminality is not None:
            try:
                terminality = ActionTerminality(str(raw_terminality))
            except ValueError as exc:
                # Fail-closed parse: a typo must not silently grant the observable default's
                # OPPOSITE either way — an unknown value is a malformed descriptor, full stop.
                raise ValueError(f"invalid action terminality: {raw_terminality!r}") from exc
        return cls(
            name=str(d.get("name", "")),
            summary=str(d.get("summary", ""))[:200],
            effects=tuple(Effect.from_dict(e) for e in _as_list(d.get("effects"))),
            target=target,
            # Descriptive prose, so an over-long list is trimmed the way every over-long string
            # here is. `effects` above is deliberately NOT trimmed: dropping one would make the
            # action read as less reaching than it is, and the confirmation class is derived from
            # exactly that list — a silent trim there buys a lower policy class. Over-declaring
            # effects is a caller's own problem; under-declaring is the user's.
            # Values are trimmed; NAMES are not, because `_ARGUMENT_RE` rejects them in
            # `__post_init__` instead. That closes the gap where a name was the one string in
            # a descriptor with no bound at all — the count cap does not help, since 32 legal
            # arguments named a megabyte each is still a megabyte of prompt prefix. Trimming
            # would have been the wrong fix anyway: a silently shortened name no longer
            # matches the key the caller sends, so the argument becomes unaddressable rather
            # than merely ugly.
            arguments=dict(
                list(
                    {
                        str(k): str(v)[:80] for k, v in _as_mapping(d.get("arguments")).items()
                    }.items()
                )[:MAX_ACTION_ARGUMENTS]
            ),
            required_arguments=tuple(str(name) for name in _as_list(d.get("required_arguments"))),
            preconditions=tuple(str(p)[:120] for p in _as_list(d.get("preconditions")))[
                :MAX_PRECONDITIONS
            ],
            verification=str(d.get("verification", ""))[:200],
            idempotent=bool(d.get("idempotent", False)),
            undo_of=_opt_action(d.get("undo_of")),
            terminality=terminality,
        )


@dataclass(frozen=True, slots=True)
class CapabilitySummary:
    """One capability as it appears in a manifest: ids only, no schemas."""

    id: str
    """Capability id, e.g. ``portal.navigation``, ``device.calendar``."""

    title: str
    """Short human label, spoken or shown in a permission prompt."""

    actions: tuple[str, ...] = ()
    """Action names in this capability. Descriptors are fetched separately."""

    action_count: int | None = None
    """How many actions this capability holds, when they are not listed here.

    The grouped discovery mode (spec §Large surfaces): a capability that would blow
    :data:`MAX_ACTIONS_PER_CAPABILITY` declares its size and resolves the list on demand,
    pushing the existing "fetched on demand" boundary up one level — from action
    descriptor to action *list*. A five-thousand-command editor becomes twenty group
    lines instead of an unaffordable manifest.

    ``None`` means the list here is complete, which keeps every existing manifest valid.
    When actions *are* inlined the count must agree with them, so the two can never tell
    the host different stories.

    Declared but not yet resolved by the host: Phase 0 implements enumerated discovery
    only. Frozen now for the same reason as :attr:`ProviderFeatures.capability_query`.
    """

    def __post_init__(self) -> None:
        if not _ID_RE.match(self.id):
            raise ValueError(f"invalid capability id: {self.id!r}")
        if len(self.actions) > MAX_ACTIONS_PER_CAPABILITY:
            raise ValueError(f"capability {self.id} declares too many actions")
        for name in self.actions:
            if not _ACTION_RE.match(name):
                raise ValueError(f"invalid action name: {name!r}")
        if self.action_count is not None:
            if not 0 <= self.action_count <= MAX_DECLARED_ACTIONS:
                raise ValueError(f"capability {self.id} declares implausible action_count")
            if self.actions and self.action_count != len(self.actions):
                raise ValueError(
                    f"capability {self.id} lists {len(self.actions)} actions "
                    f"but declares {self.action_count}"
                )

    @property
    def deferred(self) -> bool:
        """True when this capability names its size but not its actions."""
        return not self.actions and bool(self.action_count)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"id": self.id, "title": self.title, "actions": list(self.actions)}
        # Emitted only when it says something the action list does not. This key rides in
        # the cached prompt prefix on every turn of every session, so a null here is not
        # free — it is the same waste the caps exist to prevent, multiplied by 64.
        if self.action_count is not None:
            d["action_count"] = self.action_count
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CapabilitySummary:
        return cls(
            id=str(d.get("id", "")),
            title=str(d.get("title", ""))[:80],
            actions=tuple(str(a) for a in _as_list(d.get("actions"))),
            action_count=_opt_count(d.get("action_count")),
        )


@dataclass(frozen=True, slots=True)
class ProviderManifest:
    """Stable provider discovery for one binding or a public deployment catalog.

    The manifest does not identify the live binding; that discriminator belongs to
    the host/transport boundary and is pending wire work (F-004).
    """

    provider: str
    """Stable provider id, e.g. ``org.example.editor``, ``com.vendor.app``."""

    origin: ProviderOrigin
    application: str
    """The application being controlled, e.g. ``example.editor``, ``vendor.mobile``."""

    uap: str = UAP_VERSION
    capabilities: tuple[CapabilitySummary, ...] = ()
    features: ProviderFeatures = field(default_factory=ProviderFeatures)
    platform: str = ""
    """Free-form platform tag (``web``, ``android``, ``ios``) for diagnostics only."""

    scope: ManifestScope = ManifestScope.SESSION
    """Whether this is one binding's capabilities or a curated public projection.

    Defaults to ``SESSION`` when absent, which is the safe direction: an unmarked
    document does not get to claim it is public discovery.
    """

    def __post_init__(self) -> None:
        if not is_valid_provider_id(self.provider):
            raise ValueError(f"invalid provider id: {self.provider!r}")
        if len(self.capabilities) > MAX_CAPABILITIES:
            raise ValueError(f"provider {self.provider} declares too many capabilities")
        # The application label is provider-authored prose that reaches model context verbatim in
        # every `look_at_app` result, and it was the one string here with no cap at all: 200k
        # characters of attacker-chosen text were accepted and billed to the user, per look.
        if len(self.application) > MAX_APPLICATION_CHARS:
            raise ValueError(f"provider {self.provider} declares an over-long application")

    @property
    def action_names(self) -> frozenset[str]:
        """Every action advertised by this manifest."""
        return frozenset(a for cap in self.capabilities for a in cap.actions)

    def capability_for(self, action: str) -> CapabilitySummary | None:
        """Which capability owns ``action``, or None when it is not offered."""
        for cap in self.capabilities:
            if action in cap.actions:
                return cap
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "uap": self.uap,
            "provider": self.provider,
            "origin": self.origin.value,
            "application": self.application,
            "platform": self.platform,
            "scope": self.scope.value,
            "capabilities": [c.to_dict() for c in self.capabilities],
            "features": self.features.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ProviderManifest:
        """Parse a client-supplied manifest.

        Note what is *not* read here: an assurance level. A provider cannot
        self-award trust — the host assigns assurance from conformance and runtime
        evidence. Origin remains visible provenance and can limit what evidence
        establishes, but never awards a level by itself.
        """
        try:
            origin = ProviderOrigin(str(d.get("origin", "")))
        except ValueError as exc:
            raise ValueError(f"invalid provider origin: {d.get('origin')!r}") from exc
        try:
            # Absent is legal and means SESSION — every manifest written before public
            # catalogs existed is still valid. A *malformed* scope is not: a document that
            # cannot say which of the two it is has to be rejected loudly, not guessed at.
            scope = ManifestScope(str(d.get("scope", ManifestScope.SESSION.value)))
        except ValueError as exc:
            raise ValueError(f"invalid manifest scope: {d.get('scope')!r}") from exc
        caps = tuple(CapabilitySummary.from_dict(c) for c in _as_list(d.get("capabilities")))
        return cls(
            provider=str(d.get("provider", "")),
            origin=origin,
            application=str(d.get("application", ""))[:MAX_APPLICATION_CHARS],
            uap=str(d.get("uap", UAP_VERSION)),
            capabilities=caps,
            features=ProviderFeatures.from_dict(_as_mapping(d.get("features"))),
            platform=str(d.get("platform", ""))[:32],
            scope=scope,
        )


def _flag(value: Any) -> bool:
    """Read a declared feature flag: only a real ``true`` declares anything.

    ``bool()`` was the trap. ``bool("false")`` is ``True``, so ``"preview": "false"`` — one
    plausible client typo, or one deliberate line in a hostile manifest — DECLARED preview,
    and a declared preview is what lets a model-set ``dry_run`` lower an action's confirmation
    class. Everything that is not the boolean ``true`` reads as absent, which is the direction
    the spec mandates: the cost of getting this wrong must be a needless confirmation.
    """
    return value is True


def _opt_count(value: Any) -> int | None:
    """Parse a declared action count, dropping anything that is not a plain integer.

    ``bool`` is excluded explicitly because it *is* an ``int`` in Python, and
    ``action_count: true`` should not silently become a capability of size one.
    Anything unparseable degrades to ``None`` — "the list here is complete" — which
    makes a malformed count show up as an empty capability rather than a phantom one.
    """
    if value is None or isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _opt_action(value: Any) -> str | None:
    """Parse an `undo_of` claim, dropping anything that is not a well-formed action name."""
    if value is None:
        return None
    name = str(value)
    return name if _ACTION_RE.match(name) else None


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
