# Current state

## Post-review qualification — 2026-10-08

The independent assessment completed on 2026-10-07 and is local-only at
`prompts/review-after-tasks01-06-report.md`. Its fresh verification reproduced
364 historical score records and eleven committed beams/reports; 167 focused
tests passed. Those are review observations, not tests rerun during this prompt
preparation. The review also reproduced four gaps: token-conditioned JSON/handle
commit failure, abrupt first-node resource-history reset, missing same-set
condition-overlap diagnostics, and dropped analysis in `best_lexicon` export.
Current traversal/normal evaluation use the analysis-preserving beam path; the
export defect does not negate those propagation controls.

No fixes or new inference have been performed by the follow-up prompt preparation.
Task05 therefore has an additional offline contract gap as well as unproven live
usability; Task06's delivered graceful recovery does not establish safe cumulative
caps over every hard-interruption window. Preserve their historical test results.

The owner requested an early stronger-model comparison on the repaired harness
before substantial redesign/pivot. R01 repairs, R02 prepares instruments/manifests,
and R03 separates supplied-hypothesis usability from linguistic judgment for a
local baseline and one stronger candidate. Local success is not a prerequisite to
the stronger arm. Most software tests are deterministic; older hosted Gemini
commit success and recent local Gemma failures are not a controlled model comparison.
See the shared handoff and research plan for the current R01–R07 sequence. Sections
below retain their dated historical task numbering/status and implemented evidence.

Updated 2026-10-05 with task 06 offline provider recovery and interruption accounting.
Task05's single local smoke failed; substantive live usability remains unresolved.
Task 04 units-v2 and task 03 final smoke accounting
is in [evidence results](research/evidence_results.md).
Prompt numbering was updated on 2026-10-04; this entry document uses the current
01–08 sequence. Dated research reports and conversations retain their original
numbering; the shared handoff contains the translation.
The September baseline was
read from the checkout, Claude conversation ending 2026-09-02, and saved experiments.
The audit changes no reconstruction behavior. Task 02 adds report-only binding
annotations and evaluation views; it changes no target forms, selection or traversal.
Last pre-reset commit: `50c4db0` (2026-09-02). The last session reported 535
passing tests; that count was not rerun for the reset. Fresh task 02 checks are below.

## R01 contract repairs — verified 2026-10-23

[R01](research/post_review_contract_repairs.md) reproduced and repaired all four
review findings offline at starting HEAD `63af18d`, committed on branch `r01-contract-repairs`. There was no
inference, model operation, paid call or dependency change.

1. **Token-conditioned claims.** These now preview, commit, persist to JSONL and
   checkpoints, re-preview immutably and reach parent nodes in both native
   profiles. Strict validation is retained.
2. **Abrupt loss.** New checkpointed runs journal each counted turn, request and
   tool call before it happens. Turn and tool caps count lost effort. Cost and
   elapsed time stay unknown and conservatively refuse their caps.
   `history_complete` stays false. A legacy checkpoint without a summary is not
   certified complete.
3. **Overlapping conditioned choices.** Overlapping choices on one set are
   reported by choice identity, with additive fields, and the emitted values are
   unchanged.
4. **`best_lexicon`.** It carries the top candidate's analysis.

Model-visible instruction, schema and node-note digests are unchanged; the
assembly preview's result carries the new ambiguity fields. An independent
review on 2026-10-25 found three journal defects (a graceful failure read as
abrupt loss, a torn tail breaking a later resume, an unwritable journal
producing fallbacks); all three are fixed, see section 6 of the R01 report.
Portable suite: 750 passed, 41 deselected. JSON dumps of boundary-token sets are now
sorted, so stored-handle digests no longer depend on the hash seed. The banked replay still agrees on 364/364
scores and 11/11 beams and reports. These fixes establish interface and
accounting behaviour only, not live usability or reconstruction quality.
Task05's offline protocol claim now includes token-conditioned JSON. Task06's
cumulative caps hold for journaled abrupt loss, not for effort lost with its
journal. R02 is ready to start.

## R02 diagnostic instruments — prepared 2026-10-25

[R02](research/model_diagnostic_design.md) prepared offline, on branch
`r01-contract-repairs`, everything R03 needs; no model was called.

