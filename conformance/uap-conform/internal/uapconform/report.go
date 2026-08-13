package uapconform

// VectorResult matches the reference suite's VectorResult.to_dict() key for key, so a
// report is diffable across runners.
type VectorResult struct {
	ID      string `json:"id"`
	Passed  bool   `json:"passed"`
	Skipped bool   `json:"skipped"`
	Detail  string `json:"detail"`
}

// Report matches ConformanceReport.to_dict(): provider, passed, results.
type Report struct {
	Provider string         `json:"provider"`
	Passed   bool           `json:"passed"`
	Results  []VectorResult `json:"results"`
}

// Failures returns what failed — skipped vectors never fail a run, but are reported.
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

func (r *Report) finalize() {
	r.Passed = len(r.Failures()) == 0
}

func pass(id string) VectorResult         { return VectorResult{ID: id, Passed: true} }
func fail(id, detail string) VectorResult { return VectorResult{ID: id, Passed: false, Detail: detail} }
func skip(id, detail string) VectorResult {
	return VectorResult{ID: id, Passed: true, Skipped: true, Detail: detail}
}
