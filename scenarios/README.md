# Pressure-test scenarios

These documents are part of the protocol's **design evidence**. Each one walks a
deliberately nasty situation through the current `1.0-draft` on paper — no
implementation is claimed unless a walk says so — and ends in exactly one of
three conclusions:

1. **Expressible cleanly** with current UAP;
2. **Provider or profile concern** — real, but belongs in a domain namespace or a
   future domain profile, not the universal core;
3. **Protocol finding** — a genuine missing primitive, recorded in
   [FINDINGS.md](FINDINGS.md).

## The discipline

- **Scenarios are designed to make UAP fail, not to demonstrate that it works.**
  A walk that never strains was designed wrong. (One deliberate exception: the
  editor scenario is the calibration control — it walks the mechanics the
  reference implementation already exercises, so strain elsewhere is measured
  against something known to hold.)
- **Walking a scenario never changes the specification.** Strain lands in the
  findings register; a finding is promoted into a spec change only when several
  scenarios — or a scenario plus live host experience — make the same case.
  This is the safeguard against speculative standards architecture: primitives
  are earned, not invented.
- **The recurring test question:** every time a walk forces application-specific
  logic into the *host*, that is a warning; every time the provider can solve it
  inside its own domain namespace, the abstraction is working.
- The invariant-coverage matrix lives in [pressure-tests.md](pressure-tests.md)
  and is what keeps the scenario set honest: new scenarios are chosen for the
  columns nothing yet exercises, never for a domain's marketing value.

## The set

| Scenario | Domain | Designed to break |
|---|---|---|
| [thunderbird-draft-send.md](thunderbird-draft-send.md) | Email client | draft vs external send; concurrent human edit of the draft |
| [browser-page-boundary.md](browser-page-boundary.md) | Browser | ownership and trust boundary between browser and page; assurance leakage |
| [home-assistant-physical-truth.md](home-assistant-physical-truth.md) | Smart home | accepted → reported device state → unknowable physical outcome |
| [automotive-preconditions.md](automotive-preconditions.md) | Vehicle (simulated) | stable capability vs changing runtime preconditions; safety aborts |
| [vscode-stale-vs-conflict.md](vscode-stale-vs-conflict.md) | Editor | stale reference vs changed revision (calibration control) |
| [long-running-cancellation.md](long-running-cancellation.md) | Live media / execution | accepted → long-running → cancellation → completion after the turn ends |
| [cross-provider-artifact.md](cross-provider-artifact.md) | Multiple applications | an artifact crossing provider boundaries |

Contributions are welcome — the most useful is a **counterexample**: a concrete
sequence a walk here calls "expressible cleanly" that in fact is not, or a new
scenario that strains a column the matrix shows untouched. See
[CONTRIBUTING](../CONTRIBUTING.md).
