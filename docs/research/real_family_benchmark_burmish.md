# B02 — Live Real-Family Benchmark (`gemini/gemini-3.8-flash` on Burmish), Stage 1 Gate Forensics, Bounded Offline Bugfixes, and Next-Step Gate

- **Date:** 2026-11-11
- **Stage:** `B02` ([`prompts/02-real-family-live-benchmark.md`](../../prompts/02-real-family-live-benchmark.md))
- **Launch Base Commit (`HEAD`):** `8243dfc52df3d8b1b2be196592e79efbed9ec7cc` (`main`, `dirty_paths: []`)
- **Experiment Directory:** `runs/experiments/b02-burmish-gemini-benchmark/`
- **Run Directory & ID:** `runs/experiments/b02-burmish-gemini-benchmark/runs/burmish-gemini/` (`b02-burmish-gemini`, `trajectory-b6263219-6775-4151-b2f9-d8a22183dba8`)
- **Machine-Readable Results:** [`docs/research/real_family_benchmark_burmish_results.json`](real_family_benchmark_burmish_results.json)
- **Driver & Evaluators:** [`tools/real_family_benchmark_probe.py`](../../tools/real_family_benchmark_probe.py) (`b02-real-family-eval-v1`), `task02-v1`, `task04-units-v1`, `units-v2`, `r06-forward-v1` ([`cognate_reconstruction/evaluation/forward.py`](../../cognate_reconstruction/evaluation/forward.py)), `r07-critic-v1` / `real_run_provenance_v1` ([`cognate_reconstruction/evaluation/critic.py`](../../cognate_reconstruction/evaluation/critic.py)), `r02-ledger-v1` / `abrupt-loss-v1` ([`cognate_reconstruction/benchmarks/ledger.py`](../../cognate_reconstruction/benchmarks/ledger.py))
- **Certified Live Paid Spend (`Stage 1` only):** `1` serial trial at `maruic` (`22` provider requests, `22` turns, `20` executed tool calls, `4,434,603` input tokens, `3,588,670` cached input tokens [`80.92%` cache hit rate], `88,855` output tokens [`36,099` reasoning]), **`US$3.659158` uncached table upper bound** (`3.6591585` exact journal sum against `--max-total-cost-usd 3.50` cap and `<= US$10.00` hard ceiling) / **`US$1.236806` actual cached-adjusted spend**, **`696.1282 s` launcher wall time** (`695.4494 s` journal elapsed); **`US$0.00` wasted on `burmic` or `proto_burmish`**.

---

## 1. Executive Summary & Stage 1 Gate Decision

`B02` executed the pre-registered two-stage single-checkpoint live benchmark on [`benchmarks/burmish.json`](../../benchmarks/burmish.json) (`maruic`, `burmic`, `proto_burmish`; `54` validated root concepts, `37` Old Burmese `provisional_proxy` concepts, morpheme-sliced `cog:*` partial cognacy, and 100% preserved tone tokens) using `gemini/gemini-3.8-flash` (`--preset gemini --reasoning-effort medium`, `temperature = 1.0`, `max_tokens = 32768`, `--inventory-protocol stored-hypothesis`, `--tied-confidence-threshold 0.5`, `--compaction-watermark-tokens 256000`).

1. **Clean Stage 1 Gate Halt (`$1.24` real spend, `$0.00` downstream waste):**
   - Stage 1 (`--stop-after-node maruic --max-total-cost-usd 3.50 --max-run-seconds 1500`) ran `22` turns at `maruic` (`738` local `csu-*` sets, `320` `csp-*` recurrence patterns). On Turn 22 (`input_tokens = 483,849`), Gemini returned a `14,873`-output-token `tool_calls` repair response that pushed cumulative uncached table cost from `$3.240498` to **`$3.6591585 >= $3.50`** (`$1.236806` cached-adjusted). `AgentOrchestrator._complete_with_retry` raised `RunBudgetExceeded` pre-dispatch, recording `status = "interrupted"` with zero unknown-cost or unrecorded requests (`history_certified = True`).
   - `gate-stage1` and `audit-run` (`$0` offline) functioned exactly as designed: `gate_stage1.json` marked `usable = False` (`maruic missing from checkpoint.steps_by_node`), halting before Stage 2 (`--resume`) and preventing any expenditure on `burmic` or `proto_burmish`.
   - Per `preregistration.md` §4.3 (*"Zero automatic reruns or prompt edits mid-run"*) and [`docs/experiment_policy.md`](../experiment_policy.md) (`$0.909312` one-response headroom inside the `$10.00` hard ceiling leaves at most `$5.43` uncached cap for a 3-node restart—below the `$6.74` mean uncached 3-node cost of pre-R01 sweeps), **paid inference stops cleanly at the Stage 1 gate**.
