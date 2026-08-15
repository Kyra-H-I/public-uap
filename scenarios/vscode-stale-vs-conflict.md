# Scenario: the tab you switched, the line you typed

**Domain:** desktop editor (VS Code-shaped)
**Status:** calibration control — this walk traces mechanics the reference
editor provider already runs live, so the other walks' strain is measured
against something known to hold. Marked ● in the matrix, not ○.
**Verdict:** expressible cleanly (by construction; that is this document's job).

## Why this scenario exists in a suite designed to fail

Every other walk needs a baseline: what does "expressible cleanly" look like
when the machinery is real rather than paper? This scenario is the two-error
distinction — `stale_reference` versus `conflict` — under the exact conditions
that tempt implementations to blur them: a human hand on the same keyboard.

## The walk

1. **Observe.** The open document, cursor, selection, diagnostics — bounded,
   with a reference whose basis is **view-grade**: document identity plus the
   clean/dirty transition. Deliberately *not* per-keystroke: a basis that
   moves on every character invalidates every handle mid-sentence, which is
   one of the two classic bad implementations the reference model exists to
   exclude.
2. **The human switches tabs.** The basis moves; the agent's held reference to
   "this document" now points at a view that is not there. Next use fails
   **`stale_reference`** — *what does "this" mean now?* — and the host
   re-resolves by identity (same document in another column? closed?) and
   retries once, silently, because this race is ordinary life with a human,
   not an error worth narrating.
3. **The human types instead.** Identity did not move — same document, same
   view — but content did. The agent's guarded edit carries
   `expect_revision` from its last observation; the provider compares
   **content-grade** revision and fails **`conflict`** — *right target,
   someone got there first.* Recovery is different in kind from step 2:
   re-observe content and rebase the edit, never re-resolve identity, and
   never retry silently — silently replaying a write over a human's fresher
   edit is the data-loss shape.
4. **The deterministic mutation.** "Rename this symbol": the provider invokes
   the editor's own semantic rename — one atomic workspace edit, computed by
   the language server. Deterministic-over-generative as protocol behaviour:
   the exact operation exists, so nobody generates forty plausible text edits
   and calls it a rename. Reversibility `none` at workspace scope is what a
   host's policy sees, and consent follows from the declaration — nothing
   special-cases "rename".
5. **The undo that must not fire twice.** A notify-grade edit returned an
   `undo_token`. The human then types. The token is bound to the operation
   and its post-state: redeeming it now is refused (`conflict`), because
   firing it would revert the *human's* newer work — the exact damage undo
   exists to prevent. Single-use, version-checked, honestly refused.

## What the calibration establishes

- The two-error split is not spec poetry; it survives a live human. Walks
  that find a domain where the split cannot be maintained (a mail store that
  rewrites message identity on every save, a browser page whose identity IS
  its content) have found something real, and this baseline is what makes
  that comparison meaningful.
- View-grade basis + content-grade revision is the recommended shape for a
  reason: each of the two failure modes it avoids (handles that die per
  keystroke; handles that silently drift) was independently rediscovered the
  hard way before landing in the spec's recommended practice.

## Verdict

**Expressible cleanly** — established by a running implementation rather than
argument. No findings; that is the point of a control.
