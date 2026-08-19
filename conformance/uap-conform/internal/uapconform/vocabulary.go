// Package uapconform is the wire-level UAP core conformance runner.
//
// It grades any provider that speaks the UAP envelope dialect — line-delimited JSON over
// stdio or a unix socket — against the same fifteen core vectors as the host's in-process
// suite (the reference Python implementation this package is a port of). The vector
// ids, the pass/skip/fail semantics, and the detail strings match the reference so that a
// report is comparable no matter which runner produced it; the reference
// implementation's integration test holds the two runners to identical verdicts.
//
// One deliberate difference: the wire adds failure modes an in-process provider cannot
// express, and this runner exists to catch them. Where the host's bridge layer would
// clamp or drop a malformed frame (over-cap snapshots truncated, unparseable references
// discarded), this runner FAILS the corresponding vector instead — a native provider
// physically cannot hand the suite 25 observed objects or a reference with no basis, so
// on the wire those are graded as the violations they are, not laundered by host-side
// defensiveness.
//
// This file is the runner's wire vocabulary, and it is a copy — the same closed sets
// exist in Python (the source of truth), two TypeScript clients, Dart, and the published
// schema. The reference implementation's parity gate reads this file as one more client and fails
// the build the moment any value here drifts. The bridge RELAY stays vocabulary-free on
// purpose (it forwards opaque frames); the grader cannot, because it judges semantics.
package uapconform

// Version is the protocol version this runner implements. A provider on a different
// major is not slightly wrong — it is speaking a different protocol ("1.0-draft").
const Version = "1.0-draft"

// Call bounds apply atomically: inputs are refused, never truncated. Argument chars count
// compact JSON; identifier chars count their string. Both use Unicode scalar values
// (utf8.RuneCountInString), not UTF-16 code units.
const (
	MaxArgumentChars       = 8000
	MaxArgumentKeys        = 20
	MaxArgumentDepth       = 16
	MaxActionChars         = 132
	MaxCommandIDChars      = 128
	MaxProviderChars       = 200
	MaxRevisionChars       = 128
	MaxReferenceKindChars  = 131
	MaxReferenceIDChars    = 256
	MaxReferenceBasisChars = 128
)

// Stdio and socket transports have no topic; it is part of the vocabulary so a provider
// built against this runner also lines up with topic-carrying transports.
// Message types. A request travels as {"type": <request type>, "id": <unique id>,
// ...body} and its reply echoes the same id; events arrive under TypeEvent with the
// semantic kind in the "event" field.
const (
	TypeDescribe         = "uap.describe_request"
	TypeCapability       = "uap.capability_request"
	TypeObserve          = "uap.observe_request"
	TypeInvoke           = "uap.invoke_request"
	TypeVerify           = "uap.verify_request"
	TypeCancel           = "uap.cancel_request"
	TypeDescribeResult   = "uap.describe_result"
	TypeCapabilityResult = "uap.capability_result"
	TypeObserveResult    = "uap.observe_result"
	TypeInvokeResult     = "uap.invoke_result"
	TypeVerifyResult     = "uap.verify_result"
	TypeCancelResult     = "uap.cancel_result"
	TypeEvent            = "uap.event"
)

// ProbeAction is the namespaced action no provider may implement. It exists to prove
// that an unknown action is refused rather than absorbed.
const ProbeAction = "uap.conformance_probe"

// ActionStatus values. Parsing fails closed: an unknown status is StatusFailed, never
// a success the provider did not earn.
const (
	StatusAccepted  = "accepted"
	StatusCompleted = "completed"
	StatusPreviewed = "previewed"
	StatusRejected  = "rejected"
	StatusFailed    = "failed"
	StatusCancelled = "cancelled"
)

