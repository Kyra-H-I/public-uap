package uapconform

import "fmt"

// Lenient typed views over wire envelopes. Parsing mirrors the host's fail-closed
// rules for SEMANTIC fields (an unknown status is failed, an unknown code is internal,
// an unknown effect kind is external) and preserves RAW structure where a vector grades
// it (object counts, omitted, reference well-formedness) — see the package comment for
// why the two are treated differently.

type manifest struct {
	Provider     string
	Application  string
	UAP          string
	Capabilities []capability
	Features     features
}

type capability struct {
	ID      string
	Actions []string
}

type features struct {
	Events       bool
	Preview      bool
	Transactions bool
	Cancellation bool
}

type effect struct {
	Kind          string
	Reversibility string
}

type descriptor struct {
	Name         string
	Verification string
	Effects      []effect
	// Target is the required reference lifetime, or "" for a targetless action.
	Target string
}

type reference struct {
	Kind     string
	ID       string
	Lifetime string
	Basis    string
}

// wellFormed reports whether this reference could exist in-process at all: a known
// lifetime, an identity, and a basis wherever the lifetime demands one.
func (r reference) wellFormed() string {
	if r.Kind == "" || r.ID == "" {
		return "missing kind or id"
	}
	if !knownLifetimes[r.Lifetime] {
		return fmt.Sprintf("unknown lifetime %q", r.Lifetime)
	}
	if r.Lifetime != LifetimePersistent && r.Basis == "" {
		return fmt.Sprintf("%s reference with no basis", r.Lifetime)
	}
	return ""
}

// checkAgainst mirrors the host's check_reference: persistent is always current;
// everything else must match the epoch it was minted against, and a scope that does
// not currently exist invalidates every reference scoped to it.
func (r reference) checkAgainst(epochs map[string]string) string {
	if r.Lifetime == LifetimePersistent {
		return ""
	}
	current, ok := epochs[r.Lifetime]
	if !ok {
		return CodeStaleReference
	}
	if current != r.Basis {
		return CodeStaleReference
	}
	return ""
}

func (r reference) toMap() map[string]any {
	m := map[string]any{"kind": r.Kind, "id": r.ID, "lifetime": r.Lifetime}
	if r.Basis != "" {
		m["basis"] = r.Basis
	}
	return m
}

type observedObject struct {
	Ref     reference
	RefErr  string // non-empty when the reference is not even well-formed
	Actions []string
}

type observation struct {
	Epochs  map[string]string
	Objects []observedObject
	// RawObjectCount is the length of the objects list as sent, before any parsing —
	// what observe.bounded grades. A host would truncate; a grader must not.
	RawObjectCount int
	Omitted        int
}

type actionResult struct {
	CommandID string
	Status    string
	HasError  bool
	ErrorCode string
}

// changedNothing mirrors ActionResult.changed_nothing: only a rejection or a preview
// guarantees the world is untouched.
func (r actionResult) changedNothing() bool {
	return r.Status == StatusRejected || r.Status == StatusPreviewed
}

type cancelOutcome struct {
	State string
}

// -- parsing -----------------------------------------------------------------

func asString(v any) string {
	s, _ := v.(string)
	return s
}

func asBool(v any) bool {
	b, _ := v.(bool)
	return b
}

func asMap(v any) map[string]any {
	m, _ := v.(map[string]any)
	return m
}

func asList(v any) []any {
	l, _ := v.([]any)
	return l
}

func asStrings(v any) []string {
	raw := asList(v)
	out := make([]string, 0, len(raw))
	for _, item := range raw {
		if s, ok := item.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

func parseManifest(d map[string]any) manifest {
	m := manifest{
		Provider:    asString(d["provider"]),
		Application: asString(d["application"]),
		UAP:         asString(d["uap"]),
	}
	f := asMap(d["features"])
	m.Features = features{
		Events:       asBool(f["events"]),
		Preview:      asBool(f["preview"]),
		Transactions: asBool(f["transactions"]),
		Cancellation: asBool(f["cancellation"]),
	}
	for _, raw := range asList(d["capabilities"]) {
		c := asMap(raw)
		if c == nil {
			continue
		}
		m.Capabilities = append(m.Capabilities, capability{
			ID:      asString(c["id"]),
			Actions: asStrings(c["actions"]),
		})
	}
	return m
}

func parseEffect(d map[string]any) effect {
	e := effect{Kind: asString(d["kind"]), Reversibility: asString(d["reversibility"])}
	// Fail closed, exactly as the host does: a garbled declaration gets the strictest
	// treatment, never the most permissive.
	if !knownKinds[e.Kind] {
		e.Kind = KindExternal
	}
	if !knownReversibility[e.Reversibility] {
		e.Reversibility = ReversibilityNone
	}
	return e
}

// parseDescriptor returns the descriptor and whether it was usable at all. A descriptor
// with no name, or a target naming an unknown lifetime, is dropped — the host would
// refuse to construct it, and the gap then surfaces as `undescribed` in
// capability.describes rather than vanishing.
func parseDescriptor(d map[string]any) (descriptor, bool) {
	out := descriptor{
		Name:         asString(d["name"]),
		Verification: asString(d["verification"]),
		Target:       asString(d["target"]),
	}
	if out.Name == "" {
		return out, false
	}
	if out.Target != "" && !knownLifetimes[out.Target] {
		return out, false
	}
	for _, raw := range asList(d["effects"]) {
		if e := asMap(raw); e != nil {
			out.Effects = append(out.Effects, parseEffect(e))
		}
	}
	return out, true
}

func parseReference(d map[string]any) reference {
	return reference{
		Kind:     asString(d["kind"]),
		ID:       asString(d["id"]),
		Lifetime: asString(d["lifetime"]),
		Basis:    asString(d["basis"]),
	}
}

func parseObservation(d map[string]any) observation {
	obs := observation{Epochs: map[string]string{}}
	for key, value := range asMap(d["epochs"]) {
		if s, ok := value.(string); ok {
			obs.Epochs[key] = s
		}
	}
	if omitted, ok := d["omitted"].(float64); ok {
		obs.Omitted = int(omitted)
	}
	rawObjects := asList(d["objects"])
	obs.RawObjectCount = len(rawObjects)
	for _, raw := range rawObjects {
		o := asMap(raw)
		if o == nil {
			obs.Objects = append(obs.Objects, observedObject{RefErr: "object is not a JSON object"})
			continue
		}
		ref := parseReference(asMap(o["ref"]))
		obs.Objects = append(obs.Objects, observedObject{
			Ref:     ref,
			RefErr:  ref.wellFormed(),
			Actions: asStrings(o["actions"]),
		})
	}
	return obs
}

func parseActionResult(d map[string]any) actionResult {
	r := actionResult{CommandID: asString(d["command_id"]), Status: asString(d["status"])}
	// An unknown status becomes failed, not completed: the runner must never credit
	// success because a provider sent a word the protocol does not have.
	if !knownStatuses[r.Status] {
		r.Status = StatusFailed
	}
	if e := asMap(d["error"]); e != nil {
		r.HasError = true
		r.ErrorCode = asString(e["code"])
		if !knownCodes[r.ErrorCode] {
			r.ErrorCode = CodeInternal
		}
	}
	return r
}

func parseCancelOutcome(d map[string]any) cancelOutcome {
	out := cancelOutcome{State: asString(d["state"])}
	if !knownCancelStates[out.State] {
		out.State = CancelTooLate
	}
	return out
}
