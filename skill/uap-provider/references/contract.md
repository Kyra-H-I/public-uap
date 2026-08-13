# The contract, method by method

A provider implements seven methods. The prose below explains what each one means
and where providers go wrong; the exact core vocabulary is machine-readable in
`schema/uap-vocabulary.json`, while the schema-only query/repair/plan shapes are in
`schema/uap-workflow.schema.json`. Both are generated under a parity gate. Where
this file restates a value list it is teaching, not defining: when in doubt, the
generated contract files win.

## `describe() -> ProviderManifest`

Cheap routing metadata, cached by the caller: identity, capability **ids only**, and
declared features. Must reflect what is available *right now* for this device,
account and permission state.

`origin` is `native | adapter | accessibility | vision_hid` — implementation
provenance, shown separately from assurance. Origin alone never earns a level:
`A_CONTROL_READY` through `D_VISUAL_LEGACY` are determined by the conformance report
and runtime evidence, never self-awarded. The manifest deliberately has no assurance
field to fill in — a host will not read one off the wire.

## `describe_capability(capability_id) -> tuple[ActionDescriptor, ...]`

The expensive schemas, fetched only for a capability the host is about to use. Split
from `describe` because argument specs are the bulky part of discovery and are needed
one capability at a time.

Every advertised action needs a descriptor and every descriptor needs to be
advertised — `capability.describes` fails on a mismatch in either direction. If you
offer a capability conditionally, filter the descriptors the same way.

An `ActionDescriptor` carries: `name`, `summary`, `effects`, `target`
(a `ReferenceLifetime` or `None` for targetless actions), `arguments`,
`preconditions`, `verification`, `idempotent`, `undo_of`, `terminality`.

`terminality` is `observable` unless declared `handoff`, and it is only emitted when
it is *not* the default. `handoff` is the sole reason a terminal `accepted` is legal —
the action hands off to something this provider cannot read back (a dialer, a print
spooler), so the honest ending is "sent it, cannot confirm" rather than an invented
success or an invented failure.

`undo_of` names the action this one reverses. It is not self-certifying: the host
grants reduced confirmation friction only when it can see the named action, that
action declares an operation-bound undo, and it was not outward-facing — otherwise
any provider could dodge confirmation by claiming everything undoes something.

## `observe(query) -> Observation`

A bounded, coherent snapshot **with the epochs its references belong to**. The query
carries `scopes` (`view | focus | selection | document | objects`), an optional `ref`
to scope to, and a `limit`. Asking for less costs less. An unknown scope is ignored,
never treated as "all".

The returned `Observation` carries `provider`, `epochs`, `view_key`, `view_title`,
`focus_kind`, `objects`, and `omitted`. Every reference inside it must validate
against that same observation's epochs — `observe.references` checks exactly this, and
a snapshot that hands out references it would itself reject is incoherent.

Set `omitted` honestly when the cap bites, so the host knows to narrow rather than
assume the list is complete.

## `invoke(call) -> ActionResult`

One typed command. The `ActionCall` carries `action`, `command_id`, optional `ref`,
`arguments`, optional `expect_revision` (optimistic concurrency), `dry_run`, and
optional `provider` (the answer to an `ambiguous` routing result).

`arguments` is a required finite-JSON object with string keys: at most 20
top-level keys, 8,000 Unicode scalar values in compact JSON, and container depth
at most 16. Missing/null/non-object, non-finite, cyclic, or otherwise non-JSON
input is rejected atomically as structured `invalid_call`, never coerced to `{}`
or truncated into a different command. The envelope can be repaired from
`field_path`, typed `expected`, bounded `got`, and optional deterministic
`suggestion`. `invalid_argument` remains the provider's answer when a well-formed
value violates domain rules. The `provider` pin is restrictive: a pinned provider
that cannot perform the action is a refusal, never permission to fall through to
another application.

The controls are exact too, not truthy/coercible: `action` (1–132 Unicode
scalars) and `command_id` (1–128) are required strings; present `provider`
(1–200) and `expect_revision` (1–128) are strings; present `dry_run` is a
boolean and defaults to false only when absent. A present `ref` is a closed
object with required valid `kind`, `id`, and `lifetime`; every non-persistent
reference has a non-empty basis (at most 128 scalars). A malformed present
reference is `invalid_call`—never dropped into an untargeted action.