2. **Root-Cause Separation (3 Distinct Strata):**
   - **Stratum (i) — 4 Concrete Runtime Bugs in `proto_assembly.py` and `orchestrator.py` (Fixed Offline at `$0` in `B02`):**
     1. `proto_assembly.py:assembly_result` cleared `columns=()` under `detail="summary"` while leaving full `source_positions` provenance on `unmatched_columns` (`245,995 B` compact / `257,521 B` spaced = `92.1%`–`96.4%` of Turn 17's `267,149 B` preview).
     2. `orchestrator.py:_supersedes` compared un-normalized raw arguments and required exact `limit` equality, preventing Turn 16 `summarize_correspondences(limit=50, offset=0)` from superseding Turn 2 `summarize_correspondences(reading="recurrence")` (`offset=0, limit=30`, stranding `68,897 B` / `38,226` tokens).
     3. `orchestrator.py:_compact_watermark_previews` stubbed `805 B` empty identity probes (Turns 7 & 8) into `873 B` stubs (`+68 B` each, net `-5,215 B` across 3 stubs), mutating `msg[15]` early in the prompt and invalidating Gemini's prefix cache on Turn 19 (`246,893 -> 15,135` cached tokens; `$0.327424` single-turn real cash cost = `26.5%` of total Stage 1 actual spend).
     4. `orchestrator.py:_complete_with_retry` / `run()` raised `RunBudgetExceeded` after appending `provider_responses` but before updating `state.latest_prompt_tokens` / `state.peak_prompt_tokens` and `messages.audit`, leaving `compaction_summary.peak_prompt_tokens` (`468,811`) one turn behind `max_request_input_tokens` (`483,849`) and omitting Turn 22's paid assistant message from `trajectories.jsonl`.
   - **Stratum (ii) — Architectural `units-v2` Scaling Friction on `738`-Set Morpheme-Sliced Nodes (Deferred to `B03`):** `units-v2` expanded `maruic` from `150` legacy sets (`39` at `support >= 2`) to `738` local `csu-*` sets (`113` `csp-*` patterns at `support >= 2`), requiring `~299k` tokens of disjoint survey/alignment pages and `14.8k–22k+` output tokens for full-replacement `shared_claims` JSON (causing Turn 20's `32,764`-token truncation). Moreover, `$0` offline deduplicated replay of Turn 21 (`394/738` sets) proves `inventory_contrast_reductions` flags **`346/394` (`87.82%`)** sets for `missing-directionality-rationale` (`commit_ready = False`) by treating unanimous retentions (`['j','j','j','j'] -> *j`) and 1-daughter compound boundaries (`[None,'+',None,None] -> *+`) as unconditioned mergers whenever two tuples share a proto-segment.
   - **Stratum (iii) — Uncached-vs-Cached Cost-Cap Calibration:** `pricing.py` enforced `--max-total-cost-usd 3.50` on uncached table prices (`$0.75/1M` on all `4.43M` input tokens), which at `80.92%` cache hit translated to a `$1.18` real-cash ceiling—below two of the four pre-R01 `maruic` runs (`$4.1120` and `$3.9012` uncached).

---

## 2. Provenance, Frozen Configuration, & Artifact SHA-256 Digests

### 2.1 Model-Visible Contract & Configuration Digests

All live Stage 1 requests used the frozen `stored-hypothesis` contract from [`manifest.b02-burmish.json`](../../runs/experiments/b02-burmish-gemini-benchmark/manifest.b02-burmish.json) (`configuration_sha256 = 89a49065883951bc68bc0943898ae6681be7ee6f9371ef52fe3c417d5e69ed22`):

- **`the evidence/assembly contract`:** `b1f459e783712306fab58d8a350a304ad52ba5b8db660d2444afc33a77e19ec7`
- **`the agent instructions`:** `0b9d91cf5f5fd469fea1f5ec277ab436b7a412d4d2a87b94a766ff37166dc46d`
- **`the node commit requirements`:** `1ddfc0fcf882c4d425b1bb09aeb0cd74f05c5e18d52e4d5c8e51282cd03c1e4c`
- **`the tool schemas`:** `628f0f32eca43a872c7fb72c90e67b1ba3e00b9a1f9b4057e1cf702175584a72`
- **`first_request_maruic`:** `node_prompt_sha256 = 21a54c336f8268910b6eefa9f63a51ed1edce9934267494eb74e4b1e5e2d1094` (`3,098` chars), `tool_definitions_sha256 = d8566a1c5282e2253c7f799de10031703c8c515f47b89e389b2a617a59265359`
- **Post-Bugfix Digest Invariance:** All four `behavioural_digests("stored-hypothesis")` above and active recomputation of banked `c-gemini-r04` (`339adb1338add17c78a0b5477d9c0b9dd85b64501e2be314951627861adce38a`) remain **100% bit-for-bit identical** after the four `B02` offline runtime bugfixes (§7).

### 2.2 Complete Post-`evaluate` Artifact Digest Table (`19` Files on Disk)

Recomputed directly from disk after offline `evaluate` finalized `runs/burmish-gemini/evaluation.json` and `batch_ledger.json` (`written_at = 2026-11-11T17:50:19.069892+00:00`; pre-`evaluate` Stage 1 `batch_ledger.json` snapshot was `35307fa2c2f878734b55871a4bec32f175ee827df09d7b6b638ed22169d2401b`):

| Relative Path (`runs/experiments/b02-burmish-gemini-benchmark/`) | Bytes | SHA-256 |
|---|---:|---|
| `batch_events.jsonl` | `2,160` | `d6de734d394ad5679e1820192dc481b54c0f4c6c6c6e9b1288f40c373f576544` |
| `batch_ledger.json` | `5,333` | `3ad9c02faeb318ed5b4d2b5960f4888b6c9f79467d8427cce87bf437561e5ca9` |
| `inputs/burmish.payload.json` | `1,515,426` | `092ae5b1534f3beb025d5114d4b37524ea213411a5595a6870df1bc2d63d39e9` |
| `inputs/price-table.json` | `521` | `f07736e17fe8a06a8b4e9a77d0d43577a071d456066aa0d993d161bc1950f521` |
| `inputs/provider-config.json` | `26` | `027bbb0a9e0d8ac63339623ff801caecd5de86d0d5f381feff0775ab5c13b01b` |
| `manifest.b02-burmish.json` | `33,769` | `b717efd6c7013c900f9f23ba15cef4626fa1d79812a8e767deaef44c41b11805` |
| `preregistration.md` | `11,206` | `95a6ad3b164a3b2b51757bf95bfadeff8a074cb391da3e4e1b24e7f74e091204` |
| `review.md` | `11,990` | `405a83413d175ef893b2443c34e00bf6a0f0e3dd43f32df9b4b7a5430dd6bea1` |
| `runs/burmish-gemini/checkpoint.json` | `1,460` | `e2aa105dcd6937b66360ed68efc91f7c333e0df2ec6a269b103e97c993223913` |
| `runs/burmish-gemini/checkpoint.requests.jsonl` | `35,522` | `6e95006a7898d671a6db0ad53063cb69d16b0b395883b369b29b10a84ac19991` |
| `runs/burmish-gemini/evaluation.json` | `225,599` | `915de014385e6960894e47cdc01c63585ba622fb4e9169a7dd3c63701b211639` |
| `runs/burmish-gemini/events.jsonl` | `995,480` | `d8ac8097c3b07ee70bebfb2736f484cee6c2a9c616da4d5f008161e82865f9e2` |
| `runs/burmish-gemini/gate_stage1.json` | `4,293` | `6279721ca2d09e4996ee786de2547c13f5af416a93ab5a0e6df568343cf76e0b` |
| `runs/burmish-gemini/inspect_stage1.txt` | `6,433` | `4ce4df6a64c55e362f2408b538836fee9d2bfb039ed31c8db51c893d5b5b79c6` |
| `runs/burmish-gemini/run_summary.json` | `212,993` | `e1d96cd230bedc05d4370f2b369b19422243540140154e4d3c1f9bfe3b57dd99` |
| `runs/burmish-gemini/stage1.stderr.log` | `22,138` | `1c483634db392ab41633e38c88bdef1436019aa5363851934110f0c41a0b61e0` |
| `runs/burmish-gemini/stage1.stdout.log` | `0` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `runs/burmish-gemini/trajectories.jsonl` | `1,145,330` | `4a776b4616face9cca05958ce706fda1b8fc2dc54eb16a28325faee7576e0e94` |
| `source_manifest.json` | `28,846` | `5a811ce7064ee669ae1d6e7cc448797765fdadb01d5d5e6fcfbd0bcd717263de` |

---

## 3. Certified Resource & Request-by-Request Ledger (`maruic`, Requests 1–22)

Cross-verified across `trajectories.jsonl` (`provider_responses[0..21]`), `checkpoint.requests.jsonl` (`88` records: `journal_opened`×1, `turn`×22, `request_start`×22, `request_end`×22, `tool_call`×20, `usage_recorded`×1), `events.jsonl` (`91` events), `run_summary.json`, and `batch_ledger.json`. Pricing (`price-table.json`, `f07736e1…`): uncached table `$0.75/1M` input + `$3.75/1M` output (`cost_usd`); cached-adjusted `$0.75/1M` uncached input + `$0.075/1M` cached input + `$3.75/1M` output (`provider_reported_cost_usd`).

| Turn | `input_tokens` | `cached_input_tokens` | `output_tokens` | `reasoning_tokens` | `finish_reason` | Dur (s) | Uncached $ (Cum $) | Cached-Adj $ (Cum $) | Tool Call (`call_id` suffix) | `ok` / Outcome | Res B | Compaction / Control Event |
|---:|---:|---:|---:|---:|---|---:|---|---|---|---:|---:|---|
| 1 | 16,120 | `null` (0) | 95 | 83 | `tool_calls` | 4.95 | `0.012446` (`0.012446`) | `0.012446` (`0.012446`) | `list_available_nodes` (`..a285`) | `true` | `1,371` | — |
| 2 | 16,706 | 14,069 | 149 | 130 | `tool_calls` | 5.11 | `0.013088` (`0.025535`) | `0.003592` (`0.016038`) | `summarize_correspondences` (`..1a19`) | `true` | `68,897` | — |
| 3 | 55,081 | 16,772 | 176 | 84 | `tool_calls` | 5.12 | `0.041971` (`0.067505`) | `0.030650` (`0.046688`) | `get_alignments` (`..2a09`) | `true` | `166,043` | — |
| 4 | 116,626 | 55,134 | 594 | 571 | `tool_calls` | 9.91 | `0.089697` (`0.157202`) | `0.052482` (`0.099169`) | `summarize_correspondences` (`..681b`) | `true` | `955` | Exceeds `96k` local Qwen watermark |
| 5 | 117,526 | 114,568 | 111 | 82 | `tool_calls` | 4.91 | `0.088561` (`0.245763`) | `0.011227` (`0.110396`) | `summarize_correspondences` (`..fb0a`) | `true` | `9,980` | — |
| 6 | 122,197 | 117,520 | 352 | 333 | `tool_calls` | 7.71 | `0.092968` (`0.338731`) | `0.013642` (`0.124038`) | `list_available_nodes` (`..6817`) | `true` | `46` | — |
| 7 | 122,568 | 120,139 | 234 | 187 | `tool_calls` | 6.11 | `0.092804` (`0.431534`) | `0.011710` (`0.135748`) | `test_proto_assembly` (`..6090`) | `true` | `805` | Empty identity probe (`choices=[]`) |
| 8 | 123,107 | 120,510 | 167 | 103 | `tool_calls` | 5.08 | `0.092957` (`0.524491`) | `0.011612` (`0.147360`) | `test_proto_assembly` (`..2265`) | `true` | `805` | Empty identity probe (`1223`) |
| 9 | 123,580 | 121,049 | 485 | 462 | `tool_calls` | 9.24 | `0.094504` (`0.618995`) | `0.012796` (`0.160156`) | `search_forms` (`..a51f`) | `true` | `52,484` | — |
| 10 | 146,065 | 123,597 | 613 | 501 | `tool_calls` | 9.89 | `0.111848` (`0.730842`) | `0.028420` (`0.188575`) | `get_alignments` (`..fe63f`) | `true` | `26,127` | 7 nodes (`1248, 1350`) |
| 11 | 158,825 | 146,069 | 423 | 321 | `tool_calls` | 8.17 | `0.120705` (`0.851547`) | `0.022108` (`0.210684`) | `polarize` (`..2d7c`) | `false` (`unknown-correspondence-set`) | `191` | Mismatched `csp-*` ID |
| 12 | 159,297 | 156,767 | 363 | 292 | `tool_calls` | 8.74 | `0.120834` (`0.972381`) | `0.015016` (`0.225700`) | `polarize` (`..de21`) | `true` | `6,384` | Repaired `["ʔ","ʔ","k","k"]` |
| 13 | 162,602 | 159,290 | 394 | 355 | `tool_calls` | 8.68 | `0.123429` (`1.095810`) | `0.015908` (`0.241608`) | `test_sound_law` (`..c472`) | `true` | `25,776` | `ʔ > k / _ #` on Atsi |
| 14 | 174,007 | 162,606 | 707 | 672 | `tool_calls` | 11.54 | `0.133157` (`1.228966`) | `0.023397` (`0.265006`) | `summarize_correspondences` (`..3caf`) | `true` | `9,593` | `concept_ids=["1209"]` |
| 15 | 179,220 | 174,003 | 397 | 163 | `tool_calls` | 7.75 | `0.135904` (`1.364870`) | `0.018452` (`0.283457`) | `test_proto_assembly` (`..8b26`) | `true` | `6,224` | `3` choices on `["1209"]` (`full`) |
| 16 | 182,229 | 179,213 | 1,929 | 1,908 | `tool_calls` | 23.24 | `0.143906` (`1.508776`) | `0.022937` (`0.306394`) | `summarize_correspondences` (`..6cd4`) | `true` | `116,689` | `offset=0, limit=50` |
| 17 | 246,816 | 182,287 | 530 | 302 | `tool_calls` | 12.78 | `0.187100` (`1.695875`) | `0.064056` (`0.370450`) | `test_proto_assembly` (`..4fc8`) | `true` | `267,149` | `3` choices over 54 concepts (`last_preview`) |
| 18 | 363,088 | 246,893 | 14,086 | 14,064 | `tool_calls` | 97.65 | `0.325139` (`2.021014`) | `0.158486` (`0.528936`) | `summarize_correspondences` (`..ff29`) | `true` | `105,052` | **Watermark trigger** (`363,088 >= 256,000`): stubbed `msg[15], msg[17], msg[31]` |
| 19 | 427,502 | **15,135** | 4,537 | 4,514 | `tool_calls` | 49.23 | `0.337640` (`2.358654`) | **`0.327424`** (`0.856360`) | `summarize_correspondences` (`..74c8`) | `true` | `75,086` | Prefix cache busted at `msg[15]` (`3.54%` hit) |
| 20 | 468,781 | 427,517 | **32,764** | 10,618 | `length` | 208.27 | `0.474451` (`2.833105`) | `0.185877` (`1.042237`) | *(none — truncated)* | `response_truncated` | `0` | `truncation_recovery` (`tool_choice="required"`) |
| 21 | 468,811 | 466,723 | 14,876 | 123 | `tool_calls` | 96.08 | `0.407393` (`3.240498`) | `0.092355` (`1.134592`) | `test_proto_assembly` (`..e38c`) | `false` (`invalid-shared-claim`) | `647` | `3` choices + `55` `shared_claims` (`394` sets; `2` overlap) |
| 22 | **483,849** | 468,809 | 14,873 | 231 | `tool_calls` | 92.82 | `0.418661` (**`3.659158`**) | `0.102214` (**`1.236806`**) | *(received; aborted pre-dispatch)* | `RunBudgetExceeded` | `0` | `$3.6591585 >= $3.50` uncached cap |
| **Total** | **4,434,603** | **3,588,670** (`80.92%`) | **88,855** | **36,099** | — | **695.45** (`696.13` wall) | **`$3.6591585`** | **`$1.236806`** | **20 calls** (`2` rejected) | `interrupted` | **`940,304`** | `watermark_trigger_count=1`, `compacted_preview_results=3` |

---

## 4. Side-by-Side Comparison: Deterministic Ceilings vs Pre-R01 Gemini 3.7 vs `B02` Live Gemini 3.8 Flash

### 4.1 Deterministic Ceilings (`beam_width = 5`, `boundaries = "include"`, Tones 100% Intact)

| Instrument / Oracle Mode | Gold Target | Validity | `n` | Top-1 Exact | Beam Exact | Mean Top NED | Mean Word BCubed F1 | Notes |
|---|---|---|---:|---|---|---:|---:|---|
| Daughter selection bar | `proto_burmish` | `validated_target` | 54 | `0/54` (`0.00%`) | — | — | — | `0` gold forms copyable verbatim from daughters |
| `assembly_ceiling` (node-local) | `proto_burmish` | `validated_target` | 54 | `6/54` (`11.11%`) | — | — | — | Reflex-restricted lower bound (`5/54` flat) |
| `oracle_ceiling --oracle context_free` | `proto_burmish` | `validated_target` | 54 | `7/54` (`12.96%`) | `15/54` (`27.78%`) | `0.489644` | `0.909540` | `236` rules |
| `oracle_ceiling --oracle contextual` | `proto_burmish` | `validated_target` | 54 | `16/54` (`29.63%`) | `26/54` (`48.15%`) | `0.292615` | `0.960443` | `621` rules, `1` fallback branch |
| `oracle_ceiling --oracle assembly` | `proto_burmish` | `validated_target` | 54 | `42/54` (`77.78%`) | `42/54` (`77.78%`) | `0.070370` | `0.988598` | `529` commitments, `0.000` unaccounted col rate |
| Daughter selection bar | `burmic` (`OldBurmese`) | `provisional_proxy` | 37 | `0/37` (`0.00%`) | — | — | — | `0` proxy forms copyable verbatim |
| `assembly_ceiling` (node-local) | `burmic` (`OldBurmese`) | `provisional_proxy` | 37 | `4/37` (`10.81%`) | — | — | — | Reflex-restricted lower bound |
| `oracle_ceiling --oracle context_free` | `burmic` (`OldBurmese`) | `provisional_proxy` | 37 | `11/37` (`29.73%`) | `15/37` (`40.54%`) | `0.370967` | `0.951593` | `194` rules |
| `oracle_ceiling --oracle contextual` | `burmic` (`OldBurmese`) | `provisional_proxy` | 37 | `10/37` (`27.03%`) | `17/37` (`45.95%`) | `0.312484` | `0.955025` | `380` rules, `1` fallback branch |
| `oracle_ceiling --oracle assembly` | `burmic` (`OldBurmese`) | `provisional_proxy` | 37 | `25/37` (`67.57%`) | `25/37` (`67.57%`) | `0.090015` | `0.974465` | `335` commitments |

### 4.2 Family-Level Outcome Comparison (Tones 100% Intact)

| Run / Arm | Model & Evidence Regime | Committed Nodes | `proto_burmish` (`n=54`) Top Exact / Mean NED / Word BCubed | `proto_burmish` R06 `corpus_bcubed_f1` (`P` / `R`, `bijective`) | `burmic` (`n=37`) Top Exact / Mean NED / R06 `corpus_bcubed_f1` | `audit-run` Defects (`maruic` / `burmic` / `proto_burmish`) | 3-Node Cost (Cached-Adj / Uncached Table) |
|---|---|---|---|---|---|---|---|
| `t36-r2/seed-00` | `gemini-3.7-flash` (legacy `150` sets) | `2/3` (`maruic` fallback) | `0/54` / `0.707279` / `0.861123` | `0.390326` (`0.436447` / `0.353021`, `False`) | `0/37` / `0.672351` / `0.473031` | **`12`** (`9` / `2` / `1`; `0` root FP) | `$2.827991` / `$8.949286` |
| `t36-r2/seed-01` | `gemini-3.7-flash` (legacy `150` sets) | `3/3` | `0/54` / `0.706526` / `0.889002` | `0.472894` (`0.487920` / `0.458766`, `False`) | `1/37` (`NEEDLE`) / `0.666645` / `0.452765` | **`7`** (`3` / `4` / `0`; `0` root FP) | `$2.197753` / `$6.994879` |
| `t36-r3/seed-00` | `gemini-3.7-flash` (legacy `150` sets) | `3/3` | `0/54` / `0.738608` / `0.857031` | `0.394367` (`0.438775` / `0.358123`, `False`) | `0/37` / `0.714843` / `0.443895` | **`16`** (`8` / `7` / `1`; `0` root FP) | `$1.935673` / `$5.098639` |
| `t36-r3/seed-01` | `gemini-3.7-flash` (legacy `150` sets) | `3/3` | `0/54` / `0.689469` / `0.890353` | `0.478021` (`0.472987` / `0.483164`, `False`) | `0/37` / `0.682561` / `0.505197` | **`6`** (`3` / `2` / `1`; `0` root FP) | `$1.793139` / `$5.905770` |
| **Pre-R01 4-Seed Mean / Aggregate** | `gemini-3.7-flash` (`4` repeated runs) | **`11/12`** | **`0/216`** / **`0.710471 ± 0.020482`** / **`0.874377 ± 0.017754`** | **`0.433902 ± 0.048058`** (`0/4` bijective) | **`1/148`** / **`0.684100 ± 0.021527`** / **`0.468722 ± 0.027203`** | **`41` total** (`24` uninspected outgroup, `7` provenance loss, `10` `<1.0` identity bias) | **`$2.188639` / `$6.737144`** (mean) |
| **`B02` Stage 1 (`b02-burmish-gemini`)** | `gemini-3.8-flash` (`medium` thinking, `units-v2` `738` sets, `tied=0.5`, `wm=256k`) | **`0/3`** (`maruic` interrupted at Stage 1 gate; `burmic` & `proto_burmish` unattempted) | **`0/54` missing** (`end_to_end_output_top_exact_rate = 0.0`, `mean_ned = null`) | **`0.000000`** (`output_kind = "missing"`, `evaluated_concept_count = 0`, `False`) | **`0/37` missing** (`mean_ned = null`, `R06 = 0.000000`) | **`0`** at `maruic` (`last_preview`; `burmic` & `proto_burmish` unattempted) | **`$1.236806` / `$3.659158`** (`maruic` only; `$0.00` downstream) |

**Why Multi-Node `None` vs `0.5` Counterfactual Tied-Beam Replay Was Not Reached:** In `evaluation.json`, `counterfactual_tied_beam_replay` reports `nodes_replayed = []` and `node_deltas = {}` under both `single_winner_none` and `tied_beam_0_5`. Isolating the multi-level tied-beam propagation effect at `proto_burmish` requires committed child inventories at `maruic` and `burmic`; because `maruic` stopped pre-commit at Turn 22 (`checkpoint.steps_by_node == {}`), no committed child beams existed to propagate to `proto_burmish`.

### 4.3 Node-Level `maruic` Comparison & `$0` Deduplicated Turn-21 Counterfactual Audit

| `maruic` Metric | `t36-r2/seed-00` | `t36-r2/seed-01` | `t36-r3/seed-00` | `t36-r3/seed-01` | **`B02` Live (`Turn 17` `last_preview`)** | **`B02` `$0` Deduplicated `Turn 21` Replay** |
|---|---|---|---|---|---|---|
| Node Outcome | Fallback (`ProtocolStallError`) | Committed (`inventory`) | Committed (`inventory`) | Committed (`inventory`) | Interrupted (`RunBudgetExceeded` at T22) | Offline replay (`executable=True`, `commit_ready=False`) |
| Local Sets Available | `150` `cs-*` (`341` cols) | `150` `cs-*` (`341` cols) | `150` `cs-*` (`341` cols) | `150` `cs-*` (`341` cols) | `738` `csu-*` / `320` `csp-*` (`589` cols) | `738` `csu-*` / `320` `csp-*` (`589` cols) |
| Covered Sets / Share | `0` (`38` in last preview) | `39 / 150` (`26.0%`) | `39 / 150` (`26.0%`) | `39 / 150` (`26.0%`) | `3 / 738` (`0.41%`) | **`394 / 738` (`53.39%`)** (`1` choice + `55` `shared_claims`) |
| `unaccounted_column_rate` | `null` (`0.522857` preview) | `0.495601` (`169/341`) | `0.495601` (`169/341`) | `0.495601` (`169/341`) | `0.994907` (`586/589`) | **`0.443124` (`261/589`)** (`cross_branch = 0.685185`) |
| Turns / Tool Calls (Failed) | `28 / 28` (`8`) | `29 / 29` (`4`) | `18 / 18` (`2`) | `28 / 28` (`2`) | `22 / 20` (`2` + 1 trunc + T22 abort) | *(offline replay of T21 payload)* |
| Peak `input_tokens` / `output_tokens` | `336,176` / `7,538` | `276,939` / `8,673` | `273,714` / `9,398` | `248,102` / `10,110` | **`483,849` / `32,764`** | — |
| Node `input_tokens` (Cache `%`) | `5,074,144` (`84.33%`) | `4,909,993` (`83.72%`) | `2,762,739` (`70.93%`) | `4,215,171` (`88.38%`) | `4,434,603` (`80.92%`) | — |
| Node Cost (Cached / Uncached) | `$1.223684` / `$4.111968` | `$1.126611` / `$3.901244` | `$0.912273` / `$2.235100` | `$0.801811` / `$3.316576` | **`$1.236806` / `$3.6591585`** | `$0.00` |
| `audit-run` Defects at `maruic` | `9` | `3` | `8` | `3` | **`0`** (`retain_from_witness`) | `346` sets blocked by `missing-directionality-rationale` |

---

## 5. Deep Turn 1–22 Linguistic & Protocol Forensics at `maruic`

### 5.1 Phase I (Turns 1–13): Morpheme-Unit Discovery, `support == 1` Local Sets, and Stop-Coda Polarization

1. **Tree & Correspondence Survey (Turns 1–2):** Gemini inspected node topology (`4` active Maruic children: `Atsi, Bola, Lashi, Maru`; `3` Burmic outgroups: `AchangLongchuan, Rangoon, Xiandao`) and called `summarize_correspondences(reading="recurrence")` (`min_support=2, offset=0, limit=30`), observing `320` total `csp-*` recurrence patterns, `113` matching `support >= 2`, and `738` local `csu-*` sets (`68,897 B`).
2. **Morpheme Slicing & `support == 1` Local Scope Geometry (Turns 3–8):**
   - On **Turn 3**, `get_alignments(detail="full")` on four compound concepts (`1007` COW, `1055` FATHER-IN-LAW, `1223` HEART, `1248` EYE) exposed `cog:*` morpheme slicing and Maruic creaky-vowel reflexes (`1223` HEART: Atsi `n i̱ k ⁵⁵ + l u̱ m ²¹`, Bola/Maru `n a̱ k ⁵⁵`, Lashi `n ə̱ k ⁵⁵`), but `detail="full"` serialized all $\binom{4}{2}=6$ pairwise correspondence tables (`133,644 B`), returning `166,043 B` (`+61,545` tokens) and pushing Turn 4's prompt to **`116,626` tokens**.
   - On **Turn 4**, `summarize_correspondences(reading="local", limit=50)` with default `min_support=2` returned **`0` matched sets** (`738` suppressed), because under `units-v2` (`independent-etyma-v1`) each `cog:*` unit represents one etymon, so **all `738/738` local `csu-*` sets have `support == 1`**. Switching to `min_support=1, limit=10` on Turn 5 returned `10/738` sets. Turns 7–8 ran empty `choices=[]` `retain_from_witness` (`Atsi`) baseline probes (`805 B` each).
3. **Stop-Coda Debuccalization & Turn-11 Repair (Turns 9–13):**
   - After `search_forms` (Turn 9) and 7-language `get_alignments(detail="summary")` on `1248` EYE and `1350` MONKEY (`cog:hillburmish:452`: Atsi `m j u ʔ ²¹`, Bola `m j au ʔ ³¹`, Lashi `m j u k ³¹`, Maru `m j au k ³¹` vs Rangoon `m j ɑu ʔ ⁴`, Achang/Xiandao `ȵ/ɲ u ʔ ⁵⁵`), Gemini called `polarize` on `["ʔ", "ʔ", "k", "k"]` on **Turn 11**, pasting `set_id="csp-60a6be6dfa55f66232460d06"` from Turn 2 (which actually encodes Maru singleton `[None, None, None, "k"]`, `support=20`, rather than `csp-11da406b24d8839c282b5b92`). `polarize` rejected the mismatch (`unknown-correspondence-set`), and Gemini repaired immediately on **Turn 12** by omitting `set_id` (`ok=True`, `5` witnesses across `3` outgroups) before testing `ʔ > k / _ #` on **Turn 13**.

### 5.2 Phase II (Turns 14–22): Full-Replacement Preview Scaling, Turn-20 Truncation, Turn-21 Overlap, and Pre-Dispatch Budget Stop

1. **Why Recorded `last_preview` Covered Only `3/738` Sets (Turns 14–17):** Gemini surveyed `1209` `I` (`Atsi ŋ o ⁵¹`, `Bola ŋ a ⁵⁵`, `Lashi ŋ o ³¹`, `Maru ŋ ɔ ³¹`) on Turn 14 and validated `3` `choices` (`*ŋ, *a, *⁵⁵`) scoped to `concept_ids=["1209"]` on Turn 15 (`commit_ready=True`, `6,224 B`). On **Turn 17**, it re-tested those same `3` `choices` globally (`concept_ids=[]`, `detail="summary"`), yielding `unaccounted_column_rate = 0.994907` (`586/589` columns) and a **`267,149 B` (`+116,272` token)** payload dominated by `source_positions` inside `unmatched_columns`.
2. **Full `csp-*` Pagination, Output Truncation, and 2-Set Claim Overlap (Turns 16, 18–22):**
   - Across Turns 16 (`offset=0, limit=50`), 18 (`offset=50, limit=50`, `14,064` reasoning tokens), and 19 (`offset=100, limit=30`), Gemini paged all `113` `support >= 2` `csp-*` patterns.
   - On **Turn 20**, after `10,618` reasoning tokens, Gemini attempted to emit a full-replacement `test_proto_assembly` payload and hit `max_tokens = 32,768` at **`32,764` output tokens** (`22,146` non-reasoning tokens of unclosed JSON dropped -> `finish_reason="length"`).
   - On **Turn 21** (`truncation_recovery` with `tool_choice="required"`), Gemini compressed reasoning to `123` tokens and emitted a `21,276 B` compact (`22,207 B` spaced / `14,876` output-token) `test_proto_assembly` call combining **`55` `shared_claims` (`393` unique `csu-*` sets) + Turn 15's `3` `choices` (`394` unique sets = `53.39%` of `738`)**. `expand_shared_claims` (`inventory_evidence.py:735`) rejected the call with `invalid-shared-claim` solely because two of Turn 15's `choices` (`csu-b61d042a30f0d854c5daeffa` `*ŋ` and `csu-c739e7ed4afdb0fa6101d1c3` `*⁵⁵`) were also listed inside `shared_claims` (`csp-b34fa49e12ac175d9314c3d8` and `csp-e945f4bc420aca3eec2b6110`).
   - On **Turn 22**, Gemini spent `231` reasoning tokens and returned a `14,873`-output-token repair (`+$0.418661` uncached -> `$3.6591585 >= $3.50`), where `RunBudgetExceeded` terminated Stage 1 before tool dispatch.
3. **`$0` Offline Deduplicated Turn-21 Replay & `inventory_contrast_reductions` Finding:** Removing the `2` duplicate `choices` (`1` remaining `choice` `csu-8ec518e00fcc660ed10274aa` `*a` + `55` `shared_claims` = `394` unique `csu-*` sets) executes cleanly (`ok=True`, `executable=True`), cutting `unaccounted_column_rate` from `0.994907` to **`0.443124` (`261/589`)** (`cross_branch_assembly_rate = 0.685185`), **but returns `commit_ready = False` (`missing-directionality-rationale` on `346/394` = `87.82%` sets)**. Because `inventory_contrast_reductions` (`assembler.py:436-495`) marks *every* unconditioned set sharing a `proto_segment` with any other tuple as contrast-reducing, unanimous `['j','j','j','j'] -> *j` is flagged alongside `[None, None, 'j', None] -> *j`, and 1-daughter compound boundaries `[None,'+',None,None] -> *+` are flagged across `77` sets—proving that even if Turn 22 had dispatched, `maruic` would have required another `15k–32k`-output-token revision pass.

### 5.3 Linguistic Assessment (`*ˀm/*ˀŋ` Initials, `cog:*` Boundaries, and 4 Tone Categories)

- **100% Tone-Contour Preservation & Stop Codas (Strong):** Across all `55` `shared_claims` in Turn 21, Gemini stripped **`0` tone tokens**, reconstructing distinct surface contour categories (`*⁵⁵` [`51` sets], `*³¹` [`26`], `*²¹` [`17`], `*³⁵` [`15`], `*⁵¹` [`9`], `*³³` [`6`]) with explicit comparative rationales (`51/55/31/31 -> *⁵⁵` Tone 1; `21/31/31/31 -> *²¹` checked/low tone; `21/31/33/35 -> *²¹` Tone 2/3) and polarizing Maruic stop-coda debuccalization (`p/ʔ/p/ʔ -> *p` on `csp-37927da23cb8f32ee3d355f3`; `ʔ/ʔ/k/k -> *k` on `csp-11da406b24d8839c282b5b92`).
- **Why Pre-Glottalized Initials (`*ˀm, *ˀn, *ˀŋ`) Were Missed Under `min_support = 2`:** In Maruic, Proto-Burmish pre-glottalized sonorants merge segmentally with plain nasals (`m, n, ŋ`) while conditioning creaky vowel register (`V̱`: `a̱, i̱, u̱, ə̱`, contrasting with Burmic voiceless sonorants `m̥, n̥, ȵ̥`). Because daughter vowel qualities split across conditioning rhymes, **`40/42` (`95.24%`) creaky-vowel (`V̱`) `csp-*` patterns at `maruic` have `support == 1`** (`0` multi-daughter `V̱` patterns have `support >= 2`!). Relying on `min_support=2` recurrence pages hid the Maruic creaky-register reflex of `*ˀN-` and led Gemini to posit plain `*m, *n, *ŋ, *l`.
- **`cog:*` Singleton-Morpheme Distortion:** Conversely, **`67/113` (`59.29%`)** of `support >= 2` `csp-*` patterns at `maruic` are **1-daughter compound-boundary or affix singletons** (e.g., `[None, '+', None, None]` `support=22`, `[None, None, None, 'k']` `support=20`), which Gemini over-retained as Proto-Maruic `*+` (`77` sets) and `*k` (`34` sets).

---

## 6. Turn-22 Peak Prompt Attribution (`483,849` Tokens), Turn-19 Cache Bust, & `96k` Local Qwen Infeasibility

### 6.1 Exact Turn-22 Prompt Attribution (`483,849` Input Tokens)

| Turn-22 Live Prompt Component (`_MessageLog.prompt` + Wire State) | Live UTF-8 Bytes | Exact Gemini Tokens | Share of `483,849` | Root Cause |
|---|---:|---:|---:|---|
| System (`12,807 B`) + User (`3,098 B`) + 13 Tool Schemas (`52,896 B`) + T20 Nudge (`147 B`) | `68,948 B` | **`16,150`** | **`3.34%`** | Fixed instructions, schemas, and recovery cue |
| **(a1) Uncompacted read-only inspection outputs** (`7` `summarize_correspondences` = `386,252 B` [`209,526` tok]; `2` `get_alignments` = `192,170 B` [`73,516` tok]; `1` `search_forms` = `52,484 B` [`22,000` tok]; `2` `polarize` + `2` `list_available_nodes` = `7,992 B` [`3,501` tok]; minus `9,502` tok BPE/compaction offset) | `638,898 B` | **`299,041`** | **`61.80%`** | Disjoint survey pages/concepts (`_supersedes=False`) + `_supersedes` bug on T16 vs T2 (`38,226` tok) |
| **(a2) Uncompacted `test_sound_law` output** (Turn 13) | `25,776 B` | **`11,011`** | **`2.28%`** | Only `1` `test_sound_law` call occurred (remained newest for that tool) |
| **(b1) Newest live `test_proto_assembly` preview** (Turn 17 `..4fc8`) | `267,149 B` | **`115,742`** | **`23.92%`** | Newest accepted preview kept verbatim (`245,995 B` compact / `257,521 B` spaced is `unmatched_columns`) |
| **(b2) `3` compacted preview stubs + Turn 21 `ok=false` error** | `3,266 B` | **`687`** | **`0.14%`** | Stubbing T7 (`805 B`), T8 (`805 B`), T15 (`6,224 B`) saved only `~2,698` tokens (`5,215 B` net) |
| **(c) Assistant `tool_calls` JSON arguments** (`20` calls; Turn 21 = `21,276 B` compact / `22,437 B` wire) | `25,960 B` | **`15,968`** | **`3.30%`** | Assistant `tool_calls` stay uncompacted in history |
| **(d) Gemini `thought_signature` wire state** (`20` tool-calling assistant turns; `--reasoning-history auto -> drop` sent `0 B` text) | *(opaque wire b64)* | **`25,250`** | **`5.22%`** | Required by Gemini 3 tool loop (`1:1` with `reasoning_output_tokens`) |
| **TOTAL (Turn 22 Request)** | **`1,029,997 B`** (+sigs) | **`483,849`** | **`100.00%`** | — |

### 6.2 Turn-19 Prefix-Cache Invalidation & `96,000`-Token Local `qwen3.8-27b-splash` Infeasibility

- **Turn-19 Prefix-Cache Bust (`+$0.30` Single-Turn Penalty):** When `_compact_watermark_previews` fired after Turn 18 (`363,088 >= 256,000`), replacing `msg[15]` (`805 B` -> `873 B`, `+68 B`) and `msg[17]` (`805 B` -> `873 B`, `+68 B`) alongside `msg[31]` (`6,224 B` -> `873 B`, `-5,351 B`) saved only `5,215 B` (`~2,698` tokens), **but mutated `msg[15]` near the front of the conversation**, collapsing `cached_input_tokens` from `246,893` (`68.00%`) on Turn 18 to **`15,135` (`3.54%`) on Turn 19** and costing **`$0.327424` cached-adjusted USD on a single turn (`26.47%` of Stage 1's entire `$1.236806` spend)**.
- **Quantitative Proof That `96,000`-Token Local `qwen3.8-27b-splash` (`128k` Context) Is Currently Infeasible on `burmish.json`:** Even stripping Gemini's `25,250` `thought_signature` tokens (`--reasoning-history drop`), `maruic` crossed **`116,626` prompt tokens on Turn 4** (with `0` previews to compact) and reached **`458,599` non-signature prompt tokens by Turn 22 (`4.78×` the `96,000` watermark and `3.58×` Qwen's `128,000` hard context limit)**, plus `32,768` output-token reservation. Running `qwen3.8-27b-splash` on `units-v2` `burmish.json` before `B03` context/protocol scaling would deterministically overflow its `128k` context window.

---

## 7. Bounded, Digest-Preserving `$0` Offline Runtime Bugfixes Landed in `B02`

Implemented strictly offline (`0` live model calls, `US$0.00` spend, banked `runs/` untouched) with all 4 `stored-hypothesis` behavioural digests and `c-gemini-r04` `configuration_sha256` (`339adb13…`) verified bit-for-bit invariant:

1. **[`cognate_reconstruction/agent/tools/proto_assembly.py`](../../cognate_reconstruction/agent/tools/proto_assembly.py) (`assembly_result`):** Under `detail is AssemblyDetail.SUMMARY`, clears `source_positions=()` on `report.unmatched_columns` (matching `columns=()` in `SUMMARY` and honoring `TestProtoAssemblyArgs.detail`'s contract while retaining `concept_id`, `column_index`, `unit_id`, `evidence_column_id`, `reflexes`, `set_id`, `unmatched_reason`, and `resolved_by`, and keeping full `source_positions` under `AssemblyDetail.FULL`). Replaying `maruic` Turn 17 offline cuts `unmatched_columns` bytes by **`50.45%` compact (`245,995 -> 121,881 B`) / `50.60%` spaced (`257,521 -> 127,209 B`)** and total Turn-17 preview size by **`46.46%` (`267,149 -> 143,035 B`)** (and cuts deduplicated Turn-21 preview size from `288,173 B` to `206,643 B`).
2. **[`cognate_reconstruction/agent/orchestrator.py`](../../cognate_reconstruction/agent/orchestrator.py) (`_supersedes`):** Normalizes read-only tool arguments against `spec.args_model` defaults (when validation succeeds) and allows paginated slice `[later_offset, later_offset + later_limit]` to supersede `[earlier_offset, earlier_offset + earlier_limit]` when all non-pagination arguments match (`later_offset <= earlier_offset` and `later_offset + later_limit >= earlier_offset + earlier_limit`). Reclaims Turn 2 (`offset=0, limit=30`) when Turn 16 requests `offset=0, limit=50` (`-68,897 B` / `-38,226` tokens) while protecting scoped queries (`concept_ids=["1209"]`).
3. **[`cognate_reconstruction/agent/orchestrator.py`](../../cognate_reconstruction/agent/orchestrator.py) (`_compact_watermark_previews`):** Enforces `MIN_PREVIEW_COMPACTION_SAVINGS_BYTES = 256` net UTF-8 byte savings (`live_bytes - stub_bytes >= 256`) before stubbing any superseded preview, so `805 B -> 873 B` empty identity probes are never rewritten and never invalidate early provider prefix caches.
4. **[`cognate_reconstruction/agent/orchestrator.py`](../../cognate_reconstruction/agent/orchestrator.py) (`_complete_with_retry` / `run`):** Keeps `self._check_run_budget()` raising `RunBudgetExceeded` pre-dispatch (`test_reported_cost_at_cap_stops_without_replaying_response` green), while updating `state.latest_prompt_tokens` / `state.peak_prompt_tokens` immediately upon response receipt and flushing the paid `response.message` into `messages.audit` (`trajectories.jsonl`) on exception without touching `messages.prompt` or dispatching tool calls.
5. **Offline Regression Suite ([`tests/workbench/test_real_family_harness_prep.py`](../../tests/workbench/test_real_family_harness_prep.py)):** Added 4 focused regression tests (`15 passed` in `test_real_family_harness_prep.py`; **`887 passed, 41 deselected`** across the full portable suite `conda run -n llm_reconstruction python -m pytest -q -p no:cacheprovider -k 'not local_run_artifacts'`).

---

## 8. Concrete Next-Step Gate Recommendation

Evaluating all three candidate next steps from [`prompts/02-real-family-live-benchmark.md`](../../prompts/02-real-family-live-benchmark.md) Step 4.1 against the empirical evidence above:

1. **Immediate Step 1 — Targeted Offline `units-v2` Scaling & Cost-Cap Package (`B03`, `$0` Offline):**
   - Before spending another paid dollar on `burmish.json`, implement a dedicated, versioned offline protocol & scaling package (`B03`):
     - *(a) Incremental / Patch Hypothesis Updates in `stored-hypothesis`:* Allow `test_proto_assembly` to extend or patch a prior `hypothesis_id` (`base_hypothesis_id` + delta `choices`/`shared_claims`) so 400–738-set nodes never require emitting `15k–32k` output tokens of full-replacement JSON in a single turn.
     - *(b) `inventory_contrast_reductions` Refinement:* Exclude unanimous cross-child retentions (`['j','j','j','j'] -> *j`) and single-daughter morpheme-boundary/affix retentions (`[None,'+',None,None] -> *+`) from false-positive `missing-directionality-rationale` blocks unless a genuine cross-set phonemic merger or non-boundary segment deletion is proposed.
     - *(c) Watermark-Gated Read-Only Page Compaction & Multi-Daughter `support == 1` Phonation Surfacing:* Compact older disjoint survey/alignment pages above the watermark (leaving a compact summary index) and surface multi-daughter `support == 1` phonation/creaky-register (`V̱`) correspondences alongside `support >= 2` patterns while separating 1-daughter compound/affix singletons (`67/113` `csp-*` rows).
     - *(d) Verified-Cached Cost-Cap Accounting:* Support enforcing `--max-total-cost-usd` against cached-adjusted spend when `cached_input_tokens` and `cached_input_usd_per_million` are certified, while continuing to report both uncached upper-bound and cached-adjusted totals in `batch_ledger.json`.
2. **Immediate Step 2 — Live `benchmarks/polynesian.json` on `gemini/gemini-3.8-flash` (and First `96k` Local `qwen3.8-27b-splash` Transfer):**
   - [`benchmarks/polynesian.json`](../../benchmarks/polynesian.json) (`10` daughters, `7` internal nodes [`6` non-root subgroups + `proto_polynesian` root] across `5` tree levels: `tongic`, `futunic`, `marquesic`, `tahitic`, `central_eastern`, `nuclear_polynesian`, `proto_polynesian`; simplex `fully_cognate_with_target` lexicon without compound morpheme explosion; measured R03f prompt peaks `46k–93k` tokens, `< 100k` p90) is **already within the current harness's scaling envelope** (enhanced by our 4 `B02` runtime bugfixes) and directly tests deep 5-level post-order propagation and `$0` `None` vs `0.5` tied-beam counterfactual replay end-to-end.
   - Because Polynesian prompt peaks fit inside `96,000` tokens (`< 128k` window), **`polynesian.json`—NOT `burmish.json`—should also serve as the first real-family transfer benchmark for local dense `qwen3.8-27b-splash` (`--compaction-watermark-tokens 96000`)**.
3. **Step 3 — Re-Benchmark `benchmarks/burmish.json` After `B03` Lands:**
   - Re-freeze and run `burmish.json` on `gemini/gemini-3.8-flash` once `B03` brings `maruic` and `burmic` prompt/output footprints well below `128k` input / `8k` output tokens, and defer local `qwen3.8-27b-splash` on `burmish.json` until `B03` proves `maruic` fits comfortably under the `96,000`-token watermark.
