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
| Follow-ups (local, separate identities) | R03b (Gemma, its published sampler): A **no_commit**, same error classes (§15). R03c (Qwen3.6 35B-A3B, its published sampler): A **success**, 0 rejected; B **10/18, 0/6 pairs**, baseline-level, outgroup absence read as a tie (§16). R03d (Gemma on the `unit_orders`-fixed code): A **no_commit** again, 7/9 rejected; the fix was not exercised (§17). R03e (Gemma with its reasoning resent within the tool loop): thinking sustained, A **success** (1/6 rejected); B **no commit**, three 16k-token thoughts that never reached a call (§18). R03f (Qwen on creation-time tool-result slimming, Option 1a): A **success**, identical to R03c; B `x` **no commit**, three 16k-token thoughts; no slimmed content reached the model, so not attributable to 1a (§19) |
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

## 12a. Open questions and room for improvement

Noted after the run (2026-10-25). None of these changes R03's results.

**Claim confidence is self-reported and unvalidated.**
- **What it is.** Every claim carries a model-stated `confidence` in (0, 1]. It is required and never defaulted, but nothing computes or checks it.
- **Where it acts.**
  - Between competing claims on one correspondence, the higher confidence wins (`decided_by_equal_confidence` reports ties).
  - It feeds candidate ranking. Normalized beam weights are therefore not calibrated probabilities.
- **What R03 observed.** None of it supports a calibration claim, because one trial per model is too few.
  - Gemini, Stage B: 58 claims at 1.0 and the two genuine ties at 0.5, a coarse "determined / tie" split.
  - Gemini, Stage A: copied the supplied 0.8 and 0.9.
  - Gemma: placeholder-like 0.7 throughout.
- **Until validated.** Read confidence as descriptive or ordinal, never as a probability.
- **Possible improvements, cheapest first:**
  1. Score confidence as ordinal labels (determined under the criterion / tie or unresolved / weak). Stage B already tests the tie label.
  2. Pool enough claims with known answers to measure calibration; an 18-item panel is too small.
  3. Add harness-computed signals beside the self-report: counts of supporting and contradicting forms, and agreement across repeated samples (a measure of stability, not of correctness).
  4. Refuse or flag a confidence of 1.0 on a claim the evidence shows as tied.
  5. Stop letting self-reported confidence silently settle competing claims: flag the conflict for an explicit decision, or break ties on evidence.

**Identifier bookkeeping.**
- **What failed.** Gemma's Stage A failure was mostly clerical. Of its 7 rejected calls, 2 were schema errors that constrained decoding could prevent. The other 5 were schema-valid JSON with stale, invented or incomplete IDs.
- **Candidate fixes** (each is an interface change, to be compared current-versus-new on the same tasks):
  - claims that name a correspondence by reflex pattern and unit, with the harness resolving the ID and refusing ambiguous matches;
  - per-turn enums of the IDs that are currently valid;
  - server-side constrained tool calls, if LM Studio supports them for MLX tool arguments. Unverified.

**Proposed: pattern-based correspondence references** (planned, not implemented).
- **Why.** The set IDs serve the harness, which needs every claim tied to exact evidence rows under the current overlays. They need not be the model's job. The Stage A instructions already state each claim as a pattern in a unit ("the `[p, f]` pattern → p before `i`", "the `[m, m]` sets in unit u07 → null"), and that description is unambiguous enough to execute. Letting the model say just that would remove most of Gemma's failure surface without losing rigor:
  - copying 24-hex IDs;
  - the `csu-`/`csp-` distinction;
  - IDs renamed by an overlay.

  It would also shrink every transcript.
- **Design.**
  - **A new opt-in profile.** It would be a new `--inventory-protocol` value (working name `pattern-reference`). `stored-hypothesis` and its tool-schema digest `628f0f32…` stay byte-identical, so R03 remains the comparison baseline.
  - **New claim forms.** A local choice may give `unit` (a `cog:`/`boundary:` scope as the surveys print it) and `reflexes` (the per-child tuple, null for a gap) instead of `set_id`. A shared claim may give `reflexes` and the units it covers instead of `pattern_id`/`member_set_ids`. ID fields remain accepted.
  - **Resolution at every preview.** References are resolved against the node's current inventory under the submitted overlays (`verify_commitments` and `expand_shared_claims` in `agent/tools/inventory_evidence.py`). A reference is therefore never stale; nothing has to be re-copied after a re-survey.
  - **Refusal, never a guess.** Zero matches, or more than one, is refused with the candidate rows listed. The same pattern can occur twice in one unit (both `k`s in `k u k`), so a small optional disambiguator (position, or an example concept) is accepted only when the reference is ambiguous.
  - **Persistence unchanged.** The committed inventory stores the resolved exact set IDs, so commit, JSONL, checkpoint, readback, the evaluator and the parent beams are all unchanged.
- **Work.**
  - schema fields (`agent/tools/stored_hypothesis.py`), resolution and refusals;
  - registry and CLI wiring, with short tool descriptions for the profile;
  - the Stage A checker (`evaluation/usability.py`) comparing claims after resolution;
  - a scripted Stage A operator for the profile, proved through `cli infer` with the real `LiteLLMProvider`;
  - tests for ambiguous, absent and stale references, and the Gemini wire check for the new profile.

  That is roughly 300–500 lines including tests: one focused coding session, separate from R03.
- **Prerequisite.** First fix the no-op `unit_orders` gap (§15). Done after R03c (§16): an entry naming no concept at the node is refused. A unit absent from the concept is still accepted, because projection over a superset of units is used deliberately; such a claim still orders the concept's real units.
- **Evaluation.** A frozen, local-only Stage A comparison with Gemma 4 26B under Gemma's published sampler (as in R03b): current profile against `pattern-reference`, on the same fixture, caps, checker and gate. It costs only machine time, about 5 minutes per Stage A trial. Use a few trials per arm, prespecified, to tell an effect from sampling variation.
- **Decision rule.**
  - **Gemma passes Stage A with references:** the bookkeeping was the barrier. Keep the profile, run its conditional Stage B, and keep local models for cheap iteration.
  - **Gemma still fails** on field names or ignored corrections: treat it as a capability limit. Use the hosted model for substantive runs, or give the other preferred local model one Stage A check before ruling local models out.

  Gemini's clerical slips (an omitted required null once per stage) suggest the profile could help the hosted arm too. That would need its own paid comparison.

