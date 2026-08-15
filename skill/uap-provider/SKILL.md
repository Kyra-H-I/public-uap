---
name: uap-provider
description: Build or review a UAP provider or adapter — the interface that lets a voice agent observe and control an application semantically instead of clicking through its UI. Use when writing a native provider inside an application, an adapter over an application's existing API, or a browser/accessibility bridge; when adding or changing actions, effects, references, observation, or events on an existing provider; and when a conformance vector is failing. Teaches the contract, the declarations that drive the host's safety policy, and the conformance run that grades the result.
---

# Writing a UAP provider

This skill teaches UAP (the Universal Application Protocol) version `1.0-draft`.
A **provider** lets a host observe and act on one application through declared
semantics rather than synthesised clicks. Two routes, one interface: a **native
provider** implements it inside the application; an **adapter** implements it by
calling the application's own documented API. Above the interface the host cannot
tell which it got — that invariant is what makes an adapter a migration step rather
than a competing architecture.

The core wire vocabulary — error codes, statuses, effect kinds, lifetimes,
request/result types, envelope keys, identifier grammars, payload bounds — is
machine-readable in `schema/uap-vocabulary.json`. The adopted query, structured
repair, and plan shapes are in `schema/uap-workflow.schema.json`. Both are generated
and parity-gated. **Read values there, never from memory and never from a prose copy,
including this one.** The workflow schema freezes interchange but does not mean a
host implements query evaluation, automatic repair, or plan execution; those remain
execution-gated in this draft. Your manifest declares the protocol version you
implement; a protocol-major mismatch fails the `manifest.version` vector.


## Start by declaring, not implementing

Write the `ActionDescriptor` set before any handler. Each action declares its name,
summary, effects, target reference class, arguments, preconditions, verification
method, idempotency, and whether it is the undo of another action.

If you cannot state an action's effects and how to verify it, you do not yet
understand the operation well enough to expose it. That is a signal to go read the
application's API documentation, not to write a handler and fill the descriptor in
afterwards.

## The rules

**1. Declare every effect.** An `Effect` is `(kind, scope, reversibility)`.
Unrecognised values fail *closed* — an unknown kind parses as `EXTERNAL`, an unknown
reversibility as `NONE` — so a garbled declaration earns the strictest treatment,
never the most permissive. Silence about effects fails `action.effects`.

**2. You never choose your own confirmation class.** You declare what an action
does; the host's policy engine derives whether it runs quietly, notifies, or
requires the user's agreement. Do not add a `confirm` argument, do not prompt the
user yourself, do not reason about consequence in the handler. A provider that
could mark "email the customer" as a quiet local edit would be the whole safety
model's single point of failure.

**3. Absent, never no-op.** A capability unavailable for this device, account, or
permission state is *missing from the manifest*, not present and failing. An action
that is always there and always fails teaches the model to ignore discovery.

**4. Reversibility means operation-bound.** A generic Edit→Undo menu is not a
transaction protocol. Unless you can hand back a token that undoes **this command**,
the honest answer is `NONE`, whatever the application's UI offers.

**5. An undo token is single-use.** Redeeming it twice reverts a *later* operation —
exactly the damage undo exists to prevent.

**6. Never silently retarget a stale reference.** Every reference declares its
`kind`, `id`, `lifetime` and the `basis` (epoch) it was minted against. If the basis
has moved, refuse with `stale_reference`. Acting on "the current one instead" is the
failure mode this vocabulary exists to make impossible.

**7. Two staleness mechanisms, never merged.** `stale_reference` means *re-resolve
what "this" meant*. `conflict` means *right target, someone else got there first*.
They have different recoveries, and collapsing them makes the host retry the wrong
thing.

**8. Do not claim a feature you do not back.** `ProviderFeatures.preview` and
`cancellation` are promises the suite checks live; `transactions` and
`capability_query` are declarations no vector grades yet, so they are checked by
review and you should not declare them speculatively. Declaring
`preview: false` means a `dry_run` call must be **rejected**, never silently
executed — "show me what this would do" turning into "do it" is the exact bug
`invoke.dry_run` exists to catch.

**9. Answer every cancel, honestly.** Providers that cannot cancel answer
`UNSUPPORTED`. Say `stopped` only when you can *prove* the work never began;
otherwise `too_late`. A user who said "stop" reads silence as success.

