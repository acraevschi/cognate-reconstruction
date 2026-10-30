# Cognate reconstruction at one node

Infer a defensible parent hypothesis from this node's active direct children.
Keep unresolved analyses and uncertainty explicit. The tree may be a polytomy;
do not invent intermediate nodes. Tools establish tokenization, alignment,
execution and exact outputs. They do not establish historical truth.

## Choosing a representation

Both an inventory and an ordered child-to-parent rule cascade are supported.
Use the representation convenient for the evidence and inspect its execution.
An inventory makes local correspondence values, unit scope and cross-child
assembly explicit. A cascade is convenient for sequential rewrites and contexts
created by earlier rewrites. Its operational order is not automatically historical
chronology. Inventory conditioning is evaluated on reconstructed neighbours;
commitment order carries no meaning. These conveniences imply no universal order
for linguistic reasoning.

Rules can emit literal new tokens and token sequences absent from the children:
the abstract rule `x > z q` can emit two new tokens. Expressibility does not license
a historical interpretation. The DSL requires a nonempty target, so it cannot
insert at an empty position. A nonempty target can expand into several tokens.
Neither the harness nor a child-to-parent rule inverts a forward sound change.
State the proposed parent-to-daughter history and its uncertainty in your reasoning.

## Evidence and linguistic judgment

Compare concepts and supplied cognate units; similarity alone does not establish
cognacy. Seek recurrence and conditioning, then inspect exceptions, morphology,
possible lexical mismatches and alignment assumptions. A regular account is a
working hypothesis, not permission to hide counterexamples. Do not identify
loans or innovations from irregularity alone.

`support` uses independent-etyma-v1: supplied etyma plus separately reported
unresolved concept/unit opportunities. Supplied IDs do not prove historical
independence. Concepts, positioned source columns and alternative occurrences
have separate counts. Several sister languages are not independent historical
witnesses. A local singleton is sparse evidence, not automatically residue or
innovation. Witness absence, missing annotation and alignment gaps do not decide
polarity. Inspect sparse material that a global witness policy could lose.

A segment against gaps may reflect loss, insertion, morphology or an unresolved
analysis. Retention can be a qualified hypothesis; it is not mandatory regardless
of morphology. Material at a boundary is not automatically innovative either.
Novel proto values are allowed, but require a reason grounded in these observations
and an explicit uncertainty judgment. State sound-change typology you rely on;
there is no built-in sound-change database or historical naturalness score.

Inspect supplied outgroup profiles when they bear on directionality. Use scoped
`polarize` to resolve a specific question, keeping set_id, unit_orders and overlays
consistent. It describes witnesses and never chooses the original value. Only
true outgroups offer evidence outside the subtree. Descendants and reconstructed
nodes are not independent attestation. Outgroup presence in the appropriate unit
may support a history but does not prove inheritance or exclude borrowing. An
outgroup gap does not establish innovation. At the root no outgroup exists;
explain uncertainty from available evidence instead of repeatedly requesting one.
The tree/classification itself may constrain what can be inferred.

Tone/category and phonation notation remain raw tokens. No source-backed
category-to-contour or phonation map has been established here. Do not equate a
category digit with a daughter contour automatically or use target-like output
as a reason for a value. Reference forms, answer keys and target annotations
are outside your evidence. Respect anchor_policy: ignore excludes anchors from
reasoning; advisory allows supplementary interpretation; scored uses the explicit
engine match factor. Anchors are optional and must not dictate an analysis.

## Inspect, propose, preview, commit

1. Start with `summarize_correspondences`. The default recurrence reading returns
   descriptive csp-* patterns and exact local member_set_ids, not automatic
   historical equivalence. Inspect pagination and filter coverage. min_support=2
   is an inspection filter; use min_support=1 for sparse material and reading=local
   for individual csu-* execution sets. Never silently narrow the input or beam.
2. Inspect the units and source positions behind consequential choices with bounded
   `get_alignments` selections. Summary is usually sufficient; full detail exposes
   exact columns and contexts. `list_concepts`, `search_forms`, available nodes and
   scoped witnesses answer specific evidence questions. Previous reconstructions
   are prior hypotheses, not new independent support. Report meaningful conflicts.
3. Propose only the values you can defend. Local `commitments` use exact set_id,
   reflexes and support; if the tool offers `choices`, give set_id and your linguistic
   decisions while the harness resolves reflexes/support. Each local ID names one
   token-correspondence row, not a whole concept or word. Put choices in a flat
   top-level list; never nest them inside commitments. State a claim list explicitly,
   including [] for deliberate identity. `shared_claims` explicitly
   selects pattern_id/member_set_ids and one value over those members. Exclude local
   exceptions from that collection and give them their own choices. A csp-* pattern
   ID cannot be used as a local commitment.
4. Every choice requires proto_segment (including explicit null) and confidence
   in (0,1]. Null asserts no parent material at that position; omission asserts
   nothing and is refused. Full reflex tuples include one entry per child in order,
   including null positions. Never shorten tuples or invent proto_segment_is_null.
   More than one expanded local commitment requires a rationale on each. Shared
   claims always require a rationale. Deletions and actual differing-reflex reductions
   require directionality_rationale; repeated identical retention is not a merger.
   Give your proposed history, available evidence and uncertainty, including when
   polarity remains unresolved. The harness checks presence, not historical truth.
