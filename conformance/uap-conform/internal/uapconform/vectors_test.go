package uapconform

import (
	"fmt"
	"testing"
)

// fakeProvider is the envelope-level twin of the reference implementation's FakeProvider — an
// honest provider, with one flag per flaw so each test breaks exactly one property.
type fakeProvider struct {
	advertiseGhost      bool // advertise an action that has no descriptor
	silentEffects       bool // fake.read declares no effects
	unfoundedUndo       bool // fake.save claims operation_undo with no verification
	badVersion          bool // manifest on a different protocol major
	overCap             bool // observation dumps more objects than the cap
	incoherentRefs      bool // references minted against a basis the epochs reject
	malformedRef        bool // a document reference with no basis at all (wire-only flaw)
	absorbUnknown       bool // unknown action returns completed
	lyingActionCount    bool // a DEFERRED capability declares a size its reply does not match
	unfoundedCheckpoint bool // fake.save claims checkpoint reversibility with no verification
	forgetCommandID     bool // results echo a different command id
	nondeterministic    bool // the same command id gives a different answer on replay
	cancelTooLate       bool // declares cancellation but answers too_late for unstarted work
	eagerDryRun         bool // executes a dry run
	proseRefusal        bool // answers a missing required argument with terminal prose

	calls map[string]int
}

const (
	fakeRead = "fake.read"
	fakeSave = "fake.save"
	fakeSend = "fake.send"
	fakeDial = "fake.dial"
	// Read-only AND carries a required argument, so invoke.required_arguments has a probe it
	// can safely omit one from. fake.dial would have been the tempting place for the
	// requirement — it already takes an argument and no reference — but its effect is
	// external, and the suite may not invoke that to find out whether it refuses.
	fakeFind = "fake.find"
)

func (f *fakeProvider) Call(reqType string, body map[string]any) (map[string]any, error) {
	switch reqType {
	case TypeDescribe:
		return f.describe(), nil
	case TypeCapability:
		return f.capability(), nil
	case TypeObserve:
		return f.observe(), nil
	case TypeInvoke:
		return f.invoke(body), nil
	case TypeCancel:
		return f.cancel(body), nil
	}
	return nil, fmt.Errorf("fake: unexpected %s", reqType)
}

func (f *fakeProvider) actions() []string {
	actions := []string{fakeRead, fakeSave, fakeSend, fakeDial, fakeFind}
	if f.advertiseGhost {
		actions = append(actions, "fake.ghost")
	}
	return actions
}

func (f *fakeProvider) describe() map[string]any {
	version := Version
	if f.badVersion {
		version = "2.0-draft"
	}
	return map[string]any{
		"provider":     "com.example.fake",
		"application":  "example.app",
		"uap":          version,
		"capabilities": []any{f.capabilityEntry()},
		"features":     map[string]any{"events": true, "cancellation": true},
	}
}

// capabilityEntry is the manifest's view of the one capability. A DEFERRED capability lists no
// actions and declares how many it has instead, which is the shape whose claim can be false.
func (f *fakeProvider) capabilityEntry() map[string]any {
	if f.lyingActionCount {
		return map[string]any{
			"id":           "fake.documents",
			"title":        "Documents",
			"action_count": 400, // the reply describes four
		}
	}
	return map[string]any{
		"id":      "fake.documents",
		"title":   "Documents",
		"actions": toAny(f.actions()),
	}
}

