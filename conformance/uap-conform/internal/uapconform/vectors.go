package uapconform

import (
	"fmt"
	"sort"
	"strings"
)

// ctx is what every vector gets: the peer plus the state already fetched from it —
// the same shape as the reference suite's _Ctx.
type ctx struct {
	peer        Peer
	manifest    manifest
	observation observation
	descriptors map[string]descriptor
	// order preserves first-seen descriptor order for probe selection, which the
	// reference gets for free from Python's ordered dicts.
	order []string
}

// RunCore runs every core vector, in the reference suite's order, and never mutates:
// reads and refusals only. A transport failure on describe or observe aborts the run —
// a provider that cannot answer those is not gradable — while a failure fetching
// descriptors is a finding (capability.describes), not a crash.
func RunCore(peer Peer) (*Report, error) {
	describeReply, err := peer.Call(TypeDescribe, map[string]any{})
	if err != nil {
		return nil, fmt.Errorf("describe: %w", err)
	}
	m := parseManifest(describeReply)
	report := &Report{Provider: m.Provider}

	descriptors := map[string]descriptor{}
	var order []string
	describeError := ""
	for _, cap := range m.Capabilities {
		reply, err := peer.Call(TypeCapability, map[string]any{"capability": cap.ID})
		if err != nil {
			describeError = fmt.Sprintf("%s: %v", cap.ID, err)
			break
		}
		for _, raw := range asList(reply["actions"]) {
			d := asMap(raw)
			if d == nil {
				continue
			}
			// A malformed descriptor is dropped, exactly as the host drops one it
			// cannot construct; the gap then surfaces as `undescribed` below.
			parsed, ok := parseDescriptor(d)
			if !ok {
				continue
			}
			if _, seen := descriptors[parsed.Name]; !seen {
				order = append(order, parsed.Name)
			}
			descriptors[parsed.Name] = parsed
		}
	}

	observeReply, err := peer.Call(TypeObserve, map[string]any{
		"scopes": []string{ScopeView, ScopeFocus, ScopeDocument, ScopeObjects},
		"limit":  MaxObservedObjects,
	})
	if err != nil {
		return nil, fmt.Errorf("observe: %w", err)
	}

	c := &ctx{
		peer:        peer,
		manifest:    m,
		observation: parseObservation(observeReply),
		descriptors: descriptors,
		order:       order,
	}

	if describeError != "" {
		report.Results = append(report.Results,
			fail("capability.describes", "describe_capability raised "+describeError))
	} else {
		report.Results = append(report.Results, vectorCapabilityDescribes(c))
	}

	report.Results = append(report.Results,
		vectorManifestWellformed(c),
		vectorEffectsDeclared(c),
		vectorUndoClaimsBacked(c),
		vectorPreviewDeclared(c),
		vectorObservationBounded(c),
		vectorObservationReferencesValid(c),
		vectorAddressableState(c),
	)

	for _, vector := range []func(*ctx) (VectorResult, error){
		vectorUnknownActionRefused,
		vectorCommandIDEchoed,
		vectorReplayIsNotASecondExecution,
		vectorCancelIsAnsweredHonestly,
		vectorDryRunNeverExecutes,
		vectorStaleReferenceFailsClosed,
	} {
		result, err := vector(c)
		if err != nil {
			return nil, err
		}
		report.Results = append(report.Results, result)
	}

	report.finalize()
	return report, nil
}

// -- discovery ----------------------------------------------------------------

func vectorManifestWellformed(c *ctx) VectorResult {
	m := c.manifest
	if !strings.HasPrefix(m.UAP, "1.") {
		return fail("manifest.version",
			fmt.Sprintf("declares %q, host implements %s", m.UAP, Version))
	}
	if m.Provider == "" || m.Application == "" {
		return fail("manifest.version", "provider/application id missing")
	}
	if len(m.Capabilities) > MaxCapabilities {
		return fail("manifest.version", "too many capabilities")
	}
	return pass("manifest.version")
}