**10. Echo `command_id`, and replay it.** It is the idempotency and audit key. The
same id twice must return the same answer, not a second execution.

**11. `verify` must actually check.** It exists precisely because a provider
self-reporting success proves nothing. An expectation you cannot evaluate is
`verified: false` — "I could not check" and "it is fine" are different answers and
only one is safe to say out loud. On this draft's wire, a completed mutation must
return a post-action `ref` or `revision_after` — the only evidence shape the current
vocabulary lets a host check. (The spec's evidence model is broader — a readback or a
Sent-folder entry are valid in principle — but a typed verification-method declaration
does not exist yet; see the spec's Known Gaps #5. Build to ref/revision today.) A host
that cannot verify a completion must not announce success.

**12. Observation is a bounded query, not a dump.** Rank *before* you cap, so that
when the limit bites it drops the least urgent object rather than an arbitrary slice.
Every result token is billed; return what the decision needs and report what you
omitted.

**13. `ACCEPTED` is not `COMPLETED`.** It is nonterminal. The current draft event
envelope carries state invalidations but has no `command_id`/terminal-result linkage.
Read/view work may return honest acceptance, but neither provider nor host may call it
success. For a durable-audit-required mutation, the host records acceptance and then
returns a terminal ambiguous `FAILED`/`timeout` with no automatic retry. A durable
command-correlated receiver must land before later asynchronous completion can be
reported and verified.

**14. Name actions `<noun>.<verb>`.** Names collide across providers by design; the
router answers ambiguity with `ambiguous` and the caller disambiguates by provider id.
Do not invent a unique per-application prefix to dodge the collision.

**15. Reject the whole malformed call; never trim actionable input.** `arguments`
is a required finite-JSON object with string keys, at most 20 top-level keys,
8,000 Unicode scalar values in compact JSON, and maximum container depth 16. A wire/decode
mismatch returns structured `invalid_call` (`field_path`, typed `expected`, bounded
`got`, optional deterministic `suggestion`) and may be repaired once by a host.
`invalid_argument` is different: the call was well formed but failed your domain
validation. Never drop extra recipients, ranges, or options and execute the subset.
Apply the same exactness to control fields: required non-empty bounded `action`
and `command_id`; bounded string `provider` / `expect_revision` when present;
boolean `dry_run` when present (false only when absent); and a closed, fully valid
`ref` when present. Never coerce a scalar or discard a malformed reference.

## Then run the suite

Non-negotiable final step. It is safe — reads and refusals only:

```python
from uap_core.conformance import run_core_conformance
report = await run_core_conformance(provider)
assert report.passed, [r.to_dict() for r in report.failures]
```


The report is machine-readable and names the exact gap per vector. A failing vector
is a defect in the provider, not a test to work around; a `skipped` vector is a
capability you did not offer, which is fine and is reported as such.

Three qualifications, each load-bearing:

- **A provider in another language is graded across the wire.** The suite calls a
  provider object; if yours lives in TypeScript, Dart, or anything else, drive the
  *real* implementation with *real* host envelopes under its own test runner and
  assert the semantics survive the boundary — fixtures matching fixtures prove
  nothing (see `references/traps.md`). The protocol tooling ships `uap-conform`,
  a wire-level runner that grades any provider over stdio or a unix socket
  through a ~20-line harness (`references/conformance.md`).
- **Green is pre-flight, not the grade.** A host runs its own suite against your
  provider and assigns the assurance level from that report plus runtime evidence.
  A level is never self-awarded.
- **Green is not done.** Rules 2, 5, 11 and 13 have no core vector — nothing
  mechanical fails when you break them. They are checked by review.

Details of all fourteen vectors: `references/conformance.md`.

## Worked example

The smallest honest provider ships with the protocol bundle under
`examples/minimal/`, and the reference implementation's CI keeps it passing
conformance — an example that cannot rot. Read it before writing your first
descriptor.

## References

- `references/contract.md` — the seven methods, envelope by envelope.
- `references/conformance.md` — every vector, what failing it means, how to run it.
- `references/traps.md` — failures that actually happened, with their symptoms.
  Read this before writing an adapter; several are invisible to unit tests.
