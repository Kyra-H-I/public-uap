# Failures that actually happened

Each of these shipped, passed its unit tests, and was found later. They are here
because they are invisible to the obvious test.

## A reference that is stale the moment it is returned

`note.undo` was unreachable. Saving cleared the editor's `dirty` flag, which advanced
the document epoch — so the reference the save handed back was already stale when the
host tried to use it. The fixtures held the open note constant across the save, so the
epoch never moved in tests and nothing failed.

**Rule:** a reference an action returns must be valid in the state that action
*leaves behind*, not the state it started in. **Test rule:** a fixture that holds
state constant across an action cannot see this class of bug — move the state.

## An approval key that was a constant

Confirmations were keyed `action:ref`. For actions with no target — dialling a number,
where the target is an *argument* — the key rendered as `phone.call:-` for every call.
Arming a second number silently displaced the first, and the confirmation then fired
under the key the user had heard read back as the first number.

**Rule:** when an action has no reference, its approval identity must come from the
arguments that decide what happens. A constant key means every instance of that action
is the same pending approval.

## A wire field that type-checked on both sides

The host read `event`; the TypeScript client sent `type`. Both sides compiled, every
unit test passed on both sides, and the host read every event as empty forever.

**Rule:** fixtures matching fixtures prove nothing across a language boundary. Drive
the real implementations against real envelopes from the other side of the wire — a
cross-language integration test built that way is what caught this one.

## The verifier that self-reported

`verify` returned `verified: true` unconditionally. The one method that exists because
a provider's claim of success cannot be trusted was a provider claiming success.

**Rule:** if you cannot evaluate the expectation, return `false`.

## The actionable input that was silently shortened

The host bounded a too-large argument map by keeping the first keys. That is safe for
display output with an explicit truncation marker; it is unsafe for a command. A
recipient, range, or option can disappear and leave behind a smaller call that is
still valid enough to execute — but is no longer what the user asked for.

**Rule:** actionable input is atomic. Reject the complete call with structured
`invalid_call`; never execute a subset.

## Names that collide, resolved by coin flip

Standardising on `<noun>.<verb>` made names collide across providers — two providers
can both offer `note.save`. The router picked one. It looked fine until the wrong
application acted.

**Rule:** collisions are expected. The router returns `ambiguous`, and the caller
answers with `ActionCall.provider`. Do not dodge this by prefixing your actions with
your application name.

## Object-literal lookup keyed by a caller's string

In TypeScript, `DESCRIPTORS[name]` on an object literal reaches `Object.prototype`.
`DESCRIPTORS["constructor"]` returns a *function* — truthy, so `?? []` does not catch
it, and the fallback never runs. Any `name` that arrives over the wire can do this:
`constructor`, `toString`, `valueOf`, `hasOwnProperty`.

**Rule:** a lookup table keyed by an untrusted string is a `Map`, or
`Object.create(null)`, or is guarded with `Object.hasOwn`. A plain object literal with
`??` is the shape that fails.

## Inventing durability out of an undocumented id

Driving an application through internal command ids that are not part of its public
contract — undocumented `executeCommand` ids, private selectors — produces a provider
that works today and breaks silently on the next release, under a name that still
looks right.

**Rule:** prefer the documented, deterministic operation. If only an undocumented path
exists, the reference is positional and the assurance level is lower; say so rather
than presenting it as a semantic action.

## Identity that names the wrong machine

An editor attached to a remote or a devcontainer will happily apply an edit to a
right-looking path on the wrong filesystem. Provider identity has to capture the
remote authority, not just the application.

**Rule:** identity includes *where*, and a provider that cannot establish where it is
acting should refuse rather than guess.

## Building your own confirmation

The provider-side version of this trap is simply doing it at all: a `confirm` argument
on your action, a prompt from your handler, a judgement in your code about whether
something is risky enough to ask about. All three break the model, because the host
cannot enforce a policy a provider has already decided.

**Rule:** declare effects. Nothing else.

---

A new failure that ships belongs here, stated the same way: the symptom, why the
obvious test missed it, and the rule that prevents the class.
