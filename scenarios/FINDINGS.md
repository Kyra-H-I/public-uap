# Findings register

Strain discovered by scenario walks lands here — **never directly in the
specification**. A finding is promoted into spec work only when several
scenarios, or a scenario plus live host experience, make the same case from
unrelated directions. Rejected findings stay listed: a closed door with its
reasoning attached is worth as much as an open one.

Statuses: **open** (evidence accumulating) · **promoted** (accepted as spec
work, target named) · **rejected** (with reasoning) · **absorbed** (already
covered by a named known gap).

| Id | Finding | Evidence | Status |
|---|---|---|---|
| F-001 | **Cross-turn command lifecycle.** Events carry no command identity, progress, or terminal result, so work that outlives its turn can never resolve its command's ending. | Long-running walk (defining case); automotive preconditioning; live host experience with unresolved navigation acceptances. Three unrelated sources. | **Promoted** — pre-1.0 wire-binding milestone, alongside emitted-envelope schemas and undo redemption. Shape is deliberately minimal: `command_id` + optional progress + terminal result on events, feeding the existing accepted-resolution machinery. |
| F-002 | **Evidence attestation layer.** `completed` cannot state how far its evidence reaches (hub state vs device ack vs physical outcome; app streaming vs platform accepted vs viewers receiving). | Smart-home walk; live-media half of the long-running walk. Two domains — one short of comfortable. | **Open.** Deliberately not promoted; a print/scan-queue scenario is the planned third look. If promoted, the shape is a declaration on evidence, never a device ontology. |
| F-003 | **Cross-provider data plane.** No mechanism for an artifact to cross provider boundaries with provenance, consent readability, and fidelity. | Cross-provider walk (defining case); email walk's attachment boundary. Already named as known gap #6. | **Absorbed / design-gated.** Requirements are mapped in the cross-provider walk; design is deliberately deferred until live usage shows which crossings actually fail which axes. Consent/audit story before transport. |
| F-004 | **Provider identity is session-granular.** Two live windows/tabs of one application collide on one provider id; `ambiguous` covers rival providers, not twin sessions. | Browser walk; live field experience with two desktop editor windows. Two unrelated sources. | **Promoted** — identity/binding section of the wire-binding milestone: host-qualified session identities reusing existing routing machinery (provider pin, working context, ambiguous-as-cold-case). |
| F-005 | **Binding lifecycle on provider death.** A provider vanishing mid-binding (page navigation, app crash, restart with handles outstanding) has no specified sequence: in-flight command resolution, terminal notice, what a reappearing provider may claim. | Browser walk. One source. | **Open.** The application-restart-while-handles-exist case in other domains is the natural second look. |
| F-006 | **Browser must not shadow native providers** — proposed core rule that a mediating provider refuse origins publishing their own UAP endpoint. | Browser walk (raised and examined). | **Rejected.** Route preference is host policy, already assurance-driven per operation; freezing it into the core would forbid legitimate mixed compositions on one origin. Recorded so it is not re-litigated from scratch. |

## Standing observations (not findings)

- **Structured partial failure** keeps accumulating want (smart-home group
  actions; interrupted execution) but is already inside the declared
  transactions gap — tracked there, not here.
- **The effect model's adequacy** for consent (volume-down vs door-unlock)
  has survived both walks that attacked it, *on paper*, without
  provider-specific host branches — the simulated automotive provider is
  where that claim gets falsified or confirmed with running code. No new
  policy enum is justified by current evidence.
