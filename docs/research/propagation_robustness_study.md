# Two-Level Intermediate Propagation and Robustness Study (`two-level-propagation-v1`)

- **Date:** 2026-10-30
- **Branch / base commit:** `main` (`aca7ed91b82e34959b9a2a1661570b7dc040`)
- **Diagnostic fixture:** [`benchmarks/diagnostic/two-level-propagation-v1.json`](../../benchmarks/diagnostic/two-level-propagation-v1.json) (`sha256: 49089bef878c1c6f8129f9668f5a8cb7e859f30c8d6343d5d28d540e1bd3fa09`)
- **Historical definitions preserved unchanged:**
  - [`benchmarks/diagnostic/stage-b-retention-v1.json`](../../benchmarks/diagnostic/stage-b-retention-v1.json) (`sha256: 65ca991eb226ff922e73b66f9d2cf8769cd741224a4288628430b20e259be21f`)
  - [`benchmarks/diagnostic/stage-c-multi-outgroup-v1.json`](../../benchmarks/diagnostic/stage-c-multi-outgroup-v1.json) (`sha256: fe66f5460de88823c9487792b713709c41ed7960ac85060f44d01ef013bdde67`)
- **Study driver & results:** [`tools/propagation_robustness_probe.py`](../../tools/propagation_robustness_probe.py), [`docs/research/propagation_robustness_study_results.json`](propagation_robustness_study_results.json)
- **Focused behavioral tests:** [`tests/workbench/test_propagation_robustness.py`](../../tests/workbench/test_propagation_robustness.py)
- **Live model calls:** **0** (offline mechanical/counterfactual study and banked checkpoint replay; live response at `r` under tied-beam retention is marked unknown pending any future authorized envelope).

---

## 1. Entry Gate and Prioritized Question

### 1.1 Gate Verification from R03 and R04

Per [`docs/research/model_capability_diagnostic.md`](model_capability_diagnostic.md) (R03) and [`docs/research/focused_interface_study.md`](focused_interface_study.md) (R04):

1. **Demonstrated local capability at `x`:** On R04 Stage C (`r04-stage-c-v1`), both Tier 1 (`gemini-3.8-flash`, `c-gemini-r04`) and Tier 2 (`qwen3.8-27b-splash`, `c-local-qwen38-27b-r04`, under `max_output_tokens = 32,768` and `--reasoning-history drop`) achieved **19/19** decided opportunities (`1.0000`), **5/5** matched pairs, **6/6** on R02's outgroup-witness error set, and **4/4** tied items (`T1`–`T4`: `y05, y03, y09, y08`) marked at `confidence = 0.50` with **0** false confident claims.
2. **Specific mechanical propagation bottleneck identified by R03 and R04:**
   - `TreeTraverser` walks strictly one-way bottom-up (`post-order`), and `ProtoInventoryAssembler` emits a **single winning proto-segment per column per input candidate tuple**.
   - Even when a model explicitly marks a genuine `1–1` parsimony tie at `confidence = 0.50`, `ProtoInventoryAssembler` collapses that column to whichever single `proto_segment` (`"k"` or `None`) was written in the `CorrespondenceCommitment`, emitting a width-1 distribution (`probability = 1.0`, `decided_by_tie_break = False`) into `x`'s `NodeBeamState`.
   - In R03 Stage B (`b-gemini`), Gemini committed ties `U1` (`w13`) and `U2` (`w08`) as `proto_segment = None` at `0.50`, erasing `-k` and `-n` from `x`'s beam.
   - In R04 Stage C (`c-gemini-r04` and `c-local-qwen38-27b-r04`), both models committed ties `T1`–`T4` (`y05, y03, y09, y08`) as `proto_segment = "k"` at `0.50`, erasing the equally supported `-Ø` alternative from `x`'s beam and causing `x` to cast a full `1.0` vote for `*k` at the parent node `r`.

The entry gate is therefore satisfied: local comparative judgment works on both cloud and dense-27B local models, and single-winner intermediate beam collapse is the exact mechanical boundary between node `x` and parent node `r`.

### 1.2 Question and Counterfactual Structure

We test whether intermediate reconstruction at `x` helps or loses useful information at root `r` on a two-level synthetic family `((a,b)x,(c,d)y)r;`, combining:

