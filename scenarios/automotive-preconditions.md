# Scenario: the trunk, the motorway, and the charge limit

**Domain:** vehicle (simulated provider; VSS-flavoured vocabulary, no OEM API)
**Status:** paper walk against `1.0-draft`. A simulated provider is the
intended first implementation — a protocol stress test needing no hardware.
**Verdict:** expressible cleanly on the walk's core; adds the second domain's
evidence to the cross-turn lifecycle finding (F-001).

## Why this scenario is designed to break UAP

A car is the strictest examiner of the discovery/precondition boundary:
capabilities are decided by trim level and OEM policy (stable), while
permission to act changes with speed, gear, and charging state (transient, and
safety-loaded). It also tests whether "Universal" survives contact with a
physical domain — if the walk needs `automotive_effect`, `motion_control`, or
any vehicle-specific core vocabulary, the universality claim fails exactly
where it was advertised to hold.

## The walk

1. **Discovery, once, at bind.** The manifest lists what this vehicle, account,
   and OEM policy allow *at all*: climate, media, navigation, charging state
   and limits, cabin (trunk, windows), interior lights. Deliberately absent —
   not present-and-refused, absent: steering, braking, gear, immobilizer. The
   provider decides its exposed surface; UAP never learns why something is
   missing, and conformance demands semantic parity, never capability parity.
2. **`cabin.trunk.open` at 120 km/h.** The action is *in* the manifest — "the
   car is moving" is the textbook transient fact — and the invocation fails
   **`precondition_failed`** with the typed reason. The manifest did not
   flicker; the model learns "not while driving", a sentence worth speaking,
   instead of the capability inexplicably vanishing. (This step is the fixed
   discovery rule exercising its own example.)
3. **Stop at a red light; retry.** Same call, new `command_id`, succeeds:
   `device` effect, observable, verified against reported trunk state. Same
   binding throughout — no rebind dance as state changed.
4. **`charging.set_limit` to 80%.** `persist` effect (a setting, not motion),
   reversibility `operation_undo` (restore prior limit), verified by reading
   the limit back. Host policy derives minimal friction: a reversible,
   verifiable setting on a bound account does not deserve confirmation
   theater. Contrast **`cabin.doors.unlock`**: also `device`, but the host's
   consent derivation weighs its declared scope and irreversibility-in-effect
   (an unlocked door in the world cannot be un-exposed) differently. The
   walk's test is that *host policy plus declarations* separates these two
   `device` actions without an `if action == unlock` branch — the effect
   model's adequacy question, kept under observation rather than pre-answered
   with new enums.
5. **Preconditioning: "warm the car for 7:30."** `climate.precondition`
   accepted; the compressor runs for twenty minutes. The session that asked
   is long gone when it finishes. The provider can emit state events, but the
   draft's event envelope has no command identity, progress, or terminal
   result — the *command's* ending is unreportable across turns. **Finding
   F-001, second unrelated domain** (with live-media/execution), which is
   what promotes it.
6. **Safety abort mid-action.** Trunk opening; the car starts rolling. The
   provider aborts by its own safety rule and the action fails with a typed
   error and a declared post-state (trunk relatched). The host never asked
   the provider to be unsafe, and the provider never asked the host for
   permission to be safe — the authority split working as designed. A
   *host*-initiated cancel races the same physics honestly: `stopped` only
   if provably never begun, else `too_late`.
7. **The passenger.** A second occupant closes the trunk by hand mid-walk.
   User precedence: real input wins, the provider reports reality, the
   host's next observation sees a closed trunk and says so. No locking, no
   fight.

## Where it strains

- Step 5 is the only wall, and it is the *same* wall the execution domain
  hits — strong evidence it is a universal lifecycle primitive, not a
  vehicle feature.
- Step 4 deliberately produces **evidence, not vocabulary**: if a simulated
  provider plus generic host policy cannot keep volume-down and door-unlock
  apart without provider-specific branches, *that* concrete failure — not
  intuition — justifies an extra policy signal. The walk found the
  declarations sufficient on paper; the simulated implementation is where
  the claim gets falsified.
- VSS is used as naming inspiration for the domain namespace
  (`vehicle.cabin.*`, `charging.*`) and nothing more; coupling the core to
  any vehicle vocabulary would fail the driver/vehicle admission test by
  definition.

## Verdict

**Expressible cleanly, one promoted finding.** The stable-capability /
transient-precondition boundary, the safety abort, occupant precedence, and
consent separation all hold with existing machinery and zero automotive core
vocabulary — which is precisely the "Universal" evidence this scenario was
built to demand. F-001 gains its second unrelated domain and is promoted to
the pre-1.0 wire-binding milestone.