func vectorCapabilityDescribes(c *ctx) VectorResult {
	advertised := map[string]bool{}
	for _, cap := range c.manifest.Capabilities {
		for _, action := range cap.Actions {
			advertised[action] = true
		}
	}
	var missing, extra []string
	for action := range advertised {
		if _, ok := c.descriptors[action]; !ok {
			missing = append(missing, action)
		}
	}
	for name := range c.descriptors {
		if !advertised[name] {
			extra = append(extra, name)
		}
	}
	if len(missing) > 0 {
		sort.Strings(missing)
		return fail("capability.describes", "undescribed: "+strings.Join(firstFive(missing), ", "))
	}
	if len(extra) > 0 {
		sort.Strings(extra)
		return fail("capability.describes", "undiscoverable: "+strings.Join(firstFive(extra), ", "))
	}
	for _, cap := range c.manifest.Capabilities {
		if len(cap.Actions) > MaxActionsPerCapability {
			return fail("capability.describes", cap.ID+" exceeds action cap")
		}
	}
	return pass("capability.describes")
}

func vectorEffectsDeclared(c *ctx) VectorResult {
	var silent []string
	for name, d := range c.descriptors {
		if len(d.Effects) == 0 {
			silent = append(silent, name)
		}
	}
	if len(silent) > 0 {
		sort.Strings(silent)
		return fail("action.effects", "no declared effects: "+strings.Join(firstFive(silent), ", "))
	}
	return pass("action.effects")
}

func vectorUndoClaimsBacked(c *ctx) VectorResult {
	var unfounded []string
	for name, d := range c.descriptors {
		claims := false
		for _, e := range d.Effects {
			if e.Reversibility == ReversibilityOperationUndo {
				claims = true
			}
		}
		if claims && d.Verification == "" {
			unfounded = append(unfounded, name)
		}
	}
	if len(unfounded) > 0 {
		sort.Strings(unfounded)
		return fail("action.undo_claim",
			"undo claimed without verification: "+strings.Join(firstFive(unfounded), ", "))
	}
	return pass("action.undo_claim")
}

func vectorPreviewDeclared(c *ctx) VectorResult {
	if c.manifest.Features.Preview {
		return pass("action.preview")
	}
	return skip("action.preview", "preview not offered")
}

// -- observation ----------------------------------------------------------------

func vectorObservationBounded(c *ctx) VectorResult {
	// Graded on the RAW count. The host's parser would truncate an over-sent snapshot
	// in self-defence; a grader crediting that defence would let the violation hide.
	if c.observation.RawObjectCount > MaxObservedObjects {
		return fail("observe.bounded",
			fmt.Sprintf("%d objects over cap", c.observation.RawObjectCount))
	}
	if c.observation.Omitted < 0 {
		return fail("observe.bounded", "negative omitted count")
	}
	return pass("observe.bounded")
}

func vectorObservationReferencesValid(c *ctx) VectorResult {
	epochs := c.observation.Epochs
	for _, obj := range c.observation.Objects {
		// Wire-only failure mode: an in-process provider cannot construct a malformed
		// reference, so on the wire one fails here rather than being dropped.
		if obj.RefErr != "" {
			return fail("observe.references",
				fmt.Sprintf("%s/%s: %s", obj.Ref.Kind, obj.Ref.ID, obj.RefErr))
		}
		if code := obj.Ref.checkAgainst(epochs); code != "" {
			return fail("observe.references",
				fmt.Sprintf("%s/%s: %s", obj.Ref.Kind, obj.Ref.ID, code))
		}
	}
	return pass("observe.references")
}