**Local sampler settings.**
- **What was sent.** The local arm sent only temperature 0.1 (the harness default, not tuned for Gemma) and `max_tokens`. top_p, top_k and the repetition penalty came from LM Studio's defaults. The tracked `examples/sampling/gemma-4-26b-a4b.json` was not used.
- **The vendor default.** Google's default for Gemma 4 is temperature 1.0, top_p 0.95, top_k 64.
- **A suggestive pattern.** Gemma resubmitted the same stale IDs four times and almost stopped thinking after turn 3. That fits low-temperature perseveration but does not establish it.
- **Next test.** A free, prespecified local Stage A comparison: current settings versus explicit vendor settings, about 3 trials each.
- **Status.** One trial with the vendor settings ran as R03b (§15). The errors persisted, in the same classes.

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

## 15. Follow-up R03b — local arm with Gemma's published sampler (2026-10-25)

This was a separate experiment, requested by the owner after R03, with its own
identity: `runs/experiments/r03b-local-sampling-20261025/`. It does not change or
pool with R03. It ran 21:30:56–21:35:47 UTC.

**What changed.** Only the sampler:
- **R03:** the LM Studio server log shows R03's local request body carried only `temperature: 0.1` and `max_tokens`. Everything else was LM Studio's default, which `examples/sampling/README.md` gives as a 1.1 repetition penalty; the effective values are not logged.
- **R03b:** sent temperature 1.0, top_k 64, top_p 0.95, repeat_penalty 1.0 (`examples/sampling/gemma-4-26b-a4b.json`), min_p 0.0 and max_tokens 16,384. All were confirmed in the request body by an offline rehearsal.

Model, instance (MLX 6-bit, context 262,144), server-default thinking, tools
`628f0f32…`, instructions, payloads, caps, checker and gate are as in R03. The
code change is outside the model-visible path: `tools/r02_diagnostics.py` gained
a `--arms` freeze option and a `local-vendor-sampling` arm, with a test.
- **Frozen files:** `plan.json` `c7c41dc6…`, manifests A `af96deb6…` and B `6cba2859…`, `source_manifest.json` `2ee7469d…` (HEAD `1711093` + those two files), `preregistration.md` `e42bbf17…`.
- **Tests:** portable suite 805 passed, 41 deselected.

**Result: the errors persist.** Stage A ended `no_commit`. The node hit
`ProtocolStallError` after 10 turns with 7 of 10 calls rejected, so B was refused.
One trial; 290 s; 207,201 input / 11,195 output tokens; largest request 30,139.

| Error class | R03 (temperature 0.1, server sampler) | R03b (Gemma sampler) |
| --- | --- | --- |
| Invented or wrong field names (`explanation`, `local_set_id`, missing `rationale`/`member_set_ids`) | 1 | 2 |
| Pattern ID used as a choice, or an invented ID | yes (turn 4) | yes (turn 3: `csp-` IDs in `choices`) |
| Malformed `unit_orders` (`child_id`/`order`) | 1 | 1 |
| Unrequested `unit_orders` overlay | real concepts, incomplete units (`alignment-failed` 1) | a unit given as the concept (`cog:u07`) |
| `unknown-correspondence-set` (IDs from another overlay) | 4 | 4 |
| Re-surveyed under the overlay, then reused old IDs | yes | yes, then mixed IDs from two surveys |

Prompt tokens rose monotonically (no truncation). Thinking again fell to about 1
token per turn from the third request on (until the final 6,503-token turn), so
that pattern is not explained by the low temperature.

**Reading (pre-registered).** "Errors persist" is satisfied: A is not usable,
and the rejections fall in the same classes. On one trial per setting, the
explicit vendor sampler did not remove the failure. That makes a sampler-only
explanation unlikely, but it cannot be excluded statistically. Temperature and
the repetition penalty changed together.

**Harness counterexample found here (not repaired).**
- **The defect.** A `unit_orders` entry naming a nonexistent concept is accepted without error. The overlay is a no-op, because orders are looked up by concept, yet every entry joins the evidence digest. So every set ID is renamed (`alignment/units.py:273–295`). The R03b model sent `{"concept_id": "cog:u07", …}`; the survey returned identical evidence under new IDs, and the next previews were rejected as `unknown-correspondence-set`.
- **Reproduction.** `runs/experiments/r03-offline-checks-20261025/noop_overlay.py`: the same 21 local sets, 0 IDs shared, no refusal.
- **Effect.** It did not cause the failure: the overlay was itself an invalid, unrequested submission. But it hid that error behind a misleading one.
- **Fix, for a separate scope before any new batch:** refuse `unit_orders` that name an unknown concept, or a unit absent from that concept. (Implemented after R03c for the unknown-concept case only; see §16.)

**Consequence for the next step.** This supports the identifier-bookkeeping
explanation in §12a over a sampler explanation. For the local model, the next
discriminating comparison is an interface one:
- name a correspondence by pattern and unit, with the harness resolving the ID; or
- offer per-turn enums of the IDs currently valid.

Either would be compared with today's interface on Stage A, with the no-op overlay
refusal fixed first. More sampler variants are not the next test.

## 16. Follow-up R03c — Qwen3.6 35B-A3B, and the `unit_orders` fix (2026-10-25)

A separate experiment, requested by the owner to check whether R03/R03b's Stage A
failure is specific to Gemma: `runs/experiments/r03c-local-qwen-20261025/`. It ran
22:26:12–23:03:07 UTC on the code Gemma met, before the `unit_orders` fix below,
so that only the model and its sampler differ from R03b.

**What changed from R03b.** The model and that model's own published sampler:
- **Model:** `qwen3.6-35b-a3b`, unsloth Qwen3.6-35B-A3B-UD-MLX-4bit (4-bit), context 262,144, the sole loaded model, idle at launch.
- **Sampler:** the model card's thinking-mode "precise coding" setting, sent explicitly: temperature 0.6, top_p 0.95, top_k 20, min_p 0, presence_penalty 0, repeat_penalty 1.0 (`examples/sampling/qwen3.6-35b-a3b.json` + presence_penalty 0), max_tokens 16,384. An offline rehearsal confirmed every value in the request body.
- **Not chosen:** the card's general thinking setting (temperature 1.0, presence_penalty 1.5). A presence penalty discourages re-emitting tokens already generated, and this protocol requires re-citing identifiers. The choice was recorded before launch. Gemma ran at 1.0, so this is each model at its own published sampler, not both at one sampler.
- **LM Studio defaults:** the saved per-model settings for this model hold no sampler fields, so values set in the LM Studio UI did not apply; the explicit values governed.

