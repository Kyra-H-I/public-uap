# Universal Application Protocol (UAP) — Specification

**Protocol version:** `1.0-draft` · **Status: DRAFT** — this specification is
exercised against live reference providers and may change incompatibly until the
draft label is removed. `manifest.uap` fails a protocol-major mismatch, which is
the compatibility backstop while the draft moves.

This document is licensed **CC-BY-4.0** (see `../LICENSE-SPEC`). The schemas,
golden vectors, conformance suite, and authoring skill it references are licensed
**Apache-2.0** (see `../LICENSE`).

---

## Abstract

UAP is an application-facing protocol that lets a host — a voice agent, or any
conversational agent — observe and control an application through **declared
semantics** rather than synthesized input: typed actions with declared effects,
epoch-scoped references, bounded observation, honest verification and
cancellation, and operation-scoped undo. It is designed so that the *application*
states what is true and what an action does, while the *host* alone decides how
much user agreement an action needs and what the user is told.

The protocol has two implementation routes with identical observable semantics: a
**native provider** inside the application, and an **adapter** — ordinary typed
code mapping the application's existing documented API into the same contract. A
host cannot tell which it got, apart from provenance and assurance metadata. That
invariant makes the adapter a migration path rather than a competing
architecture.

## Motivation

Keyboards, pointers, and screenshots are interfaces for humans. Driving them
synthetically gives an agent breadth but not reliability: coordinates address
pixels rather than objects, screenshots cannot express hidden state or whether an
operation succeeded, and Ctrl-Z is not a transaction protocol. Above shallow
tasks, the failure mode is not "the agent cannot act" but "the agent cannot know
what its action did" — and an agent that cannot know will guess, in both
directions: announcing successes that never happened and failures the user can
watch being false.

UAP's position: the durable abstraction is the **meaning inside the
application** — the open document, the selected objects, the available
operations, the command result, the undo boundary. Pixels and synthetic input
remain the universal fallback, at an honestly disclosed lower assurance, never
the target.

## Design principles

1. **Meaning before pixels.** Prefer document/object/action semantics over
   coordinates and gestures.
2. **One contract, two routes.** Native providers and adapters obey the same
   observable semantics and the same conformance suite.
3. **Small universal core, rich domain capabilities.** The core standardizes
   discovery, identity, state, invocation, results, effects, events,
   verification, and transactions. Domain vocabulary stays namespaced and
   versions independently; the protocol does not flatten CAD, documents, and
   code into one lowest-common-denominator verb set.
4. **Observe, act, verify.** A dispatched action is not successful because input
   was sent. "Completed" requires evidence; endings that cannot be observed say
   so by declaration.
5. **Declared, never asserted.** A provider declares what an action touches and
   whether it can be taken back; it never chooses its own confirmation class,
   approves its own action, or upgrades its own result.
6. **Reversibility is a capability.** Preview, checkpoint, and undo are explicit
   declared properties bound to operations — never assumed from a menu.
7. **The user stays the primary operator.** Real user input takes precedence;
   the host does not fight the keyboard, the pointer, or assistive technology.
8. **Local by default.** Raw application state stays on the user's machine;
   only bounded, declared projections reach the model.
9. **Deterministic over generative.** Where the application can perform an
   operation exactly (a language-server rename, a formatter), the host
   orchestrates that operation; it does not have a model generate the
   equivalent. Exact, reversible, verifiable beats plausible.

## Architecture

```text
user intent
    |
    v
host: planning, policy, consent, audit, memory
    |
    v
UAP runtime: routing, staleness, effect-derived consent, verification
    |
    |-- native UAP provider          (in-application; lowest translation cost)
    |-- adapter -> documented API    (typed compatibility bridge)
    |-- browser / accessibility      (normalized generic semantics)
    `-- vision + synthetic input     (universal fallback, lowest assurance)
