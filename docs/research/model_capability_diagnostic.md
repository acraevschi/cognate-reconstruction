# R03 — Stronger-model diagnostic on the repaired harness

2026-10-25, branch `r01-contract-repairs`, HEAD `19fd76d` plus one pre-launch
repair (uncommitted at launch; section 3). Live inference ran once, serially,
18:51:32–19:07:48 UTC. Environment `llm_reconstruction`: Python 3.11.0,
LiteLLM 1.81.16, httpx 0.28.1, Pydantic 2.13.4 (`pip freeze` SHA-256
`448a3e5b…`). Compact numbers:
[model_capability_diagnostic_results.json](model_capability_diagnostic_results.json).

## 0. Status at a glance

| Item | Result |
| --- | --- |
| Required read-only manifest review (Opus 5.5, medium) | Done. First freeze **not launch-ready**: one blocker (Gemini wire lost every argument of `test_proto_assembly`). Repair approved by the owner; scoped re-review **launch-ready with the pre-registered mitigations** |
| A-gemini (Gemini 3.8 Flash, medium thinking) | **success**: supplied nonempty token-conditioned hypothesis, original and revised previews, handle commit of the revision, reference output, readback intact |
| B-gemini | Node `x` committed by the model: **18/18 `model_committed_correct`, 6/6 matched pairs**, all 18 decided by explicit claims; both unresolved items committed at confidence 0.5 with the tie stated. The unscored root session was stopped by the per-trial cost cap |
| A-local (Gemma 4 26B A4B, LM Studio) | **no_commit**: `ProtocolStallError` after 11 turns, 7 of 11 calls rejected as invalid submissions |
| B-local | **Not run** (gated on A-local). A missing paired outcome, not a judgment result |
| Gemini spend | **US$2.4754** by the pre-registered upper-bound price table (no unknown-cost request, no retry); about **US$0.81** with the cached-token counts Gemini reported. Ceiling US$5. Paid wall time 690.5 s of 3,600 s |
| Local time | 283.9 s of 7,200 s |
| External cost check | **Pending**: the owner reads the AI Studio balance (7.36 CHF before R03) at least 24 h after 19:07 UTC on 2026-10-25 |

