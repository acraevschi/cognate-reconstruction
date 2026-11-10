# Forward-Prediction Feasibility and Minimal Withheld-Data Prototype (`r06-forward-v1`)

- **Date:** 2026-10-30
- **Task ID:** R06 (optional successor to historical Task08)
- **Branch / starting commit:** `main` (`f64011dbd6f2745ba8f68ac652da78cfba5360a3`)
- **Evaluator & split contracts:** `FORWARD_EVALUATOR_VERSION = "r06-forward-v1"`, `ETYMON_SPLIT_VERSION = "r06-etymon-split-v1"`
- **Implementation & study artifacts:**
  - Evaluator: [`cognate_reconstruction/evaluation/forward.py`](../../cognate_reconstruction/evaluation/forward.py)
  - Diagnostic fixture: [`benchmarks/diagnostic/forward-prediction-v1.json`](../../benchmarks/diagnostic/forward-prediction-v1.json) (`sha256: c2e500ea82400cff5c491d7592ebc00ea23a61b3d867be661a1c55590b10926e`)
  - Cross-check fixture (R05): [`benchmarks/diagnostic/two-level-propagation-v1.json`](../../benchmarks/diagnostic/two-level-propagation-v1.json) (`sha256: 49089bef878c1c6f8129f9668f5a8cb7e859f30c8d6343d5d28d540e1bd3fa09`)
  - Study driver & results JSON: [`tools/forward_prediction_probe.py`](../../tools/forward_prediction_probe.py), [`docs/research/forward_prediction_feasibility_results.json`](forward_prediction_feasibility_results.json)
  - Focused regression suite: [`tests/workbench/test_forward_prediction.py`](../../tests/workbench/test_forward_prediction.py)
- **Live model calls / API spend:** **0** live calls, **US\$0.00** paid spend (offline deterministic prototype and scripted hypothesis controls; model-facing tool-schema digest `628f0f32…` is preserved unchanged).

---

## 1. Motivation from R01–R05 Evidence and Chosen Prediction Regime

### 1.1 What Uncertainty R06 Addresses After R03–R05

Across R01–R05, the project repaired native token-conditioned serialization and provenance export ([`post_review_contract_repairs.md`](post_review_contract_repairs.md)), verified single-node comparative judgment on both cloud (`gemini-3.8-flash`, `18/18` on Stage B and `19/19` on Stage C) and dense-27B local (`qwen3.8-27b-splash`, `19/19` on Stage C; [`model_capability_diagnostic.md`](model_capability_diagnostic.md), [`focused_interface_study.md`](focused_interface_study.md)), and resolved the two-level single-winner tie-collapse bottleneck via opt-in `tied_confidence_threshold = 0.5` ([`propagation_robustness_study.md`](propagation_robustness_study.md)).

However, three evaluation and identifiability limits remain unresolved by bottom-up proto-form comparison alone:

1. **Observational equivalence of unanchored proto-symbols and intermediate histories:** When daughter reflexes establish that an ancestral contrast existed (e.g., `⟨a x : b ɢ : c ʔ⟩`, distinct from `⟨a k : b k : c k⟩`), raw exactness against a single reference proto-lexicon rewards matching the generator's or editor's symbol choice (`*q`) and penalizes an observationally equivalent symbol choice (`*ɢ`, scoring `0%` raw exact on those etyma despite `1.0` contrast isomorphism). Conversely, existing `bcubed` in [`cognate_reconstruction/evaluation/metrics.py`](../../cognate_reconstruction/evaluation/metrics.py) is computed *per word* and can score `1.0` even when symbol mappings contradict across words ([`evaluation_contract.md`](evaluation_contract.md)).
2. **Non-invertibility of existing child-to-parent rules and inventory-derived views:** The workbench commits child-to-parent cascades (`ReconstructionRule`) or correspondence inventories whose derived rules (`derive_branch_rules` in [`cognate_reconstruction/traversal/assembler.py`](../../cognate_reconstruction/traversal/assembler.py)) are unscoped child-to-parent rewrites. Whenever a branch undergoes a **deletion** (`t > Ø / _ #`), a **contextual or unconditional merger** (`i > e / _ #`, `p > f / # _`), or an **ordered counterbleeding/bleeding interaction** (`k > tʃ / _ i` before `i > e / _ #`), child-to-parent rules cannot be inverted by swapping arrows (`Ø > t / _ #` is forbidden by the DSL, and `e > i / _ #` over-applies to original `*-e`).
3. **In-sample circularity of visible concept partitions:** The existing `ConceptSplit` in [`cognate_reconstruction/agent/holdout.py`](../../cognate_reconstruction/agent/holdout.py) is visible to the session during reconstruction. If a daughter reflex was already present in the alignment or outgroup evidence used to infer its ancestor, predicting that daughter reflex back is an **in-sample consistency check**, not held-out generalization.

