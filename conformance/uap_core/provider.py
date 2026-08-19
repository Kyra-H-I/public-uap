"""The UAP provider contract (spec §Adapters).

One observable contract, many implementation routes. A provider may be native or
mediate a documented API, browser structure, accessibility, or vision and synthetic
input as a fallback. Every route exposes this contract;
:attr:`ProviderManifest.origin` keeps provenance visible, while assurance is assessed
separately and earned from conformance and runtime evidence.

The stable provider id names the application integration, not a live window,
machine, or session. A live binding is selected separately by the host and transport;
its pending discriminator (F-004) is deliberately not invented here.

Structural typing (``Protocol``, no inheritance) matches the host's device-transport
seam: a provider that lives in
another process, another language, or a browser tab cannot inherit from a Python
base class, and requiring it to would make the contract un-implementable exactly
where it needs to be implemented.

Method-by-method, the reason each exists:

``describe``
    Cheap routing metadata, cached by the caller. Capability *ids* only.
``describe_capability``
    The expensive schemas, fetched only for a capability the host is about to use.
``observe``
    A bounded query. Never a state dump.
``invoke``
    One typed command with an idempotency key and an optional optimistic basis.
``verify``
    "Did that actually happen?" — for every claimed state transition, including a
    view transition, and separate from ``invoke`` because a provider that
    self-reports success is exactly what principle 5 refuses to trust.
``cancel``
    "Stop!" — with an honest answer about whether it actually stopped.
``events``
    An ordered state-invalidation stream per live binding, so the host can react
    without polling.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from uap_core.cancel import CancelOutcome
from uap_core.manifest import ActionDescriptor, ProviderManifest
from uap_core.model import (
    ActionCall,
    ActionResult,
    Expectation,
    Observation,
    ObservationQuery,
    ProviderEvent,
    VerificationResult,
)


@runtime_checkable
class UapProvider(Protocol):
    """What every native or mediated UAP route exposes."""

    async def describe(self) -> ProviderManifest:
        """Identity, capabilities (ids only), and declared safety features.

        Include only capabilities this binding can attempt based on binding-stable,
        target-independent facts. Transient state and target-specific permission
        are typed invocation failures, not reasons to churn the manifest.
        """
        ...

    async def describe_capability(self, capability_id: str) -> tuple[ActionDescriptor, ...]:
        """Full typed descriptors for one capability, fetched on demand."""
        ...

    async def observe(self, query: ObservationQuery) -> Observation:
        """A bounded, coherent snapshot with the epochs its references belong to."""
        ...

    async def invoke(self, call: ActionCall) -> ActionResult:
        """Execute one typed action, returning a structured result — never a bare bool.

        ``call.provider`` disambiguates rival stable provider identities only. The
        host and transport resolve the live binding outside this field.
        """
        ...

    async def verify(self, expectation: Expectation) -> VerificationResult:
        """Freshly check a claimed postcondition, including any view-state change.

        The current draft wire dispatches only reference/revision-shaped evidence;
        return ``verified=False`` for anything this binding cannot evaluate (Known
        Gaps #5).
        """
        ...

    async def cancel(self, command_id: str) -> CancelOutcome:
        """Try to stop one in-flight command, and say honestly what was achieved.

        Required of every provider, including those that cannot cancel: they answer
        ``UNSUPPORTED``. An unimplementable method is better than an optional one here,
        because the alternative is silence — and a user who said "stop" reads silence as
        success.
        """
        ...

    def events(self) -> AsyncIterator[ProviderEvent]:
        """Ordered state invalidations for this binding; gaps cue re-observation."""
        ...


class ProviderUnreachable(Exception):
    """The provider could not be reached, so the host has no view of it at all.

    Distinct from "the application is empty", and the distinction is the whole reason this
    exists. `observe` returns an `Observation`, so a transport timeout had nowhere to go but an
    empty one — after which the host said "nothing is open in VS Code on that machine" about a
    machine it had failed to contact, and cached the empty epochs, invalidating every reference
    the session already held. `invoke` on the same transport already gets this right: it reports
    a timeout as FAILED rather than REJECTED, precisely so a lost message is never spoken as
    "it didn't go through".
    """