```

A host composes capabilities per operation rather than choosing one route per
application: a native provider may serve the document model while accessibility
serves a file dialog. The router selects the highest-assurance implementation
available for the requested operation and target.

The host side of this diagram is deliberately out of scope: UAP specifies the
application boundary. Routing, consent policy, audit persistence, replay
protection, and spoken output are host obligations, and this specification does not
constrain how a host meets them.

## The control contract

### §1 Manifest and capability discovery

A provider declares identity, origin, application compatibility, capability ids,
and safety features before it is invoked:

```json
{
  "uap": "1.0-draft",
  "provider": "org.example.editor",
  "origin": "native",
  "application": "example.editor",
  "platform": "linux",
  "scope": "session",
  "capabilities": [{ "id": "editor.documents", "title": "Documents", "actions": ["note.read", "note.append"] }],
  "features": { "events": true, "preview": false, "transactions": false, "cancellation": true, "capability_query": false }
}
```

Every key above is emitted by the reference serializer; `provider_manifest.always`
in `schema/uap-vocabulary.json` is the authoritative list.

Normative requirements:

- **Discovery is cheap and deterministic.** The manifest carries capability
  *ids* and action *names* only. Full action descriptors — typed arguments,
  preconditions, effects, usage guidance — are fetched **per capability, on
  demand**. Rationale: anything advertised to a model is paid for on every
  conversational turn for the life of a session; a provider with forty actions
  must not put forty schemas in front of a user who asked to open a note.
- **Discovery resolves to a durable session fact.** The capability set is
  established from durable facts (application, account, device, granted
  permissions) at bind time — never re-derived per turn from a guess about what
  the user might ask next.
- **An action the provider cannot currently perform is absent, not
  present-and-failing.** Discovery is shaped by live device, account, and
  permission state.
- **Features default to absent.** A provider gets no credit for machinery it
  did not declare; the failure direction is a confirmation the user did not
  need, never a skipped one they did.
- Origin (`native`, `adapter`, `accessibility`, `vision_hid`) is provenance,
  **not** an assurance level. Assurance (§Conformance) is earned by evidence and
  is never read off the wire.

#### What belongs in a manifest at all

Discovery and results answer different questions, and the boundary is a test rather
than a matter of taste:

> **Discovery describes what this binding can attempt. Results describe what this
> target permits.** A fact belongs in the manifest only if it is **(1) stable for the
> lifetime of the binding** and **(2) knowable without naming a target**. Everything
> else is a typed failure on the result.

An operating-system permission the user has not granted is stable and target-free, so
it shapes discovery — the capability is simply absent. A row-level access rule cannot
be evaluated without naming the row, so it fails (2) and is a `permission_denied`
result, never absence. The second clause is the one that is easy to get wrong: "a
document is currently open" is target-free but *not* stable, so gating a capability on
it strands the binding the moment the user opens or closes a file. That is a
precondition, and §5 is where preconditions belong.

#### `scope` — session manifest or public catalog

`scope` distinguishes the two documents that share this schema:

- `session` (the default, and what an absent `scope` means) — what *this* binding can
  do: shaped by device, account, permissions, and feature state.
- `public` — a deployment's **unscoped superset**, suitable for serving pre-authentication
  so a host can discover that an application speaks UAP at all.

A public catalog is a claim about the deployment, not a grant: it never carries an
assurance level or a confirmation class, and a host assigns both exactly as it does for
any other provider. The binding invariant is **`bound ⊆ public`** — a session manifest
may offer *less* than the catalog (no permission, feature disabled), and offering *more*
is drift. For a capability that declares its size rather than its members, containment
is asserted at capability level.

#### Large surfaces: enumerate, group, or ask

`MAX_CAPABILITIES` (64) and `MAX_ACTIONS_PER_CAPABILITY` (32) bound what a manifest may
**inline**. They are a context budget, not a statement about how capable an application
may be: a fully populated manifest already costs more model context than a typical
conversational turn. Applications larger than that escape by indirection, in one of three
modes:

1. **Enumerated** — capabilities list their action names. The default, and the only mode
   required of a conforming provider.
2. **Grouped** — a capability sets `action_count` to its size and omits `actions`; the
   list is resolved through the ordinary per-capability descriptor fetch. A declared count
   is a checked claim: conformance fails a capability whose resolved actions do not match
   the number it declared.
3. **Queryable** — the provider sets `features.capability_query`, declaring that its own
   registry can be asked whether an action exists. The manifest then stays small
   regardless of application size.

> **Status:** grouped discovery and `capability_query` are **specified ahead of host
> execution**. A provider may declare them and the schema is frozen, but a conforming
> host is only required to implement enumerated discovery in this draft. Asking costs a
> model turn, so the rule is: enumerate if it fits, group if it does not, ask for the tail.

#### Public discovery at the origin

Everything above describes the manifest a host fetches *after* it holds a session and a
credential. That leaves the question a third party cannot otherwise answer: **how does an
application advertise that it speaks UAP at all?** A desktop provider announces itself over a
local channel whose peer credentials the operating system supplies; a web application has no
such channel, and the web is where third-party adoption starts.

Web applications advertise at a well-known URI
([RFC 8615](https://www.rfc-editor.org/rfc/rfc8615)):

```
GET https://app.example.com/.well-known/uap.json
```

The document is deliberately thin — identity and reach, nothing else:

```json
{
  "uap": "1.0-draft",
  "provider": "com.example.app",
  "application": "example.app",
  "endpoint": "https://app.example.com/uap",
  "authorization_server": "https://auth.example.com",
  "catalog": {
    "url": "https://app.example.com/uap/catalog.json",
    "digest": "sha256:…"
  }
}
```

**Two documents, not one.** The origin document is an identity record and changes almost
never; the catalog changes with every application release. Conflating them would invalidate
the identity record's cache on every deploy — and, once signing exists, its signature too.
The extra fetch is cacheable and paid once per origin.

The normative rules:

- **The catalog is a `ProviderManifest`, not a second format.** It carries `scope: "public"`
  and is otherwise the same schema, so one parity gate and one set of conformance vectors
  cover both. A separately specified public format drifts against the bound one within two
  releases.
- **`bound ⊆ public`.** The catalog is the unscoped superset — what this deployment can ever
  do — while the bound manifest is what *this* session can do now. A capability present at
  bind but absent from the catalog is drift or a dishonest provider. A catalog capability
  absent at bind is ordinary: no permission, wrong plan, feature disabled.
- **The catalog is a curated projection, not a dump.** Publication is opt-in per capability;
  an application may expose six capabilities publicly and keep two hundred behind
  authentication. Unauthenticated enumeration of every consequential action is a
  reconnaissance gift, and the answer is curation rather than obscurity.
- **Neither document sets an assurance level or a confirmation class.** A public file served
  by the application is the same untrusted-content class as page text, and a
  pre-authentication document is weaker evidence again. The catalog names *what exists*; the
  host decides *what it costs*.
- **Origin-scoped, with a document-level escape hatch.** RFC 8615 is rooted at the origin,
  which excludes tenants at a path and many-applications-per-origin deployments. A document
  may therefore point at its own catalog with `<link rel="uap" href="…">`, constrained to
  **same-origin hrefs** — a cross-origin link is an injection redirecting the host at
  attacker infrastructure.

> **Status:** specified ahead of host execution, as with grouped discovery above. The two
> documents and the invariants binding them are frozen, but a conforming host is not required
> to implement a fetch path in this draft, and no conformance vector grades one. The `uap`
> well-known suffix is to be registered provisionally under RFC 8615.

### §2 References and staleness

Objects are addressed by **references**, never by coordinates. Every reference
declares `(kind, id, lifetime, basis)`: a domain kind (`note.document`,
`app.page`), an identifier, a scoped lifetime (`view`, `focus`, `document`,
`session`, `persistent`), and the opaque **basis** (epoch) it was minted under.
Every non-persistent reference requires a basis.

The protocol requires providers to be **truthful about identity, not to
manufacture durability**. A provider answers "is this still the same object?"
via a durable identifier where the application has one, or a re-resolution
predicate plus an invalidating revision where it does not. An application that
offers neither gets view-scoped references that expire on the next state change,
with assurance downgraded accordingly.

Three invariants are frozen in v1:

1. A stale reference is **never silently retargeted** to a different object.
2. A stale reference is a **typed error** (`stale_reference`); re-resolution is
   the host's decision, never the provider's convenience.
3. References become invalid **explicitly** — by basis change — never by
   timeout alone.

**Two staleness mechanisms, never merged.** A reference basis answers *which
object, in which editing state*; the optimistic precondition
(`expect_revision`) answers *has its content moved since the caller looked*. A
mismatched basis is `stale_reference` (re-resolve what "this" meant); a
mismatched revision is `conflict` (right target, someone else got there first).
They demand different recovery, and collapsing them either invalidates every
handle on every keystroke or claims a stability the application does not have.
Recommended practice: keep the reference basis **view-grade** (identity plus
the clean/dirty transition) and the revision **content-grade**.

### §3 Observation and query

Observation returns a **bounded snapshot**: the current view, focus, a capped
list of addressable objects (each carrying its reference, type, title, bounded
properties, and available actions), the provider's current epochs, and an
explicit count of omitted objects — so the model can narrow a query instead of
assuming it saw everything. A snapshot is a query result, never a dump; bulk
content stays behind handles in the local tool plane, and only facts needed for
the current decision reach the model.

Observation accepts **scopes** (`view`, `focus`, `selection`, `document`,
`objects`) so a caller asking less pays less.

**Query algebra (interchange schema, published ahead of execution).** The draft
freezes one composition algebra — `and` / `or` / `not` over typed predicates,
with a core predicate set (`ref.eq`, `type.is`, `rel.of`, `prop.cmp`,
`text.range`, `text.contains`, `view.visible`, `symbol.matches`) and declared
bounds — so that independent implementations cannot invent incompatible
grammars. Domain-specific predicates are namespaced and declared in on-demand
capability documentation; only the carrier is core. Query *evaluation* is not
yet part of the conformance surface; do not infer runtime availability from the
schema's existence.

### §4 Typed actions and declared effects

Actions are namespaced `<noun>.<verb>` operations (`note.append`,
`calendar_event.list`, `document.open`) — the noun is the thing acted on, so a
host can reason about `*.undo` or `note.*` across applications. The protocol
standardizes the **envelope**; domain namespaces carry the meaning.

An `ActionCall` carries: the action name, a caller-supplied `command_id`
(idempotency identity), an optional target reference, a bounded typed argument
map, an optional `expect_revision`, a `dry_run` flag, and an optional provider
pin for disambiguation.

**Strict, atomic decoding.** Malformed calls are rejected whole, never
truncated: a truncated input can silently drop a recipient or an option and
execute a *different* command. Every implementation decodes in one canonical
field order so multi-error calls name the same first repair everywhere. Bounds
(sizes, depths, key counts) are published in the vocabulary schema.

Every action descriptor declares:

- typed arguments and preconditions;
- **effects** — what escapes, ordered by radius: `read`, `view`, `draft`,
  `persist`, `device`, `external` — each with a scope and an operation-bound
  **reversibility** (`none`, `checkpoint`, `operation_undo`);
- **terminality** — whether the outcome is observable at all: `observable` (the
  default: COMPLETED must verify; an acceptance that never resolves is an
  ambiguous failure) or `handoff` (the request verifiably leaves the provider
  with nothing any receiver could ever watch — a dialer intent, a posted
  notification — so ACCEPTED is the terminal truth, reported as
  sent-but-not-confirmed, never converted into a false failure);
- a verification method; idempotency; and optionally `undo_of`, naming the
  action this one reverses.

**The host derives consent; the provider never chooses it.** Confirmation
classes are computed by host policy from declared effects and assurance — a
provider (or an adapter generated from vendor documentation, or a page whose
content is attacker-controlled) must not be able to mark "email the customer"
as a quiet local edit. Declarations parse **fail-closed**: an unknown effect
kind is treated as `external`, an unknown reversibility as `none`, and an
unknown terminality is a malformed descriptor. `undo_of` is not
self-certifying: the reversal relief applies only when the host can see the
named action, that action declares an operation-bound undo, and it was not
outward-facing.

### §5 Results, errors, and honest endings

An `ActionResult` carries the command id, a status, an optional re-minted
post-action reference, `revision_before`/`revision_after`, bounded structured
`data`, an optional single-use `undo_token`, and on failure a typed error.

Statuses: `accepted`, `completed`, `previewed`, `rejected`, `failed`,
`cancelled`. Their honesty rules:

- **`completed` requires evidence.** For state-changing actions the result must
  carry a verifiable post-action revision, and hosts are expected to verify it;
  a provider reporting its own success proves nothing. Read/view-only
  completions need no verification round trip — their postcondition is the
  returned data.
- **`accepted` is nonterminal** (except for declared handoffs). A host MUST
  resolve a non-handoff acceptance by observation — confirm the effect against
  provider state, or report the observed current state — and MUST NOT present
  an unconfirmed acceptance as success. The current draft's event envelope has
  no command-terminal linkage; an effect landing after the session's turn ends
  cannot yet resolve its command.
- **`rejected` means nothing ran; `failed` means the outcome is unknown.** A
  provider must never report `rejected` when work may have started.
- **Idempotency:** re-presenting the same `command_id` returns the original
  outcome; it never runs the work twice. Rejections replay too — the same
  command must not get a different answer because the world moved.

The error taxonomy is closed, and each code names its recovery:
`stale_reference` (re-observe, re-resolve by identity, retry once — silently;
this race is ordinary), `unknown_reference`, `unsupported`, `ambiguous` (more
than one provider serves the action at equal assurance — ask, by name),
`precondition_failed`, `invalid_call` (machine-repairable: `field_path`, a
typed `expected` constraint, `got`, an optional suggestion — one automatic
repair attempt, then an honest surfaced failure), `invalid_argument`,
`permission_denied` (see below), `confirmation_required`, `conflict` (never
auto-retried: someone else's edit won), `cancelled`, `timeout`, `unavailable`,
`internal`. Provider prose in errors is **untrusted input**: hosts speak their own
words and keep provider text out of durable records.

**`permission_denied` carries how far the refusal reaches.** Two refusals wear this
code and mean opposite things, so the error may set `denied_scope`:

- `target` — this record, document, or object only. Discovery is untouched and another
  target may well succeed.
- `capability` — the whole capability, for this binding. The manifest is now stale and a
  host should stop offering it rather than fail the same way repeatedly.

**An absent `denied_scope` reads as `target`.** That is the direction that fails safely:
a provider that does not classify its refusal costs one wasted retry, never a capability
the user still holds. Note the asymmetry a host inherits — a capability-scoped refusal
narrows the bound manifest, but a capability *gained* mid-binding cannot appear until the
next bind.

**Cancellation is honest about what it achieved:** `stopped` only when the work
provably never began (the host's own not-yet-dispatched check is the only hard
guarantee), `too_late` when it was already under way — cancelling is not
undoing — and `unsupported` rather than silence.

### §6 Events

Providers with `events: true` emit bounded, typed lifecycle events
(`view.changed`, `document.changed`, `reference.invalidated`, …) carrying
references and routing facts, never content. Events are ordered by a monotonic
per-session sequence; a gap obliges the host to discard cached state and
re-observe. Events let a host react and verify without polling; they are local
runtime traffic.

### §7 Transactions, preview, and undo

Consequential work follows *inspect → propose → preview → commit → verify →
undo if needed*. The protocol supports `dry_run`/native preview, optimistic
revision preconditions, atomic batches where the application can honour them
with **structured partial failure** where it cannot, and checkpoint/undo tokens
with explicit lifetimes.

Undo honesty: a provider must not claim reversibility merely because the
application has an Undo menu. An undo token is bound to *this* command,
**single-use** — a second firing would revert a later operation, the exact
damage undo exists to prevent — and a spent or guard-refused token returns
`conflict` rather than pretending. If no operation-bound basis exists, the
action is irreversible for policy purposes.

### §8 Workflow interchange (plans)

The draft also freezes the interchange shapes for **plans** — host-executed,
bounded, guarded straight-line sequences of action calls (no loops, no
branching beyond guard-skip: the model is the loop) with typed reference slots
between steps and per-step reversibility reporting. As with queries, these are
published **schema-only** so independent implementations share one grammar;
plan execution is not yet on the conformance surface.

## Efficiency requirements

Efficiency is a protocol requirement, not an optimization left for later:

- local-first transport; no mandatory network service or cloud hop;
- one capability negotiation per bind, cacheable by digest;
- on-demand domain schemas and documentation — nothing advertised per turn;
- bounded queries and event deltas rather than repeated full state dumps;
- opaque handles for large payloads — documents, meshes, images never cross the
  control channel;
- explicit payload bounds published in the vocabulary schema and enforced by
  parsers on both sides ("not by politeness");
- results shaped for decisions: withheld-count markers instead of silent
  truncation, truncation markers on bounded text, no unrequested fields.

The canonical wire binding is deliberately **not chosen in this draft**; the
reference deployments run schema-first JSON over their existing transports.
Transport details belong to the binding, never to the semantic core. A
binding that multiplexes UAP onto a shared channel MUST route every frame
under one dedicated topic; a dedicated channel needs none. The topic value is
implementor-defined — the vocabulary fixes no value.
Binding selection is a benchmark decision, and where results are close, the
debuggable option wins — the binding is not this protocol's bottleneck; model
tokens and application latency are.

## Protocol strength requirements

Reference slices stay small; the protocol must not be *designed around* small
slices, because complex professional work is the point. Each of the following
must be demonstrable in the protocol (and is being encoded as conformance
vectors):

- **Composition and atomicity** — an N-action batch that commits atomically or
  returns structured partial failure with a defined post-state.
- **Long-running work** — progress, mid-flight cancellation, and a cancel that
  leaves a *declared* state.
- **Concurrency with a human** — the user edits while the agent acts; revision
  preconditions reject the stale write and never silently merge.
- **Expressive bounded observation** — the query capability, proven on a deep
  object graph without dumping it.
- **Domain depth without core bloat** — namespaces carry units, constraints,
  and topology while the core stays fixed.
- **Cross-provider reference passing** — the reference and permission model
  must not preclude document-to-document workflows across applications.
- **Honest reversibility at scale** — in a large batch, reversibility is
  reported per operation, never collapsed into one optimistic flag.

A written set of genuinely complex scenarios (a multi-hour parametric CAD
revision with interruption; cross-document report assembly; a multi-record
business workflow with a concurrent second user; a project-wide refactor with
verification and exact undo) must be expressible **on paper** in the protocol
even where unimplemented. Anything inexpressible is a protocol finding before
it is a code finding.

## Conformance and assurance

One core suite runs unchanged against every provider. Its rule is **semantic
parity, not capability parity**: a phone exposes a calendar and a web portal
exposes a notebook cursor, and neither fact may change how discovery,
references, results, errors, cancellation, or policy-relevant declarations
behave. Capabilities a platform does not have are absent — never stubbed.

The suite is safe against live applications: it reads, and it probes the paths
that must *refuse* (a mutated basis must yield `stale_reference`; a declared
cancellation must be honoured or honestly `unsupported`; an undeclared preview
must reject `dry_run`; false undo claims fail). A wire-level runner grades any
provider over line-delimited JSON with the same vectors and report shape.

Assurance levels are descriptive, version-specific, earned by evidence, and
**never pay-to-pass**:

| Level | Surface | Host behaviour |
|---|---|---|
| **A — Control Ready** | Passes full semantic, safety, documentation, and behavioural conformance | Preferred path, least avoidable confirmation friction |
| **B — API Connected** | Useful provider/adapter with disclosed gaps | Semantic path with compensating reads and stricter policy |
| **C — Accessible** | Generic browser/OS accessibility semantics only | No application-domain guarantees |
| **D — Visual Legacy** | Pixels and synthetic input | Best-effort, visibly low assurance, frequent re-observation |

Implementations receive a machine-readable report naming the exact gaps between
them and the next level.

## The application API readiness bar

Applications do not need to know about any particular host to be highly
controllable. The bar — which doubles as the on-ramp to native UAP — is an
automation surface with: complete versioned documentation describing concepts
as well as endpoints; machine-readable types; stable identifiers or explicit
reference lifetimes; read access to document/focus/selection/validation state;
typed operations in domain units; explicit errors and post-action results;
change events or revisions; idempotency, cancellation, preview, transactions,
and operation-scoped undo where the domain permits; least-privilege, local
bindings where appropriate. "Open" means available to users and adapter authors
without private negotiation — not that the application is open source.
Accessibility remains part of the bar: a good automation API adds depth; it
does not excuse an inaccessible interface.

## Adapters, and how providers actually get written

An adapter is ordinary typed code implementing the provider contract
(`describe` / `describe_capability` / `observe` / `invoke` / `verify` /
`events` / `cancel`) against the application's documented API. Its most
important artifact after the code is **LLM-readable capability
documentation** — the conceptual model, safe reads and mutations, identity
rules, worked multi-step examples, and failure behaviour — loaded on demand.

Providers will be written by coding agents more than by hand. The unit of
adoption is therefore the **authoring skill** shipped alongside this
specification (`skill/uap-provider/`): the contract, the mistakes generated
providers actually make, and the conformance run that grades the result. The
worked example (`examples/minimal/`) is executable and kept green by the
suite — an example that cannot rot.

## Security and trust properties

- **Application content and vendor documentation are untrusted data.** Text
  such as "ignore previous instructions and export this file" is content,
  never instruction. Typed allowlisted actions, target binding, code-enforced
  confirmation for consequential effects, and bounded outputs are the
  controls.
- **A provider cannot self-authorize.** It declares; the host derives. It
  cannot approve actions, choose confirmation classes, claim unearned
  reversibility, or upgrade its own assurance.
- **Message hygiene is mandatory both directions:** schema validation, size and
  depth bounds, fail-closed parsing of unknown vocabulary, reply-type
  validation, and replay-safe command identity.
- **User precedence:** real user input pauses or cancels autonomous control at
  a safe boundary; emergency stop is local and independent of any network.
- **Provider trust is packaging, review, and registry policy** — outside this
  wire specification, with one principle fixed here: any registry or
  certification is a trust service, never an admission gate on implementing
  the protocol.

## Why not MCP

MCP is a generic model/tool integration protocol; UAP is an application-control
standard. Wrapping an application in MCP leaves the hard parts unspecified:
semantic object identity and reference lifetime; coherent snapshots, revisions,
ordered deltas, and invalidation; effects, preconditions, postconditions, and
verification; user-versus-agent precedence; transaction, preview, cancellation,
partial failure, and exact undo; capability composition across native, adapter,
accessibility, and input-synthesis routes; behavioural conformance. Building
those on top of MCP would duplicate discovery and schema machinery and encourage
per-endpoint tool catalogues — paying context cost without gaining the control
guarantees. UAP therefore stands alone and is independent of any model vendor or
host product.

## Governance, licensing, versioning

Published with an irrevocable open license from this first draft:
specification documents CC-BY-4.0; schemas, vectors, examples, skill, and
conformance tooling Apache-2.0 — which carries an express patent grant. Note
that CC-BY-4.0 does **not** license patent rights, so the specification prose
carries no patent grant; the normative artefacts an implementer actually builds
against (schemas, vectors, conformance tooling) do, under Apache-2.0. Adopting UAP carries no dependence on the
publisher's continued goodwill. No foundation or standards-body donation until
at least two independent hosts implement the protocol; a lightweight neutral
steering group forms if real adopters appear.

Versioning: `manifest.uap` names the semantic-model version; hosts fail closed
on a major mismatch. Domain capabilities version independently of core.
Vocabulary is closed per version: implementations must not invent codes or
statuses (hosts parse unknown vocabulary fail-closed, to the strictest
reading).

**Forward compatibility, and how a minor adds a field.** The published schemas
close every object, and a conforming decoder ignores fields it does not know —
two rules that contradict each other the moment a v1.1 field appears on the
wire, because a strict validator rejects the call while a lenient host executes
a different command than the sender wrote. The resolution is one namespace:

- A field a future version adds, or a vendor adds, MUST be named `x-<name>`
  (lowercase, hyphen-separated). The schemas admit `x-` fields on every object
  via `patternProperties`; they still reject any other unknown field, so a
  misspelling — the common case — is caught rather than silently ignored.
- A peer MUST ignore an `x-` field it does not understand, and MUST NOT treat
  its presence as a version signal. Anything load-bearing belongs in a major.
- A minor version is therefore additive by construction, and needs no
  negotiation: `manifest.uap` continues to carry `major.minor`, hosts compare
  only the major, and a peer discovers what a newer minor offers through
  `features` and capability discovery rather than through the version string.

Until this draft's label drops, the version string itself may move without a
major bump; treat `1.0-draft` as unstable and re-read this section on each
change.

## Status of this draft

Implemented and conformance-gated in the reference deployment: the core
contract (§1–§7) across two unlike first-party providers (an authenticated web
application and a native mobile client) plus a wire-graded read provider in a
desktop editor; strict atomic call decoding with machine-repairable
`invalid_call`; declared terminality with the eventual-completion behaviour of
§5; the fourteen-vector core suite and its wire-level runner.

Schema-only in this draft (shared grammar published ahead of execution): the
query algebra and plan envelopes (§3, §8), grouped capability discovery,
`features.capability_query`, and public discovery at the origin (§1). A provider
may declare or serve these and the shapes are frozen, but a conforming host is
not required to execute or fetch them yet.

### Known gaps — read this before implementing

This is a draft, and the honest reading is that **an in-process provider graded by
the published suite is fully buildable from this bundle, while an out-of-process
provider is not yet**. The gaps below are known, and reports against them are the
most useful contribution this draft can receive.

1. **No normative wire binding.** The canonical binding is deliberately not chosen
   here (§Efficiency), pending a benchmark. But `uap-conform` grades over
   line-delimited JSON, and the framing rules it assumes — delimiter and encoding,
   request/reply correlation by echoed `id`, whether requests may be pipelined or
   must be sequential, the maximum frame size, the reply deadline, and the fact that
   event frames carry no `id` — live in `schema/uap-vocabulary.json` comments, the
   golden vectors, and the runner's source rather than in this document. Treat
   `vectors/core-wire.json` plus `examples/minimal/stdio_harness.py` as the working
   definition until a binding section exists.
2. **Only inbound envelopes have a JSON Schema.** `schema/uap-workflow.schema.json`
   types `ActionCall`, the `invalid_call` error, references, queries and plans.
   Everything a provider *emits* — manifests, descriptors, observations, results,
   verification, cancellation, events — is published as key lists under
   `envelopes` in `schema/uap-vocabulary.json`, with no types or value constraints.
   The reference serializers and the golden vectors are authoritative for those
   shapes.
3. **Undo tokens have no redemption call.** §7 specifies that an `undo_token` is
   single-use and bound to the operation that issued it, but this draft does not
   specify how a host presents one back to a provider. Until it does, undo is a
   provider-local convention.
4. **`features.transactions` has no wire surface and no vector.** A provider may
   declare it; nothing in this draft says how a batch is submitted, and the
   conformance suite does not grade it. Do not declare it expecting it to be
   exercised.
5. **Normative language is not RFC 2119-tagged.** Where this document says "must"
   in lower case it means the same thing as upper case; the distinction is not yet
   used consistently, and §5's verification requirement in particular is stated at
   different strengths here, in the authoring skill, and in the vocabulary.

Also not yet specified: cross-turn command-terminal events (§5), and the
standing-consent and workflow-reuse layers sketched by the adopted amendments —
they will enter the specification as their reference implementations land.