### 1.2 Explicit Regime Selection: Inferred-Ancestor Masked-Daughter Prediction

We explicitly select the **Inferred-ancestor (masked-daughter reflex prediction)** regime as the primary task, while reporting **Given-ancestor (`given_ancestor_control`)** and **In-sample unmasked circularity (`in_sample_circular_unmasked_check`)** in separate, explicitly labelled tables:

- **Why Inferred-ancestor is chosen over Known-ancestor as the primary regime:** Known-ancestor forward induction supplies the hidden proto-forms directly to the learner, reducing the task to single-branch string transduction (like PBEBench) without testing multi-daughter comparative reconstruction or observational equivalence of inferred proto-symbols. The **Inferred-ancestor** regime tests the actual combined comparative hypothesis $(\hat{w}_r, \mathcal{F}_{r \to a})$:
  1. On **development etyma** ($E_{\text{dev}}$), all daughters $(a, b, c)$ are observed; the parent-to-child cascade $\mathcal{F}_{r \to a}$ (`direction = "parent_to_child"`) is fit and frozen on $E_{\text{dev}}$ under an explicit lexical-exception bound.
  2. On **held-out test etyma** ($E_{\text{test}}$), target daughter $a$'s forms are **physically removed** from the `WorkbenchPayload` before ingestion. Ancestral forms $\hat{w}_r(e)$ for $e \in E_{\text{test}}$ are inferred solely from the non-masked sisters $(b, c)$ via the native `ProtoInventoryAssembler`, and the frozen cascade $\mathcal{F}_{r \to a}$ is executed on $\hat{w}_r(e)$ via `RuleEngine.apply_rules` to predict the withheld reflexes $\hat{w}_a(e)$.
