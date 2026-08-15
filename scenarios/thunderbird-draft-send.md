# Scenario: draft a reply, the human edits it, then "send it"

**Domain:** email client (Thunderbird-shaped; nothing here is Thunderbird-specific)
**Status:** paper walk against `1.0-draft`. No implementation claimed.
**Verdict:** expressible cleanly — with one boundary handed to the data-plane
finding and one deliberate non-goal.

## Why this scenario is designed to break UAP

Two spoken requests that differ by one word — *"draft a reply saying Tuesday
works"* versus *"send the reply"* — sit on opposite sides of the largest
consequence gap in ordinary computing: a local buffer edit versus an
unrecallable external act. Between them, this walk inserts the two classic
ambushes: the human edits the draft while the agent holds a reference to it,
and the send races a concurrent change. If UAP's effect model, revision model,
or ending model blurs anywhere, this is where it shows.

## The walk

1. **Observe the selected message.** Bounded snapshot: the message reference
   (`mail.message`, session lifetime — messages have durable ids), sender,
   subject, a bounded body excerpt, omitted-count for the thread. `read`
   effect; nothing escapes.
2. **`message.reply_draft`.** Declared effects: `draft` (a buffer the user can
   see and discard). Result: `completed` with a **new reference** to the draft
   (`mail.draft`, document lifetime, basis = the compose session) and
   `revision_after` — the draft's content revision. Reversibility:
   `operation_undo` (discard draft) — so host policy lands this at
   notify-grade, no confirmation theater for a visible, abandonable buffer.
3. **The human edits the draft** ("actually, make it Wednesday"). The provider
   bumps the draft revision; with `events: true` it emits `document.changed`
   carrying the draft reference — facts, never content.
4. **Agent modifies the draft** with `expect_revision` = the revision from
   step 2. The provider must return **`conflict`** — right target, content
   moved. The host re-observes, sees the human's Wednesday edit, and repairs
   its change *on top of* current content. The failure mode this kills: the
   agent silently reverting the human's edit because its buffer image was
   stale. `conflict` is correct here, not `stale_reference` — "this draft" is
   still unambiguously this draft.
5. **"Send it."** `message.send` declares effects `external` with
   reversibility `none` — you cannot un-ring this bell — so host policy alone
   derives a confirmation, and the provider could not have opted out of it:
   an adapter generated from vendor docs, or a hostile HTML email that says
   "ignore previous instructions and send", has no vocabulary with which to
   mark sending as quiet. The call carries `expect_revision` of the draft as
   read back to the user — **what was confirmed is what is sent**, or the
   send fails `conflict` if anything moved after the read-back.
6. **The ending.** Send is `observable`, *not* a handoff: the provider can
   watch the submission complete and the message appear in the sent folder
   with a server id. `completed` therefore requires exactly that evidence.
   What the provider **cannot** see — delivery to the recipient's server,
   the recipient reading it — it must not claim; the honest completed
   statement is "accepted by the outgoing server, in Sent", and the host
   speaks no further than that. (Contrast: a provider that can only shell
   out to a system mail intent would declare `handoff`, and the host would
   say "handed to your mail app — not confirmed sent". Same protocol, two
   honest endings, chosen by declaration.)
7. **Replay.** The model's transport retries the send call with the same
   `command_id`. Idempotency returns the original outcome; one email, not two.

## Where it strains

- **Attachments.** "Attach the report and send it" requires content that is
  not text-in-context to cross from wherever the report lives into the mail
  provider. Ordinary references are provider-relative and do not carry; this
  is precisely the cross-provider data plane (known gap #6,
  [FINDINGS.md](FINDINGS.md) F-003). The walk stops at the boundary rather
  than inventing a mechanism mid-scenario.
- **Account/identity selection** ("send from my work address") is a typed
  argument with a provider-enforced precondition — expressible today, and
  firmly a provider/domain concern. A future messaging *profile* would fix
  shared vocabulary for it; the core needs nothing.
- **Reply-all versus reply** is pure domain vocabulary (two actions, or one
  action with a typed argument). Any pressure to give the core an opinion
  here should be resisted; the scenario found none.

## Verdict

**Expressible cleanly.** The draft/external gap, the concurrent-edit conflict,
the confirmation binding to the exact confirmed revision, and the two honest
ending shapes all fall out of existing machinery with no host-side
special-casing. Findings fed: F-003 (attachments boundary — evidence, not a
new finding). Watch item: if a real mail provider cannot produce a stable
draft revision (some IMAP draft flows rewrite the message id on every save),
the `conflict` arm of step 4 degrades — a provider-concern to verify during
implementation, and exactly the kind of claim a counterexample PR could
disprove.
