# Exported from the reference implementation's test suite.
# The reference copy is the editable one; its conformance run in CI keeps it honest.
"""A scriptable in-memory UAP provider for the UAP conformance tests.

Deliberately faithful rather than convenient: it enforces its own reference basis, refuses
unknown actions, and echoes command ids — so it passes the core conformance suite honestly,
and each test that wants a *misbehaving* provider builds one by overriding a single hook.
That way "the suite catches X" is demonstrated against a provider that is otherwise correct,
which is the realistic case.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from uap_core.cancel import CancelOutcome, CancelState
from uap_core.effects import ActionTerminality, Effect, EffectKind, Reversibility
from uap_core.errors import InvalidCallExpectation, UapError, UapErrorCode
from uap_core.manifest import (
    ActionDescriptor,
    CapabilitySummary,
    ProviderFeatures,
    ProviderManifest,
    ProviderOrigin,
)
from uap_core.model import (
    ActionCall,
    ActionResult,
    ActionStatus,
    Expectation,
    Observation,
    ObservationQuery,
    ObservedObject,
    ProviderEvent,
    VerificationResult,
)
from uap_core.provider import ProviderUnreachable
from uap_core.references import EpochSet, Reference, ReferenceLifetime, check_reference

READ_ACTION = "fake.read"
WRITE_ACTION = "fake.save"
SEND_ACTION = "fake.send"
#: Addressed entirely by ARGUMENT, with no reference — the shape of `phone.call`.
DIAL_ACTION = "fake.dial"
#: Declares a REQUIRED argument, and is read-only so omitting it can be probed safely.
#: `fake.dial` would have been the tempting place to put the requirement — it already takes
#: an argument and no reference — but its effect is `external`, and the conformance suite may
#: not invoke an action that could reach outside to find out whether it refuses.
FIND_ACTION = "fake.find"
CAPABILITY = "fake.documents"

DESCRIPTORS: dict[str, ActionDescriptor] = {
    READ_ACTION: ActionDescriptor(
        name=READ_ACTION,
        summary="Read one document.",
        effects=(Effect(EffectKind.READ, "one document"),),
        target=ReferenceLifetime.DOCUMENT,
        verification="the document is returned",
        idempotent=True,
    ),
    WRITE_ACTION: ActionDescriptor(
        name=WRITE_ACTION,
        summary="Save the open document.",
        effects=(Effect(EffectKind.PERSIST, "the open document", Reversibility.OPERATION_UNDO),),
        target=ReferenceLifetime.DOCUMENT,
        verification="re-read the revision",
    ),
    DIAL_ACTION: ActionDescriptor(
        name=DIAL_ACTION,
        summary="Call a number.",
        effects=(Effect(EffectKind.EXTERNAL, "an outbound call"),),
        arguments={"number": "the number to dial"},
        verification="the dialler reports it",
        # Mirrors the real `phone.call`: the intent verifiably leaves the provider and
        # nothing on this transport can ever observe the call connect, so ACCEPTED is
        # this action's terminal truth rather than a state awaiting an outcome.
        terminality=ActionTerminality.HANDOFF,
    ),
    FIND_ACTION: ActionDescriptor(
        name=FIND_ACTION,
        summary="Find documents matching a query.",
        effects=(Effect(EffectKind.READ, "the document index"),),
        arguments={"query": "what to look for"},
        required_arguments=("query",),
        verification="the matches are returned",
        idempotent=True,
    ),
    SEND_ACTION: ActionDescriptor(
        name=SEND_ACTION,
        summary="Send the document to someone.",
        effects=(Effect(EffectKind.EXTERNAL, "an outbound email"),),
        target=ReferenceLifetime.DOCUMENT,
        verification="the send receipt",
    ),
}


@dataclass
class FakeProvider:
    """An honest provider. Tests break exactly one property at a time by subclassing."""

    provider_id: str = "com.example.fake"
    #: When true, `observe` raises the way a provider whose far end has gone does.
    unreachable: bool = False
    origin: ProviderOrigin = ProviderOrigin.NATIVE
    document_basis: str = "rev-1"
    operation_revision: str = ""
    actions: tuple[str, ...] = (READ_ACTION, WRITE_ACTION, SEND_ACTION, DIAL_ACTION, FIND_ACTION)
    #: Per-instance, so a test can add an action without mutating the module-level dict and
    #: leaking it into every test that runs after it. `describe_capability` and `invoke` both
    #: read this, which is what stops a subclass's extra action from being described and then
    #: refused as `unsupported` by an invoke that consulted a different map.
    descriptors: dict[str, ActionDescriptor] = field(default_factory=lambda: dict(DESCRIPTORS))
    invoked: list[ActionCall] = field(default_factory=list)

    # -- discovery ---------------------------------------------------------
    async def describe(self) -> ProviderManifest:
        return ProviderManifest(
            provider=self.provider_id,
            origin=self.origin,
            application="example.app",
            capabilities=(
                CapabilitySummary(id=CAPABILITY, title="Documents", actions=self.actions),
            ),
            # Declares what it can actually do: it prevents work it never saw, and reports
            # anything already invoked as too late.
            features=ProviderFeatures(events=True, cancellation=True),
        )

    async def describe_capability(self, capability_id: str) -> tuple[ActionDescriptor, ...]:
        if capability_id != CAPABILITY:
            return ()
        return tuple(self.descriptors[name] for name in self.actions)

    # -- state -------------------------------------------------------------
    def epochs(self) -> EpochSet:
        return EpochSet(document=self.document_basis)

    def document_ref(self, doc_id: str = "doc-1") -> Reference:
        return Reference(
            kind="fake.document",
            id=doc_id,
            lifetime=ReferenceLifetime.DOCUMENT,
            basis=self.document_basis,
        )

    async def observe(self, query: ObservationQuery) -> Observation:
        if self.unreachable:
            raise ProviderUnreachable(f"{self.provider_id} is gone")
        # Two documents, so a test can prove an approval bound to one cannot fire on the other.
        return Observation(
            provider=self.provider_id,
            epochs=self.epochs(),
            view_key="documents",
            view_title="Documents",
            objects=tuple(
                ObservedObject(
                    ref=self.document_ref(doc_id),
                    type="fake.document",
                    title=doc_id,
                    actions=self.actions,
                )
                for doc_id in ("doc-1", "doc-2")
            ),
        )

    # -- invocation --------------------------------------------------------
    async def invoke(self, call: ActionCall) -> ActionResult:
        self.invoked.append(call)
        # Declares `preview: false`, so a dry run must be REFUSED rather than executed.
        # Silently ignoring the flag turns "show me what this would do" into "do it", which is
        # what `invoke.dry_run` exists to catch — and it caught this fake first.
        if call.dry_run:
            return ActionResult(
                command_id=call.command_id,
                status=ActionStatus.REJECTED,
                error=UapError(UapErrorCode.UNSUPPORTED, "no preview"),
            )
        descriptor = self.descriptors.get(call.action)
        if descriptor is None or call.action not in self.actions:
            return ActionResult(
                command_id=call.command_id,
                status=ActionStatus.REJECTED,
                error=UapError(UapErrorCode.UNSUPPORTED, "no such action"),
            )
        # Before the target check, because a malformed call is answered before a precondition:
        # the host can repair the first from the structured fields and can only re-observe for
        # the second, so answering them in the wrong order sends it down the wrong path.
        missing = [name for name in descriptor.required_arguments if name not in call.arguments]
        if missing:
            return ActionResult(
                command_id=call.command_id,
                status=ActionStatus.REJECTED,
                error=UapError(
                    UapErrorCode.INVALID_CALL,
                    f"{missing[0]} is required",
                    field_path=f"/arguments/{missing[0]}",
                    expected=InvalidCallExpectation.type("string"),
                    got="absent",
                ),
            )
        if descriptor.target is not None:
            if call.ref is None:
                return ActionResult(
                    command_id=call.command_id,
                    status=ActionStatus.REJECTED,
                    error=UapError(UapErrorCode.PRECONDITION_FAILED, "no target"),
                )
            stale = check_reference(call.ref, self.epochs())
            if stale is not None:
                return ActionResult(
                    command_id=call.command_id, status=ActionStatus.REJECTED, error=stale
                )
        revision_after = None
        if any(effect.kind is not EffectKind.READ for effect in descriptor.effects):
            self.operation_revision = f"operation-{len(self.invoked)}"
            revision_after = self.operation_revision
        return ActionResult(
            command_id=call.command_id,
            status=ActionStatus.COMPLETED,
            ref=call.ref,
            revision_after=revision_after,
        )

    async def cancel(self, command_id: str) -> CancelOutcome:
        # Honest: it can only prove a command never ran if it never saw it.
        if any(c.command_id == command_id for c in self.invoked):
            return CancelOutcome(command_id, CancelState.TOO_LATE, "already under way")
        return CancelOutcome(command_id, CancelState.STOPPED, "not started")

    async def verify(self, expectation: Expectation) -> VerificationResult:
        if expectation.revision is not None:
            return VerificationResult(
                verified=expectation.revision in {self.document_basis, self.operation_revision}
            )
        if expectation.ref is not None:
            return VerificationResult(
                verified=check_reference(expectation.ref, self.epochs()) is None
            )
        return VerificationResult(verified=False, detail="nothing to verify")

    async def events(self) -> AsyncIterator[ProviderEvent]:
        yield ProviderEvent(provider=self.provider_id, type="document.changed", seq=1)
