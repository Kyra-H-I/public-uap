package uapconform

import "testing"

// A provider whose only targeted action MUTATES and reaches outside.
//
// This runner used to fall back to invoking exactly that, with dry_run=true, to probe
// staleness — the fallback the reference suite removed after a reviewer watched it invoke
// mail.send. The cross-runner test could not see the drift, because the reference fake has a
// read-only action and never reaches the fallback. Hence a test that has no read-only action
// at all.
type mutatingOnlyProvider struct {
	fakeProvider
	invokedExternal bool
}

func (m *mutatingOnlyProvider) Call(reqType string, body map[string]any) (map[string]any, error) {
	if reqType == TypeCapability {
		return map[string]any{"actions": []any{
			map[string]any{
				"name": fakeSend, "summary": "Send the document to someone.",
				"effects":      []any{map[string]any{"kind": KindExternal}},
				"target":       LifetimeDocument,
				"verification": "the send receipt",
			},
		}}, nil
	}
	if reqType == TypeInvoke && asString(body["action"]) == fakeSend {
		m.invokedExternal = true
	}
	if reqType == TypeDescribe {
		d, _ := m.fakeProvider.Call(reqType, body)
		caps := asList(d["capabilities"])
		if len(caps) > 0 {
			asMap(caps[0])["actions"] = []any{fakeSend}
		}
		return d, nil
	}
	if reqType == TypeObserve {
		o, _ := m.fakeProvider.Call(reqType, body)
		for _, raw := range asList(o["objects"]) {
			asMap(raw)["actions"] = []any{fakeSend}
		}
		return o, nil
	}
	return m.fakeProvider.Call(reqType, body)
}

func TestGoRunnerNeverInvokesAMutatingActionToProbeStaleness(t *testing.T) {
	p := &mutatingOnlyProvider{}
	if _, err := RunCore(p); err != nil {
		t.Fatal(err)
	}
	if p.invokedExternal {
		t.Fatal("the Go runner invoked an EXTERNAL action to probe staleness — " +
			"the reference suite removed exactly this fallback")
	}
}