Tools `628f0f32…`, instructions, payloads, caps, checker, scorer and gate are as
in R03b. Server-default thinking (Qwen thinks by default; `preserve_thinking`
not set). Frozen: `plan.json` `9fd6bb74…`, manifests A `69e0ea31…` / B
`799723e0…`, `source_manifest.json` `9ff3b30f…` (HEAD `1711093` + the arm in
`tools/r02_diagnostics.py` and its test), `preregistration.md` `34c99681…`.

**Stage A: success.** 4 turns, 5 calls, 0 rejected: a local and a recurrence
survey, the original preview, the revised preview, and a handle commit. Output
matches the reference with provenance and readback intact; `stage_gate.usable`.
119 s; 114,135 input / 5,253 output tokens. None of Gemma's error classes
occurred: no invented fields, no pattern IDs in `choices`, no unrequested
`unit_orders`, no stale IDs.

**Stage B: baseline-level judgment** (pre-registered label: ≤11/18 or ≤2/6).

| Measure | Qwen (R03c) | Gemini (R03) |
| --- | --- | --- |
| `model_committed_correct` | **10/18** | 18/18 |
| outgroup presence (6) | 6 | 6 |
| complementary outgroup presence (4) | 4 | 4 |
| outgroup absence (8) | **0** | 8 |
| matched pairs | **0/6** | 6/6 |
| decided by | explicit claims, all 20 opportunities | explicit claims |
| unresolved U1/U2 | committed `retain` | committed null at 0.5 |

- **Every opportunity was read `retain`.** 10/18 equals the identity, daughter-b and union baselines (§8).
- **How Qwen read the evidence.** The local survey carries `outgroup_reflexes` for the sets the outgroup witnesses, and the note: "a node showing nothing is absent above". Qwen used the witnesses correctly: its rationales name the right forms (c shows g in w03, w06, w07, w09, w12, w14). Where c has the concept but lacks the segment (w01, w05, w11, w16; the suffix cases), it wrote "no outgroup" and called the set a tie. It then retained the segment at confidence 0.5. It treated absence of a witness as absence of evidence, against the stated note.
- **Bookkeeping.** Of 18 calls at x and r, 1 was rejected: `child_node_ids` in a root preview (`extra_forbidden`), corrected next turn. Both nodes committed through handles.
- **Resources.** 2,095 s; 18 requests; 965,072 input / 91,619 output tokens; largest request 90,509. Prompt tokens never dropped (no truncation). At each node one response spent the whole 16,384-token budget on thinking (`response_truncated`). The harness's truncation recovery then asked for a tool call, and the session continued.

**Reading.**
- **Gemma's Stage A failure is not a general local-model limit with this interface.** A second local model of similar class passed the same frozen Stage A cleanly on its first trial. The bookkeeping is learnable without the §12a interface change. One trial each, different sampler and quantization: this is consistent with a model difference, not proof of one.
- **The judgment gap is real and separate.** On Stage B, Qwen used the protocol correctly but not the outgroup-absence criterion. That is a valid but scientifically poor decision, not an interface failure. Gemini applied the same criterion to the same survey output.
- **For R04 and the §12a plan.** The pattern-reference profile is still motivated for Gemma, but no longer as a precondition for using local models at all. A local model is usable for protocol-level iteration (Stage A–type checks) now. Judgment experiments still need the hosted model, or a model that passes Stage B.

**The `unit_orders` fix (after R03c, not used by any run).**
- `cognate_reconstruction/alignment/units.py` `evidence_map` now refuses a `unit_orders` entry whose `concept_id` has no form at the node. The message lists the valid concept IDs and says to omit `unit_orders` unless units conflict in order. Tools surface it as `alignment-failed`.
- A claim for a present concept already had to list all of its units (`_unit_order`), so it always orders something. Unit IDs beyond the concept's own stay accepted: `tools/evidence_repair_controls.py` uses one order per concept across nodes on purpose. A first, stricter version refusing them broke that control (`test_diagnostic_suite.py`) and was narrowed.
- **Remaining gap:** a concept present in only one child is not aligned, so a claim for it still orders nothing yet enters the digest. It is not refused, because `polarize` may evaluate a child subset where that is legitimate.
- **Test:** `test_a_unit_order_that_orders_nothing_is_refused_not_folded_into_set_ids` fails before the fix and passes after; the portable suite passed 848.
- R03b's offending call (`concept_id: "cog:u07"`) would now be refused with the concept list, instead of silently renaming every set.

## 17. Follow-up R03d — Gemma on the code with the `unit_orders` fix (2026-10-26)

Requested by the owner after R03c: one Gemma Stage A (B conditional) on the fixed
code with Gemma's published sampler. Directory
`runs/experiments/r03d-gemma-fixed-20261026/`; ran 18:28:58–18:34:42 UTC.

**Design.** Byte-identical to R03b apart from paths: the argv, the provider
config `2e8866c5…` (temperature 1.0, top_k 64, top_p 0.95, repeat_penalty 1.0,
min_p 0), tools `628f0f32…`, instructions, payloads, caps, checker and gate. The
same LM Studio instance class (MLX 6-bit, context 262,144, sole loaded model). The
only model-path change is the §16 fix. Frozen: `plan.json` `f859ed73…`, manifests
A `d6c652a4…` / B `120f16aa…`, `source_manifest.json` `144a13fc…`,
`preregistration.md` `4b4252cc…`.

**Result: A `no_commit`, B refused.** `ProtocolStallError` after 9 turns; 7 of 9
calls rejected; 343 s; 178,451 input / 13,791 output tokens.

**The fix was not exercised.** Gemma sent no `unit_orders` at all this time, so
no IDs went stale and there was no `unknown-correspondence-set`. By the
pre-registered rule, this is a second sample of R03b's condition, not a test of
the fix. Every rejection was in how the claims themselves were written:

| Turn | Rejection | What the model sent |
| --- | --- | --- |
| 3 | schema (15 errors) | `csp-` pattern IDs as `choices`; invented `explanation` and `reflexes` in choices; shared claims with `set_ids` and no `pattern_id`/`member_set_ids`; commitments without `support` |
| 4 | schema | `set_ids` instead of `member_set_ids`; shared claim without `proto_segment`; commitments without `reflexes`/`support` |
| 5 | schema | commitment without `support` |
| 6 | schema | `support: [4]` (a list for an integer) |
| 7, 8 | `invalid-shared-claim` | the same local set both in `choices` and in a shared claim. Turn 8 repeats turn 7 unchanged |
| 9 | schema | after the harness's targeted correction: invented `explanation` again |

