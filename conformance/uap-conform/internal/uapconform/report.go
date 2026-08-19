package uapconform

// conditionalVectors mirrors the reference suite's CONDITIONAL_VECTORS.
//
// Vectors whose skip is an honest absence rather than missing evidence: each probes an OPTIONAL
// declared feature, so a provider that does not implement preview or cancellation, or claims no
// undo, has nothing for them to grade. An exception list rather than an inclusion list, on
// purpose — a vector added later counts as core until someone argues otherwise, because the
// permissive default is exactly how a provider that could be probed by nothing at all came to be
// graded level A (verified semantic control).
var conditionalVectors = map[string]bool{
	"action.preview":    true,
	"action.undo_claim": true,
	"cancel.honest":     true,
	"invoke.dry_run":    true,
}

// VectorResult matches the reference suite's VectorResult.to_dict() key for key, so a
// report is diffable across runners.
type VectorResult struct {
	ID      string `json:"id"`
	Passed  bool   `json:"passed"`
	Skipped bool   `json:"skipped"`
	Outcome string `json:"outcome"`
	Detail  string `json:"detail"`
}

// Report matches ConformanceReport.to_dict(): provider, passed, complete, earns_control_ready,
// results.
type Report struct {
	Provider string `json:"provider"`
	Passed   bool   `json:"passed"`
	Complete bool   `json:"complete"`
	// EarnsControlReady is the field a host should read to award assurance A. `Passed` alone
	// counted only failures, so a provider nothing could probe collected an all-skipped run and
	// reported success — including a silent skip of invoke.stale_reference, the check this
	// package's own comments call the most important one in the suite.
	EarnsControlReady bool           `json:"earns_control_ready"`
	Results           []VectorResult `json:"results"`
}

// Failures returns what failed. A skipped vector does not fail a run — but it is not a pass
// either, and Unproven below is what keeps those apart.
func (r *Report) Failures() []VectorResult {
	var out []VectorResult
	for _, res := range r.Results {
		if !res.Passed && !res.Skipped {
			out = append(out, res)
		}
	}
	return out
}

// Skipped returns the capabilities the provider did not offer.
func (r *Report) Skipped() []VectorResult {
	var out []VectorResult
	for _, res := range r.Results {
		if res.Skipped {
			out = append(out, res)
		}
	}
	return out
}

// Unproven returns skipped vectors that examine core semantics rather than an optional feature —
// the ones whose absence means the run demonstrated nothing about the property being graded.
func (r *Report) Unproven() []VectorResult {
	var out []VectorResult
	for _, res := range r.Results {
		if res.Skipped && !conditionalVectors[res.ID] {
			out = append(out, res)
		}
	}
	return out
}

func (r *Report) finalize() {
	r.Passed = len(r.Failures()) == 0
	r.Complete = len(r.Skipped()) == 0
	r.EarnsControlReady = r.Passed && len(r.Unproven()) == 0
}

func pass(id string) VectorResult {
	return VectorResult{ID: id, Passed: true, Outcome: "passed"}
}

// passWithDetail is a pass that still has something to say — a vector whose obligation was
// conditional and had no instances. The detail is what stops a vacuous pass being read, or
// quoted, as evidence the thing was actually exercised.
func passWithDetail(id, detail string) VectorResult {
	return VectorResult{ID: id, Passed: true, Outcome: "passed", Detail: detail}
}

func fail(id, detail string) VectorResult {
	return VectorResult{ID: id, Passed: false, Outcome: "failed", Detail: detail}
}

// skip records that a vector graded NOTHING. `Passed` stays true so a legitimate absence does not
// fail a run, but `Outcome` says what actually happened: the serialised shape used to be
// `passed: true, skipped: true`, which every reader and every downstream consumer takes for a pass.
func skip(id, detail string) VectorResult {
	return VectorResult{ID: id, Passed: true, Skipped: true, Outcome: "skipped", Detail: detail}
}
