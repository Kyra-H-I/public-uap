---
name: uap-provider
description: Build or review a UAP provider — the contract for semantic application control across native, documented-API, browser/accessibility, or vision/input routes. Use when writing or changing a provider's actions, effects, references, observation, events, or route implementation, and when a conformance vector is failing. Teaches the declarations that drive host safety policy and the conformance run that grades the result.
---

# Writing a UAP provider

This skill teaches UAP (the Universal Application Protocol) version `1.0-draft`.
A **provider** lets a host observe and act on one application through declared
semantics rather than synthesised clicks. **One contract, many routes:** a provider
may be native or mediate a documented API, browser structure, accessibility, or
vision and synthetic input as a fallback. Every route implements the same observable
contract. `ProviderManifest.origin` keeps provenance visible; assurance is assessed
separately and earned from conformance and runtime evidence, never from the route's
label.

The core wire vocabulary — error codes, statuses, effect kinds, lifetimes,
request/result types, envelope keys, identifier grammars, payload bounds — is
machine-readable in `schema/uap-vocabulary.json`. The adopted query, structured
repair, and plan shapes are in `schema/uap-workflow.schema.json`. Both are generated
and parity-gated. **Read values there, never from memory and never from a prose copy,
including this one.** The workflow schema freezes interchange but does not mean a
host implements query evaluation, automatic repair, or plan execution; those remain
execution-gated in this draft. Your manifest declares the protocol version you
implement; a protocol-major mismatch fails the `manifest.version` vector.

`provider` is the stable application-integration identity, shared across machines,
windows, and sessions. A **binding** is one live attachment; references name targets
inside it. Dispatch, cancellation, events, and non-persistent references are
binding-scoped, while durable grants attach to the provider only within the host's
authority context. The binding discriminator remains pending transport work (F-004),
so do not invent wire fields for it. `ActionCall.provider` disambiguates rival
providers at equal assurance, not sibling bindings of one provider.


## Start by declaring, not implementing

Write the `ActionDescriptor` set before any handler. Each action declares its name,
summary, effects, target reference class, arguments, preconditions, verification
method, idempotency, and whether it is the undo of another action.

If you cannot state an action's effects and how to verify it, you do not yet
understand the operation well enough to expose it. That is a signal to go read the
application's API documentation, not to write a handler and fill the descriptor in
afterwards. Write each one as a claim rather than an explanation — rule 17.

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

**3. Absent only for binding-stable, target-independent reasons.** A capability the
binding cannot attempt because the build omits it, the account lacks it, or a required
platform permission was not granted is *missing from the manifest*. Transient state
and target-specific permission are typed invocation failures, not manifest churn.

**4. Reversibility means operation-bound.** A generic Edit→Undo menu is not a
transaction protocol. Unless you can hand back a token that undoes **this command**,
the honest answer is `NONE`, whatever the application's UI offers.

**5. An undo token is single-use.** Redeeming it twice reverts a *later* operation —
exactly the damage undo exists to prevent.

**6. Validate every reference before work; never silently retarget.** Every reference
declares its `kind`, `id`, `lifetime` and the `basis` (epoch) it was minted against.
Check ownership and basis before any action effect. If it was never issued, refuse
with `unknown_reference`; if its basis moved, refuse with `stale_reference`. Both are
no-effect `REJECTED` results. Acting first or substituting "the current one instead"
is the failure mode this vocabulary exists to make impossible.

**7. Two staleness mechanisms, never merged.** `stale_reference` means *re-resolve
what "this" meant*. `conflict` means *right target, someone else got there first*.
They have different recoveries, and collapsing them makes the host retry the wrong
thing. If you are arriving from HTTP, read the codes twice: this taxonomy follows
gRPC's status codes, so `conflict` is the failed revision check (gRPC `ABORTED`) and
`precondition_failed` is gRPC's `FAILED_PRECONDITION`, the state guard — *not* HTTP's
412, which is the `If-Match` answer (RFC 9110 §15.5.13). The names collide; the
meanings do not. `conflict` is also deliberately excluded from automatic retry, because
in an interactive application the other writer is usually a person and winning the race
is the wrong outcome.

**8. Do not claim a feature you do not back.** `ProviderFeatures.preview` and
`cancellation` are promises the suite checks live; `transactions` and
`capability_query` are declarations no vector grades yet, so they are checked by
review and you should not declare them speculatively. Declaring
`preview: false` means a `dry_run` call must be **rejected**, never silently
executed — "show me what this would do" turning into "do it" is the exact bug
`invoke.dry_run` exists to catch.

**9. Answer every cancel, honestly.** Providers that cannot cancel answer
`UNSUPPORTED`. Say `stopped` only when you can *prove* the work never began;
otherwise `too_late`. A user who said "stop" reads silence as success. If the
command is over *and* you can prove it left nothing behind, `nothing_changed`
says so without the offer to undo that `too_late` carries.