Each remediation fixed the named error and the next call introduced another.
Turn 8 ignored a rejection entirely.

**Thinking collapses again.** Reasoning tokens per turn were 551, 2,278, then
**1** on every turn from the first preview (turns 3–8), until the post-correction
turn (6,464). R03b showed the same pattern at temperature 1.0, and R03 at 0.1. Qwen
in R03c thought for hundreds to thousands of tokens on most turns. So Gemma wrote
every rejected claim structure without visible reasoning. Whether that is the model's
choice or a template/server effect (for example, how LM Studio's Gemma template
handles thinking after tool turns) was not established when this run was read.
§17a traces it to how the harness and Gemma's template combine.

**Reading.** Across three Gemma trials (R03, R03b, R03d), Stage A failed through
invalid claim structure every time. The ID-overlay path (`unit_orders` → stale IDs)
was one route among several, not the cause. With R03c's clean Qwen pass on the same
interface, the evidence points to a Gemma-specific limit under this protocol, as
deployed. The thinking collapse has since been traced to an integration gap (§17a). It
is not yet separated from model capability by a live run. For the §12a decision rule:
- this weakens the case for building the pattern-reference profile for Gemma's
  sake, because most R03d errors were field names and claim shapes, not IDs;
- Qwen is the local model to use for protocol-level iteration;
- local judgment (Stage B) remains undemonstrated.

### 17a. Why Gemma's thinking drops to one token (offline and server log only)

Requested by the owner before committing. No model calls were made. The sources
were LM Studio's request/response log for R03d
(`~/.lmstudio/server-logs/2026-10/2026-10-26.1.log`), the model's
`chat_template.jinja` (lmstudio-community gemma-4-26B-A4B-it-MLX-6bit, SHA-256
`85a08664…`), and the hub `model.yaml`. The template was rendered offline on the
logged requests: `runs/experiments/r03-offline-checks-20261025/gemma-thinking/`
(`render.py`, rendered requests 3 and 9).

**What the one token is.** From request 3 on, every response's `reasoning_content`
is exactly `"\n"`. Gemma opens and immediately closes its thought channel
(`<|channel>thought\n<channel|>`). That is the same string the template inserts
when thinking is switched off. Thinking was on: `model.yaml` sets
`enableThinking` true by default, and the rendered system turn begins with `<|think|>`.

**Why it happens.** Three facts combine:
1. **The harness discards reasoning.** `LLMMessage` has no reasoning field.
   `LiteLLMProvider._message_payload` sends earlier assistant steps back with
   `content` and `tool_calls` only. It keeps Gemini thought signatures, but on
   the OpenAI-shaped route the reasoning text is counted and dropped. The logged
   requests confirm this: no assistant message carries `reasoning_content`.
2. **Gemma's template renders a tool loop as one model turn.** After the user
   message, every step continues the same `<|turn>model`:
   `<|tool_call>…<tool_call|><|tool_response>…<tool_response|><|tool_call>…`.
   After a tool response the generation prompt adds nothing: no new turn and no
   thinking cue. Earlier thoughts are rendered back
   (`<|channel>thought …<channel|>` before each call) only when the client
   supplies `reasoning_content`.
3. **So Gemma continues the turn as it sees it.** By request 3 its own turn shows
   two or three tool calls with no thought before any of them. It writes the next
   step the same way, behind an empty thought block.

**The natural experiment in all three Gemma runs.** Reasoning tokens per step,
with the harness's protocol correction marked. The correction is a user message,
so it starts a new `<|turn>model` with no bare calls in it:

| Run | Reasoning tokens per step |
| --- | --- |
| R03 (temperature 0.1) | 703, 1,591, 1,754, 1, 1, 1, 1, 1, 1, **[correction]** 2,062, 1 |
| R03b (Gemma sampler) | 141, 1,195, 1, 1, 1, 1, 1, 1, 1, **[correction]** 6,503 |
| R03d (fixed code) | 551, 2,278, 1, 1, 1, 1, 1, 1, **[correction]** 6,464 |

Thinking stops once the current model turn holds two or three thoughtless calls.
It returns on the first step of each new model turn. In R03 it stops again one
step later, once that new turn holds a thoughtless call. It is independent of
temperature and sampler.

**Why Qwen was unaffected.** Qwen's template renders each step as its own
`<|im_start|>assistant` turn, and its generation prompt opens `<think>\n` every
time. It is made to think at every step, whatever history it receives. The
harness dropped Qwen's reasoning too; that did not matter there.

**Reading.**
- **Established:** the collapse comes from the harness dropping reasoning
  combined with Gemma's single-turn tool-loop template. It is not a sampler
  effect, and it is not Gemma declining to think on a fresh turn. In all three
  runs Gemma thought for thousands of tokens whenever a new turn began.
- **Not established:**
  - whether sending `reasoning_content` back would sustain Gemma's thinking;
  - whether sustained thinking would remove its claim-structure errors.
  The only steps with thinking after the start were the post-correction steps.
  In R03b and R03d, that step was the last before the stall, so there is no
  evidence either way on the errors.
- **Consequence for R03/R03b/R03d.** Gemma's Stage A failures happened under an
  interface condition Qwen did not face: it wrote its claims with no reasoning
  from the third step on. "Gemma-specific limit" (§17) should be read as "Gemma
  as deployed by this harness". The model's capability with its thinking
  sustained is untested.

**Candidate repair (not implemented).**
- Add an optional reasoning field to assistant `LLMMessage`s.
- Capture it from the response (`reasoning_content`).
- Send it back on the OpenAI-shaped route, as is already done for Gemini thought signatures.

Before any live use:
- an offline wire check that LiteLLM forwards the field to LM Studio;
- a trajectory/checkpoint schema decision (the text must be stored to be resent);
- a token-cost note: Gemma's thoughts ran to about 2k tokens per step.

A single pre-registered Gemma Stage A trial on the repaired harness would then
test whether thinking is sustained and whether the claim errors persist. That
would be an interface change to the local route, run under a new identity.

## 18. Follow-up R03e — Gemma with its reasoning resent, and the context budget (2026-10-26)

### 18.1 What was built