func vectorAddressableState(c *ctx) VectorResult {
	wanted := map[string]bool{}
	for _, d := range c.descriptors {
		if d.Target != "" {
			wanted[d.Target] = true
		}
	}
	if len(wanted) == 0 {
		return skip("observe.addressable", "no targeted actions")
	}
	if len(c.observation.Objects) == 0 {
		return skip("observe.addressable", "nothing addressable in the current view")
	}

	// Graded per TARGET CLASS, matching the reference suite. Asking only whether SOMETHING was
	// addressable is how an editor shipped two actions declaring `target: "focus"` against a
	// provider publishing only document- and session-lifetime references: the host refused every
	// call and this vector passed throughout. Go awarded A where Python withheld it, which is the
	// divergence that matters most — the two runners are supposed to be interchangeable.
	reachable := map[string]bool{}
	for _, o := range c.observation.Objects {
		reachable[o.Ref.Lifetime] = true
	}
	for lifetime := range wanted {
		if basis, ok := c.observation.Epochs[lifetime]; ok && basis != "" {
			reachable[lifetime] = true
		}
	}
	var unreachable []string
	for lifetime := range wanted {
		if !reachable[lifetime] {
			unreachable = append(unreachable, lifetime)
		}
	}
	if len(unreachable) > 0 {
		sort.Strings(unreachable)
		return skip("observe.addressable", fmt.Sprintf(
			"declares actions targeting %s but published no reference or basis of that lifetime, "+
				"so the host can never address them", strings.Join(unreachable, ", ")))
	}
	return pass("observe.addressable")
}

// -- refusal paths ----------------------------------------------------------------

func (c *ctx) invoke(body map[string]any) (actionResult, error) {
	reply, err := c.peer.Call(TypeInvoke, body)
	if err != nil {
		return actionResult{}, err
	}
	return parseActionResult(reply), nil
}

func probeCall(commandID string) map[string]any {
	return map[string]any{
		"action":     ProbeAction,
		"command_id": commandID,
		"arguments":  map[string]any{},
		"dry_run":    false,
	}
}

func vectorUnknownActionRefused(c *ctx) (VectorResult, error) {
	result, err := c.invoke(probeCall(newID()))
	if err != nil {
		return VectorResult{}, err
	}
	if result.Status != StatusRejected {
		return fail("invoke.unknown",
			fmt.Sprintf("returned %s, not rejected", result.Status)), nil
	}
	if !result.HasError {
		return fail("invoke.unknown", "rejected with no error code"), nil
	}
	return pass("invoke.unknown"), nil
}

func vectorCommandIDEchoed(c *ctx) (VectorResult, error) {
	commandID := newID()
	result, err := c.invoke(probeCall(commandID))
	if err != nil {
		return VectorResult{}, err
	}
	if result.CommandID != commandID {
		return fail("invoke.command_id", fmt.Sprintf("echoed %q", result.CommandID)), nil
	}
	return pass("invoke.command_id"), nil
}

func vectorReplayIsNotASecondExecution(c *ctx) (VectorResult, error) {
	commandID := newID()
	first, err := c.invoke(probeCall(commandID))
	if err != nil {
		return VectorResult{}, err
	}
	second, err := c.invoke(probeCall(commandID))
	if err != nil {
		return VectorResult{}, err
	}
	if first.Status != second.Status || first.CommandID != second.CommandID {
		return fail("invoke.replay",
			fmt.Sprintf("same command_id gave %s then %s", first.Status, second.Status)), nil
	}
	return pass("invoke.replay"), nil
}

func vectorCancelIsAnsweredHonestly(c *ctx) (VectorResult, error) {
	reply, err := c.peer.Call(TypeCancel, map[string]any{"command_id": "never-invoked-" + newID()})
	if err != nil {
		return VectorResult{}, err
	}
	outcome := parseCancelOutcome(reply)
	if c.manifest.Features.Cancellation {
		if outcome.State != CancelStopped {
			return fail("cancel.honest", fmt.Sprintf(
				"declares cancellation but returned %s for unstarted work", outcome.State)), nil
		}
	} else if outcome.State != CancelUnsupported {
		return fail("cancel.honest", fmt.Sprintf(
			"does not declare cancellation but answered %s", outcome.State)), nil
	}
	return pass("cancel.honest"), nil
}