- **Option 2 (primary):** Value of retaining competing alternatives in `x`'s beam on low-confidence/tied commitments (`tied_confidence_threshold = 0.5`, Arm `c1`) versus relying on raw leaf witnesses at `r` (`search_forms(scope="available_tree")`, Arm `c2`) versus ordinary single-winner assembly at `x` (`tied_confidence_threshold = None`, Arms `a1` and `a2`).
- **Option 1 (operator control):** Privileged synthetic intermediate truth at `x` with full unit analyses (`b1`) versus segment strings only (`whole:unknown`, `b2`), isolating segment-level accuracy from `FormAnalysis` (`cognate_set_id`) provenance.
- **Option 3 (robustness & order):** Tree rotation `((c,d)y,(a,b)x)r;` (`d1`, which changes which reconstructed sister clade is available in `reconstructed_evidence` when `x` runs) versus arbitrary serialization order (`commitment_order_reversal`, `child_order_swap_ba_vs_ab`, and `source_duplication`).

---

## 2. Two-Level Fixture and Survival Ledger (`two-level-propagation-v1`)

Built with `SyntheticFamilyDefinition` and `generate_family` (`cognate_reconstruction/synthesis/generator.py`) on `((a,b)x,(c,d)y)r;` with 12 concepts (`c001`–`c012`), 12 cognate units (`cog:two_level_propagation_v1:c001` .. `c012`), 8 primary retention/absence opportunities (`R1`–`R4`, `A1`–`A4`), 4 matched vowel-environment pairs (`P1`–`P4`), and 2 explicit ambiguity/loss controls (`L1`, `L2`):

| Group | Concepts | Root `*r` | `*x` | `*y` | Leaves `(a, b, c, d)` | What survives / is lost / remains underidentified |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`R1`–`R4`** (Complementary retention) | `c001`–`c004` (`P1`–`P4`) | `*p i k`, `*t e k`, `*p a k`, `*t u k` | `*p i k`, `*t e k`, `*p a k`, `*t u k` | `*p i g`, `*t e g`, `*p a g`, `*t u g` | `a`: `f i k, t e k, f a k, t u k`<br>`b`: `p i, t e, p a, t u`<br>`c`: `p i, t e g, p a, t u g`<br>`d`: `p i g, t e, p a g, t u` | Within `x`, `a` shifts `*p > f / #_` while retaining `-k`; `b` retains `*p` while deleting `*-k` after `{i,e,a,u}`. Within `y`, `*-k > *-g / _#`, and `c`/`d` delete `-g` in complementary vowel contexts (`{i,a}` vs `{e,u}`). When `x` runs before `y`, raw leaf outgroups `(c, d)` split `1–1` on every `R1`–`R4` item, whereas reconstructed `*y` preserves `*g` on all four. |
| **`A1`–`A4`** (Daughter-`a` innovation) | `c005`–`c008` (`P1`–`P4`) | `*m i`, `*n e`, `*m a`, `*n u` | `*m i`, `*n e`, `*m a`, `*n u` | `*m i`, `*n e`, `*m a`, `*n u` | `a`: `m i k, n e k, m a k, n u k`<br>`b`: `m i, n e, m a, n u`<br>`c`: `m i, n e, m a, n u`<br>`d`: `m i, n e, m a, n u` | `a` innovates final `-k` after nasal + vowel (`V > V k / N _ #`). Shares local `⟨a k : b Ø⟩` correspondence at `x` with `R1`–`R4`, against `0/2` outgroups. If `x` over-retains `-k`, `r` sees `⟨x k : y Ø⟩` and can still discount `-k` to `null`. |
| **`U1`–`U2`** (Unanimous velar anchors) | `c009`–`c010` | `*l o k`, `*s o k` | `*l o k`, `*s o k` | `*l o g`, `*s o g` | `a, b`: `l o k, s o k`<br>`c, d`: `l o g, s o g` | Unanimous retention after `o` in both clades; establishes the regular `⟨x k : y g⟩ → *k` correspondence at `r`. |
| **`L1`** (Unrecoverable root merger control) | `c011` (`underdetermined` at `r`) | `*w o` | `*l o` | `*l o` | `a, b, c, d`: `l o` | Parallel `w > l / #_` on both branch `x` and branch `y` merges `*w` with `*l` (`c009` `*l o k`). Identifiable as `*l o` at `x` and `y`, but strictly **underidentified at `r`** (`*w o` vs `*l o`) even under oracle intermediates. |
| **`L2`** (Whole-tree `2-vs-2` tie & restoration control) | `c012` (`underdetermined` at `x, y, r`) | `*k o t` (tied with `*k o`) | `*k o t` / `*k o` | `*k o t` / `*k o` | `a, c`: `k o t`<br>`b, d`: `k o` | `b` and `d` delete `-t`. Retention (2 losses on `b, d`) and absence (2 gains on `a, c`) tie at 2 changes across the whole tree. If both `x` and `y` collapse their `0.50` tie to `*k o`, `-t` is absent from `r`'s alignment and `verify_restorations` forbids restoring `-t` at the root (`restoration-without-outgroup`). |

