# Pressure-test matrix — protocol invariants × reference domains

This matrix keeps the scenario set honest. Rows are the protocol properties a
provider can genuinely exercise; columns are where each one is (or will be) put
under load. A row with no mark is an **uncovered invariant** — the strongest
argument for the next scenario or vector, and visible here on purpose rather
than discovered three years into an ecosystem.

Markers:

- **●** — exercised *today* by the conformance suite or the reference
  implementations' test surface (an authenticated web application, a native
  mobile client, a desktop editor extension).
- **○** — covered by a paper-walk scenario in this directory.
- *(blank)* — uncovered. Honest gap.

| Invariant | Today | Email | Browser | Smart home | Automotive | Editor | Long-running | Cross-provider |
|---|---|---|---|---|---|---|---|---|
| Reference lifetime | ● | | ○ | | | ○ | | |
| Stale reference | ● | | | | | ○ | | |
| Content revision | ● | ○ | | | | ○ | | |
| Conflict (concurrent write) | ● | ○ | | | | ○ | | |
| Bounded observation | ● | | | ○ | | | | |
| Deep query | | | | | | | | |
| User concurrent interaction | ● | ○ | | | ○ | ○ | | |
| Deterministic action | ● | | | | | ○ | | |
| Typed preconditions | ● | | | | ○ | | | |
| Permission denial (target) | | | ○ | | ○ | | | |
| Permission loss (capability) | | | ○ | | ○ | | | |
| Effect classification | ● | ○ | | ○ | ○ | | | |
| Reversibility declarations | ● | ○ | | | | ○ | | |
| Preview / dry-run honesty | ● | ○ | | | | | | |
| Idempotency (command replay) | ● | | | | | | ○ | |
| Accepted ≠ completed | ● | ○ | | ○ | | | ○ | |
| Handoff terminality | ● | ○ | | | ○ | | | |
| Verification | ● | | | ○ | | | ○ | |
| Long-running operation | | | | | ○ | | ○ | |
| Cancellation | ● | | | | ○ | | ○ | |
| Events / invalidation | ● | | ○ | ○ | | | | |
| Structured partial failure | | | | | | | ○ | |
| Transaction / atomic batch | | | | | | | | |
| Cross-provider artifact passing | | | | | | | | ○ |
| Provider trust boundary | | | ○ | | | | | |
| Physical-world uncertainty | | | | ○ | ○ | | | |

## What the matrix already says

- **Four rows lack live (●) coverage**: deep query, transaction/atomic batch,
  structured partial failure, and long-running work. Of those, deep query and
  transaction/atomic batch are entirely uncovered — not even a paper walk —
  while structured partial failure and long-running work have paper-scenario
  (○) coverage only. That matches the draft's own stability labelling — the
  query algebra and transactions are provisional precisely because nothing
  exercises them — and it is why those shapes must not freeze yet.
- **The editor column is the calibration control.** Its marks trace mechanics
  the reference implementation already runs live; strain in other columns is
  measured against it.
- **No two scenarios exist to prove the same thing.** Where two share a row
  (accepted ≠ completed; physical-world uncertainty) they attack it from
  different layers — an email server versus a relay versus a vehicle — because
  a primitive is only promoted when *unrelated* domains demand it.

## Choosing the next scenario

Rank candidate domains by the number of currently-unmarked rows they would
genuinely exercise, not by how impressive the application is. By that rule the
current backlog after this set: a business-records system (transactions,
partial failure, permission loss under concurrency), a parametric CAD system
(deep query, cascading recomputation, transaction boundaries), and a
print/scan queue (physical-world uncertainty from a second, unrelated angle).
