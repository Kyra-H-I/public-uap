# Scenario: the render, the report, and the email

**Domain:** three applications in one request (Blender-, OnlyOffice-, and
Thunderbird-shaped)
**Status:** paper walk against `1.0-draft`. No implementation claimed.
**Verdict:** genuine missing primitive — this walk exists to hit known gap #6
head-on and map its exact edges (F-003).

## Why this scenario is designed to break UAP

"Take the graph from Blender, insert it into the report, and email John the
PDF" is the most ordinary sentence a user will say and the least answerable
one in the draft. Three providers, two boundary crossings, and the protocol's
own rules — references are provider-relative, bulk content never crosses the
control channel — close every obvious door on purpose. The walk's job is not
to solve the data plane mid-scenario; it is to find precisely where the
current machinery stops and what any future mechanism must answer.

## The walk

1. **Render the graph.** The 3D provider completes `scene.render` — `persist`,
   observable, verified. The result names the artifact the only way it can
   today: a provider-local handle plus facts (format, size). Within *this*
   provider, done cleanly.
2. **First crossing: render → document.** The document provider's
   `document.insert_image` needs content the mail of which lives behind
   another provider's handle. The options the current draft actually offers:
   - **Through model context** — for small text this is not a workaround but
     the *correct* bridge (the model should read what informs its
     decisions). For a binary render it fails on every axis at once: size,
     format, and fidelity (a model retyping bytes is not a transport).
   - **Through a provider-relative reference** — fails by design; the
     document provider has no interpretation of another provider's `Ref`,
     and pretending otherwise would silently couple every provider to every
     other's identity scheme. The walk *confirms this door should stay
     closed*: portable refs are the wrong fix.
   - **Through the filesystem out-of-band** — "render to a path, insert from
     the path" works today and is the honest degenerate answer, but it lives
     entirely outside the contract: no declared effects on the crossing, no
     provenance, nothing for consent to read back, nothing audited. The
     escape hatch proves the demand and none of the properties.
3. **Second crossing: document → PDF → mail attachment.** Same wall, with the
   stakes raised: attaching to mail feeds an `external` action. Whatever
   crosses here is about to leave the machine, so the crossing is exactly
   where consent needs a truthful sentence — *which* PDF, produced from
   what, unmodified since when. The out-of-band path cannot produce that
   sentence; model context must not (the user's mail may be precisely what
   should not transit a model).
4. **What the mechanism must therefore be able to say** (requirements
   extracted, not designed): an artifact crossing is **host-brokered** (the
   host is the only party both providers already trust structurally);
   content is **immutable and content-addressed** (a digest is the only
   honest answer to "is this still what I confirmed" — the same reasoning
   that made revisions content-grade); the handle carries **provenance and
   facts, never content** on the control channel; **redemption is
   observable and consented** like any other effect; and content enters
   model context only by an explicit bounded observation. None of this
   exists in the draft, and none of it should be invented by one scenario.

## Where it strains

Everywhere — by design. Two boundaries worth keeping sharp in the eventual
design:

- **This is not a reference-model bug.** References answer "which object, in
  which state" *within* a semantic domain; an artifact crossing moves
  *content between* domains. The strength requirement was renamed
  (artifact/resource passing, not reference passing) for exactly this
  reason: fixing this by making `Ref` portable would break the better
  abstraction to patch the worse gap.
- **The degenerate answers must stay legal.** Small text through context and
  explicit user-visible files are both correct in their regimes; the
  mechanism is for what those regimes cannot carry (large, binary,
  fidelity-critical, or private payloads). A design that makes the simple
  cases heavier has failed this scenario even if it makes the hard case
  work.

## Verdict

**Genuine missing primitive (F-003, confirmed).** The walk sharpens the gap
without designing into it: what is missing is a host-brokered,
content-addressed artifact handle with consent-readable provenance — and the
discipline note in the findings register applies with full force: this
mechanism deliberately moves content *without* the model seeing it, so its
consent and audit story must be designed before its transport, not after.
