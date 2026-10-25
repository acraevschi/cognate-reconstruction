# Evaluation contract — task02-v1

Written before implementation, 2026-10-02. Report-only: none of these fields
changes candidate ranking, protocol validity, export gates, selection or traversal.
The task 01 audit (`docs/research/failure_audit.md`, local only) and traces (`docs/research/failure_audit_traces.md`, local only) supply
the frozen development cases, not a prevalence sample. Zero live inference.

## Reference, units and compatibility

Old fields retain their definitions and all target alternatives. Raw exact is
token identity (including boundaries and tone); edit distance is unit-cost token
Levenshtein; NED divides by the longer sequence. Nearest alternative minimizes
NED, then edit distance, then token order. Beam-best ties retain beam order.
No Unicode, phonation, contour/category or substring normalization is added.

`target_validity` is a binding annotation: `validated_target` means an explicitly
accepted evaluation relationship, not that a published reconstruction is historical
truth; `provisional_proxy` excludes it from the validated-target view;
`underdetermined` excludes unique-answer scoring; null is unknown. Evidence kind
(attested/reconstructed/synthetic) remains separate. Old Burmese at `burmic`
receives a documented exact-identity legacy annotation, never prose parsing.
Unknown bindings are never promoted automatically. The Burmish selection source,
54 selected IDs, 37 proxy IDs and tree stay unchanged. Gold-based cognacy selection
is disclosed separately from absence of gold in model evidence.

New schemas are additive with null defaults. New reports identify evaluator
`task02-v1`; banked results/aggregates are not rewritten. Offline reports may
recompute from supplied payload plus faithful saved steps/trajectories. They retain
saved scores separately and explain whether the planned set is available.

## Field contract

All fields below are report-only. Gold is used only after inference. Target validity
travels with every score, including fallback and proxy scores. Counts are nested
run × node × concept observations, not independent word samples.

| Fields | Unit / denominator | Missingness | Fallback treatment | Gold use |
| --- | --- | --- | --- | --- |
| source IDs/reference, evidence kind, validity/note | one binding; no denominator | null unknown; exact legacy proxy identified explicitly | identical annotation on every view | annotation only; hidden from model |
| selection provenance | declared definition recipe, selection source, target-cognacy flag; no denominator | null when not recorded; supplied definition does not rebuild the frozen payload | unchanged across output kinds | records whether sample selection used target cognacy; never model evidence |
| target form IDs/segment alternatives, nearest target | source form / concept; every alternative retained | no target means ineligible, not a missing output | retained | yes |
| evaluated concepts, missing reconstruction concepts | target-bearing concepts / node | missing output has false exact, null distances | raw fields include labelled fallback | yes, planned gold set |
| top/beam exact counts/rates | target concepts, including missing outputs | missing is a miss; zero eligible raw legacy rate stays 0 | original raw comparisons retained | yes, any alternative |
| edit distance/NED, beam best, selection gap, graded distributions | available outputs; distribution count explicit | null for missing output; never NED=1 imputation | raw scores labelled | yes, nearest alternative |
| per-word B-Cubed P/R/F1 | aligned columns within one word; mean over available words | null missing output | raw scores labelled | yes; aligned repetition, not linguistic accuracy or across-word consistency |
| token diagnostic version/status, segment-only exact/NED | whole token sequence after superscript-only token partition; nearest alternative independently selected | missing output null; attached digits/slash notation flagged ambiguous and not scored | displayed for every output kind | yes; task01-v1 partition only |
| tone-token sequences/exact | ordered superscript-only tokens, any alternative | both unmarked null; one side unmarked visible; ambiguous notation null | displayed, no category/contour equivalence | yes; token disagreement only |
| morphology status, pieces, counts | boundary-delimited pieces of whole words (`+`, `-`); no substring score | no boundaries means unanalyzed; output cognate memberships unavailable; unresolved lexical scope explicit | displayed | target pieces yes; no inferred cognacy |
| cognate-unit comparison (separate function) | explicitly identified morpheme IDs and complete piece tokens; target units denominator, extra/missing/reordered IDs explicit | absent/ambiguous IDs unscorable; caller must supply independent annotations | caller labels output; never supplies evidence to model | yes; independent whole units, never match by resemblance |
| daughter selection eligible/reachable IDs/counts, outside-selection top/beam hit IDs/counts | target concept; observed descendant leaves with form present; whole forms, all alternatives | null without observed leaves; no witness is ineligible | retained separately; copying commitments remain commitments | yes; reachable is a gold-assisted best-daughter oracle diagnostic, not a baseline |
| direct fallback, descendant fallback IDs, output kind, commitment known | one node | missing steps and missing commitment evidence explicit unknown | direct fallback never commitment; ancestors committed with dependencies flagged | no |
| operational nodes/status, run status, notes | every internal tree node, including unscored nodes; no score denominator | committed-without-saved-output and unvisited/missing distinct; no-result status separate from cause | failed/fallback nodes never commitments | no |
| failure kind/error type | structured failure record, not parsed provider prose | unknown without structured cause; legacy provider cause remains unspecified | recorded alongside fallback | no |
| planned/committed/available/fallback/unknown/missing counts and IDs | planned target concepts at each node in supplied payload | plan unavailable null; unvisited nodes and missing concepts included | separate coverage, never counted as model commits | yes, evaluation plan only |
| conditional committed exact/NED | all planned concepts at committed nodes for exact; available committed outputs for NED | empty denominator null; missing committed outputs exact miss | ancestor dependence labelled, direct fallback excluded | yes |
| end-to-end model exact, available-output exact, fallback exact | entire planned evaluation set, including abandoned runs and missing nodes | empty denominator null; absent output miss | model hits exclude direct fallback and unknown commitments; output hits include labelled fallback/unknown | yes |
| validated-target view | same rules, only explicitly validated bindings | proxies, unknown and underdetermined remain in raw views | same rules | yes |