`--reasoning-history keep` (default `drop`, so existing configurations and their
digests are unchanged).
- **What is resent.** Within the current tool loop, each assistant step goes back with the `reasoning_content` of the response that made it.
- **Budget.** The most recent steps go in full up to `--reasoning-history-budget` reasoning tokens (default 16,000). Older steps keep their first `--reasoning-history-head` tokens (default 200).
- **What is excluded.** Nothing from before the last user message, so a node start or a harness correction resets the history, as Gemma's template does. Nothing from responses that made no call (runaway thoughts).
- **Where it is stored.** On the adapter, like Gemini's thought signatures, so trajectory schemas are unchanged.
- **Recording.** In the configuration digest only when used. Refused for Gemini.
- **Tests and checks:**
  - tests: `tests/workbench/test_reasoning_history.py` and a freeze-arm test; suite 853 passed;
  - wire: LiteLLM forwards the field (offline rehearsal of the frozen argv);
  - server: a live probe showed LM Studio renders it into Gemma's template (prompt 85 → 430 tokens with a 345-token thought).
- **Vendor guidance** (from the web review, §18.4): Gemma 4's prompt-formatting guide says thoughts must not be removed between the function calls of one turn. The harness had been doing exactly that.

### 18.2 Result

`runs/experiments/r03e-gemma-reasoning-20261026/`; 18:52:54–19:19:34 UTC.
- **Design:** R03d's argv plus the three flags. Inputs, sampler config `2e8866c5…`, tools `628f0f32…` and caps are byte-identical.
- **Frozen:** `plan.json` `26ee6ccd…`, manifests A `2e1e6ef5…` / B `b295d30f…`, `source_manifest.json` `9760f694…` (re-verified against disk before launch), `preregistration.md` `8bae0717…`.

**Mechanism: thinking sustained.** Reasoning tokens per Stage A step:

| Run | Reasoning tokens per step |
| --- | --- |
| R03d (reasoning dropped) | 551, 2,278, 1, 1, 1, 1, 1, 1, [correction] 6,464 |
| **R03e (reasoning resent)** | **567, 296, 2,553, 263, 320, 344** |

**Stage A: success, Gemma's first.** 6 calls, 1 rejected
(`shared_claims[].member_set_ids` missing, fixed on the next call). Original and
revised previews, handle commit, reference output, provenance and readback intact.
161 s; 127,840 input / 6,057 output tokens; peak prompt 35,669.

