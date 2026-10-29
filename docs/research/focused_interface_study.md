# R04 — Focused study: Gemini judgment where the outgroup-witness rule is not the answer

2026-10-28, branch `r01-contract-repairs`, HEAD `0d7c37b` plus the uncommitted
changes listed in §5. Environment `llm_reconstruction` (Python 3.11.0, LiteLLM
1.81.16). **Live status: pending the owner's paid envelope and approval of one
pre-launch repair (§4.4).** No model request, model discovery or paid call was
made in this session.

## 0. Status at a glance

| Item | Status |
| --- | --- |
| Upstream recommendation (R03 §13 and its amendments) | Verified against the R03 report, results and code; adopted |
| Interface redesign (dossier, selection surface, reduced IDs) | **Deferred** with reasons (§2); not built |
| Stage C panel `r04-stage-c-v1` and scorer `r04-judgment-v1` | Built; key re-derived from observed forms in a test |
| Frozen deployable baselines | R02 rule 13/19; best shallow rule 15/19; stated criterion 19/19 (ceiling by construction) |
| `--stop-after-node` (score only x) | Built and tested through `cli infer`, the launcher and the ledger |
| Defect found by rehearsal: a Gemini reply cut off at the cap crashed the node | Reproduced, repaired, red→green tests; **needs the owner's approval before launch** |
| Frozen launch candidate | `runs/experiments/r04-stage-c-20261028/` (hashes §6) |
| Independent read-only review | Launch-ready with mitigations (§7): fixes need a v2 re-freeze, not yet applied |
| Live Gemini trial | **Pending**: needs US$3.50 / 35 min approved by the owner |
| Tests | Stage C 17, Gemini provider +3; portable suite 850 passed, 41 deselected |

## 1. Question

R03's selected question replaces the brief's default interface question:

> Does Gemini 3.8 Flash make evidence-sensitive decisions on a panel where
> R02's deployable outgroup-witness rule is not the answer?

On R02's Stage B the rule "keep one-sided material when the survey reports an
outgroup witness in that exact column" equals the answer key. Gemini's 18/18
there therefore cannot separate judgment from reading the survey's label. The
survey's own note also states the rule as doctrine: "A segment one of them
shows was present before this node split; a node showing nothing is absent
above" (`agent/tools/correspondences.py`).

**Verification of the upstream recommendation.** R03's Gemini arm needed no
interface simplification: one omitted-null rejection per stage, fixed on the
next call (R03 §7–§8, §11). The local blockers are elsewhere: Gemma's Stage A
failures came from dropped reasoning (R03 §17a, R03e passed A), and both local
models fail Stage B by thinking that does not converge under the 16,384 cap
(R03e, R03f), not by navigation or transcription. So "does reducing
navigation and transcription burden improve decisions for the selected model"
has no failing condition to explain yet. The narrower judgment question is the
open one, and it can show whether navigation becomes the problem on harder
evidence (§8).

## 2. Designs considered

