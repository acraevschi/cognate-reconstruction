# R07 — Source-Linked Hypothesis Criticism and Evaluation Prototype

- **Date:** 2026-11-10
- **Stage:** R07 (Optional source-linked hypothesis critic and evaluation prototype)
- **Evaluator Version:** `r07-critic-v1` ([`cognate_reconstruction/evaluation/critic.py`](file:///Users/acraev/Work/cognate-reconstruction/cognate_reconstruction/evaluation/critic.py))
- **Corpus Version:** `r07-critic-corpus-v1` ([`benchmarks/diagnostic/r07-hypothesis-critic-v1.json`](file:///Users/acraev/Work/cognate-reconstruction/benchmarks/diagnostic/r07-hypothesis-critic-v1.json), SHA-256 `a014260da8e25107245c2c59ef358beed4a216cfbe5cb9c42c5a5a359cf0faa7`)
- **CLI Probe:** [`tools/hypothesis_critic_probe.py`](file:///Users/acraev/Work/cognate-reconstruction/tools/hypothesis_critic_probe.py)
- **Machine-Readable Results:** [`docs/research/hypothesis_criticism_feasibility_results.json`](file:///Users/acraev/Work/cognate-reconstruction/docs/research/hypothesis_criticism_feasibility_results.json)
- **Banked Live Experiment Directory:** [`runs/experiments/r07-hypothesis-critic-20261110/`](file:///Users/acraev/Work/cognate-reconstruction/runs/experiments/r07-hypothesis-critic-20261110/)
- **Live Paid Model Calls:** `1` serial trial (`R07-gemini-r07-critic`, `gemini/gemini-3.8-flash`, `thinkingLevel: "medium"`, `10` requests across `10` held-out packets, `31,209` input tokens, `43,280` output tokens, certified table cost **`US$0.185707`** vs `US$1.50` ceiling, launcher wall time **`344.5 s`** vs `1,200.0 s` ceiling)

---

## 1. Selected Error Class and Motivation from R03–R06

Across the banked model diagnostics (R03, R04, R04b, R04c) and the offline two-level propagation (R05) and forward-prediction (R06) studies, the harness already preserves observed daughter forms, cognate-unit memberships (`cog:*`), alignment column bindings, tool-call trajectories, deterministic `RuleEngine` execution, and versioned beam outcomes. Those studies showed that the primary bottlenecks in LLM-assisted reconstruction are **concrete, auditable discrepancies between a hypothesis's stated rationale and its underlying trace/execution provenance**, rather than an inability to write fluent prose or a need for a standalone reflex-prediction benchmark.

Accordingly, R07 selects **source-linked claim-evidence and provenance discrepancy criticism** across two explicit epistemic strata:

### Stratum A — Exact Mechanical, Navigation, Provenance, and Execution Defects (`exact_mechanical`)
1. **`uninspected_outgroup_citation`** (*R04c `c-local-qwen36-35b-r04` `y01`*): A committed or previewed claim cites outgroup corroboration in its rationale when `trajectory_navigation_summary.concept_outgroup_forms_seen` is `False` (the trajectory never inspected outgroups for that concept).
2. **`silent_residue_drop_truncation`** (*R03 `a-local-122b`, R04c `c-local-qwen36-35b-r04`*): Committing a subset of local correspondence sets (`13/57` `csu-*` sets) under `residue_policy: "drop"` silently truncates uncommitted columns and concepts (`unaccounted_column_rate = 0.5667`, `dropped_concept_ids` non-empty).
3. **`unit_provenance_loss`** (*R05 Arm `b2`*): Intermediate node assembly emits `assembled_candidate_unit_id = "whole:unknown"` (`cognate_set_id = None`) when active child inputs carry explicit `cog:*` provenance, preserving raw string exactness while collapsing downstream unit-scoped alignment (`0/10` unit exact, `8 unit_missing`).
4. **`identity_confidence_length_bias`** (*R05 `L2` `c012` operational weight sensitivity*): Committing unanimous identity correspondences (`[t, t] -> *t`) at `confidence < 1.0` (`0.95`) imposes an extra `log(0.95)` column-length penalty on longer candidates (`*k o t`, 3 columns, `p = 0.4937`) relative to shorter candidates (`*k o`, 2 columns, `p = 0.5063`), breaking a genuine `0.5000 / 0.5000` tie.
5. **`counterexample_or_bleeding_order`** (*R06 `forward-prediction-v1` `h3_wrong_order_bleeding`*): Forward cascade ordering (`i > e / _ #` before `k > tʃ / _ i`) bleeds palatalization on `d01` (`*p a k i`) and `d02` (`*f a k i`), while an over-broad patch (`k > tʃ / _ e`) repairs `d01, d02` at the cost of newly breaking `d03` (`*p a k e -> *p a tʃ e` vs observed `p a k e`).

### Stratum B — Comparative Inference Discrepancies (`warranted_inference_critique`)
6. **`upstream_tie_collapse_majority`** (*R05 / Stage C `T1` `y05`, `T2` `y03`*): When child node `x` commits a `1–1` leaf tie (`a:y05` `s i k` vs `b:y05` `s i`) at `confidence <= 0.50` under single-winner assembly (`tied_confidence_threshold = None`), `x` emits a single winner (`probability = 1.0`), turning a whole-tree `2-vs-2` tie at root `r` into an apparent `2-of-3` active-child majority (`x:y05, d:y05` vs `f:y05` at `confidence = 0.90`).
7. **`wrong_unit_or_lookalike_support`** (*R04 Stage C `K8` `y14`, `y01`*): Polarizing a stem correspondence (`cog:cs312` on `y14`) by citing a surface segment from a heteromorphemic suffix unit (`cog:cs338` `kʰ a` in compound `f:y14` `t e + kʰ a`) or from a non-cognate replacement unit (`cog:cs351`, `cog:cs323` on `y01`), contradicting the `2-of-3` same-unit outgroup majority.
8. **`false_confident_tie_or_misread_absence`** (*R03c `b-local-qwen` `w01`*): Treating segment absence (`Ø` in `c:w01` `s o` within `cog:stage_b_v1:w01`) as "no outgroup evidence" or asserting `confidence > 0.50` on a `1–1` active-child split when same-unit outgroups are tied (`1–1`).

---

## 2. Architecture and Evidence-Boundary Guarantees

Implemented in [`cognate_reconstruction/evaluation/critic.py`](file:///Users/acraev/Work/cognate-reconstruction/cognate_reconstruction/evaluation/critic.py) and [`tools/hypothesis_critic_probe.py`](file:///Users/acraev/Work/cognate-reconstruction/tools/hypothesis_critic_probe.py):

1. **Strict Separation of Deterministic Detector vs. Fallible LLM Critic:**
   - `run_deterministic_mechanical_detector(packet)` checks only Stratum A mechanical, navigation, provenance, length-bias, and forward-execution invariants (`is_fallible_interpretation = False`, `uncertainty_label = "exact_mechanical"`).
   - `run_deterministic_full_detector(packet, *, include_comparative_trace_rules=True)` adds deterministic cross-node tie-confidence (`prior_node_commit_summary.confidence <= 0.50`) and unit-scoped outgroup witness counting (`same_unit_as_target`, `piece_breakdown`), labeling comparative findings as `warranted_inference_critique` (and is wired as the default in `run_default_hypothesis_critic`, `run_default_critic_report`, and `tools/hypothesis_critic_probe.py audit` via `DEFAULT_CRITIC_MODE = "deterministic_full"`).
   - `run_llm_critic_on_packet(packet, provider, *, apply_deterministic_guard=False)` sanitizes the packet via `to_model_visible_packet(packet)` and prompts an `LLMProvider` using the structured tool `submit_hypothesis_critique`. Every LLM-derived `CriticAssessment` is marked `is_fallible_interpretation = True`; when called via `run_default_hypothesis_critic(..., mode="llm", apply_deterministic_guard=True)`, `filter_llm_assessment_with_deterministic_guard` strips any hallucinated pointers and enforces the deterministic epistemic `uncertainty_label` (`warranted_inference_critique` on Stratum B comparative categories vs `exact_mechanical` on Stratum A categories).
2. **Evidence-Channel Boundary (`EvidenceChannel`):**
   - Every packet carries an explicit `evidence_channel`: `inference_available_daughter_fitting` (observations and trace records already visible during bottom-up inference) or `offline_held_out_scorer_only` (privileged generator/oracle residuals).
   - `to_model_visible_packet(packet)` mechanically refuses any `offline_held_out_scorer_only` / `offline_gold_residual_only` packet (`G01`, `G02`) with a `ValueError` and strips `ground_truth`, `pair_id`, `pair_role`, `origin_artifact`, and internal `packet_id` strings.
   - `verify_no_critic_leakage(packets, visible_packets)` audits serialized prompts and visible payloads to certify zero exposure of held-out scorer packets, ground-truth fields, or internal IDs before any model call.
3. **Non-Mutating Forward Revision and Contrast-Equivalence Integration (R06):**
   - `evaluate_forward_revision_on_packet(...)` calls `evaluate_forward_split`, `compare_forward_hypotheses`, `build_residual_autopsy`, and `compute_corpus_contrast_equivalence` from [`cognate_reconstruction/evaluation/forward.py`](file:///Users/acraev/Work/cognate-reconstruction/cognate_reconstruction/evaluation/forward.py) (`r06-forward-v1`) on copies of inference-available forms, reporting both `repaired_concept_ids` and `newly_broken_concept_ids` without mutating any original hypothesis or banked run directory.

---

## 3. Balanced Paired Corpus and Independent Ground-Truth Derivations

The offline corpus ([`benchmarks/diagnostic/r07-hypothesis-critic-v1.json`](file:///Users/acraev/Work/cognate-reconstruction/benchmarks/diagnostic/r07-hypothesis-critic-v1.json)) contains **18 packets**:
- **Development split (`development`):** 6 packets = 3 matched pairs (`DP1`–`DP3`, blind codes `D01`–`D06`), used for developing and tuning deterministic rules and prompt instructions.
- **Held-out evaluation split (`held_out_evaluation`):** 10 packets = 5 matched pairs (`EP1`–`EP5`, blind codes `P01`–`P10`), presented in deterministic non-alternating order `['P04', 'P02', 'P01', 'P10', 'P09', 'P07', 'P06', 'P08', 'P03', 'P05']` (`seed = 20261110`).
- **Offline gold boundary guards (`offline_gold_residual_only`):** 2 packets (`G01`–`G02`), verifying that held-out answer-key residuals and unrecoverable pan-sister merger oracle labels (`u01` `*w a l a` vs `*l a l a`) are blocked from reaching any inference-time critic.

| Split | Pair ID | Defective Packet (Blind Code) | Defect Category | Paired Legitimate Control (Blind Code) | Legitimate Trap Tested | Origin Artifact / Trace |
|---|---|---|---|---|---|---|
| `dev` | `DP1` | `dev_d01_defect_silent_residue_drop` (`D01`) | `silent_residue_drop_truncation` (`13/57` sets, `56.67%` dropped) | `dev_d01_legit_complete_local_coverage_drop` (`D02`) | `residue_policy: "drop"` with `57/57` coverage (`0.0%` dropped) | `r04c-local-qwen36-35b` vs `r04-stage-c` `c-gemini-r04` |
| `dev` | `DP2` | `dev_d02_defect_unit_provenance_loss` (`D03`) | `unit_provenance_loss` (`cog:*` -> `whole:unknown`) | `dev_d02_legit_unknown_leaf_analysis` (`D04`) | Unknown leaf analysis (`whole:unknown` -> `whole:unknown`) | R05 Arm `b2` (`two-level-propagation-v1` `c001`) |
| `dev` | `DP3` | `dev_d03_defect_misread_outgroup_absence` (`D05`) | `false_confident_tie_or_misread_absence` (`c:w01` `s o` misread as no outgroup) | `dev_d03_legit_repeated_retention_and_singleton_unit` (`D06`) | Repeated identical retention (`[p, p] -> *p`) + singleton support (`support = 1`) | `r03c-local-qwen` `b-local-qwen` vs `r03` `b-gemini` `w01` |
| `eval` | `EP1` | `eval_e01_upstream_tie_collapse` (`P02`) | `upstream_tie_collapse_majority` (`x:y05` `0.50` tie -> `r:y05` `0.90` majority) | `eval_c01_legitimate_parent_majority` (`P06`) | Legitimate `2-of-3` / `3-of-5` parent majority (`y07`, `x` polarized at `0.85`) | R05 / Stage C `T1` `y05` vs `y07` (`c-gemini-r04`) |
| `eval` | `EP2` | `eval_e02_uninspected_and_wrong_unit_outgroup` (`P08`) | `uninspected_outgroup_citation` + `wrong_unit_or_lookalike_support` (`y01`) | `eval_c02_legitimate_inspected_shifted_outgroup` (`P01`) | Inspected shifted velar (`c:y04` `p a g` in `cog:cs379`) with missing outgroups `d, f` | `r04c-local-qwen36-35b` `y01` vs `r04` `c-gemini-r04` `y04` |
| `eval` | `EP3` | `eval_e03_suffix_lookalike_scope_confusion` (`P05`) | `wrong_unit_or_lookalike_support` (`f:y14` `t e + kʰ a` suffix `cog:cs338` vs stem `cog:cs312`) | `eval_c03_genuine_tie_and_child_swap_invariance` (`P07`) | Genuine `1–1` tie (`y09`, `0` same-unit outgroups) at `confidence = 0.50` under `(b, a)` child-order swap | Stage C `K8` `y14` vs `r04b-local-qwen38-27b` `y09` |
| `eval` | `EP4` | `eval_e04_identity_confidence_length_bias` (`P03`) | `identity_confidence_length_bias` (`0.95` identity -> `0.5063` `*k o` vs `0.4937` `*k o t`) | `eval_c04_equal_length_and_provisional_proxy` (`P09`) | Equal-length candidate (`*l o k` on `c009`) + disagreement with single `provisional_proxy` (`l u k`) | R05 `two-level-propagation-v1` `c012` vs `c009` |
| `eval` | `EP5` | `eval_e05_bleeding_order_and_leaky_revision` (`P10`) | `counterexample_or_bleeding_order` (`repaired=['d01','d02']`, `newly_broken=['d03']`) | `eval_c05_bijective_proto_relabelling` (`P04`) | Bijective proto-symbol relabelling (`*ɢ` vs `*q`, `B-Cubed F1 = 1.0`, `dev_exact = 1.0`) | R06 `forward-prediction-v1` `h3_wrong_order_bleeding` vs `h2_alt_symbol_G` |
| `gold` | `GP1` | `gold_g01_held_out_scorer_residual_guard` (`G01`) | Refused at boundary (`offline_held_out_scorer_only`) | `gold_g02_unrecoverable_parallel_merger_oracle_guard` (`G02`) | Refused at boundary (`u01` pan-sister merger oracle) | R06 `forward-prediction-v1` held-out `t01`–`t08` & `u01` |

### Independent Ground-Truth Verification
Rather than copying detector outputs, `verify_independent_ground_truth()` in [`tools/hypothesis_critic_probe.py`](file:///Users/acraev/Work/cognate-reconstruction/tools/hypothesis_critic_probe.py) independently derives all 11 ground-truth checks (`ok = True`, `11/11` passed):
- **Stage C Fitch parsimony (`y01, y03, y04, y05, y07, y09, y14`):** Recomputes same-unit outgroup counts directly from `benchmarks/diagnostic/stage-c-multi-outgroup-v1.json` and verifies agreement with `opp["expected"]` (`y04 -> retain` `1/1`; `y05 -> unresolved` `1/2`; `y14 -> absent` `1/3` in `cog:cs312`; `y07 -> retain` `2/3`; `y09 -> unresolved` `0/0`; `y01 -> absent` `0/1`; `y03 -> unresolved` `1/2`).
- **R05 log-mass arithmetic (`eval_e04`):** Recomputes `m_short = 0.25 * 0.95^2 * (1 + 0.5 + 0.5)` and `m_long = 0.25 * 0.95^2 * (0.5 + 0.5 + 0.95)` across the 4 child-beam tuples on `c012`, normalizing to `[0.5063, 0.4937]` at `confidence = 0.95` vs `[0.5000, 0.5000]` at `confidence = 1.0`.
- **R06 `RuleEngine` execution and B-Cubed equivalence (`eval_e05`, `eval_c05`):** Executes `evaluate_forward_revision_on_packet` on `d01`–`d08` of `benchmarks/diagnostic/forward-prediction-v1.json`, verifying `mismatched_concept_ids = ['d01', 'd02']`, `repaired_concept_ids = ['d01', 'd02']`, `newly_broken_concept_ids = ['d03']` on `eval_e05`, and `dev_exact_rate = 1.0`, `is_bijective_relabelling = True`, `corpus_bcubed_f1 = 1.0` on `eval_c05`.

---

## 4. Quantitative Results: Baselines, Deterministic Detectors, Fake Controls, and Live `gemini-3.8-flash`

### 4.1 Development Split Results (`6` packets = `3` matched pairs `DP1`–`DP3`, `0` paid calls)

| Critic / Baseline Arm | Type | Actionable TP (`/3`) | Missed Defects (`/3`) | False Objections (`/3`) | Actionable Precision | Pointer Validity | Matched Pairs Both Correct (`/3`) |
|---|---|---:|---:|---:|---:|---:|---:|
| `existing_residue_ambiguity_baseline` | Surface baseline | `1/3` | `2` (`D03, D05`) | `0/3` | `1.000` | `1.000` | `1/3` (`0.333`) |
| `fixed_evidence_checklist_baseline` | Rigid checklist baseline | `1/3` | `2` (`D03, D05`) | `2/3` (`D04, D06`) | `0.333` | `1.000` | `1/3` (`0.333`) |
| `deterministic_mechanical_detector` | Exact mechanical detector | `2/3` | `1` (`D05`) | `0/3` | `1.000` | `1.000` | `2/3` (`0.667`) |
| `deterministic_full_trace_detector` | Mechanical + witness detector | **`3/3`** | **`0`** | **`0/3`** | **`1.000`** | **`1.000`** | **`3/3` (`1.000`)** |
| `FakeCriticProvider("accurate")` | Scripted control (`$0`) | `3/3` | `0` | `0/3` | `1.000` | `1.000` | `3/3` (`1.000`) |
| `FakeCriticProvider("over_objecting")` | Scripted control (`$0`) | `3/3` | `0` | `2/3` (`D04, D06`) | `0.600` | `1.000` | `1/3` (`0.333`) |
| `FakeCriticProvider("verbose_relabeller")` | Scripted control (`$0`) | `1/3` | `2` (`D03, D05`) | `0/3` | `1.000` | `1.000` | `1/3` (`0.333`) |
| `FakeCriticProvider("hallucinated_pointers")` | Scripted control (`$0`) | `0/3` (`3` raw) | `0` raw (`3` actionable) | `0/3` | `0.000` | `0.000` | `0/3` (`0.000`) |

### 4.2 Held-Out Evaluation Split Results (`10` packets = `5` matched pairs `EP1`–`EP5`)

The single authorized live pass (`R07-gemini-r07-critic`) was launched via `tools/experiment_batch.py` after the independent read-only subagent review ([`runs/experiments/r07-hypothesis-critic-20261110/review.md`](file:///Users/acraev/Work/cognate-reconstruction/runs/experiments/r07-hypothesis-critic-20261110/review.md)) verified the frozen manifest and inputs.

| Critic / Baseline Arm | Type & Cost | Actionable TP (`/5`) | Missed Defects (`/5`) | False Objections (`/5`) | Actionable Precision | Pointer Validity | Defect Pointer Completeness | Matched Pairs Both Correct (`/5`) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `existing_residue_ambiguity_baseline` | Offline baseline (`$0`) | `1/5` | `4` (`E01–E04`) | `0/5` | `1.000` | `1.000` | `0.200` | `1/5` (`0.200`) |
| `fixed_evidence_checklist_baseline` | Offline baseline (`$0`) | `1/5` | `4` (`E01, E03–E05`) | `3/5` (`C02, C03, C05`) | `0.250` | `1.000` | `0.200` | `0/5` (`0.000`) |
| `deterministic_mechanical_detector` | Offline Stratum A detector (`$0`) | `3/5` | `2` (`E01, E03`) | `0/5` | `1.000` | `1.000` | `0.600` | `3/5` (`0.600`) |
| `deterministic_full_trace_detector` | Offline Stratum A+B detector (`$0`) | **`5/5`** | **`0`** | **`0/5`** | **`1.000`** | **`1.000`** | **`1.000`** | **`5/5` (`1.000`)** |
| `FakeCriticProvider("accurate")` | Scripted control (`$0`) | `5/5` | `0` | `0/5` | `1.000` | `1.000` | `1.000` | `5/5` (`1.000`) |
| `FakeCriticProvider("over_objecting")` | Scripted control (`$0`) | `5/5` | `0` | `4/5` (`C02–C05`) | `0.556` | `1.000` | `1.000` | `1/5` (`0.200`) |
| `FakeCriticProvider("verbose_relabeller")` | Scripted control (`$0`) | `1/5` | `4` (`E01–E04`) | `0/5` | `1.000` | `1.000` | `0.200` | `1/5` (`0.200`) |
| `FakeCriticProvider("hallucinated_pointers")` | Scripted control (`$0`) | `0/5` (`5` raw) | `0` raw (`5` actionable) | `0/5` | `0.000` | `0.000` | `0.000` | `0/5` (`0.000`) |
| **Live `gemini/gemini-3.8-flash` (`medium`)** | **Live LLM (`US$0.1857` / `344.5 s`)** | **`5/5`** | **`0`** | **`1/5` (`C01`)** | **`0.833`** | **`1.000`** | **`1.000`** | **`4/5` (`0.800`)** |

### 4.3 Per-Packet Breakdown of the Live `gemini/gemini-3.8-flash` Serial Pass

Executed in randomized presentation order `['P04', 'P02', 'P01', 'P10', 'P09', 'P07', 'P06', 'P08', 'P03', 'P05']` ([`evaluation.json`](file:///Users/acraev/Work/cognate-reconstruction/runs/experiments/r07-hypothesis-critic-20261110/runs/r07-gemini-r07-critic/evaluation.json)):

| Req # | Blind Code | Packet ID | Pair Role | Expected Verdict / Category | Live `gemini-3.8-flash` Verdict / Category | Pointers Valid & Complete? | In / Out (Reason) Tokens | Cost (USD) | Wall (s) | Outcome |
|---:|---|---|---|---|---|---|---:|---:|---:|---|
| 1 | `P04` | `eval_c05_bijective_proto_relabelling` | Control (`EP5`) | `legitimate_no_objection` / `none` | `legitimate_no_objection` / `none` | Yes (`1.0`) | `3,156` / `2,741` (`2,374`) | `$0.012646` | `23.68` | **Correct** (approved `*ɢ` vs `*q` bijective relabelling) |
| 2 | `P02` | `eval_e01_upstream_tie_collapse` | Defect (`EP1`) | `defect_found` / `upstream_tie_collapse_majority` | `defect_found` / `upstream_tie_collapse_majority` | Yes (`5` src, `2` call, `2` set, col `[2]`) | `3,003` / `2,760` (`2,215`) | `$0.012602` | `25.12` | **Actionable Hit** (caught `x:y05` `0.50` tie collapse) |
| 3 | `P01` | `eval_c02_legitimate_inspected_shifted_outgroup` | Control (`EP2`) | `legitimate_no_objection` / `none` | `legitimate_no_objection` / `none` | Yes (`1.0`) | `2,939` / `3,820` (`3,317`) | `$0.016529` | `31.88` | **Correct** (approved `c:y04` `p a g` with missing `d, f`) |
| 4 | `P10` | `eval_e05_bleeding_order_and_leaky_revision` | Defect (`EP5`) | `defect_found` / `counterexample_or_bleeding_order` | `defect_found` / `counterexample_or_bleeding_order` | Yes + exact `repaired=['d01','d02']`, `newly_broken=['d03']` | `3,716` / `2,086` (`1,650`) | `$0.010609` | `20.38` | **Actionable Hit** (caught bleeding order & `d03` regression) |
| 5 | `P09` | `eval_c04_equal_length_and_provisional_proxy` | Control (`EP4`) | `legitimate_no_objection` / `none` | `legitimate_no_objection` / `none` | Yes (`1.0`) | `3,209` / `3,600` (`3,094`) | `$0.015907` | `28.31` | **Correct** (approved `*l o k` despite `provisional_proxy` `l u k`) |
| 6 | `P07` | `eval_c03_genuine_tie_and_child_swap_invariance` | Control (`EP3`) | `genuine_ambiguity_noted` / `none` | `genuine_ambiguity_noted` / `none` | Yes (`1.0`) | `2,814` / `1,922` (`1,523`) | `$0.009318` | `18.82` | **Correct** (recognized `1–1` tie at `0.50` under `(b, a)` swap) |
| 7 | `P06` | `eval_c01_legitimate_parent_majority` | Control (`EP1`) | `legitimate_no_objection` / `none` | `defect_found` / `upstream_tie_collapse_majority` | Valid IDs, but **False Objection** | `3,081` / `3,126` (`2,585`) | `$0.014033` | `26.87` | **False Objection** (objected to double-counting `x:y07` alongside `c, d`) |
| 8 | `P08` | `eval_e02_uninspected_and_wrong_unit_outgroup` | Defect (`EP2`) | `defect_found` / `uninspected_outgroup_citation` | `defect_found` / `uninspected_outgroup_citation` | Yes (`3`+ src, `2` call, `1` set, col `[2]`) | `2,909` / `16,255` (`15,726`) | `$0.063138` | `111.90` | **Actionable Hit** (caught `concept_outgroup_forms_seen=False` & wrong units) |
| 9 | `P03` | `eval_e04_identity_confidence_length_bias` | Defect (`EP4`) | `defect_found` / `identity_confidence_length_bias` | `defect_found` / `identity_confidence_length_bias` | Yes (`6` src, `3` call, `4` set, cols `[0,1,2]`) | `3,394` / `4,937` (`4,352`) | `$0.021059` | `39.93` | **Actionable Hit** (caught `0.95` length penalty `0.5063` vs `0.4937`) |
| 10 | `P05` | `eval_e03_suffix_lookalike_scope_confusion` | Defect (`EP3`) | `defect_found` / `wrong_unit_or_lookalike_support` | `defect_found` / `wrong_unit_or_lookalike_support` | Yes (`5` src, `3` call, `1` set, col `[2]`) | `2,988` / `2,033` (`1,473`) | `$0.009865` | `16.96` | **Actionable Hit** (caught suffix `cog:cs338` vs stem `cog:cs312` in `f:y14`) |

### 4.4 Analysis of Key Live Findings

1. **Zero Pointer Hallucination and 100% Defect Recall (`5/5` Actionable Hits):**
   - Across all 10 held-out packets, `gemini/gemini-3.8-flash` (`medium` thinking) cited **zero hallucinated IDs** (`pointer_validity_rate = 1.000`) and included **100% of required source, call, set, and column pointers** on all 5 defective packets (`defect_pointer_completeness_rate = 1.000`).
   - Unlike `deterministic_mechanical_detector` (`3/5` TP), the live LLM critic caught both comparative Stratum B defects (`P02` `eval_e01_upstream_tie_collapse` and `P05` `eval_e03_suffix_lookalike_scope_confusion`), correctly isolating `f:y14`'s heteromorphemic suffix piece `['kʰ', 'a']` in `cog:cs338` from stem `['t', 'e']` in `cog:cs312` and proposing a concrete falsifier.
   - Unlike `fixed_evidence_checklist_baseline` (`3/5` false objections) and `FakeCriticProvider("over_objecting")` (`4/5` false objections), the live LLM critic passed 4 of the 5 paired controls: it approved the bijective `*ɢ` vs `*q` relabelling (`P04`), the single shifted same-unit outgroup with missing `d, f` (`P01`), the equal-length candidate disagreeing with a `provisional_proxy` (`P09`), and the `(b, a)` child-swapped `1–1` tie at `confidence = 0.50` (`P07`, returning `genuine_ambiguity_noted`).
2. **Why `gemini-3.8-flash` Raised Its Single False Objection on `P06` (`eval_c01_legitimate_parent_majority`):**
   - On `P06` (`y07`), root `r = (x, c, d, f)` reconstructs final `*k` at `confidence = 0.90`. Under Fitch parsimony, `*k` is genuinely supported both by the non-`x` children (`c:y07` `h o g` and `d:y07` `o k` vs `f:y07` `o`, `2-of-3`) and across all 5 leaves (`a, c, d` vs `b, f`, `3-of-5`).
   - However, `x:y07` had a `1–1` leaf split (`a:y07` `o k` vs `b:y07` `h o`) that was resolved at node `x` (`confidence = 0.85`) using outgroups `c` and `d`, and the root claim's rationale stated `"3-of-4 active-child majority (x:y07, c:y07, d:y07 vs f:y07)"`.
   - `gemini-3.8-flash` flagged `P06` as `upstream_tie_collapse_majority` because the system prompt's Rule 6 read `"(confidence <= 0.50 or disagreeing leaf_reflexes)"`, and the model reasoned that counting `x:y07` as an independent 3rd vote alongside the very siblings (`c, d`) that polarized `x`'s `1–1` leaf split double-counts `c` and `d` in the `"3-of-4"` tally.
   - While that critique of the `"3-of-4"` rationale phrasing is analytically intelligible, treating it as `verdict = "defect_found"` against a valid `*k` reconstruction (`2-of-3` among `c, d, f` and `3-of-5` across leaves) is a **false objection (`1/5`)** that a human investigator would have to dismiss if used as an automated gate.
   - By contrast, `deterministic_full_trace_detector` checks `prior_node_commit_summary.confidence <= 0.50` (`0.85 > 0.50` on `y07` vs `0.50` on `y05`), achieving **`5/5` TP and `0/5` false objections (`5/5` matched pairs)**.
3. **LLM Epistemic Label Overconfidence (`exact_mechanical` vs. `warranted_inference_critique`):**
   - On `P02` (`eval_e01_upstream_tie_collapse`) and `P05` (`eval_e03_suffix_lookalike_scope_confusion`), `gemini-3.8-flash` labeled its comparative critiques `uncertainty_label = "exact_mechanical"` instead of `"warranted_inference_critique"` (`uncertainty_label_correct = False` on 2 of 5 defects), and on `P08` (`eval_e02`) it spent `15,726` reasoning tokens (`111.9 s`, `$0.0631`) deliberating between `uninspected_outgroup_citation` and `wrong_unit_or_lookalike_support` when both defects co-occurred. This confirms that **epistemic status labels (`exact_mechanical` vs. `warranted_inference_critique`) must be assigned deterministically by the harness** rather than trusted from LLM self-reports.

---

## 5. Blinded Human Evaluation Sheet and Protocol

Generated deterministically by `build_blind_evaluation_sheet(eval_packets, seed=20261110)` and saved to:
- **Rater-Facing Blinded Form:** [`runs/experiments/r07-hypothesis-critic-20261110/blind_evaluation_sheet.md`](file:///Users/acraev/Work/cognate-reconstruction/runs/experiments/r07-hypothesis-critic-20261110/blind_evaluation_sheet.md)
- **Sealed Answer Key:** [`runs/experiments/r07-hypothesis-critic-20261110/sealed_answer_key.json`](file:///Users/acraev/Work/cognate-reconstruction/runs/experiments/r07-hypothesis-critic-20261110/sealed_answer_key.json)

The form presents the 10 held-out items (`P01`–`P10`) in randomized non-alternating order `['P04', 'P02', 'P01', 'P10', 'P09', 'P07', 'P06', 'P08', 'P03', 'P05']` with all `ground_truth`, `pair_role`, `pair_id`, and internal `packet_id` fields stripped. For each item, the human rater records:
1. `Verdict` (`defect_found | legitimate_no_objection | genuine_ambiguity_noted`),
2. `Defect Type` (one of the 8 taxonomy categories or `none`),
3. `Helpfulness of Cited Pointers` (`exact_and_helpful | partial | hallucinated_or_unhelpful`),
4. `Suggested Check / Revision Valid?` (`yes | no | not_applicable`), and
5. `Time Spent (minutes)`.

In accordance with the R07 contract, **human time saved and historical usefulness remain unverified until a real blinded expert assessment is conducted**; no external participants were recruited or messaged.

---

## 6. Cost, Resource Ledger, and Recommendation

### 6.1 Certified Resource Ledger (`runs/experiments/r07-hypothesis-critic-20261110/batch_ledger.json`)
- **Trial ID:** `R07-gemini-r07-critic` (`outcome = "committed"`, `cost_known = True`, `history_certified = True`, `stage_gate.usable = True`)
- **Requests / Turns / Tool Calls:** `10 / 10 / 10` (`0` retries, `0` unknown-cost requests)
- **Tokens:** `31,209` input tokens (`0` cached input tokens; max request `3,716` in), `43,280` output tokens (`38,309` reasoning tokens; max response `16,255` out), `74,489` total tokens
- **Certified Cost:** **`US$0.185707`** upper-bound table cost (`US$0.185707` cached-adjusted cost) vs **`US$1.50`** ceiling (`12.4%` of ceiling)
- **Wall Time:** **`344.5 s`** launcher wall time (`343.9 s` run elapsed) vs **`1,200.0 s`** ceiling (`28.7%` of ceiling)

### 6.2 Decision and Recommendation

1. **Adopt the deterministic source-linked detector (`run_deterministic_full_detector` + `evaluate_forward_revision_on_packet`) as the default offline post-run audit report (`$0` cost, `< 0.01 s`, `5/5` TP, `0/5` false objections, `5/5` matched pairs) — now wired as the default in code (`DEFAULT_CRITIC_MODE = "deterministic_full"` in `run_default_hypothesis_critic`, `run_default_critic_report`, and `python tools/hypothesis_critic_probe.py audit`):**
   - Every concrete error class demonstrated across R03–R06—silent `residue_policy: "drop"` truncation, uninspected outgroup citations (`concept_outgroup_forms_seen == False`), `FormAnalysis` unit-provenance loss (`cog:* -> whole:unknown`), `< 1.0` identity-confidence length bias, forward bleeding cascades / leaky revisions (`repaired` vs `newly_broken`), upstream `confidence <= 0.50` tie-collapse majorities, and heteromorphemic/non-cognate unit scope confusion—is **deterministically detectable from existing harness traces and `RuleEngine` execution with zero LLM cost and zero false objections**.
2. **Keep the LLM critic (`submit_hypothesis_critique`) strictly as an optional, read-only human-facing commentary layer behind deterministic pointer & epistemic filtering (`filter_llm_assessment_with_deterministic_guard`, enabled by default via `apply_deterministic_guard=True` whenever optional read-only LLM critiques are parsed)—never as an autonomous gate or repair loop:**
   - The live `gemini/gemini-3.8-flash` (`medium` thinking) pass satisfied the pre-registered continuation threshold against the pure mechanical baseline (`5/5 > 3/5` TP, `4/5 > 3/5` matched pairs, `1/5 <= 1` false objection, `1.000` pointer validity) at modest cost (`US$0.1857`), generating concise natural-language discrepancy summaries and discriminating checks.
   - However, it did **not** beat `deterministic_full_trace_detector` (`4/5` vs `5/5` matched pairs due to the `P06` `eval_c01` false objection and overconfident `exact_mechanical` labels on `P02` and `P05`). Therefore, no autonomous critic-in-the-loop repair study should be launched.

### 6.3 What Later Expert Observation Would Change This Recommendation
- **Upgrade LLM critic to standard post-run narrative summary:** If a blinded human evaluation using [`blind_evaluation_sheet.md`](file:///Users/acraev/Work/cognate-reconstruction/runs/experiments/r07-hypothesis-critic-20261110/blind_evaluation_sheet.md) demonstrates that the LLM critic's natural-language falsifiers reduce human audit time by `>= 25%` or catch free-text rationale contradictions outside the 8 structured rules without causing raters to reject legitimate parent majorities like `P06` (`eval_c01`).
- **Retire the LLM critic arm completely:** If human raters find that the structured output of `run_deterministic_full_detector` (which already supplies exact `cited_source_ids`, `cited_call_ids`, `cited_set_ids`, `cited_column_indices`, `repaired_examples`, and `newly_broken_examples`) is sufficient on its own or faster to scan than LLM prose.