func vectorDryRunNeverExecutes(c *ctx) (VectorResult, error) {
	action := c.readOnlyActionFor(c.order)
	if action == "" {
		return skip("invoke.dry_run", "no side-effect-free action to probe with"), nil
	}
	body := map[string]any{
		"action":     action,
		"command_id": newID(),
		"arguments":  map[string]any{},
		"dry_run":    true,
	}
	if ref := c.firstScopedRef(); ref != nil {
		body["ref"] = ref.toMap()
	}
	result, err := c.invoke(body)
	if err != nil {
		return VectorResult{}, err
	}
	if result.Status == StatusCompleted {
		return fail("invoke.dry_run", "a dry run reported COMPLETED"), nil
	}
	if c.manifest.Features.Preview && result.Status != StatusPreviewed {
		return fail("invoke.dry_run",
			fmt.Sprintf("preview declared but a dry run returned %s", result.Status)), nil
	}
	return pass("invoke.dry_run"), nil
}

func vectorStaleReferenceFailsClosed(c *ctx) (VectorResult, error) {
	var target *observedObject
	for i := range c.observation.Objects {
		obj := &c.observation.Objects[i]
		if obj.RefErr == "" && obj.Ref.Lifetime != LifetimePersistent && obj.Ref.Basis != "" {
			target = obj
			break
		}
	}
	if target == nil {
		return skip("invoke.stale_reference", "no scoped references"), nil
	}

	action, dryRun := c.probeActionFor(target.Actions)
	if action == "" {
		return fail("invoke.stale_reference",
			"no action on an addressable object could be probed safely — a provider whose "+
				"staleness handling cannot be checked has not demonstrated it"), nil
	}

	staleRef := target.Ref
	staleRef.Basis = staleRef.Basis + "~stale"
	result, err := c.invoke(map[string]any{
		"action":     action,
		"command_id": newID(),
		"arguments":  map[string]any{},
		"dry_run":    dryRun,
		"ref":        staleRef.toMap(),
	})
	if err != nil {
		return VectorResult{}, err
	}
	if !result.changedNothing() {
		return fail("invoke.stale_reference",
			fmt.Sprintf("stale reference returned %s", result.Status)), nil
	}
	if !result.HasError || !reobservable[result.ErrorCode] {
		code := "none"
		if result.HasError {
			code = result.ErrorCode
		}
		return fail("invoke.stale_reference",
			fmt.Sprintf("rejected as %s, not stale_reference", code)), nil
	}
	return pass("invoke.stale_reference"), nil
}

// -- probe selection ----------------------------------------------------------------

// readOnlyActionFor picks an action that provably changes nothing, or "". Mirrors the
// reference: the action must be targeted, and every declared effect must be a read.
func (c *ctx) readOnlyActionFor(available []string) string {
	for _, name := range available {
		d, ok := c.descriptors[name]
		if !ok || d.Target == "" {
			continue
		}
		allRead := true
		for _, e := range d.Effects {
			if e.Kind != KindRead {
				allRead = false
			}
		}
		if allRead {
			return name
		}
	}
	return ""
}

// probeActionFor returns an action safe to probe staleness with, and whether it needs
// dry_run. A pure read is ideal; failing that, a mutating targeted action sent as a
// dry run — the provider must refuse it either way, and invoke.dry_run separately
// proves a dry run never completes. Giving up would silently excuse the suite's most
// important check, which is worse than no gate.
func (c *ctx) probeActionFor(available []string) (string, bool) {
	if readOnly := c.readOnlyActionFor(available); readOnly != "" {
		return readOnly, false
	}
	for _, name := range available {
		if d, ok := c.descriptors[name]; ok && d.Target != "" {
			return name, true
		}
	}
	return "", false
}

func (c *ctx) firstScopedRef() *reference {
	for i := range c.observation.Objects {
		obj := &c.observation.Objects[i]
		if obj.RefErr == "" && obj.Ref.Lifetime != LifetimePersistent && obj.Ref.Basis != "" {
			return &obj.Ref
		}
	}
	return nil
}

func firstFive(items []string) []string {
	if len(items) > 5 {
		return items[:5]
	}
	return items
}