// The closed set of UAP failure codes. Providers may not invent codes: parsing fails
// closed to CodeInternal, which is neither re-observable nor retryable — mirroring the
// host, so a client-only code cannot define new runner behaviour.
const (
	CodeStaleReference       = "stale_reference"
	CodeUnknownReference     = "unknown_reference"
	CodeUnsupported          = "unsupported"
	CodeAmbiguous            = "ambiguous"
	CodePreconditionFailed   = "precondition_failed"
	CodeInvalidCall          = "invalid_call"
	CodeInvalidArgument      = "invalid_argument"
	CodePermissionDenied     = "permission_denied"
	CodeConfirmationRequired = "confirmation_required"
	CodeConflict             = "conflict"
	CodeCancelled            = "cancelled"
	CodeTimeout              = "timeout"
	CodeUnavailable          = "unavailable"
	CodeInternal             = "internal"
)

// Structured invalid_call constraints. Unlike invalid_argument (domain validation
// of a well-formed call), invalid_call may be repaired once without parsing prose.
const (
	ExpectedType  = "type"
	ExpectedEnum  = "enum"
	ExpectedRange = "range"
)

// Schema-only query/plan vocabulary. Execution is gated until it enters the
// conformance surface; these closed words mirror uap-workflow.schema.json so the
// draft grammar cannot drift while the runner does not execute it.
const (
	PredicateLeaf = "predicate"
	PredicateAnd  = "and"
	PredicateOr   = "or"
	PredicateNot  = "not"

	CompareEqual        = "eq"
	CompareNotEqual     = "ne"
	CompareLess         = "lt"
	CompareLessEqual    = "lte"
	CompareGreater      = "gt"
	CompareGreaterEqual = "gte"

	CorePredicateRefEqual      = "ref.eq"
	CorePredicateTypeIs        = "type.is"
	CorePredicateRelationOf    = "rel.of"
	CorePredicatePropertyCmp   = "prop.cmp"
	CorePredicateTextRange     = "text.range"
	CorePredicateTextContains  = "text.contains"
	CorePredicateViewVisible   = "view.visible"
	CorePredicateSymbolMatches = "symbol.matches"

	QueryAscending  = "asc"
	QueryDescending = "desc"

	PlanStop              = "stop"
	PlanSkipIfGuardFailed = "skip_if_guard_failed"
	PlanCompleted         = "completed"
	PlanStoppedAt         = "stopped_at"
	PlanCancelled         = "cancelled"
	PlanStepRan           = "ran"
	PlanStepSkipped       = "skipped"
	PlanStepNotRun        = "not_run"
	PlanRollbackReverted  = "reverted"
	PlanRollbackFailed    = "failed"
	PlanRollbackNotRun    = "not_run"
)

// EffectKind values, smallest escape radius to largest. Parsing fails closed to
// KindExternal so a garbled declaration earns the strictest treatment.
const (
	KindRead     = "read"
	KindView     = "view"
	KindDraft    = "draft"
	KindPersist  = "persist"
	KindDevice   = "device"
	KindExternal = "external"
)

// Reversibility values. Parsing fails closed to ReversibilityNone.
const (
	ReversibilityNone          = "none"
	ReversibilityCheckpoint    = "checkpoint"
	ReversibilityOperationUndo = "operation_undo"
)

// ActionTerminality values. Parsing fails closed to TerminalityObservable — the strict
// reading is the one that still demands a verified outcome.
const (
	TerminalityObservable = "observable"
	TerminalityHandoff    = "handoff"
)

// ReferenceLifetime values. Everything except persistent requires a basis.
const (
	LifetimeView       = "view"
	LifetimeFocus      = "focus"
	LifetimeDocument   = "document"
	LifetimeSession    = "session"
	LifetimePersistent = "persistent"
)

// ObservationScope values for the observe query.
const (
	ScopeView      = "view"
	ScopeFocus     = "focus"
	ScopeSelection = "selection"
	ScopeDocument  = "document"
	ScopeObjects   = "objects"
)