5. Preview the exact inventory with `test_proto_assembly`. State residue_policy,
   witness, dispositions, restorations, unit_orders and overlays as applicable.
   Read assembled forms, unaccounted columns, ambiguous matches and source-unit
   traces. Executable means the assembler ran; commit_ready also requires the
   per-set explanations. Read missing_commit_requirements and supply those in a
   new preview. Summary and anomalies remain required at the final commit.
6. If the preview returns a hypothesis_id with commit_ready=true, commit that
   immutable inspected inventory with node_id, hypothesis_id, summary and anomalies.
   Omit inventory, rules and overlay fields on a handle commit. The handle freezes
   them already. The compatible full-payload path commits inventory instead, with
   exactly the previewed choices. No successful preview means no nonempty commit.
   Rules use their own validated path below.
7. Changed values, confidence, rationales, conditioning, member selections, residue
   choices, restorations, orders, analyses, evidence or overlays require exact
   revalidation. Handles are local to this session and cannot be resumed or moved
   to another node. Re-surveying identical evidence is safe. Reporting filters/detail
   do not alter the hypothesis. Concept batches may combine only for the same
   hypothesis and evidence revision. A handle never licenses uninspected edits.

## Residue, uncertain analyses and abstention

`retain_from_witness` uses the named active child on unaccounted columns and reports
those columns as unexplained. A witness gap emits no material: this policy can lose
material present in other children. Inspect that possibility, especially in singleton
scopes, and state a local value or exact disposition when justified. Choosing a
witness is a qualified reconstruction choice, not a guarantee of conservatism.
`drop` contributes nothing on unaccounted columns and makes a stronger omission
claim. Neither policy guarantees monotonic scientific improvement.

You may leave material unexplained, lower stated confidence, record conflicting
analyses or abstain from new correspondence claims. Empty rules are an explicit
identity hypothesis; an empty inventory with no additional structural claims is
also supported. Explain its limits after inspecting evidence. Runtime failure and
identity fallback are recorded separately from a model commitment. Divergence,
residue and held-out diagnostics are reports, not gates; do not manufacture claims
to improve them. The visible development/held-out partition is not independent
unseen-word evidence.

Anomalies use anomaly_type, explanation and form_id or concept_id. Allowed types:
loanword, morphological_leveling, taboo_deformation, unknown_irregularity. Use the
last when cause is unknown; record what you inspected. An anomaly does not replace
a correspondence value or authorize a fabricated cause.

## Morphology and evidence edits

Current evidence contract is units-v2; piece representation remains units-v1.
Known pieces, exact column IDs and source positions survive parent propagation.
Unknown analysis stays unknown. Equal tokens in different unit scopes need distinct
choices. Structural + and - boundaries are not ordinary phonetic segments.

Inspect a questionable layout before accepting it. `segment_morphemes` makes a
boundary overlay, preserving phonetic tokens; analysis_claim can explicitly state
complete pieces without guessing cognacy from spelling. Partial `realign` needs a
named unit_id, and ambiguous alternatives need analysis_ids from get_alignments.
Dropping row nulls must reproduce the chosen child's unit tokens in order.
joins_set_id verifies source-column gain; independent-support gain is reported
separately. Null permits a first attestation. Explain repairs rather than using
alignment edits to fit a desired form. Overlays create new evidence/IDs: survey
again under them and preview again. Old IDs cannot authorize the new reading.
Conflicting piece order needs unit_orders and rationale; unresolved order stays
labelled. Use the same order claim throughout survey, preview and commit.

Restorations name a wholly absent position, segment and cited outgroup, with
required directionality_rationale. Partial evidence needs unit_id. The backend
checks presence in the cited corresponding unit and rejects descendant witnesses;
lost-position placement/history remains your claim. A root restoration has no
outgroup to license it and is refused. Exact ambiguous alternative positions need
before_evidence_column_id. Residue dispositions likewise name an exact column when
indices alone do not identify it. These hard restrictions are not waived by prose.
Work caps explicitly refuse excessive enumeration; they never silently prune an
analysis. Evidence results compacted after reinspection name their replacement.

## Rule DSL and rule commitment

Use `target > replacement / environment`, with optional environment. Tokens are
literal; separate token sequences with spaces. Examples: `f > p / #_`,
`k > tʃ / _i`, `n > m / _p`, `x > z q`. # is an outer word edge and _ occurs once
in an explicit environment. Ø or ∅ as replacement deletes. Empty targets and
identity rules are refused. Boundaries may constrain context but cannot be rule
targets or insertions; boundaries are not transparent. No feature notation,
regexes, optional segments or invented phonological classes are supported.
A rule that would empty a form is refused on that form and reported.

Test each exact DSL, active child scope and segmentation overlay with test_sound_law
or test_rule_cascade. A cascade preview exercises the stated order; inspect its
intermediate effects when ordering matters. The cascade preview requires at least
one rule; identity is committed as rules=[]. Each committed rule requires explicit
confidence. Multiple rules need individual rationale; mechanically detected
loss/merger needs directionality_rationale. Per-rule validation_call_id and
supporting_form_ids may be resolved from an exact matching same-session validation.
cascade_validation_call_id, when supplied, names the whole tested order, not a
single-law test. Changed rules/scopes/overlays require retesting. Never submit both
rules and inventory. The inventory's derived_rules_scope=unscoped_view omits
unit/column restrictions and is not an equivalent executable global cascade.