**10. Echo `command_id`, and replay it.** It is the idempotency and audit key. The
same id twice must return the same answer, not a second execution.

**11. `verify` must actually check.** It exists precisely because a provider
self-reporting success proves nothing. An expectation you cannot evaluate is
`verified: false` — "I could not check" and "it is fine" are different answers and
only one is safe to say out loud. Every action that claims a state transition must
satisfy its verification contract, including view transitions such as navigate,
focus, select, and activate. Only an action whose complete successful result is its
returned data and which claims no state transition needs no additional round trip.
On this draft's wire, `ref` or `revision_after` is the only structured evidence basis
a host can dispatch to `verify`. (The spec's evidence model is broader, but a typed
verification-method declaration does not exist yet; see Known Gaps #5. Build state
transitions to ref/revision evidence today.) A host that cannot verify a completion
must not announce success.

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
router answers ambiguity with `ambiguous`, and `ActionCall.provider` chooses only
among rival providers at equal assurance — never among sibling bindings of one
provider. Do not invent a unique per-application prefix to dodge the collision.

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

**16. An input the application would collect via a modal is an argument.** A
provider that opens an interactive dialog to collect a value has mis-declared the
action: take the value as a declared — usually required — argument and call the API
path that accepts it. The dialog is the application's *rendering* of a missing
parameter, not a protocol primitive; the host's conversation is the input dialog,
and the model fills the value from context or asks before invoking. Choice dialogs
become a read action returning the bounded option list, plus an argument taking the
chosen id. Consent dialogs are never modeled as input at all (rule 2) — host policy
derives confirmation from your declared effects. Secrets never transit the channel:
refuse `permission_denied` and let the user finish in the application. A missing
required argument is a structured refusal naming `/arguments/<name>` — never an
opened dialog, never a guessed default.

Declare requirements in `required_arguments`, a subset of your `arguments` keys.
Emit it only when non-empty; a name in it that you never declared in `arguments` is
a malformed descriptor, because it tells the host two different things about your own
call shape.

**17. Write the descriptor as a test, not a manual.** A capability `title` is a
`describe(...)`; an action `summary` is an `it(...)`. Make both **falsifiable claims
from the caller's point of view** — present tense, one sentence, no mechanism. The name
*is* the assertion, which is what lets a reader check it instead of believing it, and a
claim is shorter than an explanation, so this costs nothing (rule 12's economics apply
to descriptors: every byte is read by a model on the turn it chooses).

The rest of the descriptor is already Given / When / Then — behaviour-driven
development's scenario grammar (Dan North, 2006), which every reader and every model
has seen: `preconditions` is the Given, the action name plus `arguments` is the When,
`verification` is the Then. Two differences from a test matter, and both are why
authors get it wrong:

- **Your Given is a guard, not a fixture.** Nobody arranges it for you; you check it
  and refuse with `precondition_failed`.
- **The Then is split in two.** What *changed* goes in `effects` (rule 1, read by the
  host's policy engine); how you would *know* goes in `verification` (rule 11, read by
  the checker). Neither belongs in the summary as an aside.

```text
✗ summary: "Uses the workspace edit API to apply a text insertion at the position
            of the primary cursor, if a document is currently open."
✓ summary: "Types text at the cursor and hands back a way to take it back."
  preconditions: ("a document is open", "the editor has focus")
  verification:  "re-read the document; its revision is greater than the one passed in"
```

```text
✗ summary: "Confirms an order. May fail if the order is not a draft, and depending
            on configuration this can also email the customer."
✓ summary: "Confirms a draft order and reserves its stock."
  preconditions: ("the order is in draft",)
  effects:       persist(order), external(customer email)   ← the "can also email"
  verification:  "re-read the order; its state is confirmed"
```

Everything the bad summary hedges is a declaration that belongs somewhere the host can
act on it: the state guard is a precondition you enforce, and the email is an effect
that decides whether the user is asked first. Left in prose, it is decoration.

```text
✗ verification: "the call returns success"
✓ verification: "re-read the note; its revision is greater than the one passed in"
```

A provider self-reporting success proves nothing (rule 11), and a Then that restates
the When is not an assertion.

This is a **convention, not a schema**. No field is added and nothing parses it; it is
checked by review and reported beside first-call correctness. Its payoff is that a
claim plus a stated verification is enough to *draft* a conformance vector from your
declaration — which is also the fastest way to find out that a summary you wrote is not
actually checkable.

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
- **Green is not done.** Rules 2, 5, 11, 13 and 17 have no core vector — nothing
  mechanical fails when you break them. They are checked by review.

Details of all fifteen vectors: `references/conformance.md`.

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