- **Stage A** (`r02-stage-a-v1`, `r02-usability-v1`): one node with a supplied
  nonempty token-conditioned shared claim, a source-unit decision (a pooled
  `[m, m]` pattern versus the suffix unit's own sets), one specified revision
  and a handle commit. The scripted operator succeeds in both profiles through
  `cli infer` and the real LiteLLM adapter; scripted deviations are classified.
- **Stage B** (`r02-stage-b-v1`, `r02-decisions-v1`): 16 synthetic etyma at node
  `x` of `((a,b)x,c)r`, 18 identified retain/absent opportunities in the correct
  cognate unit, 2 unresolved items and 6 matched counterevidence pairs. Copying,
  uniform and no-outgroup cue policies score 8–12/18 and 0–3/6 pairs; the
  deployable outgroup-witness rule is the identification rule and scores 18/18.
  (Corrected 2026-10-25 from an earlier draft's 14/16/5 counts.)
- **Harness changes:** `--price-table` (versioned explicit prices; upper-bound
  cost; digest-joined only when used); Gemini 3+ thinking level sent explicitly,
  because LiteLLM 1.81.16 turned `medium` into `high` (or refused it) for
  `gemini-3.8-flash`; whole-batch ledger and serial launcher; `inspect_run`
  shows the abrupt-loss usage keys.
- **Candidate manifests** under `runs/experiments/r02-model-diagnostic-20261025/`
  bound Gemini 3.8 Flash at a worst case of US$4.70 within the owner's US$5 /
  60-minute ceiling, and the local arm within two hours. The required read-only
  manifest review, launch preflight and the launch itself belong to R03.

## R03 stronger-model diagnostic — measured 2026-10-25

[R03](research/model_capability_diagnostic.md) ran R02's Stage A/B once per
model, serially, on the same code, evidence, profile, instructions and tools.

- **Pre-launch repair.** The required read-only review found that LiteLLM
  1.81.16's Gemini schema mapping keeps only a top-level `anyOf`, so
  `test_proto_assembly` reached Gemini with none of its 12 arguments. The
  published `anyOf` is removed. The validator still refuses an omitted claim
  collection, and a wire test now covers every tool in both profiles. The
  stored-hypothesis tool-schema digest is `628f0f32…` (was `dd58d427…`).
- **Gemini 3.8 Flash** (medium thinking, temperature 1.0):
  - Stage A `success`: supplied conditioned hypothesis, revision, handle commit, readback.
  - Stage B node `x`: 18/18 model-committed correct and 6/6 matched pairs, all by explicit claims, in the correct units; both unresolved items committed at confidence 0.5. That equals the panel's deployable identification rule: necessary-condition evidence use on synthetic development material, not discovery.
- **Gemma 4 26B A4B** (LM Studio, MLX 6-bit, temperature 0.1): Stage A
  `no_commit`. Seven of eleven calls were invalid submissions (invented fields
  or IDs, stale IDs after a re-survey), ending in `ProtocolStallError`. There is
  no local judgment outcome.
- **Resources.** Gemini US$2.4754 upper bound (no unknown-cost or retried
  request; about US$0.81 using the cached-token counts Gemini reported) and
  690.5 s, within US$5 and 3,600 s; local 283.9 s. The external console check is
  pending.
- One trial per arm: feasibility, not reliability or a model ranking. The
  current harness is usable by this Gemini configuration and was not usable by
  this local one. Interface redesign is deferred; R04 is narrowed to a judgment
  panel that the outgroup-witness rule does not solve.
- **R03b follow-up** (separate experiment): the same local Stage A, with
  Gemma's published sampler sent explicitly (temperature 1.0, top_k 64, top_p
  0.95, repeat_penalty 1.0, min_p 0), again ended `no_commit` with the same
  error classes. A harness gap was found: `unit_orders` naming an unknown
  concept was accepted as a no-op that renamed every set ID.
- **R03c follow-up** (separate experiment, same code as R03b): Qwen3.6
  35B-A3B (MLX 4-bit) at its card's precise thinking sampler (temperature 0.6,
  top_k 20, top_p 0.95, min_p 0, presence 0) passed Stage A with 0 rejected
  calls. On Stage B it committed `retain` everywhere: 10/18, 0/6 pairs,
  baseline-level; it read outgroup witnesses correctly but treated outgroup
  absence as a tie. So Gemma's Stage A failure is not general to local models
  with this interface; the local judgment gap remains.
- **`unit_orders` fix** (after R03c; no run uses it yet): `evidence_map` now
  refuses a `unit_orders` entry whose concept has no form at the node, with
  the valid concept IDs (`alignment-failed`). Supersets of a concept's units
  stay accepted; a concept present in only one child is still not refused.