---

## 3. Mechanical Findings on the Two-Level Diagnostic (`two-level-propagation-v1`)

All 7 arms run through `ingest_payload`, `TreeTraverser`, `ProtoInventoryAssembler`, `evaluate_run` (`task02-v1` and `task04-units-v1`), and `score_decisions` (`r02-decisions-v1`):

| Arm | Intervention / Evidence Changed at `x` and `r` | Privileged Control? | `x` Primary (`r02-decisions-v1`) | `x` Validated Exact (`task02-v1`) | `r` Primary (`r02-decisions-v1`) | `r` Matched Pairs (`P1`–`P4`) | `r` Validated Exact (`task02-v1`) | `r` Unit Exact (`task04-units-v1`) | `r` `L1` (`c011` `*w o`) Exact | `r` `L2` (`c012`) Beam Candidates | `r` Tuple / Column Work |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- | :---: |
| **`a1_single_winner_absent_on_tie`** | Ordinary path (`tied_confidence_threshold=None`): `x` commits `null` at `0.50` on `1–1` leaf-outgroup ties (`R1`–`R4`, `L2`); `r` applies active-child parsimony. | No | `4/8` | `7/11` | **`4/8`** | `0/4` | `6/10` | `6/10` | `0/1` (`*l o`) | `[*k o (1.0)]` (`*k o t` lost) | `12` tuples / `56` cols |
| **`a2_single_winner_over_retain`** | Ordinary path (`tied_confidence_threshold=None`): `x` over-retains `-k` on `R1`–`R4` (`0.50`) and `A1`–`A4` (`0.60`); `r` discounts `⟨x k : y Ø⟩ → null` and keeps `⟨x k : y g⟩ → *k`. | No | `4/8` | `7/11` | **`8/8`** | `4/4` | `10/10` | `10/10` | `0/1` (`*l o`) | `[*k o (1.0)]` (`*k o t` lost) | `12` tuples / `65` cols |
| **`b1_privileged_oracle_x_full`** | **Option 1 operator control:** `x` replaced by generator-truth forms + source `FormAnalysis` (`cog:two_level_propagation_v1:c001`..`c012`). | **Yes** (operator control) | `8/8` | `11/11` | **`8/8`** | `4/4` | `10/10` | `10/10` | `0/1` (`*l o`) | `[*k o (1.0)]` | `12` tuples / `61` cols |
| **`b2_privileged_oracle_x_segments_only`** | **Option 1 operator control:** `x` replaced by generator-truth segment strings with `whole:unknown` analysis (`cognate_set_id=None`). | **Yes** (operator control) | `0/8` (`unit_missing`) | `11/11` | **`0/8`** (`unit_missing`) | `0/4` | `10/10` | **`0/10`** | `0/1` (`*l o`) | `[*k o (1.0)]` | `12` tuples / `61` cols |
| **`c1_tied_beam_retention`** | **Option 2a:** Exact same `x` and `y` commitments as `a1`, with `tied_confidence_threshold=0.5` retaining competing proto-segments on `<= 0.50` columns. | No | `4/8` (top-1) | `7/11` (`11/11` beam) | **`8/8`** | `4/4` | **`10/10`** | **`10/10`** | `0/1` (`*l o`) | **`[*k o (0.5063), *k o t (0.4937)]`** (`0.5/0.5` at id=`1.0`) | `19` tuples / `104` cols |
| **`c2_leaf_witness_at_r`** | **Option 2b:** Single-winner `a1` at `x` and `y`; `r` calls `search_forms(scope="available_tree")` over raw leaves `a, b, c, d` and commits non-invertible `⟨x Ø : y g⟩ → *k`. | No | `4/8` | `7/11` | **`8/8`** | `4/4` | `10/10` | `10/10` | `0/1` (`*l o`) | **`[*k o (1.0)]`** (`restoration-without-outgroup` on `L2`) | `12` tuples / `56` cols |
| **`d1_tree_rotation_y_before_x`** | **Option 3 tree rotation:** `((c,d)y,(a,b)x)r;` visits `y` before `x`, placing reconstructed `y` (`*p i g, *t e g, *p a g, *t u g`) in `x`'s `OUTGROUP` evidence. | No | **`8/8`** | **`11/11`** | **`8/8`** | `4/4` | `10/10` | `10/10` | `0/1` (`*l o`) | `[*k o (1.0)]` | `12` tuples / `60` cols |

