"""The UAP provider contract (spec §Adapters).

One interface, two implementation routes. A native provider implements this
directly inside the application; an adapter implements it by calling the
application's own documented API. Above this line the host cannot tell which it
got, apart from :attr:`ProviderManifest.origin` — and that compatibility invariant
is what makes an adapter a migration step rather than a competing architecture.

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
    "Did that actually happen?" — separate from ``invoke`` because a provider that
    self-reports success is exactly what principle 5 refuses to trust.
``cancel``
    "Stop!" — with an honest answer about whether it actually stopped.
``events``
    An ordered stream so the host can react and invalidate without polling.
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
    """What every UAP provider exposes, native or adapter."""

    async def describe(self) -> ProviderManifest:
        """Identity, capabilities (ids only), and declared safety features.

        Must reflect what is available *right now* for this device, account, and
        permission state: an unavailable capability is absent, never present and
        failing.
        """
        ...

    async def describe_capability(self, capability_id: str) -> tuple[ActionDescriptor, ...]:
        """Full typed descriptors for one capability, fetched on demand."""
        ...

    async def observe(self, query: ObservationQuery) -> Observation:
        """A bounded, coherent snapshot with the epochs its references belong to."""
        ...

    async def invoke(self, call: ActionCall) -> ActionResult:
        """Execute one typed action, returning a structured result — never a bare bool."""
        ...

    async def verify(self, expectation: Expectation) -> VerificationResult:
        """Check the world against what the host expected after an action."""
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
        """Ordered lifecycle events. Sequence gaps are the host's cue to re-observe."""
        ...
