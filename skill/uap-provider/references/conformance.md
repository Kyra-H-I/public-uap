# The conformance suite

Fourteen core vectors, run against a live provider. The suite ships open with the
protocol bundle. It performs reads and refusals only — it never mutates, so it is safe
against a real application.

```python
from uap_core.conformance import run_core_conformance

report = await run_core_conformance(provider)
report.passed        # nothing failed
report.failures      # the exact gaps
report.skipped       # capabilities you did not offer — never a failure
report.to_dict()     # machine-readable, this is what feeds the assurance level
```

A `skipped` vector means the provider does not offer that capability, which is a
legitimate answer. A `failed` vector is a defect in the provider.

**Providers in other languages** are graded across the wire: the suite calls a
provider object, so a TypeScript or Dart implementation is exercised by driving the
real class with real host envelopes under its own test runner and asserting the
semantics survive the boundary — a stale reference stays stale, a refusal stays a
refusal, a declared feature stays backed. Hand-written fixtures on both sides prove
only that the fixtures match (see `traps.md`).

**The wire-level runner** removes the language barrier entirely. `uap-conform`
speaks the envelope dialect — line-delimited JSON — to a provider reached by
spawning a harness command (`-cmd "…"`, stdin/stdout) or dialing a unix socket
(`-socket path`), runs the same fifteen vectors, and prints the same report shape.
Exit codes: 0 passed, 1 vectors failed, 2 not gradable. A harness is ~20 lines in
any language: read one JSON object per line, dispatch on `type`, reply on stdout
echoing `id` — and log to stderr, never stdout, because stdout is the protocol. A
wire run is additionally strict about envelope validity: violations an in-process
provider cannot even express — an over-cap snapshot, a scoped reference with no
basis — fail their vector instead of being clamped away by host-side defensiveness.

**Passing locally is pre-flight, not the grade.** A host runs its own suite against
your provider and assigns the assurance level from that report plus runtime
evidence. A level is never self-awarded.

## The vectors

**`manifest.version`** — identity present, protocol major matches, capability count
within cap. Fails when `provider`/`application` is blank or the manifest is oversized.

**`capability.describes`** — every advertised action has a descriptor, every
descriptor is advertised, no capability exceeds the action cap. Fails when discovery
and description disagree, which is the usual result of offering a capability
conditionally but describing it unconditionally.

**`action.effects`** — no action is silent about what it does. Fails on any descriptor
with an empty `effects` tuple.

**`action.undo_claim`** — an `OPERATION_UNDO` claim needs a way to verify it. Fails
when a provider promises operation-bound reversal with nothing backing the promise.

**`action.preview`** — a declared `preview` feature must be implemented; skipped when
preview is not offered.

**`observe.bounded`** — the snapshot respects the cap and reports a non-negative
`omitted`. Fails on a state dump.

**`observe.references`** — every reference in a snapshot validates against that
snapshot's own epochs. Fails when a provider hands out references it would itself
reject.

**`observe.addressable`** — a provider with targeted actions can actually publish a
target; skipped when nothing is targeted. Fails when every action needs a reference
and observation never produces one, which makes the provider unusable in practice.

**`invoke.unknown`** — an action the provider does not have is `REJECTED` with an
error code, never absorbed. Fails on a silent success or a rejection with no code.

**`invoke.command_id`** — the result echoes the id it was called with.

**`invoke.replay`** — the same `command_id` twice returns the same answer rather than
executing again.

**`cancel.honest`** — a cancel is answered, and the provider does not over-claim what
it achieved.

**`invoke.dry_run`** — a dry run never comes back `COMPLETED`. Either preview it and
return `PREVIEWED`, or refuse it as `UNSUPPORTED`. This vector caught the reference
fake itself first: a provider that ignores the flag turns "show me what this would do"
into "do it".

**`invoke.stale_reference`** — the one that matters most: a reference whose basis has
moved must be refused, never retargeted at whatever is current.

Probed **once per lifetime**, not once per run. It used to probe whichever scoped object the
observation listed first and grade the whole provider on it, which meant the provider chose
which lifetime was examined — and `focus`, which goes stale the instant the caret moves, is
the one least likely to be listed first. Only lifetimes an action can actually consume are
graded: if no action declares `target: session`, a stale session reference can never be handed
to anything, and demanding a probe for it would be a bar with no safety behind it.

Consequence worth planning for: **a lifetime you publish and act on needs a read-only action
targeting it, or its staleness is unproven.** A provider whose only focus-targeted actions
write (insert at the caret, rename the symbol under it) gets a core skip naming `focus` — not
a failure, since nothing is wrong, but level A stays out of reach until a read of that
lifetime exists to probe. The probe must *target* the lifetime: aiming a document-scoped
action at a focus reference tests nothing.

The limit, stated plainly: this grades the lifetime you **publish** on the reference. A
provider that hands back the caret labelled `document` is graded as a document and passes.
Nothing outside the provider can tell that apart from a truthful document reference.

Skipped entirely when the provider has no scoped, actionable references at all.

**`invoke.required_arguments`** — an action's declared required argument, omitted,
comes back as a repairable `invalid_call` naming `/arguments/<name>` — never executed
with a guessed default, never answered with a dialog, never refused as terminal
`invalid_argument`. Probed only with a read-only action: omitting an argument looks
self-limiting, but a send missing only its required subject still has a recipient, and
a provider that ignores the gap sends real mail.

Three outcomes, deliberately distinct. Declaring no required argument anywhere
**passes vacuously** — the obligation is conditional and every descriptor was read, so
it has no instances — and the detail says so, because a pass line is not evidence the
convention works. Declaring one only on actions that change something is a **skip**:
the suite cannot omit an argument from a write to see what happens, and the provider
has done nothing wrong, so asserting a defect would be false. That skip is *core*
though — it withholds level A and names what went unproven, because "we could not
check" must never read like "checked and fine". Expose one required argument on a read
action and the vector grades properly.

## Beyond core

Core conformance is the floor, not the ceiling. The spec's protocol-strength
properties — atomicity, long-running operations, concurrency with a human working in
the same document — are separate vectors, and a provider passing core has not yet
demonstrated them. Nor does core grade every rule in `SKILL.md`: rules 2, 5, 11 and
13 have no vector and are checked by review. The publication gate does exercise a
malformed/oversized call through the stdio harness and requires structured
`invalid_call`, but the fifteen-provider-vector suite does not yet grade automatic
repair orchestration; that execution remains gated.

Passing the suite is what makes assurance level A available. It does not grant it:
level is determined by the report plus runtime evidence, and is never self-awarded.