## Analysis limits and evidence boundary

Segment-only diagnostics preserve `ˀŋ`, nasalization and boundaries. They are
neither a phonetic segmentation nor a tone-category mapping. No source-backed
category/contour or phonation map was established in 01; those diagnostics remain
unlicensed. OLD MAN (`406`) has unresolved target lexical/cognate scope. CRAWL
and FLOWER boundary counts can expose extra pieces but cannot assign the correct
morpheme without independent output memberships (task 03).

Corpus B-Cubed is deliberately deferred: unit-cost per-word alignments can move
columns, lexical/morphological scopes differ, and conditioning may permit different
mappings. A contradiction across two words despite perfect per-word B-Cubed is
tested, but no unlabeled corpus number is added. A future measure must freeze
alignment, compare the same conditioned correspondence/unit, and state whether
it samples columns, morphemes, concepts or independent etyma.

Salvage only completed trajectories with a stored deterministic step. Never
reconstruct a missing step from a summary, failed-session prose or generated gold.
Run existence/exit status and provider cause are separate. No result.json means
abandoned/incomplete, not proof of model incapacity. Unknown causes remain unknown.

## Small mechanism suite

Use six new cases, separate from published synthetic families: complementary
retention, conditioned change, unequal/reordered morphology, two-level propagation,
identity and unrecoverable merger. Each has repeated independent concepts and a
declared limited inference question. Retaining witnesses identify the contrast
under the stated conservative-retention hypothesis; unconstrained proto-symbol
renaming and alternative histories are still equivalent solutions. No toy proves
a unique historical polarity from generated truth alone. The lost-contrast control
is underdetermined and excluded from uniquely recoverable summaries. Answer keys,
identifiability notes and gold-derived hints never enter node prompts or tools.

The morphology case also leaves ancestral order/polarity underdetermined; its
identified pieces are scored separately. An explicit observed-form morphology
overlay extends the existing generator for this case because the DSL forbids
inserting boundaries. Standard sound-rule precision is inapplicable to that
operation; the separate answer-key notes record it. Old synthetic definitions
and generator behavior are unchanged.

Verification covers perfect/scripted output, wrong output, identity, direct and
descendant fallbacks, model protocol failure, infrastructure/unknown cause, abandoned
salvage, missing concepts, alternatives, proxy annotation and payload isolation.

## Task04 scorer-layout amendment — 2026-10-04

Raw task02-v1 readings and target tokens are unchanged. The existing generated
morphology `target_unit_layouts` now become complete memberships only in hidden
historical target binding forms. No answer-key/layout metadata enters model
contexts or tools. Normal evaluation can compare actual assembled/serialized
pieces and records `unit_evaluator_version=task04-units-v1` when output analysis
is explicit. Extra/missing/wrong pieces and order remain separate. Reordered
complete pieces can score exact in the piece reading while raw whole-word exact
is false. Ancestral-order and lost-contrast validity stay underdetermined.

The five [scripted controls](evidence_repair.md) use actual preview/commit, parent
propagation, JSONL and `evaluate_run`; their success verifies the measurement
instrument, not linguistic/model improvement. Real unannotated targets and
OLD MAN's unresolved scope still have unknown piece quality.

## R02 amendment — additive stage diagnostics, 2026-10-25

task02-v1 and task04-units-v1 readings are unchanged. Two additive, report-only
versions sit beside them for the R02 stages ([design](model_diagnostic_design.md)):

- `r02-usability-v1` (Stage A): exact execution of a supplied hypothesis. Claims
  are compared after expansion to local sets with canonical conditions; prose is
  not compared. Its references are executions of supplied claims, never quality
  targets.
- `r02-decisions-v1` (Stage B): one opportunity per etymon position or piece where
  exactly one active child has material in one supplied cognate unit, read from
  the committed top candidate's analysis by cognate set, never by spelling.
  Readings `retain`/`absent`/`other`/`unscorable`/`missing`; the denominator is
  every planned identified opportunity, so missing or unanalyzed output cannot
  raise the rate. Unresolved (no-outgroup) opportunities are descriptive only.
  Correctness is conditional on the definition's stated parsimony assumptions.

Explicit diagnostic definitions (`r02-stage-a-v1`, `r02-stage-b-v1`) build
payloads from observed pieces; their operator fields never enter model evidence.
