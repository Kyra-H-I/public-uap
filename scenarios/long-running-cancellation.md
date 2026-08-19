# Scenario: run this cell — no, stop it — did it finish?

**Domain:** execution and live media (JupyterLab- and OBS-shaped)
**Status:** paper walk against `1.0-draft`. No implementation claimed.
**Verdict:** protocol finding — the walk runs into the cross-turn command
lifecycle wall from its third step onward (F-001, first domain); the
streaming half adds evidence to F-002.

## Why this scenario is designed to break UAP

"Run this cell" is the anti-editor: the action's *point* is that it keeps
happening after the reply. A cell can run thirty minutes, write files, call
external APIs, or never terminate; "start streaming" is five distinct truths
wearing one verb. Every protocol assumption tuned to request/response —
verify-then-speak, endings inside the turn, cancellation as a courtesy —
gets stress-tested by work that outlives the conversation that asked for it.

## The walk

1. **`cell.run`.** Declared effects are the honest, uncomfortable maximum the
   provider can know statically: `persist` (kernel and filesystem state) and
   — because arbitrary code reaches the network — `external`. That is the
   correct consequence of declarations-drive-policy: a provider that cannot
   bound what a cell does must not pretend it can, and host policy prices
   the action accordingly. (A notebook *profile* could later standardize
   finer, kernel-enforced sandboxed declarations; that is domain work, not
   core work.)
2. **`accepted`, honestly.** Execution starts; there is nothing to verify
   yet and no lie told. The host's within-turn hold applies: wait briefly on
   events, re-observe, and speak observed reality — "it's running, cell
   shows [*]" — never success.
3. **The turn ends. The work does not.** Twenty minutes later the cell
   completes. The provider has state events, but the event envelope carries
   no command identity, no progress, no terminal result — there is no wire
   fact that says *command 47 finished, and here is its outcome*. The
   session that asked cannot be told; a later session can observe the
   notebook but cannot *attribute* what it sees to the command that caused
   it (audit) or resolve that command's ending (honesty). **This is F-001's
   defining walk.** What it needs is narrow: command-correlated progress and
   terminal events — not a job-orchestration framework, which the draft's
   the-model-is-the-loop stance rightly refuses to become.
4. **"Stop it"** — mid-run. Cancellation's honest outcomes do their
   work: `stopped` only if the provider can prove execution never began
   (queued, not yet dispatched to the kernel); `too_late` when the cell
   already ran its side effects — cancelling is not undoing, and the
   post-cancel state must be *declared*, not implied clean; `unsupported`
   said out loud rather than a silent swallow. The fourth,
   `nothing_changed`, is unreachable in this walk and that is the point of
   it: a cell that ran is never provably harmless, so the word a host would
   use to skip the undo offer is exactly the word this domain cannot say.
   The nasty sub-case — the interrupt lands while the cell is mid-write to
   disk — resolves as `too_late` plus an observation of what actually got
   written: structured partial truth, and the walk notes the want of
   **structured partial failure** on the wire (evidence toward the
   transactions gap, not a new finding).
5. **`stream.start` (the OBS half).** Five truths: command accepted; app
   entered streaming state; network connection up; remote platform
   accepted; viewers receiving. The provider can attest the first three,
   the fourth only via the platform's protocol, the fifth never.
   `completed` with evidence = "app streaming, connection established" is
   truthful but unlabeled — the same *how-far-does-evidence-reach* wall the
   smart-home walk hit from physical devices. **F-002, second unrelated
   angle** — which moves that finding from "one scenario's intuition"
   toward promotable, pending its third look.
6. **Replay across the gap.** The session died and a recovery path
   re-presents `cell.run` with the original `command_id`. Idempotency
   answers with the original outcome — the cell does not run twice — which
   is exactly right, and only works *because* step 3's gap is about
   reporting, not about identity: command identity already spans turns;
   command *endings* do not.

## Where it strains

Step 3 is the finding, and both halves of the scenario plus the automotive
walk (preconditioning that outlives the session) hit it in unrelated domains
— the promotion bar met with room to spare. The needed shape is deliberately
minimal: events that can carry `command_id`, optional progress, and a
terminal result, feeding the same accepted-resolution machinery that already
exists within a turn.

## Verdict

**Protocol finding, promoted.** Cross-turn command-terminal linkage (F-001)
is this walk's product and belongs in the pre-1.0 wire-binding milestone.
Secondary: F-002 gains its second domain; structured partial failure gains
evidence. Cancellation and idempotency, by contrast, held completely — the
walk tried to catch them lying and failed.
