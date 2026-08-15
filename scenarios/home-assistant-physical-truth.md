# Scenario: the relay is on; is the light?

**Domain:** smart home (Home Assistant-shaped hub in front of physical devices)
**Status:** paper walk against `1.0-draft`. No implementation claimed.
**Verdict:** expressible with declared honesty — one open finding on how far
`completed` evidence reaches (F-002).

## Why this scenario is designed to break UAP

Every layer between a command and physical reality can lie by omission. "Turn
off the bedroom light" traverses: hub accepted → hub entity state changed →
device acknowledged over the radio → the bulb actually went dark. A protocol
that lets `completed` mean any of those interchangeably teaches agents to
announce physical facts they never observed — the exact failure UAP exists to
kill, now wearing a smart-home costume. The walk asks: can a provider be
honest about *which* layer its evidence reaches, without the core growing a
physical-device ontology?

## The walk

1. **Observe.** Bounded snapshot of the relevant area: entities with
   references (`home.entity`, session lifetime — entity ids are durable),
   type, current state, omitted count. A hub fronting four hundred entities
   returns the bounded, scoped answer, not the estate dump.
2. **`entity.turn_off`** on the bedroom light. Effects: `device` with scope
   naming the entity; reversibility `operation_undo` only if the provider
   genuinely restores prior state (dimmer level, not just "on"), else `none`
   — a declaration the conformance suite's false-undo probes exist to keep
   honest. Terminality: `observable` — the hub *can* watch its own entity
   state converge.
3. **Acceptance, then convergence.** The hub answers `accepted` immediately
   (the radio round-trip is pending). Accepted is nonterminal for observable
   actions: the host holds the ending, watches provider events
   (`entity.state_changed`), re-observes on wake, and only then speaks. Two
   honest outcomes: the entity reports `off` → `completed` with that
   observation as evidence; or nothing converges within the wait → the host
   reports the observed current state, never success.
4. **What did `completed` just attest?** The hub's entity state — layer two
   of four. For most devices the hub state incorporates the device's own
   acknowledgement (layer three); for a dumb relay it does not reach the
   bulb (layer four) and never can. The spec's verification method is
   declared per action, and nothing *requires* the provider to claim more
   than its window — but nothing lets it *state its window* either. The
   result vocabulary has one `completed`; whether its evidence means
   "controller state" or "physically confirmed" lives, at best, in prose
   documentation. **Finding F-002**: evidence may need a declared
   attestation layer, so a host can speak "the hub shows it off" versus
   "confirmed dark" without per-provider knowledge.
5. **The broken bulb.** Relay off, filament already dead — provider truthfully
   reports `off`; the room was never lit. No protocol can fix this, and the
   walk's point is that UAP must not pretend to: the honest ceiling of this
   provider is hub state, and the finding above is about *declaring* that
   ceiling, not raising it.
6. **Device drops off the network.** The entity's capability does not vanish
   from the manifest (absence is for binding-stable facts only); invocation
   fails `unavailable`, observation reports the entity unreachable —
   transient truth in results, stable truth in discovery, exactly the
   boundary the discovery rules fix.
7. **"Turn everything off."** A scene/group action is one provider-side
   action with declared scope — not a host-side loop over forty entities.
   Partial success (three lights off, the garage relay timed out) wants
   **structured partial failure**, which the draft names but does not yet
   give a wire surface — noted as evidence toward the transactions gap, not
   a new finding.

## Where it strains

- Step 4 is the substance. Note what it is *not*: not a request for a
  `physical_verification` boolean, a device ontology, or safety classes —
  only for evidence to carry *what it attests*. Whether even that is core is
  deliberately left to accumulate: the long-running walk's streaming half
  and a future print-queue scenario hit the same wall from unrelated
  directions, and F-002 stays open until they agree.
- The volume-versus-door-unlock question — is `device` too coarse for
  consent? — is *not* answered here by adding vocabulary. The walk's test:
  a host with per-target sensitivity input (which the spec deliberately
  leaves as host policy) needs no `if provider == hub and entity == lock`
  branch. Automotive attacks the same question with real stakes; see that
  walk.

## Verdict

**Expressible, with one honest gap.** Accepted-versus-completed, event-driven
convergence, transient unavailability, and bounded observation of a large
estate all hold with existing machinery. The open question is narrow and
precise: `completed` cannot yet say how far its evidence reaches (F-002,
open — deliberately not promoted on one scenario's word).