The `ActionResult` carries `command_id`, `status`, `error`, `ref`, `revision_before`,
`revision_after`, `undo_token`, `detail`, `data`. Never return a bare boolean.

`ActionStatus`: `ACCEPTED` (taken, outcome unknown), `COMPLETED` (the provider
finished and observed its intended effect; the host still verifies it), `PREVIEWED`
(dry run, nothing committed), `REJECTED` (refused, nothing changed), `FAILED`
(started, did not finish — state may be partial), `CANCELLED`.
Only `REJECTED` and `PREVIEWED` guarantee nothing changed. A host parses an unknown
status as `FAILED`, never as success.

On the current draft binding, `ProviderEvent` has no `command_id` or
terminal-result link. Read/view work may return an honestly nonterminal `ACCEPTED`,
which the caller must not interpret as success. If draft/persist/device/external
work returns `ACCEPTED`, the host durably records that acceptance and then returns
a terminal ambiguous `FAILED`/`timeout` with no automatic retry. Prefer an honest
inline terminal result when possible; a durable command lifecycle receiver is
needed before later completion can be reported and verified.

Reads return their payload in `data`. A read that returns nothing is a read the host
cannot use. `data` is bounded — a host truncates an oversized payload and marks it,
so return what the decision needs, not the document.

A `ref` in the result must be re-issued at its **post-action** basis — valid in the
state the action leaves behind, not the state it started in.

## `verify(expectation) -> VerificationResult`

Separate from `invoke` because a provider that self-reports success is what the host
refuses to trust. Compare the expectation — a `revision`, a `ref`, or `properties` —
against a *fresh* observation, and return `verified: false` for anything you cannot
evaluate. A completed mutation should return a post-action `ref` or
`revision_after`; without that structured basis the host has nothing safe to verify
and must not turn provider prose into a success announcement.

## `cancel(command_id) -> CancelOutcome`

Required of every provider, including those that cannot cancel. `CancelState` is
`stopped | too_late | unsupported`. `stopped` is a claim that the work never began and
you can prove it; if you merely asked something to stop, that is `too_late`.
Cancelling is not undoing: `too_late` claims no revert.

## `events() -> AsyncIterator[ProviderEvent]`

Ordered **state-invalidation** events so the host can invalidate without polling. Each carries
`provider`, `type`, `seq`, optional `ref` and `epochs`. A gap in `seq` is the host's
cue to re-observe, so the counter must be monotonic per provider session.

The current envelope does not carry command progress or completion. Do not emit
`command.progress` / `command.completed` under this shape: without `command_id`,
bounded progress, and a terminal `ActionResult`, they cannot close an accepted
command. That lifecycle contract is explicitly unimplemented.

On the wire the *semantic* type (`view.changed`, `document.changed`, …) travels in
the `event` field; the envelope's own `type` is the transport routing label. Two
fields because one cannot be both — see the wire dialect below and the trap this
distinction comes from.

Only declare `features.events = True` if you actually emit them. Diffing state you
already re-render on beats a timer: it is both cheaper and more timely.

## References and lifetimes

`ReferenceLifetime` is `view | focus | document | session | persistent`. Everything
except `persistent` requires a `basis` — the epoch it was minted against — and the
host refuses one whose basis has moved on.

One basis per **lifetime**, not per object. A singular scope ("the open document")
fits an epoch. A *collection* uses a session-scoped reference for identity plus
`expect_revision` for per-object staleness. Conflating them produces a provider that
invalidates every row because one changed.

Where identity is genuinely positional — a DOM node, an accessibility element — say
so and accept the downgraded assurance. The protocol requires honesty about identity,
not durability.

## The wire dialect (out-of-process providers)

A provider that does not run inside the host process speaks line-delimited JSON
envelopes. A request travels as `{"type": <request type>, "id": <unique id>,
...body}` and the reply echoes the same `id`; events arrive under the event type
with the semantic kind in the `event` field. The request/result pairs, topic, and
every envelope's key set are in `schema/uap-vocabulary.json` under `message_types`
and `envelopes`. A reply type must match its request type as well as echoing `id`;
a mismatched reply is ignored.

Both directions are untrusted. A host schema-parses every reply, truncates
oversized payloads, treats silence as `timeout`, and drops unknown reply types —
build your provider expecting exactly the same of its callers.