- **Literature context and boundary:** Lu, Xie, and Mortensen ([ACL 2024](https://aclanthology.org/2024.acl-long.788/)) combine proto-form reconstruction with descendant reflex prediction in a semi-supervised neural architecture trained on cognate sets, and Bouchard-Côté et al. ([PNAS 2013](https://doi.org/10.1073/pnas.1204678110)) model probabilistic sound changes along a phylogeny. Those works motivate testing descendant constraints, but their supervised/semi-supervised parameter training does not validate an training-free LLM/rule-cascade workbench or remove the need for strict etymon-level withholding and overfit controls.

---

## 2. Observation Unit, Etymon-Cluster Split, Admissible Hypotheses, and Interface Choice

### 2.1 Observation Unit and Etymon-Cluster Split (`r06-etymon-split-v1`)

- **Observation unit:** One **independent etymon cluster** $e$, comprising all concepts and forms that share an etymological root (`etymon_id`) or a non-affix cognate-unit membership (`cognate_set_id` / `CognateMembership.cognate_set_id`).
- **Why concept-level splitting is insufficient:** Splitting by `concept_id` alone (as in `agent/holdout.py`) can assign a simplex word (`t07: *m a q i`) to development and a derived/compound form sharing the same root (`t08: *m a q a k i`, both carrying `cognate_set_id = "forward_prediction_v1:etym_t07"`) to test, leaking the root stem's target-daughter reflex (`m a x-`) across the split.
- **Mechanical guard (`build_etymon_cluster_split`):** Implemented in [`cognate_reconstruction/evaluation/forward.py`](../../cognate_reconstruction/evaluation/forward.py) (`lines 107-190`). It partitions by `etymon_id` and verifies across `payload.lexicons` that the sets of non-affix `cognate_set_id`s in `development_concept_ids` and `held_out_concept_ids` are strictly disjoint (`shared_cognate_units_across_split == ()`), raising a `ValueError` if any shared cognate unit crosses the split boundary.

### 2.2 Admissible Hypotheses, Exception Bounds, and Complexity Accounting

A forward hypothesis is represented by `ForwardBranchHypothesis` ([`cognate_reconstruction/evaluation/forward.py`](../../cognate_reconstruction/evaluation/forward.py), `lines 298-346`):

- **Explicit branch identity and direction:** Requires `parent_node_id != child_node_id` and `direction = "parent_to_child"`. Passing `"child_to_parent"` or an empty-target insertion rule (`Ø > t / _ #`) is rejected at schema validation.
- **Control disclosure invariant:** Any hypothesis with `ancestor_regime = "given_ancestor_control"` or `privileged_operator_control = True` must set `privileged_operator_control = True` and `deployable_baseline = False`.
- **Exception bound and lookup-rule detection (`ForwardComplexityReport`):**
  - Per-word overrides (`ForwardLexicalException`) are explicitly counted against `max_lexical_exceptions` (default `1`), flagging `exception_bound_exceeded = True` when exceeded.
  - Because a lookup table can also be disguised as word-specific context rules with zero nominal `lexical_exceptions` (e.g., `k > tʃ / p a _ i` firing on only one development etymon), `_compute_complexity_report` executes the cascade step-by-step on the development etyma and records `single_etymon_dev_rule_ids` (rules whose `APPLIED` match locations occur in $\le 1$ development etymon) and `zero_application_dev_rule_ids`, alongside report-only `description_token_complexity` (sum of target, replacement, left/right context, boundary `#` markers, and lexical-exception override tokens).

### 2.3 Interface Comparison: Offline Report/Evaluator vs. Model-Facing Proposal Tool

| Design Option | Mechanism | Effect on Frozen `628f0f32…` Tool Surface | Feasibility & Scientific Sufficiency |
| :--- | :--- | :--- | :--- |
| **Option A (Selected): Offline evaluator (`cognate_reconstruction/evaluation/forward.py`)** | Consumes reconstructed ancestor beams from existing `ProtoInventoryAssembler` + separately supplied explicit `ForwardBranchHypothesis` cascades executed via `RuleEngine`. | **Zero change** to model-facing tool schemas (`628f0f32…`), prompts, or trajectory digests. | **Sufficient:** Tests withholding, non-invertibility, rule ordering, observational equivalence, overfit rejection, and R05 beam propagation without confounding the reconstruction interface. |
| **Option B (Deferred): New model-facing `test_forward_cascade` / `commit_forward_cascade` tool** | Adds a second direction of rule tools to `default_tool_registry` during node sessions. | **Breaks** frozen tool-schema digest `628f0f32…` and increases per-request schema token overhead (`~14k` tokens/request measured in R03f). | **Unnecessary for feasibility:** Would require re-freezing all R02–R04 manifests and spending live tokens before establishing whether forward metrics add discriminating power beyond R05/R07. |

Per the R06 brief (*"Prefer an offline report/evaluator consuming separately supplied explicit forward rules, reusing the native executor. Add a typed model-facing proposal tool only if the feasibility question cannot be answered without it"*), we select **Option A**.

---

## 3. Synthetic Family Design (`forward-prediction-v1.json`)

The family `(a, b, c)r;` ([`benchmarks/diagnostic/forward-prediction-v1.json`](../../benchmarks/diagnostic/forward-prediction-v1.json)) contains **17 concepts across 16 independent etyma**: **8 development etyma** (`d01`–`d08`, all three daughters observed) and **8 held-out test etyma** (`9` concepts: `t01`–`t08` validated identifiable, where `t07` and `t08` share `etym_t07`, plus `u01` underdetermined pan-sister merger control; target daughter `a` strictly withheld).

### 3.1 Branch Sound Laws and Complementary Sister Information

| Branch | Ordered Forward Rules (`parent_to_child`) | Contrast Reductions (`ContrastReduction`) | Invertible Child $\to$ Parent? | Role in Study |
| :--- | :--- | :--- | :---: | :--- |
| **`r -> a`** (Target daughter) | 1. `k > tʃ / _ i`<br>2. `i > e / _ #`<br>3. `t > Ø / _ #`<br>4. `q > x`<br>5. `w > v / # _` | - `i > e / _ #`: **merges** `*-i` into `*-e` (`merges=True`)<br>- `t > Ø / _ #`: **deletes** `*-t` (`deletes=True`) | **No** (`t > Ø / _ #` has no syntactic inverse; naive arrow-swap recovers only `12/17 = 70.6%`) | Counterbleeding order (`1` before `2`: `*p a k i` $\to$ `p a tʃ i` $\to$ `p a tʃ e`, whereas `*p a k e` $\to$ `p a k e`); coda deletion (`*s a t` $\to$ `s a`); dorsal shift (`*q` $\to$ `x`). |
| **`r -> b`** (Observed sister 1) | 1. `p > f / # _`<br>2. `q > ɢ`<br>3. `w > l / # _` | - `p > f / # _`: **merges** `*p-` with `*f-` (`merges=True`)<br>- `w > l / # _`: **merges** `*w-` with `*l-` (`merges=True`) | **No** (`f > p / # _` over-applies to `*f a k i` and `*f u k i`; recovers `14/17 = 82.4%`) | Retains final `*-i` vs `*-e` and final `*-t`, but **loses initial `*p-` vs `*f-`** (`*p u k i` and `*f u k i` both become `f u k i` in `b`). |
| **`r -> c`** (Observed sister 2) | 1. `i > e / _ #`<br>2. `t > Ø / _ #`<br>3. `q > ʔ`<br>4. `w > l / # _` | - `i > e / _ #`: **merges** `*-i` into `*-e` (`merges=True`)<br>- `t > Ø / _ #`: **deletes** `*-t` (`deletes=True`)<br>- `w > l / # _`: **merges** `*w-` with `*l-` (`merges=True`) | **No** (`t > Ø / _ #` has no syntactic inverse; `e > i / _ #` corrupts `*-e`; recovers `11/17 = 64.7%`) | Retains initial `*p-` vs `*f-`, but **merges `*-i` with `*-e` without palatalizing `k`** (`*p u k i` and `*p u k e` both become `p u k e` in `c`) and **deletes `*-t`**. |

### 3.2 Complete Etymon Ledger (`d01`–`d08` Development, `t01`–`t08` + `u01` Held-Out Test)

| Split | Concept | Etymon ID | Phenomenon / Control Role | Generator `*r` (Equiv. `*ɢ`) | Observed Sister `b` | Observed Sister `c` | Inferred `*r` from `(b, c)` | Target Daughter `a` |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Dev** | `d01` | `etym_d01` | Counterbleeding `k > tʃ / _i` then `i > e / _#` (`*p-`) | `*p a k i` | `f a k i` | `p a k e` | `*p a k i` (unattested) | `p a tʃ e` (observed in dev) |
| **Dev** | `d02` | `etym_d02` | Counterbleeding with `*f-` (minimal pair with `d01` in `b`) | `*f a k i` | `f a k i` | `f a k e` | `*f a k i` (attested in `b`) | `f a tʃ e` (observed in dev) |
| **Dev** | `d03` | `etym_d03` | Original `*-e` non-palatalizing (minimal pair with `d01` in `c`) | `*p a k e` | `f a k e` | `p a k e` | `*p a k e` (attested in `c`) | `p a k e` (observed in dev) |
| **Dev** | `d04` | `etym_d04` | Non-final `i` palatalization + medial `t` retention | `*k i t a` | `k i t a` | `k i t a` | `*k i t a` (attested in `b, c`) | `tʃ i t a` (observed in dev) |
| **Dev** | `d05` | `etym_d05` | Final `-t` apocope (`t > Ø / _#`) | `*s a t` | `s a t` | `s a` | `*s a t` (attested in `b`) | `s a` (observed in dev) |
| **Dev** | `d06` | `etym_d06` | Open syllable (merged with `d05` in `a` and `c`) | `*s a` | `s a` | `s a` | `*s a` (attested in `b, c`) | `s a` (observed in dev) |
| **Dev** | `d07` | `etym_d07` | Equivalent dorsal series `⟨b ɢ : c ʔ⟩` initial | `*q a l a` (`*ɢ a l a`) | `ɢ a l a` | `ʔ a l a` | `*q a l a` / `*ɢ a l a` | `x a l a` (observed in dev) |
| **Dev** | `d08` | `etym_d08` | Equivalent dorsal series medial + initial `*l-` anchor | `*l a q a` (`*l a ɢ a`) | `l a ɢ a` | `l a ʔ a` | `*l a q a` / `*l a ɢ a` | `l a x a` (observed in dev) |
| **Test** | `t01` | `etym_t01` | Held-out counterbleeding with `*p-` | `*p u k i` | `f u k i` | `p u k e` | `*p u k i` (**unattested**) | **`p u tʃ e`** (**withheld**) |
| **Test** | `t02` | `etym_t02` | Held-out counterbleeding with `*f-` (collides with `t01` in `b`) | `*f u k i` | `f u k i` | `f u k e` | `*f u k i` (attested in `b`) | **`f u tʃ e`** (**withheld**) |
| **Test** | `t03` | `etym_t03` | Held-out `*-e` contrast (collides with `t01` in `c`) | `*p u k e` | `f u k e` | `p u k e` | `*p u k e` (attested in `c`) | **`p u k e`** (**withheld**) |
| **Test** | `t04` | `etym_t04` | Held-out medial `k > tʃ / _i` + final `t > Ø / _#` | `*k i m a t` | `k i m a t` | `k i m a` | `*k i m a t` (attested in `b`) | **`tʃ i m a`** (**withheld**) |
| **Test** | `t05` | `etym_t05` | Held-out `*p-` + final `t > Ø / _#` | `*p a m u t` | `f a m u t` | `p a m u` | `*p a m u t` (**unattested**) | **`p a m u`** (**withheld**) |
| **Test** | `t06` | `etym_t06` | Held-out dorsal `*q`/`*ɢ` + final `i > e / _#` | `*q u l i` (`*ɢ u l i`) | `ɢ u l i` | `ʔ u l e` | `*q u l i` / `*ɢ u l i` | **`x u l e`** (**withheld**) |
| **Test** | `t07` | `etym_t07` | Shared-etymon simplex (`forward_prediction_v1:etym_t07`) | `*m a q i` (`*m a ɢ i`) | `m a ɢ i` | `m a ʔ e` | `*m a q i` / `*m a ɢ i` | **`m a x e`** (**withheld**) |
| **Test** | `t08` | `etym_t07` | Shared-etymon derivative + counterbleeding (`etym_t07`) | `*m a q a k i` (`*m a ɢ a k i`) | `m a ɢ a k i` | `m a ʔ a k e` | `*m a q a k i` / `*m a ɢ a k i` | **`m a x a tʃ e`** (**withheld**) |
| **Test** | `u01` | `etym_u01` | **Underdetermined pan-sister merger control** (`w > l / #_` in `b, c`) | `*w a l a` (alt. `*l a l a`) | `l a l a` | `l a l a` | `*l a l a` (underdetermined) | **`v a l a`** (**withheld**) |

---

## 4. Prototype Results and Hypothesis Comparison

All 14 hypothesis/control arms were executed deterministically via [`tools/forward_prediction_probe.py`](../../tools/forward_prediction_probe.py) (`conda run -n llm_reconstruction python -m tools.forward_prediction_probe`), producing [`docs/research/forward_prediction_feasibility_results.json`](forward_prediction_feasibility_results.json).

### 4.1 Primary Inferred-Ancestor and Direct-Sister Baseline Results (`r06-forward-v1`)

| Hypothesis ID | Ancestor Input Regime | Deployable? | Dev In-Sample Exact (`d01`–`d08`) | Dev Mean NED | Held-Out Validated Exact (`t01`–`t08`) | Held-Out Conditional Exact (Available) | Held-Out Coverage | Held-Out Validated Mean NED | Proto `*r` Raw Exact (`t01`–`t08`) | Proto `*r` Corpus B-Cubed F1 (Bijective?) | Rules / Exc. (Bound Exceeded?) | Single-Etymon Dev Rules / Complexity |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`h1_intended_cascade`** | `inferred_ancestor` (`*q` from `b, c`) | Yes | **`8/8` (`1.000`)** | `0.0000` | **`8/8` (`1.000`)** | `8/8` (`1.000`) | `1.000` | **`0.0000`** | **`8/8` (`1.000`)** | **`1.000` (`True`)** | `5` / `0` (`False`) | `2` / `13` |
| **`h2_equivalent_ancestral_label`** | `inferred_ancestor` (`*ɢ` from `b, c`) | Yes | **`8/8` (`1.000`)** | `0.0000` | **`8/8` (`1.000`)** | `8/8` (`1.000`) | `1.000` | **`0.0000`** | **`5/8` (`0.625`)** | **`1.000` (`True`)** | `5` / `0` (`False`) | `3` / `13` |
| **`h2b_equivalent_two_stage_chronology`** | `inferred_ancestor` (`*q`, `q > χ > x`) | Yes | **`8/8` (`1.000`)** | `0.0000` | **`8/8` (`1.000`)** | `8/8` (`1.000`) | `1.000` | **`0.0000`** | `8/8` (`1.000`) | `1.000` (`True`) | `6` / `0` (`False`) | `2` / `15` |
| **`h3_wrong_order_bleeding`** | `inferred_ancestor` (`i>e` before `k>tʃ`) | Yes | `6/8` (`0.750`) | `0.0625` | **`5/8` (`0.625`)** | `5/8` (`0.625`) | `1.000` | `0.0833` | `8/8` (`1.000`) | `1.000` (`True`) | `5` / `0` (`False`) | `3` / `13` |
| **`h4_overfit_dev_lookup`** | `inferred_ancestor` (bleeding + 2 dev overrides) | Yes | **`8/8` (`1.000`)** | `0.0000` | **`1/8` (`0.125`)** | `1/8` (`0.125`) | `1.000` | `0.2167` | `8/8` (`1.000`) | `1.000` (`True`) | `5` / **`2` (`True`)** | **`4` / `28`** |
| **`h4b_overfit_word_specific_zero_exceptions`** | `inferred_ancestor` (dev-stem contexts, 0 exc.) | Yes | **`8/8` (`1.000`)** | `0.0000` | **`1/8` (`0.125`)** | `1/8` (`0.125`) | `1.000` | `0.2417` | `8/8` (`1.000`) | `1.000` (`True`) | `7` / `0` (`False`) | **`6` / `32`** |
| **`h5_naive_unscoped_inventory_rules`** | `inferred_ancestor` (unscoped `i>e, k>tʃ, q>x`) | Yes | `5/8` (`0.625`) | `0.1042` | **`5/8` (`0.625`)** | `5/8` (`0.625`) | `1.000` | `0.1063` | `8/8` (`1.000`) | `1.000` (`True`) | `3` / `0` (`False`) | `0` / `6` |
| **`h6_identity_from_inferred_proto`** | `inferred_ancestor` (empty cascade `()`) | Yes | `2/8` (`0.250`) | `0.2604` | **`1/8` (`0.125`)** | `1/8` (`0.125`) | `1.000` | `0.3875` | `8/8` (`1.000`) | `1.000` (`True`) | `0` / `0` (`False`) | `0` / `0` |
| **`h7_direct_sister_b_cascade`** | `direct_sister_baseline` (`b -> a` rules) | Yes | `6/8` (`0.750`) | `0.0625` | **`5/8` (`0.625`)** | `5/8` (`0.625`) | `1.000` | `0.0938` | `2/8` (`0.250`) | `0.979` (`False`) | `4` / `0` (`False`) | `2` / `10` |
| **`h7b_copy_sister_b`** | `direct_sister_baseline` (raw copy of `b`) | Yes | `1/8` (`0.125`) | `0.3229` | **`0/8` (`0.000`)** | `0/8` (`0.000`) | `1.000` | `0.4750` | `2/8` (`0.250`) | `0.979` (`False`) | `0` / `0` (`False`) | `0` / `0` |
| **`h8_direct_sister_c_cascade`** | `direct_sister_baseline` (`c -> a` rules) | Yes | `6/8` (`0.750`) | `0.0625` | **`5/8` (`0.625`)** | `5/8` (`0.625`) | `1.000` | `0.0833` | `1/8` (`0.125`) | `0.954` (`False`) | `2` / `0` (`False`) | `1` / `5` |
| **`h8b_copy_sister_c`** | `direct_sister_baseline` (raw copy of `c`) | Yes | `3/8` (`0.375`) | `0.1563` | **`2/8` (`0.250`)** | `2/8` (`0.250`) | `1.000` | `0.1979` | `1/8` (`0.125`) | `0.954` (`False`) | `0` / `0` (`False`) | `0` / `0` |
| **`h9_missing_output_and_would_empty`** | `inferred_ancestor` (`t06`–`t08` missing, `s a > Ø`) | Yes | `6/8` (`0.750`) | `0.0625` | **`5/8` (`0.625`)** | `5/5` (`1.000`) | **`0.625`** | `0.0000` (`0.375` uncond.) | `5/5` (`1.000`) | `1.000` (`True`) | `4` / `0` (`False`) | `2` / `10` |

### 4.2 Separate Table: Privileged Given-Ancestor and Circular In-Sample Controls (`u01` Pan-Sister Merger)

On `u01` (`*w a l a`, where both non-masked sisters `b` and `c` underwent `w > l / # _` to `l a l a`, while target daughter `a` shifted `w > v / # _` to `v a l a`), the three regimes separate cleanly:

| Control / Regime | Ancestor Source on `u01` | Privileged Control? | Deployable Baseline? | Held-Out Validated (`t01`–`t08`) | Pan-Sister Merger Control (`u01`) | All Planned Test (`t01`–`t08` + `u01`) | Interpretation |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **`h1` / `h2` (`inferred_ancestor`, `a` masked)** | Reconstructed from `(b, c)` (`⟨b l : c l⟩ → *l a l a`) | No | Yes | **`8/8` (`1.000`)** | **`0/1` (`0.000`)** (`l a l a` vs `v a l a`) | `8/9` (`0.889`) | Honest comparative limit: `(b, c)` lost the `*w`/`*l` contrast on `u01`, so `*w a l a` is unidentifiable without `a`. |
| **`in_sample_circular_unmasked_check`** | Reconstructed from `(a, b, c)` with `a: v a l a` unmasked (`⟨a v : b l : c l⟩ → *w a l a`) | **Yes** (leaks `a`) | **No** | `8/8` (`1.000`) | **`1/1` (`1.000`)** (`v a l a`) | `9/9` (`1.000`) | **In-sample circularity:** using `a: v a l a` to infer `*w a l a` and then predicting `v a l a` back checks consistency, not generalization. |
| **`h10_privileged_given_ancestor_oracle`** | Supplied directly from generator truth (`*w a l a`) | **Yes** (`given_ancestor_control`) | **No** | `8/8` (`1.000`) | **`1/1` (`1.000`)** (`v a l a`) | `9/9` (`1.000`) | **Known-ancestor control:** isolates forward-cascade validity (`w > v / # _` works when `*w a l a` is supplied) from ancestor identifiability. |

---

## 5. What Held-Out Forward Prediction Can and Cannot Reject

### 5.1 What Held-Out Forward Prediction Successfully Rejects (and In-Sample Fit Cannot)

1. **Memorized / overfit development hypotheses (`h4_overfit_dev_lookup` and `h4b_overfit_word_specific_zero_exceptions`):**
   - On `development_in_sample` (`d01`–`d08`), `h1_intended_cascade`, `h4_overfit_dev_lookup`, and `h4b_overfit_word_specific_zero_exceptions` all achieve **`8/8` (`1.000`) exact match and `0.0000` NED**. In-sample development fit cannot distinguish the general ordered law from word-specific environment memorization or lexical overrides.
   - On `held_out_test` (`t01`–`t08`), `h1_intended_cascade` achieves **`8/8` (`1.000`)**, whereas both `h4` and `h4b` collapse to **`1/8` (`0.125`)** (`mean_ned = 0.2167` and `0.2417`). In addition, `ForwardComplexityReport` flags `h4` for `exception_bound_exceeded = True` (`2 > 1`) and `h4b` for `6` single-etymon development rules (`description_token_complexity = 32` vs `13` for `h1`).
2. **Wrong relative chronology / bleeding order (`h3_wrong_order_bleeding`) and auxiliary PBEBench-style permutation ordering:**
   - Placing `i > e / _ #` before `k > tʃ / _ i` (`h3`) bleeds palatalization on `d01, d02` (`6/8` dev) and `t01, t02, t08` (`5/8` held-out test).
   - In the auxiliary $4! = 24$ permutation check (`evaluate_rule_order_permutations` over the 4 core rules on `r -> a`), exactly **$12/24$ permutations achieve `8/8`** on dev and test (every permutation where `k > tʃ / _ i` precedes `i > e / _ #`), and **$12/24$ permutations drop to `6/8` dev / `5/8` test** (every permutation where `i > e / _ #` precedes `k > tʃ / _ i`).
3. **Single-sister direct mappings (`h7_direct_sister_b_cascade`, `h8_direct_sister_c_cascade`) vs. multi-daughter ancestral inference (`h1`, `h2`):**
   - Because sister `b` merged `*p > f / # _` (`t01: f u k i` = `t02: f u k i`) and sister `c` merged `i > e / _ #` (`t01: p u k e` = `t03: p u k e`), no deterministic cascade from `b` alone (`5/8` test) or from `c` alone (`5/8` test) can predict `a`'s held-out forms.
   - Furthermore, when `h7c_direct_sister_b_with_f_to_p` adds `f > p / # _` to `b -> a`, `compare_forward_hypotheses` shows that it repairs `t01, t03, t05` (`+3`) while **newly breaking** `t02` (`*f u k i` $\to$ `p u tʃ e` instead of `f u tʃ e`; `newly_broken_concept_ids = ['t02']`).
   - Only multi-daughter reconstruction from `(b, c)` (`h1`, `h2`) recovers the **5 unattested ancestor inputs** (`t01 *p u k i`, `t05 *p a m u t`, `t06 *q u l i`, `t07 *m a q i`, `t08 *m a q a k i`) and predicts the **6 sister-unattested target reflexes** (`t01 p u tʃ e`, `t02 f u tʃ e`, `t04 tʃ i m a`, `t06 x u l e`, `t07 m a x e`, `t08 m a x a tʃ e`), scoring **`8/8` (`1.000`)**.

### 5.2 What Held-Out Forward Prediction Resolves—and What It Cannot Reject

1. **Resolves false penalties on observationally equivalent ancestral symbols (`h1` vs `h2`):**
   - On `t01`–`t08`, `h2_equivalent_ancestral_label` reconstructs `*ɢ` instead of the generator's `*q` for `⟨b ɢ : c ʔ⟩` and applies `ɢ > x` on `r -> a`.
   - Raw proto-form exactness against the generator's `*r` penalizes `h2` (`5/8 = 0.625`), whereas `corpus_bcubed_f1` is **`1.000` (`is_bijective_relabelling = True`)** and held-out forward prediction on daughter `a` is **`8/8` (`1.000`, `mean_ned = 0.0000`)**.
2. **Cannot uniquely identify unanchored ancestral phonetic labels or unattested intermediate stages (`h1` vs `h2` vs `h2b`):**
   - Because `(*q, q > x)` (`h1`), `(*ɢ, ɢ > x)` (`h2`), and `(*q, q > χ, χ > x)` (`h2b`) generate the **exact same visible daughter reflexes** across all development and held-out test etyma (`8/8` dev, `8/8` test), held-out forward prediction **cannot reject** `*ɢ` in favor of `*q`, nor can it reject the two-stage intermediate cascade `q > χ > x` without an attested historical intermediate anchor (`HistoricalFormRole.ANCHOR`).

### 5.3 Cross-Check with R05 (`two-level-propagation-v1` Branch `x -> a`)

Executing branch `x -> a`'s forward cascade (`p > f / # _`, `i > i k / m _ #`, `e > e k / n _ #`, `a > a k / m _ #`, `u > u k / n _ #`) on R05's [`benchmarks/diagnostic/two-level-propagation-v1.json`](../../benchmarks/diagnostic/two-level-propagation-v1.json) confirms that R05's single-winner intermediate tie-collapse (`a1`, where `x` drops `-k` on `c001`–`c004`) reduces forward reflex prediction on daughter `a` from **`12/12` (`1.000`) to `8/12` (`0.667`)** (`c001`–`c004` predicted as `f i, t e, f a, t u` instead of `f i k, t e k, f a k, t u k`), whereas R05's tied-beam retention (`c1`, `tied_confidence_threshold = 0.5`, resolved with sister clade `y` at `r`) restores all four (`repaired_concept_ids = ['c001', 'c002', 'c003', 'c004']`, `newly_broken_concept_ids = []`).

---

## 6. Independent Audit, Resource Ledger, and Go/Defer Recommendation

### 6.1 Independent Leakage and Identifiability Audit

An independent read-only `research` subagent (`45d47c51-2421-4048-a9d3-f9221f788787`) audited [`benchmarks/diagnostic/forward-prediction-v1.json`](../../benchmarks/diagnostic/forward-prediction-v1.json), [`cognate_reconstruction/evaluation/forward.py`](../../cognate_reconstruction/evaluation/forward.py), [`tools/forward_prediction_probe.py`](../../tools/forward_prediction_probe.py), [`tests/workbench/test_forward_prediction.py`](../../tests/workbench/test_forward_prediction.py), and [`docs/research/forward_prediction_feasibility_results.json`](forward_prediction_feasibility_results.json):
- Verified zero leakage of withheld target-daughter forms (`a:t01`..`a:u01`), `historical_form_bindings`, and `SyntheticAnswerKey` rules across both `sister_only_ancestor_inference` and `masked_three_child_context` payloads and tool exchanges (`ok = True`).
- Verified that `build_etymon_cluster_split` keeps shared-root concepts `t07` and `t08` (`forward_prediction_v1:etym_t07`) in the same partition and raises `ValueError` when a split separates them.
- Verified separation of `inferred_ancestor`, `direct_sister_baseline`, `given_ancestor_control` (`privileged_operator_control = True`, `deployable_baseline = False`), and `in_sample_circular_unmasked_check`.
- Verified that no existing DSL expressivity gap blocks the prototype (all rules execute through the native literal token `RuleEngine` without importing Java/DiaSim or expanding to feature matrices).

### 6.2 Resource Ledger and Validation

- **Live LLM / API calls:** `0` requests, `0` tokens, `US$0.00` spend.
- **Focused regression tests:** `conda run -n llm_reconstruction python -m pytest -q -p no:cacheprovider tests/workbench/test_forward_prediction.py` (`9 passed`).
- **Portable test suite:** `conda run -n llm_reconstruction python -m pytest -q -p no:cacheprovider -k 'not local_run_artifacts'` (`865 passed, 41 deselected`).

### 6.3 Decision: Keep the Offline Forward Evaluator (`r06-forward-v1`); Defer Model-Facing Forward Tooling and Live Forward Sweeps

1. **Go / Retain (Offline Evaluator & Diagnostic Suite):** Retain [`cognate_reconstruction/evaluation/forward.py`](../../cognate_reconstruction/evaluation/forward.py) (`r06-forward-v1`), [`benchmarks/diagnostic/forward-prediction-v1.json`](../../benchmarks/diagnostic/forward-prediction-v1.json), and [`tools/forward_prediction_probe.py`](../../tools/forward_prediction_probe.py) as the repository's leak-tested offline instrument for evaluating explicit parent-to-child cascades, corpus-wide contrast equivalence (`corpus_bcubed_f1` / `is_bijective_relabelling`), residual context autopsies (`build_residual_autopsy`), and before/after cascade diffs (`compare_forward_hypotheses`).
2. **Defer (Model-Facing Forward Proposal Tool & Live Sweeps):** Do **not** add a new model-facing forward-rule tool to `default_tool_registry` or launch live forward-prediction sweeps at this stage:
   - The offline prototype answers the feasibility question completely without mutating the validated `628f0f32…` tool-schema surface.
   - As established in R05 and Section 5.3 above, forward reflex accuracy on multi-level trees depends upstream on intermediate hypothesis quality and trace integrity (preventing silent `residue_policy: "drop"` truncation, upstream tie-collapse, and `FormAnalysis` provenance loss)—the exact targets of **R07 (Assisted Hypothesis Criticism)** and the `build_residual_autopsy` / `compare_forward_hypotheses` primitives delivered here.
3. **What would change this decision:**
   - **To authorize a live forward-prediction experiment:** A concrete real-language or semi-synthetic benchmark slice where ancestral symbol notation is disputed/underidentified across sources (so direct proto-form exactness is uninformative) *and* multiple independent etyma per correspondence pattern allow an etymon-disjoint dev/test split where a model-proposed forward cascade beats `direct_sister_baseline` (`h7, h8`) and `overfit_dev_lookup` (`h4, h4b`) on genuinely withheld daughter forms.
   - **What does not justify expansion:** In-sample round-trip fit on visible daughters (`in_sample_circular_unmasked_check`) or agreement with an arbitrary synthetic label (`*q` vs `*ɢ`) does not support expanding the live agent protocol.