// CancelState values. Parsing fails closed to CancelTooLate — the strict reading is the
// one that does not promise the user something did not happen. CancelNothingChanged is the
// answer for a command that already finished and left nothing behind; it is separate from
// CancelTooLate because that answer offers the user an undo, and there is nothing to undo.
const (
	CancelStopped        = "stopped"
	CancelTooLate        = "too_late"
	CancelNothingChanged = "nothing_changed"
	CancelUnsupported    = "unsupported"
)

// Discovery and observation bounds, matching the host's.
const (
	MaxCapabilities         = 64
	MaxActionsPerCapability = 32
	MaxObservedObjects      = 20
)

// Workflow (plan/query) bounds, matching the host's workflow_schema.py. Schema-only
// until execution enters the conformance surface; the grader carries them so the first
// wire-level plan/query vector starts from the gated values.
const (
	MaxPlanSteps       = 32
	MaxPredicateDepth  = 8
	MaxPredicateTerms  = 16
	MaxQueryFields     = 32
	MaxQueryOrderTerms = 8
	MaxCursorChars     = 256
	MaxResultPathChars = 256
)

// knownCodes is the closed error-code set, for fail-closed parsing.
var knownCodes = map[string]bool{
	CodeStaleReference:       true,
	CodeUnknownReference:     true,
	CodeUnsupported:          true,
	CodeAmbiguous:            true,
	CodePreconditionFailed:   true,
	CodeInvalidCall:          true,
	CodeInvalidArgument:      true,
	CodePermissionDenied:     true,
	CodeConfirmationRequired: true,
	CodeConflict:             true,
	CodeCancelled:            true,
	CodeTimeout:              true,
	CodeUnavailable:          true,
	CodeInternal:             true,
}

// reobservable holds the codes a host answers by re-observing. The stale-reference
// vector accepts exactly these as an honest refusal.
var reobservable = map[string]bool{
	CodeStaleReference:   true,
	CodeUnknownReference: true,
	CodeConflict:         true,
}

var knownStatuses = map[string]bool{
	StatusAccepted:  true,
	StatusCompleted: true,
	StatusPreviewed: true,
	StatusRejected:  true,
	StatusFailed:    true,
	StatusCancelled: true,
}

var knownKinds = map[string]bool{
	KindRead:     true,
	KindView:     true,
	KindDraft:    true,
	KindPersist:  true,
	KindDevice:   true,
	KindExternal: true,
}

var knownReversibility = map[string]bool{
	ReversibilityNone:          true,
	ReversibilityCheckpoint:    true,
	ReversibilityOperationUndo: true,
}

// Vocabularies the GRADER must know even though it never mints them: it reads them off the wire
// while judging semantics, and a word it does not recognise is a verdict it cannot reach. Absent
// here, all three had already drifted from the host — which the parity gate could not see, because
// it did not check them.
const (
	// DeniedScope on a permission_denied result: whether the refusal was about this target or the
	// whole capability. The host treats the second as a mid-session capability loss.
	DeniedScopeTarget     = "target"
	DeniedScopeCapability = "capability"

	// ManifestScope: a live binding's manifest, or the pre-auth catalog a deployment publishes.
	ManifestScopeSession = "session"
	ManifestScopePublic  = "public"

	// ProviderOrigin — visible provenance, never an assurance award. Host-known provenance caps
	// what evidence can establish; a manifest may only make the answer more conservative.
	OriginNative        = "native"
	OriginAdapter       = "adapter"
	OriginAccessibility = "accessibility"
	OriginVisionHID     = "vision_hid"
)

var knownLifetimes = map[string]bool{
	LifetimeView:       true,
	LifetimeFocus:      true,
	LifetimeDocument:   true,
	LifetimeSession:    true,
	LifetimePersistent: true,
}

var knownCancelStates = map[string]bool{
	CancelStopped:     true,
	CancelTooLate:     true,
	CancelUnsupported: true,
}
