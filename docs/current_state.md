# Current state

Updated 2026-09-15 from the checkout, Claude conversation ending 2026-09-02,
and saved experiments. This documentation reset changes no runtime behavior.
Last pre-reset commit: `50c4db0` (2026-09-02). The last session reported 535
passing tests; that count was not rerun for this documentation change.

## Authority and reading order

This file summarizes implemented behavior and accepted decisions.
[Research plan](research_plan.md) is the active work queue;
[experiment policy](experiment_policy.md) governs testing and expenditure.
The local `prompts/` files implement that plan. CLI/schema behavior is ultimately
verified in code. `proto_inventory_design.md` is a historical notebook: its
original approvals, stop conditions, and “not implemented” labels are dated
claims, not fresh instructions. Do not read its 6,000+ lines before every task.

The September plan supersedes old prompt numbers 01–14, instructions to delete
rule cascades, mandatory five-seed sweeps after every change, demands that the
test count always increase, and “non-overlapping spread” as a universal verdict.

## Project contract and implemented capabilities

Every internal node gets a model session using its direct child lexicons/beams.
Typed tools expose alignments, correspondence patterns, outgroup witnesses,
previous hypotheses, segmentation/realignment overlays, and hypothesis previews.
The model commits either child-to-parent rules or a proto-inventory; deterministic
execution creates parent beams. Both paths are supported, with strict validation,
versioned trajectories (including 2.0 and 3.0), reports, and completed-node resume.
No mid-node resume or training backend exists.

Ingestion supports supplied Newick trees, native polytomies, historical targets
versus anchors, and partial cognacy. Benchmarks include Polynesian, Romance,
Burmish, and three synthetic definitions. Offline probes and graded scoring exist.
Sibling evidence is now included by default for disagreeing surveyed sets; its
causal benefit has not been isolated in a controlled comparison.

## The last experiment

Gemini Flash's Burmish sessions often exhausted the default 24 turns. Raising the
cap to 36 produced 11 commitments out of 12 node attempts over four valid runs;
the final two runs committed all nodes. One earlier node stalled on the protocol.
The turn cap was a real limitation but removing it did not establish quality.

| Target node | Four valid 36-turn runs | Interpretation |
| --- | --- | --- |
| `burmic` | 1 exact match / 148 repeated concept evaluations | One NEEDLE hit in one run, scored against a provisional Old Burmese target |
| `proto_burmish` | 0 / 216 repeated concept evaluations; beam exact also zero | No exact root target occurred in the saved beams |

These are 37 and 54 concepts repeated four times, not independent samples of
148 and 216 words. The run-level cost ceilings differed between the two pairs
and neither was reached; do not claim identical configuration hashes.

Artifacts (local only):

- `runs/sweeps/burmish-gemini-t36-r2/seed-{00,01}/result.json`
- `runs/sweeps/burmish-gemini-t36-r3/seed-{00,01}/result.json`
- `runs/sweeps/burmish-gemini-t36/` and `burmish-gemini-t36b/` are **void**
  provider-failure experiments. Do not count their aggregates as linguistic results.

NEEDLE at `burmic` combined `a p` from Achang/Xiandao with Rangoon's `⁴`, yielding
`a p ⁴`. No daughter attests that whole form. At the root in that same run the
output was `a p ⁵⁵`, against targets `ˀŋ a p ⁴` or `ʔ a p ⁴`.
The success demonstrates a useful combination, not the historical validity of the
intermediate binding or a capability exclusive to inventories.

During the September review, stripping tokens composed solely of superscript
digits from both prediction and target raised root exact matches to 5, 4, 3, 4
of 54 in r2/00, r2/01, r3/00, r3/01 respectively. This is an exploratory diagnostic,
not the official metric. Tone alone does not explain the zero.

Historical detail: [§7.29](proto_inventory_design.md#729-the-turn-budget-was-binding-and-the-first-form-no-daughter-attests).

## How to interpret earlier Polynesian results

Copying the best single daughter scored 27/46 (58.7%). An oracle selecting the
closest attested form per concept scored 38/46 (82.6%). The latter uses the
answer key and is a diagnostic, not a deployable baseline.

Gemini's three recorded runs scored 0.630 ± 0.022 (sample SD), exceeding the
single-daughter baseline. Their exact hits were all already daughter-attested.
This measures agreement with gold, but does not establish performance beyond
literal selection. It also does not prove that the model merely copied.

The named oracle probes are answer-key-assisted constructions, not live model
scores or universal proofs of representational limits. State the oracle mode,
node, input, width and alignment reading whenever quoting them.

## Accepted decisions and remaining limitations

1. **Keep both commit shapes.** Stage 4 was cancelled on 2026-08-30. The historical
   approval in §11 is superseded. No new deletion decision is pending.
2. **Keep the selection-overlap diagnostic, narrow its claim.** A correct form
   absent from every daughter exceeds literal selection. Matching a conservative
   daughter can be correct reconstruction; an unattested exact hit can still
   reflect memorization. Neither outcome alone proves the model's reasoning.
3. **Old Burmese at `burmic` is a provisional proxy.** The benchmark explicitly
   says it is not the ancestor of all that node's descendants. Preserve old
   scores for provenance, but do not treat this as validated intermediate gold.
4. **Evidence and assembly differ.** Morpheme-aware evidence uses cognate slices;
   `ProtoInventoryAssembler.align_candidate_tuple` creates whole-string forms
   without memberships. At a measured Burmish node the two views had 223 versus
   344 columns. Diagnose consequences before choosing a new representation.
5. **The runtime prompt needs correction.** Its claim that cascades cannot emit
   segments absent from daughters is false for the literal replacement DSL.
   Correcting it changes model behavior and instruction hashes, so it is assigned
   to a separate implementation prompt, not silently changed by this doc reset.
6. **Provider failures can contaminate interpretation.** Retry settings remain in
   the compatibility hash; provider outages can become node fallbacks. Planned
   recovery work must distinguish these from a model failing to solve a node.
7. **Statistics are exploratory.** Small, nested samples and multiple changed
   settings do not establish causal effects of model or commit shape. Failure
   exclusions can bias comparisons. The next evaluator must report both conditional
   quality and end-to-end outcomes with explicit denominators.
8. **B-Cubed is currently per word.** It measures aligned repetition structure;
   high scores are not evidence of consistent phoneme mappings across a lexicon.
9. **Shared-innovation reports remain deferred.** The specific proposal in
   `shared_innovation_note.md` is not implemented; existing cross-node reports
   are not equivalent to it. A derived inverse rule is not by itself proof of
   a historically shared innovation.

## What is next

Start with prompt 01: reproduce and explain a small, declared panel of banked
failures offline. Prompt 02 repairs evaluation; prompt 03 addresses the evidence
contract if diagnosis supports it. Protocol and provider work have separate
prompts so their effects can be isolated. Local experiments come after the
instruments and candidate changes. Forward prediction is an optional later study.