func (f *fakeProvider) capability() map[string]any {
	readEffects := []any{map[string]any{"kind": KindRead, "reversibility": ReversibilityNone}}
	if f.silentEffects {
		readEffects = []any{}
	}
	saveVerification := "re-read the revision"
	if f.unfoundedUndo {
		saveVerification = ""
	}
	// A checkpoint claim buys the same relief as an operation-bound undo, so an unverifiable one is
	// the same flaw wearing the other word.
	saveReversibility := ReversibilityOperationUndo
	if f.unfoundedCheckpoint {
		saveReversibility = ReversibilityCheckpoint
		saveVerification = ""
	}
	return map[string]any{"actions": []any{
		map[string]any{
			"name": fakeRead, "summary": "Read one document.",
			"effects": readEffects, "target": LifetimeDocument,
			"verification": "the document is returned",
		},
		map[string]any{
			"name": fakeSave, "summary": "Save the open document.",
			"effects": []any{map[string]any{
				"kind": KindPersist, "reversibility": saveReversibility,
			}},
			"target": LifetimeDocument, "verification": saveVerification,
		},
		map[string]any{
			"name": fakeSend, "summary": "Send the document to someone.",
			"effects": []any{map[string]any{"kind": KindExternal}},
			"target":  LifetimeDocument, "verification": "the send receipt",
		},
		map[string]any{
			"name": fakeDial, "summary": "Call a number.",
			"effects":      []any{map[string]any{"kind": KindExternal}},
			"verification": "the dialler reports it",
		},
		map[string]any{
			"name": fakeFind, "summary": "Find documents matching a query.",
			"effects":            []any{map[string]any{"kind": KindRead}},
			"arguments":          map[string]any{"query": "what to look for"},
			"required_arguments": []any{"query"},
			"verification":       "the matches are returned",
		},
	}}
}

func (f *fakeProvider) observe() map[string]any {
	basis := "rev-1"
	if f.incoherentRefs {
		basis = "rev-0"
	}
	if f.malformedRef {
		basis = ""
	}
	count := 2
	if f.overCap {
		count = MaxObservedObjects + 5
	}
	objects := make([]any, 0, count)
	for i := 0; i < count; i++ {
		ref := map[string]any{
			"kind": "fake.document", "id": fmt.Sprintf("doc-%d", i+1),
			"lifetime": LifetimeDocument,
		}
		if basis != "" {
			ref["basis"] = basis
		}
		objects = append(objects, map[string]any{
			"ref": ref, "type": "fake.document", "actions": toAny(f.actions()),
		})
	}
	return map[string]any{
		"provider": "com.example.fake",
		"epochs":   map[string]any{"document": "rev-1"},
		"objects":  objects,
		"omitted":  float64(0),
	}
}

func (f *fakeProvider) invoke(body map[string]any) map[string]any {
	commandID := asString(body["command_id"])
	if f.calls == nil {
		f.calls = map[string]int{}
	}
	f.calls[commandID]++
	echoed := commandID
	if f.forgetCommandID {
		echoed = "someone-else"
	}
	if f.nondeterministic && f.calls[commandID] > 1 {
		return result(echoed, StatusFailed, CodeInternal)
	}
	if asBool(body["dry_run"]) {
		if f.eagerDryRun {
			return result(echoed, StatusCompleted, "")
		}
		return result(echoed, StatusRejected, CodeUnsupported)
	}
	action := asString(body["action"])
	known := false
	for _, name := range f.actions() {
		if name == action {
			known = true
		}
	}
	if !known || action == "fake.ghost" {
		if f.absorbUnknown {
			return result(echoed, StatusCompleted, "")
		}
		return result(echoed, StatusRejected, CodeUnsupported)
	}
	if action == fakeFind {
		if _, ok := asMap(body["arguments"])["query"]; !ok {
			if f.proseRefusal {
				// Terminal domain validation, which is the wrong side of the taxonomy: the
				// host cannot repair what it is told is unfixable.
				return result(echoed, StatusRejected, CodeInvalidArgument)
			}
			out := result(echoed, StatusRejected, CodeInvalidCall)
			out["error"] = map[string]any{
				"code": CodeInvalidCall, "message": "query is required",
				"field_path": "/arguments/query",
				"expected":   map[string]any{"kind": ExpectedType, "type": "string"},
				"got":        "absent",
			}
			return out
		}
		return result(echoed, StatusCompleted, "")
	}
	if action != fakeDial && action != fakeFind { // every other action is targeted
		ref := asMap(body["ref"])
		if ref == nil {
			return result(echoed, StatusRejected, CodePreconditionFailed)
		}
		if asString(ref["basis"]) != "rev-1" {
			// Honest: a moved basis is refused, never resolved to what is current.
			return result(echoed, StatusRejected, CodeStaleReference)
		}
	}
	return result(echoed, StatusCompleted, "")
}