### Key Mechanical Findings

1. **Fundamental Asymmetry in One-Way Post-Order Traversal (`a1` vs. `a2`):**
   - *Over-retention at `x` (`a2`)* is recoverable at `r`: when `x` over-retains daughter `a`'s innovated `-k` on `A1`–`A4` (`*m i k, *n e k, *m a k, *n u k`), `r` aligns `x` against `y` (`*m i, *n e, *m a, *n u`) as `⟨x k : y Ø⟩` and discounts it to `null`, recovering `8/8` primary decisions and `10/10` validated exact at `r` (though `x`'s own scored output stays unrevised at `4/8`).
   - *Premature deletion / `null` tie-collapse at `x` (`a1`)* destroys the across-clade correspondence at `r`: when `x` collapses its `0.50` leaf-outgroup tie on `R1`–`R4` to `null` (`*p i, *t e, *p a, *t u`), `r` no longer sees the regular `⟨x k : y g⟩` correspondence on `R1`–`R4`, seeing only one-sided `⟨x Ø : y g⟩` and dropping from `8/8` to `4/8` (`6/10` validated exact).
2. **Corrected Segments vs. Corrected `FormAnalysis` at `x` (`b1` vs. `b2`):**
   - Supplying generator-truth segment strings at `x` without cognate-unit `FormAnalysis` (`b2`, `whole:unknown`) yields `10/10` raw whole-word segment exact at `r`, but triggers `unknown_whole = True` in [`align_tuple`](../../cognate_reconstruction/alignment/units.py) (`lines 177-185`), stripping `cognate_set_id` from `r`'s assembled output. Consequently, `task04-units-v1` `cognate_unit_exact` collapses from **`10/10` to `0/10`** and `r02-decisions-v1` collapses from **`8/8` to `0/8` (`8 unit_missing`)**.
   - Meanwhile, on `L1` (`c011`, root `*w o` with parallel `w > l / #_` on `x` and `y`), even full oracle truth at `x` (`b1`) scores `0/1` raw exact (`*l o`), confirming that parallel pre-clade mergers are strictly unidentifiable at the root.
3. **Tied-Alternative Beam Retention (`c1`) vs. Raw Leaf Witnesses at `r` (`c2`):**
   - **Option 2a (`c1_tied_beam_retention`, `tied_confidence_threshold = 0.5`):** Using the **exact same `x` and `y` commitments as `a1`**, expanding `confidence <= 0.50` columns on disagreeing child reflexes into both competing proto-segments (`None` and `"k"` on `R1`–`R4`; `None` and `"t"` on `L2`) keeps both `*C V` (`0.50`) and `*C V k` (`0.50`) in `x`'s beam. At `r`, the tuple `(x=*C V k, y=*C V g)` matches the high-confidence regular correspondence `⟨x k : y g⟩ → *k` (`0.90`), outranking `(x=*C V, y=*C V g) → *C V` (`0.50`) and rescuing `r` from **`4/8` to `8/8` primary decisions (`10/10` validated exact, `10/10` `cognate_unit_exact`)** with `r_non_invertible_child_ids = []`.
   - Furthermore, on `L2` (`c012`), `c1` preserves **both** `*k o` and `*k o t` in `r`'s beam (`beam_exact = True`), whereas in `c2_leaf_witness_at_r` (`tied_confidence_threshold = None`), even when `r` inspects raw leaf witnesses `a, b, c, d` via `search_forms`, `r` can rescue `R1`–`R4` (`⟨x Ø : y g⟩ → *k`, because `y` still carries `-g`) but is **mechanically blocked from restoring `-t` on `L2`** (`error_code: "restoration-without-outgroup"` in [`verify_restorations`](../../cognate_reconstruction/agent/tools/inventory_evidence.py)) because both active children `x` and `y` lost `-t` in their single-winner beams and the root has no outgroup.

