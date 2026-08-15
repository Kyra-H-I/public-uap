"""The shared core conformance suite (the protocol's first gate).

One suite, run unchanged against every provider — the reference web and mobile
clients, and later any adapter or native desktop endpoint. That "unchanged" is the
whole point: *semantic parity, not capability parity*. A phone exposes a
calendar and a web portal exposes a notebook cursor, and neither fact may change how
discovery, references, results, or errors behave.

These vectors are deliberately **safe to run against a live provider**: they read,
and they probe the paths that must *refuse*. Nothing here writes to a user's
document, sends anything, or touches device state. Mutation behaviour (undo tokens
actually undoing, revisions actually advancing) is exercised by each client's own
test suite, where a fixture can be thrown away afterwards.

What the suite is really hunting for is a provider that is *plausible but not
trustworthy*: one that returns success for an action it does not have, hands back
references it cannot invalidate, claims an undo it cannot perform, or quietly
retargets a stale reference to whatever is in front of it now. Every one of those
reads as working software right up until it edits the wrong document.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import uuid4

from uap_core.cancel import CancelState
from uap_core.effects import EffectKind, Reversibility
from uap_core.manifest import (
    MAX_ACTIONS_PER_CAPABILITY,
    MAX_CAPABILITIES,
    UAP_VERSION,
    ActionDescriptor,
    ProviderManifest,
)
from uap_core.model import (
    MAX_OBSERVED_OBJECTS,
    ActionCall,
    ActionStatus,
    Observation,
    ObservationQuery,
    ObservationScope,
)
from uap_core.provider import ProviderUnreachable, UapProvider
from uap_core.references import EpochSet, Reference, ReferenceLifetime, check_reference

#: A namespaced action no provider may implement. Used to prove that an unknown
#: action is REFUSED rather than silently absorbed — an adapter that returns
#: "completed" for everything passes a naive smoke test and nothing else.
PROBE_ACTION = "uap.conformance_probe"

#: Major.minor of the core model this suite tests. A provider on a different major
#: is not "slightly wrong", it is speaking a different protocol.
_VERSION_RE = re.compile(r"^1\.")

#: Vectors whose skip is an honest absence rather than missing evidence.
#:
#: Each one probes an OPTIONAL declared feature: a provider that does not implement preview or
#: cancellation, or that claims no undo, has nothing for these to grade, and demanding them would
#: put the top assurance level out of reach of a perfectly good provider.
#:
#: The set is deliberately the exception list rather than the inclusion list, so a vector added
#: later is treated as core until someone argues otherwise — the permissive default is how a
#: nothing-addressable provider came to be graded level A (verified semantic control) in the first place.
CONDITIONAL_VECTORS: frozenset[str] = frozenset(
    {
        "action.preview",
        "action.undo_claim",
        "cancel.honest",
        "invoke.dry_run",
    }
)


@dataclass(frozen=True, slots=True)
class VectorResult:
    """The outcome of one vector: it graded and passed, it graded and failed, or it graded nothing.

    Below the class, :data:`CONDITIONAL_VECTORS` decides which skips are acceptable at the top
    assurance level.

    ``skipped`` does not fail a run — a provider is not required to offer an action a vector needs
    — but it is emphatically **not a pass**, and the two must never read alike. See
    :attr:`ConformanceReport.earns_control_ready`.
    """

    id: str
    passed: bool
    detail: str = ""
    skipped: bool = False

    @property
    def outcome(self) -> str:
        """``passed`` / ``failed`` / ``skipped``, for a reader who sees only the report.

        The serialised shape used to be ``passed: true, skipped: true`` for a vector that graded
        nothing, which every human and every downstream consumer reads as a pass. A skip is an
        absence of evidence, and it now says so in one field rather than requiring two to be
        cross-referenced correctly.
        """
        if self.skipped:
            return "skipped"
        return "passed" if self.passed else "failed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "passed": self.passed,
            "skipped": self.skipped,
            "outcome": self.outcome,
            "detail": self.detail,
        }


@dataclass
class ConformanceReport:
    """A machine-readable pass/fail with the exact gaps, per spec §Conformance and assurance."""

    provider: str
    results: list[VectorResult] = field(default_factory=list)

    @property
    def failures(self) -> tuple[VectorResult, ...]:
        return tuple(r for r in self.results if not r.passed and not r.skipped)

    @property
    def skipped(self) -> tuple[VectorResult, ...]:
        return tuple(r for r in self.results if r.skipped)

    @property
    def passed(self) -> bool:
        """A run passes when nothing failed.

        Deliberately NOT the input to assurance A on its own — see
        :attr:`earns_control_ready`. Kept because "did anything fail" is a real and separate
        question: a provider with a legitimate gap is not broken.
        """
        return not self.failures

    @property
    def complete(self) -> bool:
        """Whether every vector actually graded something."""
        return not self.skipped

    @property
    def unproven(self) -> tuple[VectorResult, ...]:
        """Skipped vectors that examine core semantics rather than an optional feature.

        The distinction is the whole point. A provider that does not implement preview SHOULD
        skip the preview vectors — that is an honest absence, and requiring them would make the
        top level unreachable for a perfectly good provider. A provider that skips the
        stale-reference check has not demonstrated the property the level is *about*.
        """
        return tuple(r for r in self.skipped if r.id not in CONDITIONAL_VECTORS)

    @property
    def earns_control_ready(self) -> bool:
        """The input to assurance level A: nothing failed **and** nothing core went ungraded.

        `passed` alone was the input, and `passed` counts only failures — so a provider that
        declares no capability, exposes no addressable object, and can therefore be probed by
        nothing at all collected a full set of `skipped` results and was graded
        A_CONTROL_READY, the highest level the host awards. Among the vectors that silently skip
        in that state is the stale-reference check, which this module's own comments call the
        most important one in the suite.

        Evidence is what earns A (spec §Conformance and assurance). An absence of evidence is
        not a weaker form of evidence.
        """
        return self.passed and not self.unproven

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "passed": self.passed,
            "complete": self.complete,
            "earns_control_ready": self.earns_control_ready,
            "results": [r.to_dict() for r in self.results],
        }


@dataclass(frozen=True, slots=True)
class _Ctx:
    """What every vector gets: the provider plus the state already fetched from it."""

    provider: UapProvider
    manifest: ProviderManifest
    observation: Observation
    descriptors: dict[str, ActionDescriptor]
    #: Actions that arrived from a DEFERRED capability — one that declared its size
    #: rather than listing itself — keyed by capability id. They are legitimately absent
    #: from the manifest's action names, so the "skipped discovery" check has to know
    #: about them or the grouped discovery mode fails conformance for doing its job.
    #: Keyed rather than flattened because the declared-size check is per capability:
    #: a flat set would let two groups cover for each other's miscounts.
    deferred_actions: dict[str, frozenset[str]] = field(default_factory=dict)


async def run_core_conformance(provider: UapProvider) -> ConformanceReport:
    """Run every core vector against ``provider``. Safe: reads and refusals only."""
    manifest = await provider.describe()
    report = ConformanceReport(provider=manifest.provider)

    # Fetching descriptors is itself a vector's subject, so failures here are
    # reported rather than raised — a provider that cannot describe its own
    # capabilities must produce a report, not an exception.
    descriptors: dict[str, ActionDescriptor] = {}
    deferred: dict[str, frozenset[str]] = {}
    describe_error = ""
    for capability in manifest.capabilities:
        try:
            resolved: set[str] = set()
            for descriptor in await provider.describe_capability(capability.id):
                descriptors[descriptor.name] = descriptor
                resolved.add(descriptor.name)
            if capability.deferred:
                deferred[capability.id] = frozenset(resolved)
        except Exception as exc:  # noqa: BLE001 — a broken provider is a finding, not a crash
            describe_error = f"{capability.id}: {type(exc).__name__}"
            break

    unreachable = ""
    observation = Observation(provider=manifest.provider, epochs=EpochSet())
    try:
        observation = await provider.observe(
            ObservationQuery(
                scopes=(
                    ObservationScope.VIEW,
                    ObservationScope.FOCUS,
                    ObservationScope.DOCUMENT,
                    ObservationScope.OBJECTS,
                ),
                limit=MAX_OBSERVED_OBJECTS,
            )
        )
    except ProviderUnreachable as exc:
        # A provider the suite cannot reach is a *finding*, not a crash: the grader's job is to
        # report, and an exception escaping here took the whole run with it — including the
        # verdict a caller was going to act on. Every vector that needs state then grades against
        # an empty observation and skips, and because those skips are core the run cannot earn
        # level A, which is the honest outcome for "we could not look".
        unreachable = f"{type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001 — same reasoning, for a provider that breaks instead
        unreachable = f"{type(exc).__name__}: {exc}"
    ctx = _Ctx(
        provider=provider,
        manifest=manifest,
        observation=observation,
        descriptors=descriptors,
        deferred_actions=deferred,
    )

    if unreachable:
        # Recorded as its own result so a reader is not left inferring it from a wall of skips.
        report.results.append(
            VectorResult("observe.reachable", False, f"observe raised {unreachable}")
        )

    if describe_error:
        report.results.append(
            VectorResult(
                "capability.describes", False, f"describe_capability raised {describe_error}"
            )
        )
    else:
        report.results.append(_vector_capability_describes(ctx))

    for check in _SYNC_VECTORS:
        report.results.append(check(ctx))
    for acheck in _ASYNC_VECTORS:
        report.results.append(await acheck(ctx))
    return report


# -- discovery -------------------------------------------------------------


def _vector_manifest_wellformed(ctx: _Ctx) -> VectorResult:
    """Identity and version must be present and on this protocol major."""
    m = ctx.manifest
    if not _VERSION_RE.match(m.uap):
        return VectorResult(
            "manifest.version", False, f"declares {m.uap!r}, host implements {UAP_VERSION}"
        )
    if not m.provider or not m.application:
        return VectorResult("manifest.version", False, "provider/application id missing")
    if len(m.capabilities) > MAX_CAPABILITIES:
        return VectorResult("manifest.version", False, "too many capabilities")
    return VectorResult("manifest.version", True)


def _vector_capability_describes(ctx: _Ctx) -> VectorResult:
    """Every advertised action must have a descriptor, and vice versa.

    Both directions matter. An advertised action with no descriptor is one the
    host cannot classify — it would have to guess the risk. A descriptor for an
    unadvertised action is a capability that skipped discovery, which is how a
    provider grows a surface the user never consented to.
    """
    advertised = ctx.manifest.action_names
    described = frozenset(ctx.descriptors)
    if missing := sorted(advertised - described):
        return VectorResult("capability.describes", False, f"undescribed: {', '.join(missing[:5])}")
    # A deferred capability advertises its SIZE, not its members, so its actions reach the
    # host through the capability rather than the manifest. Discovery still happened — at
    # group level — so they are not "undiscoverable". Without this the grouped mode fails
    # the very vector that is supposed to permit it.
    grouped = (
        frozenset().union(*ctx.deferred_actions.values()) if ctx.deferred_actions else frozenset()
    )
    if extra := sorted(described - advertised - grouped):
        return VectorResult(
            "capability.describes", False, f"undiscoverable: {', '.join(extra[:5])}"
        )
    # ...but a declared size is a claim, and a claim gets checked. A capability that says
    # 400 and hands back 3 has told the host something false about how much it can do.
    for cap in ctx.manifest.capabilities:
        if not cap.deferred:
            continue
        count = len(ctx.deferred_actions.get(cap.id, ()))
        if count and count != cap.action_count:
            return VectorResult(
                "capability.describes",
                False,
                f"{cap.id} declares {cap.action_count} actions but describes {count}",
            )
    for cap in ctx.manifest.capabilities:
        if len(cap.actions) > MAX_ACTIONS_PER_CAPABILITY:
            return VectorResult("capability.describes", False, f"{cap.id} exceeds action cap")
    return VectorResult("capability.describes", True)


def _vector_effects_declared(ctx: _Ctx) -> VectorResult:
    """No action may be silent about what it does.

    An empty effect list classifies as read-only, so "declare nothing" would be a
    free pass out of the approval path. This vector closes that: silence is a
    conformance failure, not a permission.
    """
    silent = [name for name, d in ctx.descriptors.items() if not d.effects]
    if silent:
        return VectorResult(
            "action.effects", False, f"no declared effects: {', '.join(sorted(silent)[:5])}"
        )
    return VectorResult("action.effects", True)


def _vector_undo_claims_backed(ctx: _Ctx) -> VectorResult:
    """An operation-scoped undo claim requires a way to verify it.

    See the specification's transactions/preview/undo section.

    Providers must not claim reversibility because the app has an Edit▸Undo menu.
    A claim without a stated verification method cannot be checked by anyone, so
    it is treated as unfounded here rather than believed.
    """
    # CHECKPOINT counts too, and it was the gap. `Effect.consequential` gives a checkpoint claim
    # the same confirmation relief as an operation-bound undo, so a durable write declaring
    # `checkpoint` with an empty verification string was relieved of the handshake while carrying no
    # obligation the suite ever looked at — and the protocol has no call that redeems a checkpoint
    # at all, so nothing downstream could have caught it either.
    claims_a_way_back = (Reversibility.OPERATION_UNDO, Reversibility.CHECKPOINT)
    unfounded = [
        name
        for name, d in ctx.descriptors.items()
        if any(e.reversibility in claims_a_way_back for e in d.effects)
        and not d.verification.strip()
    ]
    if unfounded:
        return VectorResult(
            "action.undo_claim",
            False,
            f"undo claimed without verification: {', '.join(sorted(unfounded)[:5])}",
        )
    return VectorResult("action.undo_claim", True)


def _vector_preview_declared(ctx: _Ctx) -> VectorResult:
    """A declared feature must be backed by an implementation (checked live below).

    This is the *static* half: `dry_run` is only meaningful if the provider says it can
    preview. The dangerous half — a provider that ignores `dry_run` and executes anyway — is
    :func:`_vector_dry_run_never_executes`.
    """
    if ctx.manifest.features.preview:
        return VectorResult("action.preview", True)
    return VectorResult("action.preview", True, "preview not offered", skipped=True)


# -- observation -----------------------------------------------------------


def _vector_observation_bounded(ctx: _Ctx) -> VectorResult:
    """A snapshot is a bounded query result, never a dump (spec §Observation)."""
    obs = ctx.observation
    if len(obs.objects) > MAX_OBSERVED_OBJECTS:
        return VectorResult("observe.bounded", False, f"{len(obs.objects)} objects over cap")
    if obs.omitted < 0:
        return VectorResult("observe.bounded", False, "negative omitted count")
    return VectorResult("observe.bounded", True)


def _vector_observation_references_valid(ctx: _Ctx) -> VectorResult:
    """Every reference in a snapshot must validate against that snapshot's own epochs.

    A provider that hands out references its own published epochs reject is not
    merely inconsistent — it is guaranteeing that every action built on that
    snapshot fails closed, which the user experiences as the agent being broken.
    """
    epochs = ctx.observation.epochs
    for obj in ctx.observation.objects:
        if (err := check_reference(obj.ref, epochs)) is not None:
            return VectorResult(
                "observe.references", False, f"{obj.ref.kind}/{obj.ref.id}: {err.code.value}"
            )
    return VectorResult("observe.references", True)


def _vector_addressable_state(ctx: _Ctx) -> VectorResult:
    """A provider with targeted actions must be able to publish a target.

    Without this, the stale-reference vector below can be dodged by simply never
    exposing a reference — and a provider whose actions all need a target it never
    publishes is unusable anyway.
    """
    needs_target = [d for d in ctx.descriptors.values() if d.target is not None]
    if not needs_target:
        return VectorResult("observe.addressable", True, "no targeted actions", skipped=True)
    if not ctx.observation.objects:
        return VectorResult(
            "observe.addressable", True, "nothing addressable in the current view", skipped=True
        )

    # Per TARGET CLASS, not merely "something was addressable". The weaker reading is how an
    # editor shipped two actions that could never run: they declared `target: focus` while the
    # provider published only `document` and `session` references, so the host refused every
    # call — `precondition_failed` with no reference, `invalid_argument` with the wrong one — and
    # this vector passed the whole time because *some* object existed.
    #
    # Reported as a skip rather than a failure, because the suite sees one moment: "nothing is
    # focused right now" is a legitimate state, and the resolved design has a provider declare a
    # capability that is stable for the binding even when its target is momentarily absent. But
    # the skip is CORE (see CONDITIONAL_VECTORS), so it withholds level A and names exactly
    # which target class went unproven — which is the honest answer to "we could not check".
    reachable = {obj.ref.lifetime for obj in ctx.observation.objects}
    reachable |= {
        lifetime
        for lifetime in {d.target for d in needs_target if d.target is not None}
        if ctx.observation.epochs.current(lifetime) is not None
    }
    unreachable = sorted(
        {d.target.value for d in needs_target if d.target is not None and d.target not in reachable}
    )
    if unreachable:
        return VectorResult(
            "observe.addressable",
            True,
            f"declares actions targeting {', '.join(unreachable)} but published no reference or "
            "basis of that lifetime, so the host can never address them",
            skipped=True,
        )
    return VectorResult("observe.addressable", True)


# -- refusal paths ---------------------------------------------------------


async def _vector_unknown_action_refused(ctx: _Ctx) -> VectorResult:
    """An action the provider does not have must be REFUSED, never absorbed."""
    result = await ctx.provider.invoke(ActionCall(action=PROBE_ACTION, command_id=uuid4().hex))
    if result.status is not ActionStatus.REJECTED:
        return VectorResult(
            "invoke.unknown", False, f"returned {result.status.value}, not rejected"
        )
    if result.error is None:
        return VectorResult("invoke.unknown", False, "rejected with no error code")
    return VectorResult("invoke.unknown", True)


async def _vector_command_id_echoed(ctx: _Ctx) -> VectorResult:
    """Results must echo the command id — it is the idempotency and audit key.

    Probed on the refusal path so the vector stays side-effect free.
    """
    command_id = uuid4().hex
    result = await ctx.provider.invoke(ActionCall(action=PROBE_ACTION, command_id=command_id))
    if result.command_id != command_id:
        return VectorResult("invoke.command_id", False, f"echoed {result.command_id!r}")
    return VectorResult("invoke.command_id", True)


async def _vector_dry_run_never_executes(ctx: _Ctx) -> VectorResult:
    """A `dry_run` must never come back ``COMPLETED``. Either preview it, or refuse it.

    This is the dangerous direction of the preview feature. A provider that quietly ignores
    the flag and executes turns "show me what this would do" into "do it" — and the host
    asked for a preview precisely *because* it had not decided yet. Probed with a read-only
    action, so the vector cannot itself cause the damage it is looking for.
    """
    action = _read_only_action_for(ctx, tuple(ctx.descriptors))
    if action is None:
        if ctx.manifest.features.preview:
            # A provider that CLAIMS preview has to make the claim checkable. Skipping here let a
            # provider which silently executes every `dry_run` collect a conditional skip — and
            # conditional skips do not withhold level A — so the most dangerous direction of
            # the feature was graded by nothing at all. Declaring a safety feature nothing can
            # verify is itself the finding.
            return VectorResult(
                "invoke.dry_run",
                False,
                "preview is declared, but no side-effect-free action exists to prove a dry run "
                "never executes",
            )
        return VectorResult(
            "invoke.dry_run", True, "no side-effect-free action to probe with", skipped=True
        )
    ref = _first_scoped_ref(ctx)
    result = await ctx.provider.invoke(
        ActionCall(action=action, command_id=uuid4().hex, ref=ref, dry_run=True)
    )
    if result.status is ActionStatus.COMPLETED:
        return VectorResult("invoke.dry_run", False, "a dry run reported COMPLETED")
    if ctx.manifest.features.preview and result.status is not ActionStatus.PREVIEWED:
        return VectorResult(
            "invoke.dry_run",
            False,
            f"preview declared but a dry run returned {result.status.value}",
        )
    return VectorResult("invoke.dry_run", True)


async def _vector_replaying_a_command_id_is_not_a_second_execution(ctx: _Ctx) -> VectorResult:
    """The same `command_id` twice must return the same answer, not a fresh attempt.

    `command_id` is the idempotency key, so a host that retries after an ambiguous timeout
    must not cause a second execution. Probed on the refusal path — which is safe, and still
    catches the common bug, because a provider with no replay table re-derives the answer and
    a provider with one returns the stored result. Both look identical here *unless* the
    provider is non-deterministic, which is itself worth failing.
    """
    command_id = uuid4().hex
    first = await ctx.provider.invoke(ActionCall(action=PROBE_ACTION, command_id=command_id))
    second = await ctx.provider.invoke(ActionCall(action=PROBE_ACTION, command_id=command_id))
    if first.status is not second.status or first.command_id != second.command_id:
        return VectorResult(
            "invoke.replay",
            False,
            f"same command_id gave {first.status.value} then {second.status.value}",
        )
    return VectorResult("invoke.replay", True)


def _first_scoped_ref(ctx: _Ctx) -> Reference | None:
    for obj in ctx.observation.objects:
        if obj.ref.lifetime is not ReferenceLifetime.PERSISTENT and obj.ref.basis:
            return obj.ref
    return None


async def _vector_cancel_is_answered_honestly(ctx: _Ctx) -> VectorResult:
    """A provider must answer a cancel, and must not over-claim what it achieved.

    Probed with a command id that was never invoked. A provider declaring `cancellation` has
    to be able to prevent that one — it never started — so `stopped` is the honest answer and
    anything else means the declaration is decorative. A provider NOT declaring it must say
    `unsupported` plainly, because the alternative is silence, and a user who said "stop"
    reads silence as success.
    """
    outcome = await ctx.provider.cancel(f"never-invoked-{uuid4().hex}")
    if ctx.manifest.features.cancellation:
        if outcome.state is not CancelState.STOPPED:
            return VectorResult(
                "cancel.honest",
                False,
                f"declares cancellation but returned {outcome.state.value} for unstarted work",
            )
    elif outcome.state is not CancelState.UNSUPPORTED:
        return VectorResult(
            "cancel.honest",
            False,
            f"does not declare cancellation but answered {outcome.state.value}",
        )
    return VectorResult("cancel.honest", True)


async def _vector_stale_reference_fails_closed(ctx: _Ctx) -> VectorResult:
    """The one that matters: a stale reference must NEVER be retargeted (spec §References).

    Takes a real reference from the live snapshot, corrupts only its basis, and
    invokes a read-only action against it. Anything other than a refusal means the
    provider resolved "this object" to whatever is current — the failure mode that
    edits the wrong note.
    """
    scoped = [
        obj
        for obj in ctx.observation.objects
        if obj.ref.lifetime is not ReferenceLifetime.PERSISTENT and obj.ref.basis
    ]
    if not scoped:
        return VectorResult("invoke.stale_reference", True, "no scoped references", skipped=True)

    target = scoped[0]
    action, dry_run = _probe_action_for(ctx, target.actions)
    if action is None:
        return VectorResult(
            "invoke.stale_reference",
            False,
            "no action on an addressable object could be probed safely — a provider whose "
            "staleness handling cannot be checked has not demonstrated it",
        )

    stale_ref = replace(target.ref, basis=f"{target.ref.basis}~stale")
    result = await ctx.provider.invoke(
        ActionCall(action=action, command_id=uuid4().hex, ref=stale_ref, dry_run=dry_run)
    )
    if not result.changed_nothing:
        return VectorResult(
            "invoke.stale_reference", False, f"stale reference returned {result.status.value}"
        )
    if result.error is None or not result.error.reobservable:
        code = result.error.code.value if result.error else "none"
        return VectorResult(
            "invoke.stale_reference", False, f"rejected as {code}, not stale_reference"
        )
    return VectorResult("invoke.stale_reference", True)


def _read_only_action_for(ctx: _Ctx, available: tuple[str, ...]) -> str | None:
    """Pick an action on this object that provably changes nothing, or None."""
    for name in available:
        descriptor = ctx.descriptors.get(name)
        if descriptor is None or descriptor.target is None:
            continue
        if all(e.kind is EffectKind.READ for e in descriptor.effects):
            return name
    return None


def _probe_action_for(ctx: _Ctx, available: tuple[str, ...]) -> tuple[str | None, bool]:
    """An action safe to probe staleness with. Read-only, or nothing.

    This module's opening promise — and the published bundle's, which is the one that matters,
    because a vendor runs this against their live application as a pre-flight — is that the suite
    reads and probes refusals and never writes. It fell back to a MUTATING action sent with
    ``dry_run=True``, justified by "`invoke.dry_run` separately proves a dry run never completes".
    That justification was circular: `invoke.dry_run` picks its probe with
    :func:`_read_only_action_for`, so it SKIPS for exactly the provider that triggers this
    fallback. A reviewer ran it against a provider whose only targeted action was an
    ``external`` send and watched the suite invoke ``mail.send``.

    So there is no fallback. A provider with no read-only targeted action gets a FAILED
    ``invoke.stale_reference`` (see the caller) — "we could not check this safely" is a real
    result and blocks level A, whereas sending a real email to find out is not a trade the
    suite gets to make on an adopter's behalf.

    The second return value is retained at ``False`` so the call shape stays explicit about never
    asking for a preview.
    """
    return _read_only_action_for(ctx, available), False


_SYNC_VECTORS: tuple[Callable[[_Ctx], VectorResult], ...] = (
    _vector_manifest_wellformed,
    _vector_effects_declared,
    _vector_undo_claims_backed,
    _vector_preview_declared,
    _vector_observation_bounded,
    _vector_observation_references_valid,
    _vector_addressable_state,
)

_ASYNC_VECTORS: tuple[Callable[[_Ctx], Awaitable[VectorResult]], ...] = (
    _vector_unknown_action_refused,
    _vector_command_id_echoed,
    _vector_replaying_a_command_id_is_not_a_second_execution,
    _vector_cancel_is_answered_honestly,
    _vector_dry_run_never_executes,
    _vector_stale_reference_fails_closed,
)