| Design | Decision | Why |
| --- | --- | --- |
| Current vs fixed evidence dossier + selection surface (the brief's default) | Deferred | No observed Gemini navigation or transcription failure to remove. A dossier that pre-lists outgroup columns would hand over the decisive cue (R02 caution). Becomes the question if Stage C fails mainly through navigation (§8) |
| Pattern-reference claims / per-turn ID enums (R03 §12a) | Not built | Motivated by Gemma's clerical errors, which R03e traced to dropped reasoning |
| Local/stronger × current/reduced 2×2 | Not justified | R03 and its follow-ups do not implicate the interface; the local Stage B blocker is output-cap convergence |
| Local-only Stage B convergence study | Out of scope | The owner did not select local operation; a cap or effort change would be its own pre-registered arm |
| Tool-schema diet, preview supersession, watermark (R03 §19.4) | Not part of this study | Not selected by the owner; they change what every model sees |
| **One Gemini trial on a new panel the R02 rule does not solve (chosen)** | Built | R03's selected comparison; one arm, current interface, frozen deployable baselines |

No candidate list or selection surface is offered: the model proposes every
claim freely, as in R03. No unseen-application split exists (none can be
withheld by the harness today), so no extension rule is claimed.

## 3. The Stage C panel (`benchmarks/diagnostic/r04-stage-c-v1.json`)

**Tree and decision type.** `((a,b)x,c,d,f)r;`. At node x, material is
present in exactly one active child inside one supplied cognate unit: a final
`k` (a has it, b does not) or an initial `h` (b has it, a does not). Three
outgroups sit at the root. They show k as `g` (c), `k` (d) and `kʰ` (f).

**Criterion block** (appended to the packaged text; instructions `216ef02e…`).
It states unweighted parsimony over the whole tree, including the branches to
the outgroups. A form of another cognate unit is no evidence about this unit.
A node with the unit but without the material is one observation; a node with
no form in that unit is no observation. Where the criterion and a general
tool note disagree, the criterion governs. Ties are unresolved: the deciding
claim gets confidence ≤ 0.5 and either value is accepted; every other decision
gets a confidence above 0.5. The block names no item, unit or answer.

**Identification.** With m of the k observed outgroups showing the material:
present when m > k/2, absent when m < k/2, tied when m = k/2 (including k = 0).
A test re-derives every expected reading by brute-force parsimony over the
parsed tree from the observed forms and units, not from the builder's labels.

**Items** (19 concepts, operator labels; concept and unit IDs shuffled):

| Kind | Items | What a shallow reading does |
| --- | --- | --- |
| Majority of three outgroups | 11 decided (presence and absence) | The R02 rule keeps every minority witness (6 errors); unanimity drops every 2-of-3 majority (4 errors) |
| No observation | 3 decided | Counting a missing form as lacking turns 1-of-1 support into absence (part of 5 majority-of-three errors) |
| Wrong scope | 5 decided | An other-unit look-alike, or the reflex in a following suffix piece, counted by spelling (5 spelling errors) |
| Tied | 4 | One witness of two observed; an other-unit look-alike beside a tie; one other-unit form only; no outgroup form |

Present/absent balance 10/9. Four concepts carry two decisions (h and k), so
the correct x form is sometimes a's form, sometimes b's, and sometimes neither
(legitimate copying and combination). Five matched pairs are alike in every
daughter-visible feature (same vowel, onsets balanced) and differ only in
outgroup evidence; one is a control pair the R02 rule gets right.

**Separation.** Stage C shares no concept or unit ID with R02 Stage A/B. Its
operator fields (design labels, outgroup-state labels, rule names, history,
targets) never reach a request: a sentinel planted in the target bindings
leaves every request byte-identical.

## 4. Minimal implementation

### 4.1 Scorer `r04-judgment-v1` (`evaluation/judgment.py`)

It reuses `r02-decisions-v1` readings unchanged and adds:
- **Deciding-claim confidence and rationale** per opportunity, from the
  assembly columns and the committed (expanded) claims. Residue-decided
  columns have none.
- **Warranted uncertainty:** ties marked at ≤ 0.5; decided items hedged at
  ≤ 0.5; false confident claims (incorrect decided items and ties above 0.5).
- **Shallow-rule error sets:** the model's score on the items each frozen rule
  gets wrong, so a partial reading of the criterion shows as the component it
  misses.
- **Navigation:** calls by tool, rejections, and which outgroup forms appeared
  in a non-survey tool result (`search_forms` or `get_alignments`), per
  concept. The survey shows presence only.
- **Labels** frozen in code and in the pre-registration (§8).

Missing, unscorable and fallback outputs stay in every denominator.

### 4.2 Baselines (`tools/r04_judgment.py`)

Every policy runs through the ordinary service, JSONL, checkpoint and both
scorers. None is a model result.

| Policy | Decided /19 | R02 rule's errors /6 | Unanimity's /4 | Majority-of-three's /5 | Spelling's /5 | Pairs /5 | Ties marked /4 | Raw exact /19 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Stated criterion (ceiling by construction) | 19 | 6 | 4 | 5 | 5 | 5 | 4 | 19 |
| **R02 outgroup-witness rule (frozen)** | **13** | **0** | 4 | 5 | 4 | 1 | 0 | 13 |
| Unanimity | 15 | 6 | 0 | 5 | 5 | 3 | 0 | 15 |
| Majority of three (no form = lacking) | 14 | 6 | 4 | 0 | 2 | 3 | 0 | 15 |
| Spelling majority (units ignored) | 14 | 5 | 4 | 2 | 0 | 3 | 0 | 15 |
| Presence only (the tool note's doctrine) | 10 | 0 | 4 | 5 | 3 | 0 | 2 | 10 |
| One outgroup's state (c / d / f) | 12 / 13 / 12 | 4 | 2–3 | 1–2 | 2–3 | 1–2 | 0 | 13 |
| Union / identity / intersection | 10 / 9 / 9 | 0 / 5 / 6 | | | | 0 | 0 | 10 / 11 / 10 |
| Copy a / b (diagnostic) | 8 / 11 | | | | | | | |
| Oracle (reads gold; scorer control) | 19 | 6 | 4 | 5 | 5 | 5 | 4 | 19 |

The stated criterion is itself computable from observed data, as any
identified panel's key is. What this panel adds over Stage B: the survey's
label and the tool's doctrine are not the key, and each partial reading fails
a whole component.

### 4.3 `--stop-after-node` (traversal, service, CLI)

R03's unscored root used about 58% of Stage B's spend. `infer
--stop-after-node x` ends the traversal once x's step is recorded. It reuses
the ordinary interruption path: `run_summary.json` records `status:
interrupted`, `failure_kind: planned_stop` and `stop_after_node`. The
checkpoint and journal keep x, no `result.json` is written, the exit code is 0
and the ledger outcome reads `interrupted`. An unknown node is refused; naming
the root is a no-op. Nothing model-visible changes.

### 4.4 Defect found by rehearsal and repaired (needs the owner's approval)

**Counterexample.** The rehearsal ran the frozen argv through the real CLI and
LiteLLM, with a fake HTTP reply that Gemini returns when the output cap is hit
during thinking: `finishReason: MAX_TOKENS`, no text, no call. The harness
built an assistant message with neither content nor calls, which fails
`LLMMessage` validation. The node failed (`ValidationError`), the run stopped,
and the billed response was recorded as unknown cost. The documented one-turn
truncation recovery only ever ran on the LM Studio route (R03c/e/f), where
the server returns empty text. Gemini never reached a cap in R03 (largest
response 11,326 tokens). With the owner's 32,768 cap chosen precisely because
a cap hit is likely, this would have turned the expected hard case into a
lost outcome.

**Repair** (`agent/providers/litellm_provider.py`, about 20 lines):
- a reply with neither text nor a call becomes an empty turn, so the existing
  recovery runs and the response is priced;
- on Gemini routes that empty turn is sent back without content, which
  LiteLLM's Gemini mapping drops. The next request is a tool result followed
  by the harness's recovery message, with a forced tool call. Banked Gemini
  sweeps sent that same shape (stall corrections after tool results) and were
  answered. An empty text part, the alternative, has never been sent to Gemini.
- the OpenAI-shaped local route is unchanged (it keeps sending the empty
  string it always sent).

**Evidence.** Three provider tests fail before the change and pass after.
An end-to-end Stage C test recovers from a cut-off reply at x, prices it, and
still scores x 19/19. The rehearsal's `gemini-truncated` scenario now recovers
(5 priced requests; request 3 is `function_response` then a user turn, mode
`ANY`, no empty part). This changes what the model sees only after a cut-off
reply, which previously ended the node. It is named in the pre-registration
as a deviation, like R03's `anyOf` repair.

## 5. Package differences from R03's Gemini trial

- Panel and criterion block (§3); scorer `r04-judgment-v1`.
- `max_tokens` 32,768 (owner decision 2026-10-28); the reservation uses it.
- `--stop-after-node x` (§4.3).
- `--reasoning-history auto` (Gemini resolves to `drop`; recorded in the run
  summary; hashes as drop).
- Code since R03: `535cca9`, `7e6d637` (tool-result slimming), `350ef65`, and
  the repair in §4.4.
- Caps: 36 turns, 64 calls, US$2.50, 1,800 s.
- Unchanged: model `gemini-3.8-flash`, `--preset gemini`, thinking level
  medium, temperature 1.0, timeout and retry budget 300 s, 3 retries,
  `--max-failed-nodes 0`, stored-hypothesis profile, tool schemas
  `628f0f32…`, first-request tool definitions `d8566a1c…`, packaged text
  `0b9d91cf…`, price table `f07736e1…`, merged system-text layout under
  `LITELLM_LOCAL_MODEL_COST_MAP=True`.

Uncommitted changes: `agent/providers/litellm_provider.py`,
`agent/service.py`, `cli.py`, `synthesis/diagnostics.py` (suite version),
`traversal/{__init__,traverser}.py`, `tests/workbench/test_gemini_provider.py`;
new `benchmarks/diagnostic/r04-stage-c-v1.json`, `evaluation/judgment.py`,
`tools/r04_judgment.py`, `tests/workbench/test_r04_judgment.py`.

## 6. Frozen manifest and resources

`runs/experiments/r04-stage-c-20261028/` (ignored), regenerated by
`python tools/r04_judgment.py freeze --output-dir <dir>`, never hand-edited:

| Artifact | SHA-256 |
| --- | --- |
| `manifest.stage-c.json` | `c1f68caede79a65196a238a24ad7567b8c108261da52a0f32694e6d2dfed31c3` |
| `plan.json` | `3b779b6d1a8b0d49fb2b9cc469265e28664db45bd298e31faee724365573c91b` |
| `source_manifest.json` (HEAD `0d7c37b` + 11 dirty paths, diff `e56789a2…`) | `c0d22a8c253cd836730d978606e62ba8678748043bf909d4d5824d0ea13f0d8c` |
| `inputs/stage-c.payload.json` | `0d4b669641e7c48d20d86c180ae78afe463c323ac36422a2da81f310f84b0654` |
| `inputs/stage-c.instructions.md` | `216ef02e6022801b7cef6c4cc19ed54ee80c84ecc5017751d4a18a29e9048baa` |
| `inputs/gemini-r04.provider-config.json` (`{"max_tokens": 32768}`) | `027bbb0a9e0d8ac63339623ff801caecd5de86d0d5f381feff0775ab5c13b01b` |
| `inputs/price-table.json` | `f07736e17fe8a06a8b4e9a77d0d43577a071d456066aa0d993d161bc1950f521` |

First request at x: node prompt `e5393321…` (2,180 characters). The scripted
criterion session ends near 164k characters (R02 Stage B: 138k).

**Resources.** Cost cap US$2.50 + one response of headroom (the 1,048,576-token
context limit at US$0.75/M plus 32,768 output tokens at US$3.75/M =
US$0.909312) = **US$3.409312 worst case**. Paid wall time 1,800 s + 100 s.
Requested envelope: **US$3.50 and 35 minutes**, this trial only. R03's scored
x session cost about US$0.98 by the upper-bound table (about US$0.32 at its
reported cache share); Stage C is somewhat larger. No forecast is certified.

**Rehearsal** (exact frozen argv, real CLI and LiteLLM, only HTTP faked; not
model results):

| Scenario | Outcome |
| --- | --- |
| nominal | planned stop after x; x committed, 19/19; `max_output_tokens` 32,768, `thinkingLevel` medium, temperature 1.0 on the wire; system text merged; reasoning history `auto` → `drop` |
| cut-off reply at request 2 | recovered (after §4.4); 5 priced requests; x 19/19 |
| client timeout at request 3 | lost response, unknown cost, run stopped |
| 900k-token prompts | stopped by the cost cap at US$2.715 ≤ cap + headroom |

## 7. Independent review

A read-only Claude Opus 5.5 (medium thinking) reviewed the panel, scorer, harness
changes and frozen manifest. It returned on 2026-10-28 with **"launch-ready with
mitigations"**: no blocker, five should-fix findings and three notes. The full
record and the recommended response are in
`runs/experiments/r04-stage-c-20261028/review.md`.

It confirmed:

- the answer key, ties, builder, hashes, isolation, wire shape and planned stop;
- the cost and wall-time limits.

The findings:

- **Fairness of the task block.** The k/g/kʰ correspondence is never stated, and the packaged instructions contradict the criterion. Both need a sentence in the block.
- **Readings of the scorer.** A no-commit run and a uniform reading are mislabelled, and the navigation count misses polarize.

The fixes change frozen files, so this directory cannot launch as frozen. A v2
re-freeze is pending, and the owner paused before any of it was applied.

## 8. Pre-registered reading and what each outcome selects

The full rules are in the pre-registration (`preregistration.md` in the frozen
directory) and in code. Headline: model-committed correct of 19.
- **Value label:** *witness-rule level* if at most 2 of the 6 items the R02
  rule gets wrong are right; *criterion-sensitive on this panel* if ≥ 17/19,
  ≥ 5/6 of those items, each other shallow rule's error set at most one short,
  and ≥ 4/5 pairs; *baseline-level* if ≤ 15/19 or ≤ 1/5 pairs; else *mixed*.
- **Uncertainty label:** *warranted* if ≥ 3/4 ties are marked and at most one
  decided item is hedged; *none* if no tie is marked; else *partial*.
- **Attribution first:** each wrong or missing decision is classed as invalid
  submission, tool rejection, truncation, navigation (outgroup forms never
  read), deference to the tool note, resource stop, or a valid but poor
  decision.

| Outcome | Supports | Could reverse it |
| --- | --- | --- |
| Criterion-sensitive | No interface redesign for Gemini; the open uncertainty is validity beyond synthetic stated-criterion panels | A second trial disagreeing; evidence that the block over-cues |
| Failures mainly navigation | The dossier/evidence-presentation comparison becomes R04's question | Rationales showing the forms were known |
| Forms read, note or label followed | A versioned correction of the presence-only tool note, tested as its own arm | The same errors with the note removed |
| Baseline-level with forms read | Model capability on this task: the critic direction (R07) or deferral | Better results with another stated criterion layout |
| No commit through rejections | Protocol/interface study | — |
| Resource or provider stop | Resource outcome only | — |

## 9. Limits

- One trial at temperature 1.0: feasibility, not reliability or a ranking.
- Synthetic development material written with known answers. The criterion is
  stated, so a ceiling result shows applying a stated rule to evidence the
  survey does not pre-label, not discovery or real-language competence.
- The confidence convention is self-reported; a marked tie is a reporting
  behaviour, not calibration (R03 §12a).
- The root polytomy is a design simplification; nested outgroups produce many
  more ties under parsimony.
- No real-language outcome: no validated real targets exist (R02 §6).

## 10. Commands

```sh
PY=/opt/anaconda3/envs/llm_reconstruction/bin/python
PYTHONDONTWRITEBYTECODE=1 $PY -m pytest -q -p no:cacheprovider tests/workbench/test_r04_judgment.py tests/workbench/test_gemini_provider.py
PYTHONDONTWRITEBYTECODE=1 $PY -m pytest -q -p no:cacheprovider -k 'not local_run_artifacts'   # 850 passed, 41 deselected
PYTHONDONTWRITEBYTECODE=1 $PY tools/r04_judgment.py controls     # §4.2
PYTHONDONTWRITEBYTECODE=1 $PY tools/r04_judgment.py measure
PYTHONDONTWRITEBYTECODE=1 $PY tools/r04_judgment.py freeze --output-dir runs/experiments/<new dir>
runs/experiments/r04-offline-checks-20261028/rehearsal/run_scenarios.sh nominal gemini-truncated gemini-timeout gemini-costcap
# launch (after the owner's approval and preflight), from the frozen directory:
LITELLM_LOCAL_MODEL_COST_MAP=True PYTHONDONTWRITEBYTECODE=1 $PY /Users/acraev/Work/cognate-reconstruction/tools/experiment_batch.py run --plan plan.json
```

The portable suite count: a clean HEAD collects 826 portable tests; with the
owner's 4 local-only audit tests and the 20 new tests that is 850. The
handoff's earlier 871 matches a run without the `local_run_artifacts` filter.