**Substantive usability of the current harness:** demonstrated for Gemini 3.8
Flash with these settings (Stage A and B's own-decision preview→commit); **not
demonstrated** for local Gemma 4 26B with these settings. **Linguistic utility:**
on this synthetic development panel, Gemini's decisions met the pre-registered
"evidence-sensitive" reading. That reading equals the panel's identification
rule and ceiling: it shows necessary-condition evidence use, not discovery or
real-language utility. No local judgment outcome exists.

## 1. Question and design actually run

R02's question, unchanged: can each model (A) execute an explicitly supplied,
nonempty, unit-scoped and token-conditioned hypothesis, and (B) propose
evidence-sensitive per-etymon, per-unit decisions that copying or uniform
policies do not make? It was run on the same code, evidence, native
stored-hypothesis profile, instructions, tool schemas and evaluators for both
arms. Stage A is `r02-stage-a-v1` (checker `r02-usability-v1`). Stage B is
`r02-stage-b-v1` (scorer `r02-decisions-v1`, beside task02-v1 /
task04-units-v1, evidence units-v2). Design, panel and baselines:
[model_diagnostic_design.md](model_diagnostic_design.md). One A trial and one
conditional B trial per model; no retries, seeds or reruns.

## 2. Frozen manifests

R02's draft directory was stale (retry budget). R03 re-froze twice with
`tools/r02_diagnostics.py freeze`; nothing was hand-edited.

| Freeze | Directory (ignored) | Source | Status |
| --- | --- | --- | --- |
| R03 first | `runs/experiments/r03-model-diagnostic-20261025/` | HEAD `19fd76d`, no dirty paths | Superseded by the review blocker; **never launched** |
| **R03 v2 (launched)** | `runs/experiments/r03-model-diagnostic-20261025-v2/` | HEAD `19fd76d` + `stored_hypothesis.py`, `test_gemini_provider.py` (diff `6c438ad1…`) | Reviewed; launched |

v2 SHA-256: `manifest.stage-a.json` `bbbab7c8…`, `manifest.stage-b.json`
`e5b70ab9…`, `plan.json` `554d13a9…`, `source_manifest.json` `6e93742f…`
(220 files), `preregistration.md` `c1d24aad…`. The inputs are byte-identical to
R02's: payloads A `703b8d90…` and B `e8485112…`, instructions A `543e3f32…` and
B `5b4c7aef…`, price table `f07736e1…`, provider configs `{"max_tokens":16384}`
`4bd88ce8…`. Model-visible digests: packaged text `0b9d91cf…`, node notes
`1ddfc0fc…`, evidence `b1f459e7…`. **Tool schemas `628f0f32…`** (R02: `dd58d427…`;
section 3). First requests: A node prompt `11d958dc…`; B `x` prompt `fecbdfcd…`.
The generator's fixed status string ("not independently reviewed") is
superseded by the review record in section 3 and in `preregistration.md`.

Caps exactly as R02 froze them:
- **Gemini:** temperature 1.0, `thinkingLevel` medium, `max_tokens` 16,384, timeout and retry budget 300 s, 3 retries, `--max-failed-nodes 0`. A: 24 turns, US$0.75, 900 s. B: 30 turns per node, 60 in total, US$2.25, 1,800 s. Reservations US$1.60 + US$3.10 ≤ US$5 and 1,000 s + 1,900 s ≤ 3,600 s.
- **Local:** temperature 0.1, no reasoning field, timeout and retry budget 600 s. A 1,800 s; B 5,000 s.

## 3. Pre-launch review and the one repair

**Review (read-only, Opus 5.5 medium).** It re-derived the hashes, the cost
arithmetic (one-response headroom US$0.847872; worst case US$4.695744) and the
launcher's refusals, and found no leakage of Stage A content, targets or labels
into B. The **blocker**: `StoredAssemblyArgs` published a top-level
`anyOf: [{required:[choices]}, …]` beside its 12 properties. LiteLLM 1.81.16's
Gemini conversion (`_filter_anyof_fields`,
`litellm/llms/vertex_ai/common_utils.py`) keeps only the `anyOf`. So
`test_proto_assembly`, the preview tool both stages need, reached Gemini with
**0 of 12 argument definitions**, while the OpenAI-shaped local route kept all
of them. Reproduced on the captured first request of the exact frozen A-gemini
argv (`runs/experiments/r03-offline-checks-20261025/review/wire_a/first_request_body.json`;
`wire_all.HEAD.txt`). No live Gemini request had ever carried this schema: it
dates from 2026-10-05, after every banked Gemini run.

**Repair (owner-approved, pre-launch, no trial had run).** The published
`anyOf` is removed; `explicit_claim_collection` still refuses an omitted claim
collection with the same message, and `choices: []` still means identity. The
new `test_every_tool_keeps_its_arguments_on_gemini_s_wire` (both profiles,
through LiteLLM's Gemini mapping) fails before the fix and passes after. The
schema digest changes for **both** arms, so they again see identical tools.
`const`, `exclusiveMinimum` and `uniqueItems` are still dropped on the Gemini
wire; the harness validates those server-side.

Other review findings were resolved without code by
`preregistration.md`. Among them, `LITELLM_LOCAL_MODEL_COST_MAP=True` was
pinned (section 5) and preflight was run outside the plan. Other rules fixed
before launch:
- the "possibly billed" rule for APIConnectionError/5xx attempts;
- an exact pair-count definition;
- the Stage A gate kept as frozen, with a gate-artifact reading;
- readings for interruptions and timeouts;
- truncation checks;
- a key grep;
- the console check.

The scoped re-review confirmed the diff was exactly the repair, and that the
captured A and B Gemini requests carry every property of all 13 tools.

## 4. Offline demonstration on the interfaces actually used

`runs/experiments/r03-offline-checks-20261025/rehearsal*/` ran the exact frozen
`infer` argv of every trial through the real CLI, presets, price table and
LiteLLM routing and transforms. Only `httpx.Client.send` was faked, with
scripted policies, sockets blocked and a dummy key.

| Scenario | Result |
| --- | --- |
| Nominal (both system-text layouts; v2 with the pinned map) | A `success` both arms; B 18/18, 6/6 both arms; `right.tokens == ["i"]` survives readback on both transports (R01 §1) |
| Client timeout (`httpx.ReadTimeout` → `litellm.Timeout`) | Not replayed; 1 unknown-cost request; arm cost UNKNOWN; B refused (0aea3fe) |
| Cost cap with 300k-token responses | Interrupted at US$0.915 ≤ US$0.75 + headroom |
| SIGKILL mid-request | `abandoned`, journaled unknown cost, elapsed lower bound (R01 §2 and review D1–D3) |

The wire showed `generationConfig` `{temperature 1.0, max_output_tokens 16384,
thinkingConfig {thinkingLevel "medium", includeThoughts true}}` on LiteLLM's
`v1alpha` endpoint. LiteLLM adds thinking tokens to completion tokens, so the
price table stays an upper bound. The first rehearsal also exposed that
LiteLLM wraps exceptions raised after a request as `APIConnectionError` (500),
which the harness treats as retryable and zero-cost. This was known from R02;
handled by the pre-registered rule, and it did not occur live. R01 §4
(`best_lexicon` export) is not on this path. Portable suite: 802 passed and
41 deselected at `19fd76d`; 804 passed and 41 deselected after the repair. One
existing test (`test_a_signed_turn_becomes_a_valid_gemini_request`) needs
LiteLLM's network-fetched cost map, so it cannot run fully offline.

## 5. Launch preflight and the settings actually sent

**Preflight.** Run 2026-10-25 18:50 UTC, before validity ends 2026-12-31:
- `GEMINI_API_KEY` present, checked with `test -n` and never printed;
- `cli gemini-models` listed `gemini-3.8-flash`;
- `lms ps` showed `google/gemma-4-26b-a4b` idle, queued 0, the sole loaded model, context 262,144;
- frozen hashes and the source identity re-verified;
- no competing harness process.

The launcher ran with the env interpreter.

| | Gemini 3.8 Flash | Gemma 4 26B A4B (local) |
| --- | --- | --- |
| Route | LiteLLM `gemini/` → `v1alpha/models/gemini-3.8-flash:generateContent`, key in the `?key=` query (LiteLLM default) | LM Studio OpenAI-compatible `/v1/chat/completions` |
| Weights | Hosted (unknown) | MLX safetensors 6-bit, `parallel: 2` (used serially) |
| System text | **Merged into the first user turn**, because the bundled LiteLLM map (pinned) has no 3.8 entry | Native system message |
| Sent sampler | temperature 1.0, max_output_tokens 16,384 | temperature 0.1, max_tokens 16,384 |
| Reasoning | `thinkingLevel` medium (reported thinking 51,788 of 73,794 output tokens) | No field sent. LM Studio hub default `enableThinking: true` (reasoning parsed); top_p 0.95, top_k 64 from the hub `model.yaml`; the overflow policy was not readable |
| Tools, instructions, inputs, evaluator | identical (`628f0f32…`) | identical |

These are model/provider/configuration-conditional arms. The higher
temperature, explicit reasoning level, hosted weights and system-text layout
all differ, so no result below is attributable to model architecture alone.

## 6. Run / node / decision table

| Trial | Planned | Attempted | Node | Outcome | Turns / calls (rejected) | Requests, largest request (tokens) | Cost (upper bound) | Wall |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A-gemini | yes | yes | `r` | committed, A `success` | 5 / 6 (1) | 5, 44,325 | US$0.1439 | 68.0 s |
| B-gemini | yes | yes | `x` (scored) | committed by model, 18/18, 6/6 | 12 / 12 (1) | 12, 161,543 | ≈US$0.98 | 357 s |
| | | | `r` (descriptive) | stopped by the cost cap before a commit | 19 / 18 (0) | 19, 186,117 | ≈US$1.35 | 265 s |
| A-local | yes | yes | `r` | `no_commit`, ProtocolStallError → identity fallback (excluded) | 11 / 11 (7) | 11, 42,024 | not applicable | 283.9 s |
| B-local | conditional | no | `x` | **missing** (A-local not usable) | — | — | — | — |

No fallback output was scored as a model decision. No request failed, timed
out or was retried, and the journals hold 47 `request_start` and 47
`response` events.

## 7. Stage A — supplied-hypothesis usability

**Gemini: `success`, every criterion true.**
- **Opening.** The first turn surveyed recurrence and local sets in parallel.
- **Original preview.** It previewed the original hypothesis: the shared `[p,f]` claim with `{"right":{"tokens":["i"]}}`, the `[+,+]` null, local nulls for the `cog:u07` sets and residue `retain_from_witness` b.
- **Revision.** Its first revised preview was rejected once: two null `choices` were sent without `proto_segment` (`schema:choices[].proto_segment=missing`). The model fixed this on the next call, then committed the revised preview's handle.
- **Result.** Committed claims equal the supplied revised set (no extra or missing claims; `shape_matches_supplied`). The output equals the reference, the units match, and JSONL, checkpoint and result agree.

This is protocol usability only: the reference forms execute the supplied claims.

**Local: `no_commit`.** These were invalid submissions throughout, never a tool
rejecting a valid claim. They are traced in
`runs/.../runs/a-local/trajectories.jsonl`:
1. **Turn 4: invented fields and an invented ID.** The preview used `explanation` and `local_set_id` instead of `rationale` and `set_id`. One `csu-` ID was made by renaming the prefix of a `csp-` pattern ID.
2. **Turns 5–6: unrequested `unit_orders`.** The model added `unit_orders`, which the supplied hypothesis never asked for. They were first malformed and then incomplete (`alignment-failed`: q01 must include its boundary and suffix units).
3. **Turns 7–9: stale IDs.** Previews combined those `unit_orders` with set IDs from the default survey. Set IDs are scoped to overlays and orders, so all were `unknown-correspondence-set`, and the remediation said to re-survey.
4. **Turns 10–11: re-surveyed, then reused the stale IDs.** At turn 10 it did re-survey under the same orders (21 new sets). Turn 11 still sent the old IDs: 0 of the 5 IDs it sent appear in that survey.

The stall detector stopped the node after the fourth identical rejection that
followed a targeted correction. Prompt tokens rose monotonically, so no
context truncation is visible. Thinking produced 6,117 of 10,128 output
tokens, almost none of it after turn 3.

## 8. Stage B — evidence-sensitive judgment (Gemini only)

**Headline (pre-registered):** `model_committed_correct` **18/18**.
- **Pairs:** **6/6** model-committed matched pairs with both members correct and no fallback. Every member was decided by an explicit claim, so no pair is flagged.
- **Subtotals:** presence 10/10 (outgroup presence 6, complementary presence 4); absence 8/8.
- **Readings:** retain 10, absent 8; no `other`, `unit_missing` or `unscorable`.

The suffix items S1–S4 were decided in the correct unit, including b-only
suffix material and boundaries.

**Response to counterevidence:** in all six pairs, items alike in every
daughter-visible feature got opposite readings that follow `c`.

**Uncertainty:** the two unresolved items (U1 `k u k`/`k u`, U2 `k e n`/`k e`,
no `c` form) were committed as null at confidence **0.5**. The rationale says
that a gain in a and a loss in b are equally parsimonious and the item is
unresolved under the criterion. Either value was acceptable, and neither
answer was forced with high confidence. The other 58 commitments were at
confidence 1.0, which is defensible only conditionally on the stated criterion
and supplied tree.

**Navigation:**
- `list_available_nodes`, a default survey and `get_alignments` over a, b and c;
- `search_forms(scope=available_tree)` and `polarize([k, ∅])`;
- local surveys, then three previews (one rejected for the same omitted-null error as in A) and a handle commit.

**Ordinary evaluator (task02-v1) at `x`:** 16/16 raw top exact, mean NED 0.0,
no missing or fallback outputs, and 3 outside-selection top hits.

**Root `r`** (descriptive only): 18 accepted calls exploring correspondences,
sound laws and cascades. It was stopped at its 19th response when the
upper-bound spend reached US$2.3315 > US$2.25. This is a pre-registered
resource stop (`RunBudgetExceeded`), not a failure judgment. It cost more than
the scored node.

**Against baselines.** The result is at the panel ceiling:
- identity 10;
- daughter a 8, daughter b 10;
- union 10, intersection 8;
- no-outgroup cue rules ≤12 and ≤3/6;
- copy-c 11;
- deployable outgroup-witness rule 18/18, 6/6.

Gemini's B is indistinguishable from careful application of the stated
criterion with the outgroup evidence the default survey already labels. The
panel cannot show more than that. It is synthetic development material
designed with known answers; the forms cannot be memorized, but generic
historical-linguistic knowledge of parsimony is in play by design (the
criterion is stated).

**B-local:** missing paired outcome.

## 9. Resource ledger (all attempts, one envelope)

From `batch_ledger.json` (`r02-ledger-v1`, SHA-256 `fabf073e…`) and
`batch_events.jsonl` (`a221761a…`):

| Arm | Trials run | Requests | Input / output tokens (cumulative) | Cached input reported | Cost | Wall |
| --- | --- | --- | --- | --- | --- | --- |
| Gemini | 2 | 36 | 2,931,596 / 73,794 (51,788 thinking) | 2,471,971 | **US$2.4754** upper bound; unknown-cost requests 0; ≈US$0.807 at the cached rate | 690.5 s / 3,600 s |
| Local | 1 (+1 refused) | 11 | 314,476 / 10,128 | — | not applicable (unpriced; the ledger's UNKNOWN is by design) | 283.9 s / 7,200 s |

- **Cost totals.** The overall ledger total reads UNKNOWN only because the local arm is unpriced.
- **What the cache figure means.** The cache-adjusted figure re-prices the cached input at US$0.075/M. It is an estimate, not the pre-registered measure: billed cost is set by Google's console.
- **What drove spend.** Cumulative input dominated: each B request re-sends the transcript, so B's 31 requests carried 2.77M input tokens. The unscored root session consumed about 58% of B's upper-bound spend.
- **Secrets and the external check.** `grep -rlF "$GEMINI_API_KEY"` over the batch directory found no file. The console balance check is pending.

## 10. Deviations from R02's frozen design

1. Tool-schema digest `dd58d427…` → `628f0f32…` (both arms), by the approved repair (section 3).
2. `LITELLM_LOCAL_MODEL_COST_MAP=True` for the batch: deterministic merged system-text layout on Gemini, and `provider_reported_cost_usd` null. This setting was not in R02's manifest.
3. A second, superseded freeze directory exists, never launched.

There were no other changes: no model, cap, input, scorer or trial count
changed, and nothing ran twice.

## 11. Interpretation (conditional)

- **Stronger completes while local stalls.** This is evidence of a
  capability/compatibility limitation of **this local model and configuration
  in this workflow**: MLX 6-bit, temperature 0.1, server-default thinking and
  sampler, a 53k-character tool schema, and overlay-scoped IDs. It is not proof
  that the harness is optimal, nor that local models cannot reason about this
  linguistics. The failure pattern is schema and identifier bookkeeping:
  invented field names, invented IDs, stale IDs after a correct re-survey, and
  an unrequested overlay. The linguistic content of its claims was close to the
  supplied ones.
- **The stronger model needed no interface simplification here.** Gemini's
  only rejections were one omitted-null error per stage, each fixed on the next
  call. So the motivation for an interface redesign comes from the local arm
  alone.
- **Judgment.** Gemini's B shows that it can go from pooled recurrence to
  per-etymon, per-unit decisions that follow a stated criterion. The decisions
  respond to counterevidence and keep warranted uncertainty, executed in the
  right unit. The panel's ceiling equals a deployable rule, so this is a
  necessary-condition pass. It does not show evidence-sensitive judgment
  beyond rule-following, nor on real-language data.
- **Not identified.** A pure model effect, reliability (one trial per arm,
  temperature 1.0), or a ranking. The historical Gemini 3.7 and Gemma contrasts
  remain noncausal.

## 12. Limitations

- One trial per arm and stage; feasibility, not reliability.
- The local judgment outcome is missing.
- Both stages are synthetic development material designed in R02.
- The settings differ across arms (section 5). LM Studio's overflow policy and any server-side template effects were not observable.
- Cost is an upper bound pending the console check.
- The B root session, model-dependent and not certified, was stopped by the cap and is unscored.
- LiteLLM still drops `const`, `exclusiveMinimum` and `uniqueItems` for Gemini.
- Post-response exceptions would still be classified as zero-cost retryable; none occurred.
- Gemini saw the system text as user-turn text. Native `system_instruction` was not tested.

## 13. Preferred next action

**Defer interface-redesign implementation.** Instead, run one narrowed R04
study on the current harness with Gemini 3.8 Flash, the model that can use it:
a **judgment panel on which the outgroup-witness rule is not the answer**, so
that evidence-sensitive judgment is distinguishable from rule-following.
Examples are prespecified items where the outgroup has its own innovation,
outgroups conflict, or a change is conditioned. Score only the target node: no
unscored root session, which consumed most of B's spend. Reuse R02/R03's
scorer, baselines, ledger, launcher and pre-registration form. It needs its
own owner-approved envelope; R03's ceiling is not carried over.

What would reverse this recommendation:
- **Gemini fails the harder panel mainly through protocol or navigation** (rejections, unread evidence): run the interface study.
- **Gemini again equals a simple deployable baseline:** the task definition, not the model, is the binding limit.
- **The owner prioritizes cheap local operation:** a local-only reduced-ID/selection-surface Stage A comparison against this R03 A-local outcome becomes the next step.

No propagation question is supported yet; R05 stays deferred.

## 14. Artifacts and commands

- Launched batch: `runs/experiments/r03-model-diagnostic-20261025-v2/`. It holds:
  - `inputs/`, the manifests, `plan.json`, `source_manifest.json`, `preregistration.md`;
  - `launch_time.txt`, `launcher.*.log`, `batch_events.jsonl`, `batch_ledger.json`;
  - `runs/{a-gemini,b-gemini,a-local}/`: `trajectories.jsonl`, `events.jsonl`, `checkpoint.json`, `checkpoint.requests.jsonl`, `run_summary.json`, logs, `evaluation.json`. `result.json` exists only for a-gemini.
- Evidentiary roles: `a-*` = Stage A protocol usability; `b-gemini` `x` = Stage B judgment; `b-gemini` `r` = descriptive.
- Superseded freeze: `runs/experiments/r03-model-diagnostic-20261025/`.
- Review and rehearsal evidence: `runs/experiments/r03-offline-checks-20261025/`.

```sh
cd runs/experiments/r03-model-diagnostic-20261025-v2
LITELLM_LOCAL_MODEL_COST_MAP=True PYTHONDONTWRITEBYTECODE=1 /opt/anaconda3/envs/llm_reconstruction/bin/python \
  /Users/acraev/Work/cognate-reconstruction/tools/experiment_batch.py run --plan plan.json
# rewrite/read the ledger without running anything:
/opt/anaconda3/envs/llm_reconstruction/bin/python /Users/acraev/Work/cognate-reconstruction/tools/experiment_batch.py ledger --plan plan.json
```