---

## 4. Equivalent-Presentation Invariance vs. Tree-Rotation Information Availability

| Check | Declared Expectation | Observed Mechanical Result |
| :--- | :--- | :--- |
| **Tree rotation `((a,b)x,(c,d)y)r;` $\to$ `((c,d)y,(a,b)x)r;` (`d1`)** | **Real information-availability change** (not a presentation artifact): `y` completes first and enters `reconstructed_evidence` as an `OUTGROUP` for `x`. | Traversal order shifts from `['x', 'y', 'r']` to `['y', 'x', 'r']`. When `x` runs, `x_outgroup_node_ids` is `['c', 'd', 'y']` instead of `['c', 'd']`. Reconstructed `y` (`*p i g, *t e g, *p a g, *t u g`) breaks the `1–1` `(c, d)` leaf tie at `x`, raising `x` from `4/8` to `8/8` and `r` from `4/8` to `8/8` even under single-winner assembly. |
| **Commitment serialization order reversal** | **Strictly invariant:** `hypothesis_digest` sorts commitments and `build_plan` indexes by `set_id` / `reflexes`. | `x_evidence_revision_identical = True`, `x_top_forms_identical = True`, `r_top_forms_identical = True`. |
| **Active-child order swap `((b,a)x,(c,d)y)r;`** | **Forms and probabilities invariant; `evidence_revision` hash changes** because `child_ids = ('b', 'a')` reverses column reflex tuples. | `x_evidence_revision_changed = True`, `x_top_forms_identical = True`, `r_top_forms_identical = True`. |
| **Equivalent source duplication (1-form leaf concept vs. 2-variant leaf concept)** | **1-form duplicate:** candidate segments and probability (`1.0`) invariant; `PieceSource` provenance list lengthens from `1` to `2`.<br>**2-variant duplicate:** legitimate prior shift (`2/3` vs `1/3`). | 1-form duplicate (`f i k` twice): `1` candidate, `probability = 1.0`, `source_count = 2`.<br>2-variant duplicate (`f i k` twice, `f i` once): shifts leaf beam probabilities from `{'f i': 0.5, 'f i k': 0.5}` to `{'f i k': 0.6667, 'f i': 0.3333}`. |
| **Bounded operational-weight sensitivity (`identity_confidence = 0.95` vs `1.0` at `r` under `c1`)** | Validated top-1 forms (`c001`–`c010`) invariant; on `L2` (`c012`), `0.95 < 1.0` adds a `log(0.95)` length penalty to 3-column `(k o t, k o t)` vs 2-column `(k o, k o)`, whereas `1.0` yields an exact `0.50 / 0.50` tie. | Validated top forms identical (`10/10`); on `L2`, `identity_confidence = 0.95` gives `[*k o (0.5063), *k o t (0.4937)]` (`decided_by_tie_break = False`), whereas `identity_confidence = 1.0` gives `[*k o (0.5000), *k o t (0.5000)]` (`decided_by_tie_break = True`). |

---

## 5. Banked Live-Model Checkpoint Replays (`b-gemini`, `c-gemini-r04`, `c-local-qwen38-27b-r04`)

We replayed the exact committed `CommittedProtoInventory` at node `x` from the three completed live-model runs in R03 and R04 under `tied_confidence_threshold = None` versus `tied_confidence_threshold = 0.5` and propagated the resulting `x` beams into root `r`'s `evidence_map`:

- **`b-gemini`** ([`runs/experiments/r03-model-diagnostic-20261025-v2/runs/b-gemini`](../../runs/experiments/r03-model-diagnostic-20261025-v2/runs/b-gemini), `checkpoint.json` `sha256: 65d687085fd9f1e4…`, `trajectories.jsonl` `sha256: 7bf7b08fd71124f2…`):
  - `tied_confidence_threshold = None` reproduces the banked `checkpoint.json` `output_beam` bit-for-bit.
  - Exactly **2** commitments have `confidence <= 0.5` (`csu-406b67ac832161114a675933` on `w13` / `U1` and `csu-73b0ec7639f816f1006cb82a` on `w08` / `U2`, both committed as `proto_segment = None` at `0.50`).
  - Under `tied_confidence_threshold = 0.5`, **0** of the 10 non-tied concepts change, while `w13` expands from `[['k', 'u'] (1.0)]` to `[['k', 'u'] (0.5), ['k', 'u', 'k'] (0.5)]` (`decided_by_tie_break: False -> True`) and `w08` expands from `[['k', 'e'] (1.0)]` to `[['k', 'e'] (0.5), ['k', 'e', 'n'] (0.5)]` (`decided_by_tie_break: False -> True`).
  - At parent `r` (`((a,b)x,c)r;`, where outgroup `c` has a non-cognate unit `c91` / `c92` on `w13` and `w08`), single-winner assembly permanently erases `k u k` and `k e n` from `r`'s input, whereas `tied_confidence_threshold = 0.5` preserves both alternatives in `r`'s alignment tuples with **zero extra tuple/column work** (`14` candidate tuples / `84` projected columns in both modes, because `cog:c58` and `cog:c15` are 1-child units at `r`).
- **`c-gemini-r04`** ([`runs/experiments/r04-stage-c-20261029-v2/runs/c-gemini-r04`](../../runs/experiments/r04-stage-c-20261029-v2/runs/c-gemini-r04), `checkpoint.json` `sha256: 292c6a9216906247…`) and **`c-local-qwen38-27b-r04`** ([`runs/experiments/r04b-local-qwen38-27b-20261030/runs/c-local-qwen38-27b-r04`](../../runs/experiments/r04b-local-qwen38-27b-20261030/runs/c-local-qwen38-27b-r04), `checkpoint.json` `sha256: 028749c4223d3017…`):
  - `tied_confidence_threshold = None` reproduces both banked `output_beam`s bit-for-bit.
  - In both runs, exactly **4** commitments have `confidence <= 0.5` (`T1` `y05`, `T2` `y03`, `T3` `y09`, `T4` `y08`, all committed as `proto_segment = "k"` at `0.50`).
  - Under single-winner assembly, `x` emits only `s i k`, `t a k`, `m u k`, `n e k` (`probability = 1.0`, `decided_by_tie_break = False`). When propagated to `r` (`((a,b)x,c,d,f)r;`), `x` casts an unhedged `1.0` vote for `-k`, turning the genuine `2-vs-2` leaf ties on `y05` (`{a,d}` vs `{b,f}`) and `y03` (`{a,f}` vs `{b,d}`) into apparent **`2-of-3` active-child majorities** (`x, d` vs `f` on `y05`; `x, f` vs `d` on `y03`), and erasing `m u` and `n e` on `y09` and `y08`.
  - Under `tied_confidence_threshold = 0.5`, **0** of the 15 non-tied concepts change, while `y05, y03, y09, y08` expand to `[['s', 'i'] (0.5), ['s', 'i', 'k'] (0.5)]`, `[['t', 'a'] (0.5), ['t', 'a', 'k'] (0.5)]`, `[['m', 'u'] (0.5), ['m', 'u', 'k'] (0.5)]`, and `[['n', 'e'] (0.5), ['n', 'e', 'k'] (0.5)]` (`decided_by_tie_break = True`). At `r`, `candidate_tuples` increases by only `+3` (`18 -> 21`) and `projected_columns` by `+25` (`162 -> 187`), exposing both the retention and loss alignments on `y05` and `y03` at equal incoming child mass (`0.50` each).

---

## 6. Independent Audit, Limits, and Recommendation

### 6.1 Independent Counterfactual Audit Summary