- **R03d follow-up** (Gemma on the fixed code, R03b's sampler): Stage A
  `no_commit` again, 7/9 rejected, all claim-structure errors (invented fields,
  pattern IDs as choices, missing `support`, a set both in `choices` and a shared
  claim). Gemma sent no `unit_orders`, so the fix was not exercised. Its
  reasoning fell to 1 token per turn from the first preview, as in R03/R03b.
  Offline diagnosis (report §17a): the harness does not send `reasoning_content`
  back, and Gemma's template renders the tool loop as one model turn with no
  thinking cue. So Gemma imitates its own visible thoughtless calls; thinking
  returns whenever a new model turn starts. Gemma's failures are therefore
  "as deployed by this harness"; carrying reasoning back is tested in R03e.
  Qwen's template forces `<think>` each step, so it was unaffected.
- **R03e follow-up** (Gemma, reasoning resent within the tool loop, new
  `--reasoning-history keep`, 16k budget + 200-token heads; default stays
  `drop`): thinking was sustained on every step and Stage A **succeeded** (6
  calls, 1 rejected), Gemma's first. Stage B did not commit: three
  16,384-token thinking-only responses at node x (non-converging analysis, no
  outgroup use); peak prompt 39k. Report §18 also records per-node context
  measurements (real-data Gemma median peaks 54k–90k, tool results up to 129k)
  and context-budget design options; none of those are implemented.
- **`--reasoning-history auto`** (2026-10-28): decides `keep`/`drop` per model
  from its chat template (keep only when resent reasoning is rendered and the
  template continues one model turn through tool results), with a live server
  probe. Resolves Gemma 4 → keep, Qwen3.6/3.8 → drop, Gemini → drop. `auto`
  is the default; only `keep` enters the digest (dropping runs hash as
  before), and every decision is written to `run_summary.json`. When nothing
  can be inferred the default falls back to drop with a warning (report §20).
- **Creation-time tool-result slimming (Option 1a, R03f).** Implemented:
  `exceptions` no longer list `target_absent` forms; `get_alignments`
  `detail="summary"` omits pairwise views; `search_forms` hits and cascade
  `final_forms` show forms without provenance (memberships only when the
  `cognate_set_id` shorthand does not cover them). Tool schemas stay `628f0f32…`.
  Offline replay of 327 recorded sessions: 14.4 MB less tool output; Qwen
  Polynesian peaks p90 110k → 93k (none over 100k), Gemma Polynesian median 54k
  → 46k, Burmish Gemma 90k → 64k. Live Qwen (R03f): Stage A identical to R03c;
  Stage B `x` no commit after three 16k thinking-only responses, with no slimmed
  content in its prompt (so not attributable to 1a). Report §19 has the
  next-option analysis (supersession with a repeat guard, watermark trigger,
  versioned schema diet). Committed in `7e6d637`.

## R04 focused study — completed 2026-10-30

[R04](research/focused_interface_study.md) tested R03's narrowed question:
does Gemini 3.8 Flash decide by the stated criterion where R02's deployable
outgroup-witness rule is not the answer? Interface redesign (dossier,
selection surface, reduced IDs) is deferred: no Gemini navigation or
transcription failure has been observed, and the local blockers lie elsewhere.

- **Stage C** (`r04-stage-c-v1`): node x with three outgroups at the root,
  other-unit forms, missing forms and four tied items. 19 decided
  opportunities, 5 matched pairs. The criterion block lets the model recognize
  regularly corresponding outgroup reflexes from the tip forms without naming
  specific reflex tokens, and explicitly overrides earlier packaged instructions
  as well as tool-result notes. Frozen scripted baselines: the R02 rule
  13/19 (0 of its own 6 errors), unanimity 15, majority of three 14, spelling
  majority 14; the stated criterion 19/19 and 4/4 ties marked (the ceiling by
  construction). The key is re-derived from observed forms in a test.
- **Scorer** `r04-judgment-v1` adds deciding-claim confidence, warranted
  uncertainty (ties ≤ 0.5), false confident claims, per-rule error sets, a
  navigation reading (covering `search_forms`, `get_alignments` and `polarize`)
  and descriptive labels (`no commit` and `uniform (regularity) reading` gated
  before rule labels).
- **`infer --stop-after-node NODE`** scores one node without running later
  ones (`failure_kind: planned_stop`).
- **Repaired before any live use:** a Gemini reply cut off at the output cap
  with no text and no call crashed the node and went unpriced. It is now an
  empty turn: the truncation recovery runs, the response is priced, and Gemini
  receives the turn without content. The local route is unchanged.
- **Live result (`runs/experiments/r04-stage-c-20261029-v2/`, 2026-10-30):**
  Gemini 3.8 Flash (`--preset gemini --reasoning-effort medium`, `max_tokens`
  32,768, `--stop-after-node x`) scored **19/19** decided opportunities
  (`explicit_claim` on all 19), **5/5** matched pairs, **6/6** on R02's
  outgroup-witness errors, **4/4** on unanimity, **5/5** on majority-of-three,
  **5/5** on spelling-majority, **4/4** ties marked at confidence `0.5`, **0**
  false confident claims, and **19/19** concepts with every outgroup form seen
  (labels: `criterion-sensitive on this panel` / `warranted uncertainty`).
  Resources: 10 requests (1 rejected call on Turn 4, repaired on Turn 5),
  840,870 input tokens (619,092 cached, 73.6%), 34,573 output tokens (28,651
  thinking; peak response 16,718 tokens on Request 9, validating the 32,768
  cap), US$0.7603 upper-bound table cost (≈US$0.3424 with reported cached
  tokens), 0 unknown-cost requests, 283.9 s wall time. AI Studio balance check
  pending (≥ 24 h after 13:24 UTC).
- **Local tier-2 follow-up (`runs/experiments/r04b-local-qwen38-27b-20261030/`,
  2026-10-30):** Dense local `qwen3.8-27b-splash` (LM Studio, 128k context,
  `max_tokens` 32,768, Qwen thinking sampler, `--reasoning-history drop`,
  `--stop-after-node x`) also scored **19/19** decided opportunities, **5/5**
  matched pairs, **6/6** on R02's outgroup-witness errors, **4/4** ties marked
  at `0.5`, **0** false confident claims, and **19/19** concepts' outgroup forms
  seen (`criterion-sensitive on this panel` / `warranted uncertainty`), with
  **0** rejected calls across 9 requests (12 tool calls, 416,502 input / 63,347
  output tokens, 56,479 thinking, peak response **23,668** tokens on Request 7
  and **16,748** on Request 6—both above R03's 16,384 cap, confirming that the
  32,768 output cap resolves the local thinking-convergence bottleneck—peak
  prompt 80,200 tokens, 1,577.5 s wall time, US$0.00 paid cost).
- **Local tier-3 follow-up (`runs/experiments/r04c-local-qwen36-35b-20261030/`,
  2026-10-30):** MoE local `qwen3.6-35b-a3b-splash` (35B total / 3B active,
  LM Studio, 128k context, `max_tokens` 32,768, Qwen thinking sampler,
  `--reasoning-history drop`, `--stop-after-node x`) ended **`no commit`**
  (`ProtocolStallError` after three 32,768-token thinking-only responses on
  Requests 3, 5 and 8; 8 requests, 6 tool calls, 1 rejected call, 277,395 input
  / 115,379 output tokens, 112,038 reasoning, 666.0 s wall time). Unlike the
  27B dense model, the 3B-active MoE model never called `search_forms`,
  `get_alignments` or `polarize` (`outgroup_forms_seen: []`, 0 forms seen;
  `concepts_with_every_outgroup_form_seen: 1/19` only because `y08` has no
  outgroup forms) and previewed only 13 of the 57 local `csu-*` sets (one per
  reflex pair) with `residue_policy: "drop"` on the other 44 (assembling only
  10/19 concepts, which would have scored 4/19 even if committed). This cleanly
  separates the 16k output-cap bottleneck (resolved at 32k for dense 27B) from
  genuine active-parameter capacity limits on multi-outgroup reasoning.

## R05 propagation and robustness study — completed 2026-10-30

[R05](research/propagation_robustness_study.md) (`two-level-propagation-v1`, offline,
0 live model calls; probe [`tools/propagation_robustness_probe.py`](../tools/propagation_robustness_probe.py))
tested how one-way post-order traversal propagates
intermediate decisions and low-confidence ties from node `x` to root `r` on a
two-level synthetic family `((a,b)x,(c,d)y)r;` and replayed the banked live
commits from R03 (`b-gemini`) and R04 (`c-gemini-r04`, `c-local-qwen38-27b-r04`).

- **One-way propagation asymmetry (`a1` vs `a2`):** Over-retaining daughter `a`'s
  innovated `-k` at `x` (`a2`, `4/8` at `x`) is still discountable at `r` via
  `⟨x k : y Ø⟩ → null` (`8/8` primary, `10/10` validated exact at `r`, while
  `x` stays unrevised at `4/8`). Conversely, collapsing a `1–1` leaf-outgroup
  tie at `x` to `null` (`a1`, `4/8` at `x`) erases `-k` from `x`'s beam before
  `r` compares `x` with sister clade `y` (`*p i g, *t e g, *p a g, *t u g`),
  dropping `r` to `4/8` primary (`6/10` validated exact).
- **Segments vs. `FormAnalysis` provenance (`b1` vs `b2`, operator controls):**
  Supplying privileged generator-truth segments at `x` with `whole:unknown`
  analysis (`b2`) yields `10/10` raw whole-word exact at `r`, but collapses
  `task04-units-v1` `cognate_unit_exact` from `10/10` to `0/10` and
  `r02-decisions-v1` from `8/8` to `0/8` (`8 unit_missing`), proving that
  explicit unit-analysis provenance is load-bearing across intermediate nodes.
  On `L1` (`c011`, parallel `w > l / #_` on `x` and `y`), even full oracle truth
  at `x` (`b1`) scores `0/1` raw exact (`*l o` vs `*w o`).
- **Tied-alternative beam retention (`c1`, `tied_confidence_threshold=0.5`) vs.
  raw leaf witnesses at `r` (`c2`):** Adding opt-in
  `tied_confidence_threshold: float | None = None` to `ProtoInventoryAssembler`
  (default `None`, bit-for-bit unchanged) expands `confidence <= 0.5` columns on
  disagreeing child reflexes into both competing proto-segments at equal mass.
  With the exact same `x` and `y` commitments as `a1`, `c1` rescues `r` from
  `4/8` to `8/8` primary (`10/10` validated exact, `10/10` `cognate_unit_exact`,
  `19` tuples / `104` projected columns vs `12` / `56`) AND preserves both
  `*k o` and `*k o t` in `r`'s beam on `L2` (`c012`), whereas raw leaf witness
  lookup at `r` (`c2`) rescues `R1`–`R4` (`⟨x Ø : y g⟩ → *k`) but is
  mechanically blocked from restoring `-t` on `L2`
  (`restoration-without-outgroup`).
- **Tree rotation vs. serialization order (`d1`):** Rotating `((a,b)x,(c,d)y)r;`
  to `((c,d)y,(a,b)x)r;` changes real information availability (`y` reconstructs
  first and enters `x`'s `OUTGROUP` evidence, raising `x` and `r` from `4/8` to
  `8/8`), whereas commitment order reversal, active-child swap `(b,a)` vs
  `(a,b)`, and single-form source duplication leave reconstructed forms
  invariant.
- **Banked live-model replays (`b-gemini`, `c-gemini-r04`,
  `c-local-qwen38-27b-r04`):** `tied_confidence_threshold=None` reproduces all
  three banked `output_beam`s at `x` bit-for-bit; `tied_confidence_threshold=0.5`
  expands only the `confidence <= 0.5` tied concepts (`w13, w08` in Stage B;
  `y05, y03, y09, y08` in Stage C) into `0.5 / 0.5` candidate pairs (`0`
  non-tied concepts changed, `+0` tuples at `r` in Stage B and `+3` tuples at
  `r` in Stage C).
  (3B-active MoE).

## R06 forward-prediction feasibility — completed 2026-10-30

[R06](research/forward_prediction_feasibility.md) (`r06-forward-v1`,
`r06-etymon-split-v1`, offline, 0 live model calls; evaluator
[`cognate_reconstruction/evaluation/forward.py`](../cognate_reconstruction/evaluation/forward.py),
fixture [`benchmarks/diagnostic/forward-prediction-v1.json`](../benchmarks/diagnostic/forward-prediction-v1.json),
probe [`tools/forward_prediction_probe.py`](../tools/forward_prediction_probe.py))
evaluated explicit parent-to-child cascades under the **inferred-ancestor
(masked-daughter reflex prediction)** regime, keeping the model-facing tool
surface (`628f0f32…`) unchanged.

- **Etymon-cluster splitting and withholding (`r06-etymon-split-v1`):**
  Partitions 17 concepts across 16 independent etyma into 8 development etyma
  (`d01`–`d08`) and 8 held-out test etyma (`t01`–`t08` validated, with `t07`
  and `t08` sharing `etym_t07` / `forward_prediction_v1:etym_t07`, plus `u01`
  underdetermined pan-sister merger control), deterministically refusing splits
  that separate shared non-affix cognate units across `dev` and `test`. Target
  daughter `a`'s held-out forms and all `historical_form_bindings` / answer-key
  rules are physically absent from `masked_payload` and all tool views (`ok = True`).
- **Observational equivalence vs. arbitrary labels (`h1` vs `h2` vs `h2b`):**
  Reconstructing `*r` from non-masked sisters `(b, c)` via `ProtoInventoryAssembler`
  with `*q` (`h1`) vs `*ɢ` (`h2`) for `⟨b ɢ : c ʔ⟩` yields `5/8` (`0.625`) raw
  proto-form exactness for `h2` against the generator's `*q`, but `1.000`
  corpus-wide aligned B-Cubed (`is_bijective_relabelling = True`) and **`8/8`
  (`1.000`, `0.0000` NED)** held-out reflex prediction on daughter `a` (recovering
  5 sister-unattested ancestor inputs and 6 sister-unattested reflexes).
  Conversely, held-out forward prediction cannot distinguish `*q` from `*ɢ` or
  one-step `q > x` from two-step `q > χ > x` (`h2b`, `8/8`) without an attested
  intermediate anchor.
- **Rejection of overfit, bleeding-order, and direct-sister baselines (`h3`–`h8`):**
  Memorized development hypotheses (`h4` with 2 lexical overrides; `h4b` with 0
  overrides and 6 single-etymon context rules) score `8/8` (`1.000`) in-sample on
  `dev` but collapse to **`1/8` (`0.125`)** on held-out `test`. Reversed bleeding
  order (`h3`, `i > e / _#` before `k > tʃ / _i`) and optimal single-sister
  cascades (`h7` `b -> a`, `h8` `c -> a`) score at most **`5/8` (`0.625`)** on
  held-out `test`.
- **Inferred vs. circular in-sample vs. given-ancestor oracle (`u01`):** On pan-sister
  merger `u01` (`*w a l a`, where both `b` and `c` merged `w > l / #_` while `a`
  shifted `w > v / #_`), `inferred_ancestor` (`a` masked) scores `0/1`, whereas
  unmasking `a` (`in_sample_circular_unmasked_check`) and supplying generator
  truth (`h10_privileged_given_ancestor_oracle`, `deployable_baseline = False`)
  score `1/1`.
- **Decision:** Retain the offline `r06-forward-v1` evaluator, residual context
  autopsy (`build_residual_autopsy`), and before/after cascade comparator
  (`compare_forward_hypotheses`); defer adding a model-facing forward-rule
  proposal tool or running live forward sweeps.

## R07 source-linked hypothesis critic — completed 2026-11-10

[R07](research/hypothesis_criticism_feasibility.md) (`r07-critic-v1`,
`r07-critic-corpus-v1`; evaluator
[`cognate_reconstruction/evaluation/critic.py`](../cognate_reconstruction/evaluation/critic.py),
corpus [`benchmarks/diagnostic/r07-hypothesis-critic-v1.json`](../benchmarks/diagnostic/r07-hypothesis-critic-v1.json),
probe [`tools/hypothesis_critic_probe.py`](../tools/hypothesis_critic_probe.py),
banked experiment [`runs/experiments/r07-hypothesis-critic-20261110/`](../runs/experiments/r07-hypothesis-critic-20261110/))
investigated source-linked claim-evidence and provenance discrepancy criticism
across the concrete failure modes demonstrated in R03–R06, separating a
deterministic trace/execution detector from a fallible LLM critic (`submit_hypothesis_critique`).

- **Balanced paired corpus & independent derivations (`18` packets):**
  6 `development` packets (`3` matched pairs `DP1`–`DP3`), 10 `held_out_evaluation`
  packets (`5` matched pairs `EP1`–`EP5`, randomized order `P04, P02, P01, P10, P09, P07, P06, P08, P03, P05`),
  and 2 `offline_held_out_scorer_only` boundary guards (`G01`–`G02`, mechanically
  refused by `to_model_visible_packet`). All 11 ground-truth checks are
  independently verified (`verify_independent_ground_truth`: `ok = True`) from
  Stage C Fitch parsimony, R05 log-mass arithmetic (`0.5063` vs `0.4937`), and
  R06 `RuleEngine` execution (`repaired = ['d01', 'd02']`, `newly_broken = ['d03']`)
  plus B-Cubed contrast equivalence (`*ɢ` vs `*q`).
- **Held-out evaluation comparison (`10` packets = `5` matched pairs `EP1`–`EP5`):**
  - `existing_residue_ambiguity_baseline`: `1/5` TP, `0/5` false objections, `1/5` pairs (`0.200`).
  - `fixed_evidence_checklist_baseline`: `1/5` TP, `3/5` false objections (`C02, C03, C05`), `0/5` pairs (`0.000`).
  - `deterministic_mechanical_detector` (Stratum A mechanical/navigation/provenance/execution only): `3/5` TP (`E02, E04, E05`), `0/5` false objections, `3/5` pairs (`0.600`).
  - `deterministic_full_trace_detector` (Stratum A + cross-node tie-confidence & unit-scoped outgroup witness rules): **`5/5` TP, `0/5` false objections, `5/5` pairs (`1.000`)** at `$0` cost and `< 0.01 s`.
  - `FakeCriticProvider` controls (`$0`): `accurate` (`5/5` TP, `0/5` FO, `5/5` pairs), `over_objecting` (`5/5` TP, `4/5` FO, `1/5` pairs), `verbose_relabeller` (`1/5` TP, `0/5` FO, `1/5` pairs), `hallucinated_pointers` (`0/5` actionable TP, `0.000` pointer validity).
  - **Single live `gemini/gemini-3.8-flash` (`medium` thinking) serial pass** (`runs/r07-gemini-r07-critic/`, launched after independent read-only review [`review.md`](../runs/experiments/r07-hypothesis-critic-20261110/review.md)): **`5/5` actionable TP (`100%` recall, `1.000` pointer validity, `1.000` defect pointer completeness), `1/5` false objection (`eval_c01_legitimate_parent_majority` `P06`), `4/5` matched pairs (`0.800`), `0.833` actionable precision**. Resources: `10` requests, `31,209` input tokens (`0` cached), `43,280` output tokens (`38,309` reasoning), **`US$0.185707`** certified table cost (vs `US$1.50` ceiling), **`344.5 s`** launcher wall time (vs `1,200.0 s` ceiling).
- **Decision (adopted in code):** `run_deterministic_full_detector` (`5/5` pairs at `$0`) is
  adopted and wired as the default offline post-run audit report
  (`DEFAULT_CRITIC_MODE = "deterministic_full"` in `run_default_hypothesis_critic`,
  `run_default_critic_report`, and `tools/hypothesis_critic_probe.py audit`);
  `submit_hypothesis_critique` is kept strictly as an optional, read-only
  human-facing narrative aid filtered by `filter_llm_assessment_with_deterministic_guard`
  (`apply_deterministic_guard=True` by default), and no LLM critic is wired into
  an autonomous repair loop.

## B01 pre-benchmark harness prep — completed 2026-11-11

`B01` (`prompts/01-real-family-harness-prep.md`, strictly offline, `$0` spend,
`0` live model calls; driver [`tools/real_family_benchmark_probe.py`](../tools/real_family_benchmark_probe.py),
tests [`tests/workbench/test_real_family_harness_prep.py`](../tests/workbench/test_real_family_harness_prep.py),
independent review [`runs/experiments/b02-burmish-gemini-benchmark/review.md`](../runs/experiments/b02-burmish-gemini-benchmark/review.md))
integrated the post-review `R05`–`R07` and `R03` §19.4 runtime/audit capabilities
into the live CLI and froze the staged `B02` Burmish benchmark bundle:

- **Tied-confidence beam retention wired end-to-end (`R05`):** `cli.py infer`
  exposes `--tied-confidence-threshold FLOAT` (`[0.0, 1.0)`, default `None`;
  joined into `configuration_sha256` only when `not None`, preserving historical
  digests bit-for-bit) and threads it into both `proto_assembly.py:assemble_node`
  and `AgenticNodeReconstructor` so preview and committed multi-level beams never
  diverge.
- **Alignment-safe run-directory critic bridge (`R07`):** `audit_run_directory`
  in [`cognate_reconstruction/evaluation/critic.py`](../cognate_reconstruction/evaluation/critic.py)
  and `python tools/hypothesis_critic_probe.py audit-run` audit completed runs,
  `--stop-after-node` checkpoints, and incomplete/stalled runs across five exact
  provenance/trace invariants (`silent_residue_drop_truncation`,
  `uninspected_outgroup_citation`, `unit_provenance_loss`,
  `identity_confidence_length_bias`, `upstream_tie_collapse_majority`) with zero
  synthetic Stage-B/C false positives on 2-child root nodes (`proto_burmish`,
  `proto_polynesian`) or sound-shifted outgroups. Offline verification: `0`
  defects on `c-gemini-r04`, `14` on `c-local-qwen36-35b-r04`, and `12`, `7`,
  `16`, `6` across the four banked pre-R01 Burmish seeds (`0` root outgroup false
  positives; full-form tone-preserving `R06` `corpus_bcubed_f1` baseline at
  `proto_burmish`: `0.4339 ± 0.0481`, `0/4` bijective).
- **Watermark-gated preview compaction (`R03` §19.4):** `cli.py infer` exposes
  `--compaction-watermark-tokens INT` (`>= 8192`, default `None`; `256000` for
  Gemini, `96000` for `128k`-window local Qwen; digest-joined only when `not None`).
  Below the watermark `_MessageLog.prompt` is untouched (100% prefix-cache reuse);
  at `>= watermark` older accepted superseded `test_proto_assembly`,
  `test_rule_cascade`, and `test_sound_law` previews are stubbed in
  `_MessageLog.prompt` while preserving `validation_id`/`inventory_id` handles,
  keeping `ok=false` rejections and newest previews verbatim, enforcing an
  `argument_sha256` repeat-call guard, and keeping `trajectories.jsonl`
  (`_MessageLog.audit`) completely uncompacted.
- **Frozen `B02` candidate bundle (`runs/experiments/b02-burmish-gemini-benchmark/`):**
  Supports single-checkpoint `--stop-after-node maruic` (`$3.50` cap, `1,500 s`)
  -> `$0` `gate-stage1` -> `--resume` (`$8.50` cumulative cap, `3,600 s`, worst-case
  uncached upper bound `US$8.50 + US$0.909312 = US$9.409312 <= US$10.00`; tones
  100% intact).

## B02 live Burmish Stage 1 gate, forensics, and bounded runtime bugfixes — completed 2026-11-11

[B02](research/real_family_benchmark_burmish.md)
([machine results](research/real_family_benchmark_burmish_results.json);
banked artifacts and post-run independent review in
`runs/experiments/b02-burmish-gemini-benchmark/`) ran the pre-registered Stage 1
gate (`--stop-after-node maruic --max-total-cost-usd 3.50 --max-run-seconds 1500
--compaction-watermark-tokens 256000 --tied-confidence-threshold 0.5`) on
`benchmarks/burmish.json` (`tones_preserved = true`) with
`gemini/gemini-3.8-flash` (`medium` thinking, `max_tokens = 32768`,
`stored-hypothesis`, `configuration_sha256 = 89a490658839…`):

- **Clean Stage 1 gate halt (`US$1.2368` actual cached spend; `US$0.00` downstream waste):**
  Across `22` requests (`22` turns, `20` executed tool calls, `2` rejected calls,
  `1` truncated response at `32,764` output tokens, `4,434,603` input tokens with
  `3,588,670` cached [`80.92%`], `88,855` output tokens [`36,099` reasoning],
  `696.13 s` wall time), Turn 22 (`input_tokens = 483,849`) returned a
  `14,873`-output-token repair call that pushed cumulative uncached table cost
  from `US$3.2405` to **`US$3.6592 >= US$3.50`** (`US$1.2368` cached-adjusted),
  raising `RunBudgetExceeded` pre-dispatch (`history_certified = True`, `0`
  unknown-cost requests). `gate-stage1` marked `usable = False`, halting cleanly
  before `burmic` and `proto_burmish` with no automatic rerun.
- **Root-cause diagnosis across three strata:**
  1. **Four concrete runtime bugs (repaired offline in `B02` at `$0`):**
     `proto_assembly.py:assembly_result` retained full `source_positions` on
     `unmatched_columns` under `detail="summary"` (`245,995 B` compact = `92.1%`
     of Turn 17's `267,149 B` preview); `orchestrator.py:_supersedes` compared
     un-normalized raw arguments and required exact `limit` equality (`+68,897 B`
     / `+38,226` tokens on Turn 16 vs Turn 2); `_compact_watermark_previews`
     rewrote `805 B` empty identity probes into `873 B` stubs (`+68 B`), busting
     Gemini's prefix cache on Turn 19 (`246,893 -> 15,135` cached tokens,
     `US$0.3274` single-turn spend); and pre-dispatch `RunBudgetExceeded` left
     `compaction_summary.peak_prompt_tokens` (`468,811`) behind
     `max_request_input_tokens` (`483,849`) and omitted Turn 22's paid message
     from `trajectories.jsonl`. All four are fixed with zero behavioural or
     `configuration_sha256` digest change (`15 passed` in
     `test_real_family_harness_prep.py`; **`887 passed, 41 deselected`** across
     the portable suite; Wave 2 independent review verdict: `PASS`, `0` defects).
  2. **`units-v2` 738-set scaling & linguistic forensics (deferred to `B03`):**
      Gemini preserved 100% of surface tone contours across Turn 21's `55`
     `shared_claims` (`0` tone stripping) and polarized stop-coda debuccalization
     (`*-k > -ʔ`), while missing Maruic creaky-register reflexes of `*ˀm/*ˀŋ`
     because `40/42` (`95.2%`) creaky-vowel (`V̱`) `csp-*` patterns have
     `support == 1` (`0` multi-daughter `V̱` patterns at `support >= 2`) whereas
     `67/113` (`59.3%`) `support >= 2` patterns are 1-daughter compound/affix
     singletons. `$0` deduplicated replay of Turn 21 (`394/738` sets,
     `unaccounted_column_rate = 0.4431`) shows `inventory_contrast_reductions`
     flags `346/394` (`87.8%`) sets for `missing-directionality-rationale`
     (`commit_ready = False`), and Turn-22 prompt attribution (`299,041` tokens
     [`61.8%`] in uncompacted read-only pages; `458,599` non-signature tokens,
     crossing `116,626` on Turn 4) proves `96,000`-watermark / `128k`-context
     local `qwen3.8-27b-splash` cannot run `units-v2` `burmish.json` prior to
     `B03`.
  3. **Uncached-vs-cached cap calibration:** `pricing.py`'s deliberate uncached
     table check turned `--max-total-cost-usd 3.50` into a `US$1.18` real-cash
     cap at `80.92%` cache hit (two of the four pre-R01 `maruic` seeds also
     exceeded `US$3.50` uncached: `US$4.1120` and `US$3.9012`).

## Authority and reading order

This file summarizes implemented behavior and accepted decisions.
The session handoff (`docs/session_handoff.md`, a local, untracked file) carries
live task status, unfinished steps and amendments for later sessions; where it
exists, read it when starting or resuming work.
[Research plan](research_plan.md) defines the work packages and dependencies;
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
versioned trajectories (new 5.0, with 2.0/3.0/4.0 readable), reports, and completed-node resume.
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

## Task 01 findings, verified 2026-10-02

Failure audit (`docs/research/failure_audit.md`, local only) fixes a 12-concept panel and provides
source/column traces (`docs/research/failure_audit_traces.md`, local only). The new read-only
`tools/failure_audit.py` accepts supplied result paths, checks scores with the
existing all-alternative metric and optionally replays deterministic assembly.
All four saved inputs match their checkpoints; all 364 scored-concept flags and
top edit distances/NED agree. Eleven committed beams and reports replay exactly.
Original run artifacts are unchanged; no inference, downloads or paid calls ran.

The root zero has several causes. All 216 root top predictions disagree with
gold's tone-token sequences, but superscript-only token removal fixes just 16
top comparisons (seven distinct concepts). Source-backed category/contour mapping
is still needed; token disagreement does not prove historical tone error.
CRAWL and FLOWER demonstrate changed morpheme pairing between survey and assembly,
and every intermediate lexicon lacks inherited memberships. Simple controls and
SNOT also expose independent tone/phonological choices. NEEDLE's support-1 Maruic
initial is actually discarded by an Atsi-witness gap, while its exact Burmic
candidate reaches root unchanged and the root explicitly reassigns its tone.

No exact root gold was generated before final beam pruning; all retained input
tuples were enumerated at every committed node. Final pruning is not a demonstrated
cause here. r2/00's Maruic protocol fallback must be disclosed in root provenance;
three fully committed runs still give zero root hits. Old Burmese remains a
provisional proxy. Saved proxy gold already normalizes grapheme/phoneme slash
tokens, so the older unnormalized-source warning does not explain these scores.

Next priorities are 02's evaluation/notation contract, a bounded 03 repair for
traced unit/provenance defects, and 05's explicit sparse/polarity instructions.
These are proposals, not implemented improvements. No largest whole-benchmark
causal effect is established. Read the handoff amendments before downstream work.

## Task 02 evaluation, verified 2026-10-02

Evaluator `task02-v1` is implemented. Read the
[contract](research/evaluation_contract.md), [results](research/evaluation_results.md)
and [migration/commands](research/evaluation_migration.md). Raw exact/NED,
all alternatives and per-word B-Cubed retain their definitions. All 364 saved
Burmish concept score records reproduce unchanged; root remains 0/216, proxy
1/148, with 16/216 segment-only diagnostic hits. Original result/event hashes
are unchanged. Outside-selection IDs/counts and eligible concepts are visible;
the best-daughter selector is labelled gold-assisted oracle. Copying commits
remain commitments. No historical source mapping or model improvement is claimed.

Old Burmese at `burmic` has an explicit provisional-proxy annotation; its raw
score remains while validated-target summaries exclude it. Missing legacy
annotations remain unknown except the documented exact-identity proxy migration.
New family results and sweep views distinguish quality at committed nodes from
end-to-end planned-set coverage, direct fallback, unknown commitment and missing
outputs. Ancestors consuming fallbacks name those descendants; r2/00 root now
reports `maruic`. Abandoned runs can salvage completed stored steps faithfully.
Legacy provider causes stay unknown/unspecified. `inspect-run` text/HTML also
surface proxy and dependency labels for banked artifacts.

Superscript-token diagnostics retain task01-v1 and make ambiguous notation,
unmarked tones, unknown output memberships and OLD MAN scope visible. No tone
category/contour or phonation equivalence is licensed. Morphemes use a separate
complete-piece comparator with independently supplied IDs; real output analysis
awaits task 03. Corpus mapping consistency is deferred; per-word B-Cubed tests
repetition only and can be perfect despite contradictions across words.

Six new diagnostic cases cover complementary retention, conditioning, unequal/
reordered morphology, two-level propagation, identity and unrecoverable contrast.
They state restricted identifiability assumptions, preserve separate keys, and
exclude unrecoverable contrast and morphology order from unique-answer summaries.
Identity scores 0/6 on complementary retention and 3/18 across propagation nodes;
perfect/wrong controls are score fixtures, not live-model performance.
Old synthetic definitions are untouched. Focused checks: 106 passed; portable
suite: 571 passed, 41 deselected, one run. Zero live/paid calls or downloads.

Task 03 is ready under this contract; 05/06 have independent work, and 07 awaits
those interventions before a frozen comparison. See tracked handoff amendments.

## Task 03 evidence, verified 2026-10-03

Task 03 is delivered: [results](research/evidence_results.md) and
[migration](research/evidence_migration.md). units-v1 shares typed pieces and exact
column bindings through parent evidence, with unknown analyses explicit. Final
portable checks: 588 passed/41 deselected; a final provenance guard received 41
focused checks. All eleven old beams/reports replay exactly. Source-unit controls
repair CRAWL/FLOWER pairing but do not increase three-concept proxy exact (1/3).
Exactly one local Gemma smoke had two accepted previews and no valid commit,
ending on ProtocolStallError after 597.3 s. No broad quality improvement is claimed.
Partial scopes can lower support/pooling and increase tool costs; compare these
readings explicitly in 07. Task 05 has concrete malformed-call examples to repair.

## Task 04 evidence repair, verified 2026-10-04

[Evidence repair](research/evidence_repair.md) and
[machine results](research/evidence_repair_results.json) reproduce all review
counterexamples and repair independent-support counts, false mergers, local witnesses
and normal morphology scoring. Exact local scopes remain; default descriptive
recurrence rows support explicit `shared_claims` collections, with local exceptions
and competing conditioned values. No tuple silently assigns cognacy.

Count semantics are `independent-etyma-v1`: supplied etyma, unresolved concept/unit
opportunities, concepts, positioned source combinations and alternative execution
occurrences are distinct. Whole/full-span simplex annotation geometry is equivalent.
Burmic/Maruic retain 543/738 local sets and expose 210/320 patterns. Default filters
cover all 54 concepts but only 437/567 and 1033/1340 alternative occurrences. Sparse
material remains inspectable/committable; these counts are not a quality estimate.

The normal scorer receives hidden target layouts and actual approved parent pieces
through JSONL; correct/wrong/extra/missing/reordered scripted controls pass. Raw
scores and underdetermined order/lost contrast are retained. Trajectories/checkpoints
write 5.0/3.0; old records remain readable, but old checkpoints and units-v1
execution are explicitly refused under current semantics. Both commit shapes and
legacy replay remain. Final portable suite: 607 passed/41 deselected. All 364 banked
scores, eleven beams/reports and four result/event hash pairs reproduce unchanged.
No live inference/provider/model operations occurred. Task 05 owns the next live
smoke and broader protocol/guidance. 07 needs final usability, instrument/cap/manifest
checks and another independent review after 04/05 and relevant 06 work.

## Task 06 recovery, verified 2026-10-05

[Provider recovery](research/provider_recovery.md) and
[results/hashes](research/provider_recovery_results.json) deliver structured conservative
causes, bounded attempts/elapsed time, Retry-After, cancellation during backoff and
no automatic replay of uncertain transport responses. SDK retries are disabled.
Exhaustion/auth/quota stop the tree; protocol identity fallback remains labelled.
No linguistic hypotheses or score definitions changed, and no inference ran.

Completed nodes survive interruption. Exact matching finalized JSONL receipts can
close the checkpoint-write crash window; ancestor receipt chronology prevents
laundering earlier fallback use. Resume does not repeat completed node calls/output
or completion events. New 3.0 checkpoints declare operational-retry-v1 and log changed
retry controls; unmarked 3.0 keeps strict retry hashes, and 1.0/2.0 remains unsafe.
Instructions, schemas, node notes, evidence/backend/version, inputs, sampler/model
and model-visible budgets remain strict. Truncation token overrides are semantic.

Atomic run_summary.json reports incomplete status, structured reason, attempted/
completed/unattempted nodes, cost coverage and full planned-set missing evaluations.
Current trajectory IDs prevent stale fallback-dependent ancestor salvage after a
resumed interruption. Sweeps separate interruption, direct fallback, ancestor
provenance and conditional versus end-to-end task02-v1 views. VOID-marked t36/t36b
quality is excluded even with a root commit; raw audit data remains readable.
Caps are cumulative per seed across recorded resumes, not experiment-wide; missing
cost/history cannot silently restart a capped seed's spend at zero. One synchronous
request still needs timeout support and one-response cost headroom.

Validation: 206 focused passes; one portable run, 680 passed/41 deselected.
No provider/API calls, model operations or downloads. Task05's final interface
hashes remain unchanged; its live usability gate and task07's final review remain.

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
4. **New inventories share units-v2 evidence and execution.** Source/model-approved
   pieces and exact column bindings survive into parent beams. Unknown analysis
   stays unknown; compatible claims merge provenance and incompatible claims stay
   separate. Legacy artifacts keep their whole-string interpretation. See the
   [contract](research/evidence_contract.md) and [migration](research/evidence_migration.md).
5. **The runtime prompt now corrects the representational claim.** Rules can emit
   new literal tokens/sequences; empty targets remain forbidden. Task05 qualifies
   sparse/outgroup/morphology judgments and changes instruction/schema/checklist
   hashes separately from task04's evidence repair. Scientific benefit is untested.
6. **Provider interruption is separate from model protocol failure.** Task06 stops
   provider exhaustion/auth/quota/cancellation without walking identity fallbacks.
   Completed-node-only resume preserves semantic hashes; new checkpoints permit
   recorded retry-only changes. Old cause metadata stays unknown/unspecified.
7. **Statistics are exploratory.** Small, nested samples and multiple changed
   settings do not establish causal effects of model or commit shape. Failure
   exclusions can bias comparisons. Task02-v1 reports conditional quality and
   end-to-end outcomes with explicit denominators; sampling/causal limits remain.
8. **B-Cubed is currently per word.** It measures aligned repetition structure;
   high scores are not evidence of consistent phoneme mappings across a lexicon.
9. **Shared-innovation reports remain deferred.** The specific proposal in
   `shared_innovation_note.md` is not implemented; existing cross-node reports
   are not equivalent to it. A derived inverse rule is not by itself proof of
   a historically shared innovation.

## What is next

All historical `Task01`–`Task06` and post-review `R01`–`R07` work packages are
complete on `main`. Because both `gemini/gemini-3.8-flash` (`medium` thinking)
and local dense `qwen3.8-27b-splash` achieved `100%` (`18/18` on Stage B and
`19/19` on Stage C) on the synthetic diagnostic panels, the next phase
(`B01`–`B02` in `prompts/`) moves to **real multi-level language family
benchmarking**:

1. **`B01` (`prompts/01-real-family-harness-prep.md`, offline — completed 2026-11-11):**
   Wired `--tied-confidence-threshold` across both `proto_assembly.py` and
   `reconstructor.py`, added `audit_run_directory` and
   `hypothesis_critic_probe.py audit-run`, added watermark-gated preview
   compaction (`--compaction-watermark-tokens`) in `AgentOrchestrator`, and froze
   `runs/experiments/b02-burmish-gemini-benchmark/` (`<= US$10.00` upper-bound
   ceiling, verified by independent read-only review).
2. **`B02` (`prompts/02-real-family-live-benchmark.md`, live Stage 1 gate & bounded fixes — completed 2026-11-11):**
   Executed Stage 1 (`maruic`) on `benchmarks/burmish.json` (`US$1.2368` cached /
   `US$3.6592` uncached spent; `US$0.00` wasted downstream), repaired the four
   runtime bugs exposed on `maruic` (`proto_assembly.py` summary
   `unmatched_columns` slimming, `_supersedes` default-normalized pagination
   containment, `MIN_PREVIEW_COMPACTION_SAVINGS_BYTES = 256` prefix-cache guard,
   and pre-dispatch `RunBudgetExceeded` peak-token/audit flush; `887 passed, 41
   deselected`), and published [B02 report](research/real_family_benchmark_burmish.md).
3. **Recommended next sequence (`B03` -> `polynesian.json` -> `burmish.json`):**
   - **`B03` (offline `$0` scaling & cost-cap package):** Add incremental/patch
     `stored-hypothesis` assembly updates (`base_hypothesis_id`), refine
     `inventory_contrast_reductions` so unanimous and 1-daughter boundary
     retentions do not require hundreds of directionality rationales, compact
     older disjoint read-only survey pages above the watermark, surface
     multi-daughter `support == 1` phonation/creaky-register patterns separately
     from 1-daughter compound singletons, and support verified-cached cost-cap
     enforcement.
   - **Live `benchmarks/polynesian.json` (`gemini/gemini-3.8-flash` + `96k`-watermark local `qwen3.8-27b-splash`):**
     Test 5-level post-order propagation (`7` internal nodes, simplex lexicon,
     `46k–93k` measured prompt peaks fitting within `96k`/`128k`) and `$0`
     `None` vs `0.5` counterfactual tied-beam replay end-to-end.
   - **Re-benchmark `benchmarks/burmish.json`** after `B03` brings `maruic` and
     `burmic` context and output footprints within compact single-node bounds.