**Stage B: no commit.** At node `x`, Gemma surveyed, read alignments and
re-surveyed (4 calls, all accepted). It then produced three responses that each spent
the whole 16,384-token output cap on thinking without a call: 16,381 reasoning
tokens each, with the harness's truncation recovery between them. The third ended
the node (`ProtocolStallError`), so the root never ran. The scorer reports 18
missing (0/18, 0/6), which is a missing outcome, not a judgment. 1,438 s; peak prompt
39,355 tokens, so context length was not the limit.
- **The thoughts.** In the server log, 491 of 522 sentences in the first are
  distinct. It is not a repetition loop but analysis that does not converge.
  Gemma derives daughter-to-daughter "rules" (`k > Ø`, `u > k`, "anomalous
  insertions") instead of reconstructing the parent, and re-checks the same forms.
  The outgroup was never consulted.
- **A truncation check note.** Prompt tokens fell once (37,303 → 35,016). That was
  the harness's recovery message: a user turn that resets the resent reasoning by
  design, not server-side truncation.

**Reading (pre-registered).**
- "Thinking sustained and A usable" holds. That is consistent with the dropped
  reasoning having caused Gemma's three earlier Stage A failures (one trial).
- §17's "Gemma-specific limit" is withdrawn for Stage A. As deployed before R03e,
  the harness was disabling Gemma's thinking.
- On Stage B, Gemma with thinking does not converge within the output cap.
  This is an output-truncation outcome (the frozen 16,384 `max_tokens`). Whether a
  larger cap would yield a commit, and whether that commit would be any good, is
  untested. The content of the thoughts (no outgroup, daughter-to-daughter rules)
  does not suggest an evidence-sensitive decision was near.

### 18.3 Measured context per node session (all past runs with usage records)

| Data | Model | Sessions | Peak prompt, median | p90 | max |
| --- | --- | --- | --- | --- | --- |
| Burmish | Gemma 26B | 18 | 89,698 | 111,239 | 342,463 |
| Polynesian | Gemma 26B | 107 | 53,969 | 81,348 | 252,648 |
| Polynesian | Qwen 35B | 21 | 77,331 | 109,937 | 118,873 |
| Burmish / Polynesian | Gemini 3.7 | 23 / 21 | 216,489 / 151,390 | 336,176 / 213,005 | 400,664 / 262,415 |
| R02/R03 panels | Gemma / Qwen / Gemini 3.8 | 3 / 3 / 3 | 30,139 / 79,368 / 161,543 | — | 42,024 / 90,509 / 174,747 |

- **Growth comes from tool results.** Single results reached 128,669 tokens
  (`search_forms`), 99,019 (`test_rule_cascade`) and 84,029 (`get_alignments`).
  Over 249 `search_forms` steps, the median was 3,513 and the p90 26,552.
- **Reasoning, if all of it were resent** (simulated on Qwen's 26 sessions): median
  peak 80k → 124k, p90 114k → 170k, max 123k → 259k. With a 16k budget: median
  95k, p90 129k. With 32k: p90 144k.
- **Gemma rarely reasoned in past runs.** Median 0 tokens per call step; when it
  did, median 1,184 and p90 4,659.

### 18.4 Long-context evidence (web review, Sonnet subagent, 2026-10-26)

No benchmark measures either model's effective context between 64k and 256k, so
the following is extrapolation:
- **Gemma 4 26B-A4B:** 44.1% on MRCR v2 (8-needle, 128k), per its model card.
  Tool-markup drift has been reported in agentic sessions of about 28–41k with large
  schemas. Suggested working range about 32k, soft ceiling about 64k, never above 100k.
- **Qwen3.6 35B-A3B:** no long-context scores; the 3.5 sibling has LongBench v2
  59.0. Suggested range about 64k, soft ceiling 100–128k.
- **Interleaved thinking:** Google keeps thoughts between the calls of one turn.
  Qwen recommends `preserve_thinking` for agents.
- **Cache precision:** an 8-bit or full-precision KV cache is fine; 4-bit hurts retrieval.
- **Confidence:** low to medium. Our own real-data sessions (§18.3) already
  exceed Gemma's suggested soft ceiling before any reasoning is resent.

### 18.5 Design options for the context budget (not implemented)

Resent reasoning is the smaller cost; tool output is the larger. In order of
expected payoff:
1. **Tool-result hygiene:**
   - replace superseded results (re-surveys, replaced previews) with stubs;
   - shrink older results to a one-line stub with the call ID and a summary;
   - cap each result at about 8–16k tokens, with paging;
   - possibly a denser tabular rendering of set lists.
2. **A per-model soft ceiling with a restart from harness state.** On crossing it,
   start a fresh conversation for the node. It would carry the task, the stored
   hypothesis handle, the last preview result and the open errors, all written
   deterministically by the harness.
3. **Cheaper reasoning history:** heads only (`--reasoning-history-budget 0
   --reasoning-history-head 200`, at most about 5k per node), or the latest step in full plus heads.
4. Not recommended: overriding Gemma's template to open a new turn per step,
   which departs from the vendor format.
5. Narrower sessions per node, or routing long sessions to Gemini.

Items 1 and 2 change what every model sees, so each needs its own experiment. The
ceilings should be set from our own measurement of opaque-ID copying and
tool-call validity at 16k, 32k, 64k, 96k and 128k on both local models, not from
the extrapolation above.

## 19. Follow-up R03f — creation-time tool-result slimming (Option 1a) and Qwen on it (2026-10-28)

### 19.1 What was built

Three kinds of content in accepted tool results were never cited by a model and
are not inputs to any tool. Each is now left out when the result is created, so
no earlier prompt is ever rewritten (KV-cache prefixes are untouched).
- **`target_absent` is no longer an exception.** `RuleApplicationReport.exceptions`
  lists forms the target occurs in and the rule did not apply cleanly to.
  `results` keeps every form; `forms_evaluated` still counts them. The
  reconstructor already treated `target_absent` as "not applicable". Affects
  `test_rule_cascade` (`report_summaries` and `reports`) and `test_sound_law`.
- **`get_alignments` `detail="summary"` returns no `pairwise_correspondences`.**
  The n-way `alignments` are unchanged; `full` still returns the pairwise views.
  The aligner core still renders them (tests moved to the core call).
- **Forms show their evidence, not their source.** `search_forms` hits and
  `test_rule_cascade.final_forms` serialize each form without form or
  membership `provenance`. `cognate_memberships` is omitted when the
  `cognate_set_id` shorthand already says all of it; partial-cognate,
  alternative and doubtful judgements keep their memberships, slimmed.
  Only JSON serialization changes (`model_facing_form`); the stored result
  objects keep full forms, so `convergence` and commit checks are unaffected.
- **Not as briefed:** `get_alignments` members never embedded a `LexicalForm`
  (they carry flat membership fields), so there was no form metadata to strip
  there. Cascade `final_forms` were added because they carry the same form
  provenance (1.38 MB recorded).
- **Digests:** tool schemas `628f0f32…`, trajectory schema `9368c171…` and
  payload schema `b93ae612…` are unchanged. A known inconsistency remains: the
  frozen `detail` description still says "Summary includes counts and column
  pointers". Fixing it would change the tool-schema digest.
- **Tests:** `tests/workbench/test_tool_result_slimming.py` (9 tests), and three
  `test_affordable_evidence.py` tests repointed (the summary pairwise view is
  now tested on the aligner, the reference test on `full`). Portable suite 822
  passed, 41 deselected.

### 19.2 Offline replay over every recorded session

`runs/experiments/r03f-qwen-slim-metadata-20261028/offline-replay/`. Each
`events.jsonl` timeline (rehearsals excluded; 327 sessions) is walked in order,
and every accepted result of the four tools is re-rendered by the current code
(all 11,530 recorded forms validated). The token difference is subtracted
from every later request while that result is live. A result the harness already
compacted stops counting at its compaction. Token counts use Qwen 3.6's and
Gemma 4's own tokenizers; Gemini uses Gemma's. Calibration against recorded prompt
growth: Qwen 1.001, Gemma 1.11, Gemini 1.0–1.10 (median ratio), so savings for
Gemma/Gemini are if anything understated.

| Group | n | Peak in median / p90 / max (recorded → slimmed) | >64k | >100k | >128k | Cumulative median | Chars saved: get_alignments / search_forms / test_rule_cascade / test_sound_law |
|---|---|---|---|---|---|---|---|
| Burmish — Gemma 26B | 18 | 89.7k / 111.2k / 342.5k → **64.3k / 81.3k / 318.1k** | 12 → 10 | 5 → 2 | 1 → 1 | 859.2k → 702.3k (-19% total) | 0.56 / 0.00 / 0.24 / 0.10 MB |
| Polynesian — Gemma 26B | 107 | 54.0k / 81.3k / 252.6k → **45.9k / 67.2k / 144.3k** | 23 → 13 | 9 → 3 | 5 → 1 | 471.5k → 400.8k (-18% total) | 1.31 / 0.76 / 1.28 / 0.22 MB |
| Polynesian — Qwen 35B | 21 | 77.3k / 109.9k / 118.9k → **67.6k / 93.2k / 98.0k** | 19 → 14 | 6 → 0 | 0 → 0 | 920.6k → 831.3k (-16% total) | 0.45 / 0.42 / 0.00 / 0.00 MB |
| Burmish — Gemini 3.7 | 23 | 216.5k / 336.2k / 400.7k → **163.3k / 205.8k / 343.3k** | 23 → 23 | 22 → 22 | 22 → 22 | 2485.0k → 1737.7k (-27% total) | 1.87 / 1.75 / 0.00 / 0.00 MB |
| Polynesian — Gemini 3.7 | 21 | 151.4k / 213.0k / 262.4k → **116.8k / 158.2k / 175.8k** | 21 → 21 | 21 → 19 | 16 → 8 | 2054.4k → 1605.6k (-25% total) | 0.70 / 1.41 / 0.17 / 0.04 MB |
| R02/R03 panels — gemini-3.8 | 3 | 161.5k / 174.7k / 174.7k → **144.1k / 156.2k / 156.2k** | 2 → 2 | 2 → 2 | 2 → 2 | 1094.3k → 1051.6k (-6% total) | 0.00 / 0.06 / 0.05 / 0.01 MB |
| R02/R03 panels — gemma-4-26b | 5 | 35.7k / 42.0k / 42.0k → **35.7k / 42.0k / 42.0k** | 0 → 0 | 0 → 0 | 0 → 0 | 207.2k → 207.2k (+0% total) | 0.00 / 0.00 / 0.00 / 0.00 MB |
| R02/R03 panels — qwen3.6-35b | 3 | 79.4k / 90.5k / 90.5k → **77.5k / 90.5k / 90.5k** | 2 → 2 | 0 → 0 | 0 → 0 | 450.7k → 450.7k (-1% total) | 0.00 / 0.01 / 0.00 / 0.00 MB |

- **Saved overall:** 14.4 MB of tool-result characters: `get_alignments` 5.38,
  `search_forms` 4.68, `test_rule_cascade` 3.80, `test_sound_law` 0.52 MB. Less
  than the audit's upper bound because many recorded `get_alignments` calls used
  `detail="full"` (untouched), and superseded results were already compacted.
- **Qwen on Polynesian** now stays under 100k in every recorded session (6 → 0);
  p90 93k. **Gemma** improves but stays above its ~64k soft ceiling in 13/107
  Polynesian and 10/18 Burmish sessions. **Gemini** saves 25–27% of cumulative
  input but stays far above any local ceiling.
- **The R02/R03 panels barely move** (Qwen −1%): Qwen asked for `detail="full"`
  there, and the synthetic forms carry little provenance.
- **KV cache:** creation-time only, so every request's prefix is the prefix the
  slimmed run would have sent before. No prefix is invalidated.

**What still fills the prompt at the slimmed peak** (`residual_composition.py`,
median share of the peak request):

| Group | Fixed first request | Assistant turns + harness text | `test_proto_assembly` | `get_alignments` | `summarize_correspondences` | Rejected results |
| --- | --- | --- | --- | --- | --- | --- |
| Burmish — Gemma | 17% | 20% | 10% | 15% | 8% | 4% |
| Polynesian — Gemma | 28% | 20% | 11% | 10% | 9% | 3% |
| Polynesian — Qwen | 34% | 15% | 13% | 11% | 7% | 1% |
| Polynesian — Gemini | 19% | 29% | 15% | 14% | 10% | 1% |

- The fixed first request is mostly tool schemas: about 14k of Qwen's 17.1k
  first-request tokens (`commit_reconstruction` 4.5k, `test_proto_assembly` 3.3k).
  It is re-sent with every request.
- Upper bounds on the next options, applied to each session's slimmed peak
  (sessions over 64k / over 100k):

| Group | After 1a | + supersede older previews and rejections | + 8k cap per result | + both |
| --- | --- | --- | --- | --- |
| Burmish — Gemma (18) | 10 / 2 | 3 / 1 | 8 / 1 | 3 / 0 |
| Polynesian — Gemma (107) | 13 / 3 | 7 / 0 | 7 / 0 | 1 / 0 |
| Polynesian — Qwen (21) | 14 / 0 | 7 / 0 | 14 / 0 | 7 / 0 |
| Polynesian — Gemini (21) | 21 / 19 | 21 / 12 | 21 / 18 | 21 / 11 |

### 19.3 Live: Qwen3.6 35B-A3B on the slimmed code (R03f)

`runs/experiments/r03f-qwen-slim-metadata-20261028/`; 2026-10-27 23:13:01–23:38:24
UTC. Frozen: `plan.json` `8709b196…`, manifests A `9b1a7155…` / B `ad1037c5…`,
`source_manifest.json` `9cfa88ee…` (HEAD `535cca9` + Option 1a and its tests),
`preregistration.md` `2a6561db…` (written before launch).
- **Same as R03c:** argv apart from the path; inputs byte-identical; tools
  `628f0f32…`; first-request digests; the model (sole loaded, 4-bit, 262,144).
- **Wire:** the offline rehearsal confirmed every sampler value in the body and
  no reasoning resent.
- **Code difference besides 1a:** `535cca9`. Its `unit_orders` refusal was not
  triggered, and reasoning history stayed at the default `drop`.

| Measure | R03c | R03f |
| --- | --- | --- |
| **A** outcome | success | **success** |
| A turns / calls / rejected | 4 / 5 / 0 | 4 / 5 / 0 |
| A peak / cumulative input | 37,453 / 114,135 | 37,453 / 114,135 |
| A elapsed | 119 s | 122 s |
| **B `x`** outcome | committed | **no commit** (`ProtocolStallError`) |
| B `x` score | 10/18, 0/6 pairs, uniform `retain`; U1/U2 `retain` | 0/18 scored, 18 missing (a missing outcome, not a judgment) |
| B `x` turns / calls / rejected | 8 / 9 / 0 | 9 / 7 / 1 (`unknown-correspondence-set`: a stale pattern ID in a shared claim) |
| B `x` 16,384-token thinking-only responses | 1 (recovered) | **3** (2 recovered, the third ended the node) |
| B `x` peak / cumulative input | 90,509 / 450,708 | 67,185 / 397,203 |
| B `x` reasoning tokens | 39,024 | 62,336 |
| B `x` elapsed | 1,265 s | 1,399 s |
| B `r` | committed, 830 s, peak 79,368 | not run (the root needs `x`) |

**Option 1a was not exercised on Stage B.** At `x`, Qwen called
`list_available_nodes`, `list_concepts`, `summarize_correspondences` ×3,
`get_alignments` with `detail="full"`, and one `test_proto_assembly`. None of
those results contains anything 1a changes. The `get_alignments` result is
byte-identical to R03c's (same SHA-256). So the model-visible content was the
same condition as R03c, and the different path is sampling at temperature 0.6.
On Stage A no slimmed tool was called; the run reproduced R03c token for token
on the input side.

**Reading (pre-registered).**
- Stage A: no detectable effect (identical).
- Stage B: the outcome is a missing judgment. It is not attributable to 1a,
  because no slimmed content reached the model. It is a second sample of
  Qwen's unchanged Stage B condition.
- Across the two samples at `x`, 4 of 17 responses spent the whole 16,384-token
  budget on thinking. That is Gemma's R03e failure mode. It happened at prompts
  of only 47k–67k, well inside Qwen's ceiling.
- So on this panel, context size is not what limits the local models. The
  limit is thinking that does not converge within the output cap.
- Whether 1a changes judgment on a path that reads `search_forms` or
  summary alignments is untested: the panel never forces such a call. That needs
  a real-data session (Polynesian), where 1a measurably acts.

### 19.4 Next context-saving options (analysis, not implemented)

After 1a, Qwen fits inside its ~100k ceiling on every recorded real-data
session. Gemma does not: 13/107 Polynesian and 10/18 Burmish sessions stay
above ~64k. The measured upper bounds in §19.2 rank the options.

1. **Supersession of obsolete previews (largest measured payoff for Gemma).**
   Over 64k: Polynesian 13 → 7, Burmish 10 → 3, Qwen 14 → 7.
   - It needs loop safety by design, and measurement makes that cheap:
     rejected results are only 1–4% of the peak. **Never compact a rejection**;
     keep every error message verbatim.
   - Compact only accepted, superseded `test_proto_assembly`, `test_rule_cascade`
     and `test_sound_law` results, into a harness-written stub. The stub keeps:
     the call ID; a hash of the arguments; the hypothesis/validation IDs; the
     outcome counts (conflicts, unresolved, residue); and the superseding call
     ID.
   - **Repeat guard.** A new call with the same argument hash as a compacted
     one gets "identical to call N; result unchanged", plus the stub. The model
     then cannot loop through re-running a forgotten draft, and it always knows
     why each draft failed.
   - A commit still needs the validation ID of the exact preview it cites. So
     the newest preview, and any preview a later commit refers to, stays in full.
   - **KV cost.** The harness already rewrites superseded read-only results in
     place. The superseded preview is usually one or two turns back, so the
     prefix lost is short.
2. **Watermark-gated compaction (3) is the right *trigger*, not a separate
   mechanism.** Below a low watermark (e.g. 48k for Gemma, 80k for Qwen) nothing
   is rewritten, so the cache is fully reused. On crossing it, apply option 1's
   rules once, then turn the oldest read-only evidence into breadcrumbs: what
   was queried, the `csu-*`/`csp-*`/`hyp-*` IDs it returned, and "call again to
   retrieve". This invalidates the cache once per crossing, not per turn.
   - Breadcrumbs must be written deterministically by the harness, never
     summarized by a model.
   - The main risk is re-query loops. The repeat guard above covers them, and
     the stall detector already counts repeats.
3. **Pagination / guardrails / economical descriptions.**
   - **Opt-in pagination does little:** models do not opt in, and an 8k cap alone
     moves Polynesian Gemma 13 → 7 but Qwen 14 → 14. It helps only the long tail.
     A harness-side cap with explicit `truncated: true` and `next_offset` is the
     useful form. `search_forms` already pages.
   - **The larger lever is the tool definitions.** They are about 14k of every
     request (`commit_reconstruction` 4.5k, `test_proto_assembly` 3.3k), and 17–34%
     of the peak. Trimming duplicated `$defs` and long descriptions could take
     5–8k off every request, so cumulative input falls by the same per turn.
   - That deliberately changes the tool-schema digest. It is a new interface
     version with its own Stage A check, not a silent edit. The same holds for
     correcting the stale `detail` description noted in §19.1.

Recommended order: (1) supersession of previews with the repeat guard; (2) put it
behind the watermark; (3) a versioned schema diet. Separately, the Stage B
blocker for both local models is non-converging thinking under the 16,384-token
cap. No context option addresses it.

## 20. `--reasoning-history auto`: deciding from the chat template (2026-10-28)

Owner request: choose `keep` or `drop` per model, inferred rather than listed.

**Rule.** Two properties of a chat template decide it. Both are read by rendering
a one-step synthetic tool loop (`cognate_reconstruction/agent/providers/chat_template.py`):

| Resent reasoning reaches the prompt | New turn opens after a tool result | Mode |
| --- | --- | --- |
| yes | no | `keep` (Gemma 4: the model continues its own turn) |
| yes | yes | `drop` (Qwen3.6: each step opens a turn that thinks by itself) |
| no | either | `drop` (resending would be ignored) |

**How the template is found.**
- `--chat-template FILE` names it explicitly.
- Under the `lm-studio` preset, `lms ps --json` gives the loaded model's folder, or
  a hub ID. A hub model is resolved through its `model.yaml` to the single
  downloaded variant with the loaded quantization, and the hub's Jinja defaults
  (Gemma's `enable_thinking`) are applied.
- The template comes from `chat_template.jinja` or `tokenizer_config.json`.
- **Refused:** a per-model prompt-template override, an ambiguous hub variant, and
  GGUF models (which embed the template). Pass `--chat-template` for those.

**Live check.** Unless `--no-preflight`, two one-token requests compare prompt
tokens with and without `reasoning_content`. A disagreement between server and
template is refused. Gemini always resolves to `drop`.

**Default and recording.** `auto` is the harness default (owner decision,
2026-10-28).
- **Digest:** it records the reasoning setting only when the outcome is `keep`.
  A run that drops, by default or by decision, hashes exactly as before, so
  earlier checkpoints still resume.
- **`run_summary.json`:** gets the full decision record for every run:
  `requested`, `mode`, `reason`, template source (relative to the models folder)
  and SHA-256, variables, probe.
- **Fallback:** when nothing can be inferred, the default falls back to `drop` and
  prints why; an explicit `--reasoning-history auto` refuses instead.
- **Historical arms:** the R02–R03d arms in `tools/r02_diagnostics.py` now pass
  `--reasoning-history drop` explicitly, so re-freezing them reproduces what
  those runs saw.
- **Scope of `keep`:** within the current node's tool loop only. No reasoning
  from earlier nodes, from before a harness correction, or from responses
  without a call; recent steps in full up to the budget, older ones as heads.
- **Live check of the default (Qwen loaded):** `drop` with the full record; digest
  identical to an explicit `drop`.

**Checks.**
- **Offline, every downloaded MLX template:**
  - Gemma 4 26B (6-bit), with or without `enable_thinking`: uses resent reasoning, no new turn → `keep`;
  - Qwen3.6 35B (4-bit and 8-bit) and Qwen3.8 27B: uses it, new turn → `drop`.
- **Gemma's hub resolution** on the real LM Studio folders (simulated `lms ps`
  entry, since Gemma was not loaded) → `lmstudio-community/gemma-4-26B-A4B-it-MLX-6bit`,
  `enable_thinking: true`, `keep`.
- **Live, Qwen loaded:** template `55d49314…`; probe 320 → 682 prompt tokens
  (the field is rendered); resolved `drop`.
- **End to end:** a scratch `infer` smoke on the R02 Stage A payload with
  `--reasoning-history auto` committed in 6 steps. It is not an experiment and
  is not pooled.
- **Tests:** synthetic templates for the three patterns, a fake LM Studio home
  (folder, hub, ambiguous variant, override), the probe, CLI resolution and
  refusal, and the run-summary record. Suite: 870 passed (871 on `350ef65`).

**Limits.**
- LM Studio renders with its own Jinja implementation. The live probe covers the
  first property only; the second rests on the offline render.
- A user-level change to a hub custom field (for example `enableThinking` turned
  off in LM Studio's UI) is not read: the hub default is used.