func (f *fakeProvider) cancel(body map[string]any) map[string]any {
	state := CancelStopped
	if f.cancelTooLate {
		state = CancelTooLate
	}
	return map[string]any{
		"command_id": asString(body["command_id"]), "state": state, "detail": "",
	}
}

func result(commandID, status, code string) map[string]any {
	out := map[string]any{"command_id": commandID, "status": status, "detail": ""}
	if code != "" {
		out["error"] = map[string]any{"code": code, "message": ""}
	}
	return out
}

func toAny(items []string) []any {
	out := make([]any, len(items))
	for i, s := range items {
		out[i] = s
	}
	return out
}

// -- the tests ---------------------------------------------------------------

var expectedOrder = []string{
	"capability.describes", "manifest.version", "action.effects", "action.undo_claim",
	"action.preview", "observe.bounded", "observe.references", "observe.addressable",
	"invoke.unknown", "invoke.command_id", "invoke.replay", "cancel.honest",
	"invoke.dry_run", "invoke.stale_reference", "invoke.required_arguments",
}

func TestProseInsteadOfAStructuredRefusalFails(t *testing.T) {
	// invalid_argument is TERMINAL and invalid_call is REPAIRABLE, so prose tells the host to
	// give up on the one failure it could have fixed by supplying what it left out.
	report, err := RunCore(&fakeProvider{proseRefusal: true})
	if err != nil {
		t.Fatal(err)
	}
	if report.Passed {
		t.Fatal("a prose refusal for a missing required argument passed")
	}
	found := false
	for _, r := range report.Failures() {
		if r.ID == "invoke.required_arguments" {
			found = true
		}
	}
	if !found {
		t.Fatalf("invoke.required_arguments did not fail: %+v", report.Failures())
	}
}

func TestHonestProviderPassesEveryVector(t *testing.T) {
	report, err := RunCore(&fakeProvider{})
	if err != nil {
		t.Fatal(err)
	}
	if !report.Passed {
		t.Fatalf("honest provider failed: %+v", report.Failures())
	}
	if report.Provider != "com.example.fake" {
		t.Fatalf("provider = %q", report.Provider)
	}
	if len(report.Results) != len(expectedOrder) {
		t.Fatalf("%d results, want %d", len(report.Results), len(expectedOrder))
	}
	for i, want := range expectedOrder {
		if report.Results[i].ID != want {
			t.Fatalf("result %d = %s, want %s (order must match the reference suite)",
				i, report.Results[i].ID, want)
		}
	}
	// The only capability the fake does not offer is preview.
	if skipped := report.Skipped(); len(skipped) != 1 || skipped[0].ID != "action.preview" {
		t.Fatalf("skipped = %+v, want exactly action.preview", skipped)
	}
}