An independent read-only `research` subagent (`5015a0bb-3aca-4784-a0ce-29d455a3ddc4`) audited the code changes, fixture, and counterfactual results (**Verdict: `PASS`**):
- Verified that `b1_privileged_oracle_x_full` and `b2_privileged_oracle_x_segments_only` carry explicit `privileged_operator_control: True` / `deployable_baseline: False` annotations and that no non-privileged arm reads `historical_form_bindings`, `answer_key`, or `underdetermined_concepts`.
- Verified that `c1_tied_beam_retention` uses the identical `x` and `y` `ProtoInventorySpec` commitments as `a1_single_winner_absent_on_tie` and that the `4/8 -> 8/8` gain at `r` comes purely from preserving `x`'s `0.50`-confidence alternative in `x`'s beam so `r` can align `⟨x k : y g⟩`.
- Verified that `b2` vs `b1` isolates `FormAnalysis` provenance (`cognate_set_id`) from segment accuracy (`10/10` raw exact vs `0/10` `cognate_unit_exact`), and that `c2` hits `restoration-without-outgroup` on `L2` (`c012`).
- Verified that `tied_confidence_threshold = None` reproduces the banked `b-gemini`, `c-gemini-r04`, and `c-local-qwen38-27b-r04` `output_beam`s at `x` bit-for-bit, while `tied_confidence_threshold = 0.5` expands only the `confidence <= 0.5` tied concepts (`w13, w08` in Stage B; `y05, y03, y09, y08` in Stage C).

### 6.2 Limits

1. **Offline scope:** All root-node (`r`) evaluations in R05 use scripted comparative decision rules or banked `x` checkpoints; how a live LLM at `r` navigates multi-candidate input beams from `x` under `tied_confidence_threshold = 0.5` remains **unknown** until a bounded two-node live run is authorized.
2. **Column-length mass bias when `identity_confidence < 1.0`:** Because `assemble_concept` sums `outcome.log_mass` across resolved columns, setting `confidence < 1.0` on unanimous identity columns slightly penalizes longer candidate tuples (`0.5063` vs `0.4937` at `0.95`, versus exact `0.5000 / 0.5000` at `1.0`).
3. **Daughter-reflex scope of `_column_tied_alternatives`:** When a single commitment has `confidence <= threshold` and `len(set(reflexes)) > 1`, `_column_tied_alternatives` expands alternatives from `competing_choices` plus the column's observed child `reflexes`. This is exact for presence/absence ties (`⟨k : Ø⟩`) and 2-way reflex ties where the proto-segment is one of the child reflexes, whereas an unattested third proto-segment requires an explicit competing commitment.
4. **Unrecoverable pre-clade mergers (`L1`):** Neither tied-beam retention (`c1`), leaf witness lookup (`c2`), tree rotation (`d1`), nor privileged intermediate truth (`b1`) can recover a contrast (`*w` vs `*l` on `c011`) that merged in parallel on every descendant branch below `r`.

### 6.3 Recommendation and Downstream Gate Assessment

1. **Recommendation (adopt targeted tied-alternative beam retention, not joint global search):**
   - Retain the opt-in `tied_confidence_threshold: float | None = None` mechanism in [`ProtoInventoryAssembler`](../../cognate_reconstruction/traversal/assembler.py) (default `None` to preserve all historical digests; `0.5` when warranted-uncertainty beam propagation is enabled) and preserve explicit `FormAnalysis` (`cognate_set_id`) across every intermediate node.
   - Do **not** build a joint global inference engine or automatic tree-revision loop: the propagation loss identified in R03–R05 is caused specifically by collapsing explicitly marked `confidence <= 0.50` local ties into width-1 beams at intermediate nodes, and `tied_confidence_threshold = 0.5` resolves both the synthetic two-level loss (`4/8 -> 8/8` at `r`, `L2` beam preservation) and the banked Stage B / Stage C tie-collapse (`b-gemini`, `c-gemini-r04`, `c-local-qwen38-27b-r04`) at negligible tuple cost (`+0` to `+7` tuples per node).
2. **Downstream R06 / R07 assessment:**
   - Per the R05 brief ("Amend R06 only if forward applications would answer the remaining question, or R07 if locating failures is the more useful contribution"), we amend **only [`prompts/post-review/07-assisted-hypothesis-criticism.md`](../../prompts/post-review/07-assisted-hypothesis-criticism.md)** (leaving `06-forward-prediction.md` untouched): R05 established that the remaining two-level failure modes are concrete, auditable hypothesis/trace defects (upstream tie-collapse masquerading as a `2-of-3` active-child majority at `r`, silent `residue_policy: "drop"` truncation or uninspected outgroups, loss of `FormAnalysis` unit provenance, and `< 1.0` identity-confidence length penalties) that directly inform deterministic and assisted hypothesis criticism in R07.
