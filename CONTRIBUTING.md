# Contributing

Thanks for looking under the hood. This repository is the published face of a
protocol that is developed against a live reference implementation, and that
shapes what kinds of contribution work well right now.

## The one rule that prevents wasted work

**Every file here is generated or exported.** `schema/`, `vectors/`,
`conformance/` (including the `uap-conform` Go runner), `examples/`, `skill/`,
`spec/`, `README.md`, and this file are all produced or copied from the reference
implementation behind cross-language parity gates. A direct PR against any of them
cannot be merged as-is — the next export would erase it.

So for **anything in this repository**, please **open an issue** rather than a pull
request. Accepted changes land in the reference implementation first and flow back
out through the gates, which is what keeps every copy of the vocabulary provably in
sync. This is a real constraint of publishing a generated tree, not a lack of
interest — an issue with a concrete diff in it is as useful to us as the PR would
have been, and it will not be silently overwritten.

## The most valuable contributions

1. **Implement something and report back.** Build a provider or adapter from
   `spec/` + `skill/uap-provider/`, run it through the conformance suite (or
   the `uap-conform` wire runner), and file what was ambiguous, missing, or
   wrong. Independent implementations are how a draft earns the removal of its
   label — gaps you hit are protocol findings, and they are the contribution we
   want most.
2. **Break the honesty model.** Find a place where a provider could claim an
   undo it doesn't bind, dodge a confirmation class, report success without
   evidence, or where the conformance suite fails to catch any of those.
3. **Sharpen the spec.** Ambiguity reports with a concrete misreading beat
   style notes.

## Ground rules

- **Licensing (inbound = outbound):** contributions to specification documents
  are accepted under CC-BY-4.0; everything else under Apache-2.0, including its
  patent grant.
- **Security:** anything that looks like a vulnerability in the protocol
  design, the suite, or the runner — use GitHub's private vulnerability
  reporting on this repository rather than a public issue.
- **Conduct:** be the kind of reviewer you'd want on your own draft. Argue
  about the protocol, not the person.
- **Conformance is never pay-to-pass**, and no contribution changes that.