func TestEachFlawFailsExactlyItsVector(t *testing.T) {
	cases := []struct {
		name   string
		mutate func(*fakeProvider)
		vector string
	}{
		{"ghost action", func(f *fakeProvider) { f.advertiseGhost = true }, "capability.describes"},
		// The host's grader has always checked a deferred capability's declared size; this one did
		// not, so a provider could pass here and fail there — and this is the grader the published
		// bundle hands to anyone wanting to grade their own provider.
		{"lying action_count", func(f *fakeProvider) { f.lyingActionCount = true }, "capability.describes"},
		{"unfounded checkpoint", func(f *fakeProvider) { f.unfoundedCheckpoint = true }, "action.undo_claim"},
		{"wrong protocol major", func(f *fakeProvider) { f.badVersion = true }, "manifest.version"},
		{"silent effects", func(f *fakeProvider) { f.silentEffects = true }, "action.effects"},
		{"unfounded undo", func(f *fakeProvider) { f.unfoundedUndo = true }, "action.undo_claim"},
		{"state dump", func(f *fakeProvider) { f.overCap = true }, "observe.bounded"},
		{"incoherent references", func(f *fakeProvider) { f.incoherentRefs = true }, "observe.references"},
		{"reference with no basis", func(f *fakeProvider) { f.malformedRef = true }, "observe.references"},
		{"absorbs unknown actions", func(f *fakeProvider) { f.absorbUnknown = true }, "invoke.unknown"},
		{"forgets the command id", func(f *fakeProvider) { f.forgetCommandID = true }, "invoke.command_id"},
		{"non-deterministic replay", func(f *fakeProvider) { f.nondeterministic = true }, "invoke.replay"},
		{"over-claims a cancel", func(f *fakeProvider) { f.cancelTooLate = true }, "cancel.honest"},
		{"executes a dry run", func(f *fakeProvider) { f.eagerDryRun = true }, "invoke.dry_run"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			fake := &fakeProvider{}
			tc.mutate(fake)
			report, err := RunCore(fake)
			if err != nil {
				t.Fatal(err)
			}
			found := false
			for _, res := range report.Results {
				if res.ID == tc.vector {
					found = true
					if res.Passed || res.Skipped {
						t.Fatalf("%s should have failed, got %+v", tc.vector, res)
					}
				}
			}
			if !found {
				t.Fatalf("vector %s missing from report", tc.vector)
			}
		})
	}
}

func TestStaleReferenceRetargetingIsTheOneThatMatters(t *testing.T) {
	// A provider that resolves "this document" to whatever is current: the honest
	// fake refuses a moved basis, so simulate the flaw by never refusing it.
	fake := &retargetingProvider{}
	report, err := RunCore(fake)
	if err != nil {
		t.Fatal(err)
	}
	for _, res := range report.Results {
		if res.ID == "invoke.stale_reference" {
			if res.Passed {
				t.Fatalf("retargeting provider passed the stale vector: %+v", res)
			}
			return
		}
	}
	t.Fatal("invoke.stale_reference missing from report")
}

// retargetingProvider wraps the honest fake but treats every reference as current.
type retargetingProvider struct{ fakeProvider }

func (r *retargetingProvider) Call(reqType string, body map[string]any) (map[string]any, error) {
	if reqType == TypeInvoke && !asBool(body["dry_run"]) {
		if ref := asMap(body["ref"]); ref != nil {
			ref["basis"] = "rev-1" // "the current one will do" — the exact forbidden move
		}
	}
	return r.fakeProvider.Call(reqType, body)
}

func TestWrongRefusalCodeFailsTheStaleVector(t *testing.T) {
	fake := &wrongCodeProvider{}
	report, err := RunCore(fake)
	if err != nil {
		t.Fatal(err)
	}
	for _, res := range report.Results {
		if res.ID == "invoke.stale_reference" {
			if res.Passed {
				t.Fatal("a non-reobservable refusal code must fail the stale vector")
			}
			if res.Detail != "a stale document reference was rejected as invalid_argument, not stale_reference" {
				t.Fatalf("detail = %q", res.Detail)
			}
			return
		}
	}
	t.Fatal("invoke.stale_reference missing from report")
}

// wrongCodeProvider refuses stale references — with a code the host cannot recover from.
type wrongCodeProvider struct{ fakeProvider }

func (w *wrongCodeProvider) Call(reqType string, body map[string]any) (map[string]any, error) {
	reply, err := w.fakeProvider.Call(reqType, body)
	if err != nil || reqType != TypeInvoke {
		return reply, err
	}
	if e := asMap(reply["error"]); e != nil && asString(e["code"]) == CodeStaleReference {
		e["code"] = CodeInvalidArgument
	}
	return reply, nil
}
