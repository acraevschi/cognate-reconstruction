# R04 — Focused study: Gemini judgment where the outgroup-witness rule is not the answer

2026-10-30, branch `r01-contract-repairs`. Environment `llm_reconstruction`
(Python 3.11.0, LiteLLM 1.81.16, httpx 0.28.1, Pydantic 2.13.4). **Live status:
complete — both Gemini 3.8 Flash (R04 v2) and local dense `qwen3.8-27b-splash`
(R04b, 32k output cap) scored 19/19 primary, 5/5 matched pairs, and 4/4 ties
marked at 0.5 (`criterion-sensitive on this panel` / `warranted uncertainty`).**

## 0. Status at a glance

| Item | Status |
| --- | --- |
| Upstream recommendation (R03 §13 and its amendments) | Verified against the R03 report, results and code; adopted |
| Interface redesign (dossier, selection surface, reduced IDs) | **Deferred** with reasons (§2); not built, and not needed after both Gemini and local Qwen3.8 27B scored 19/19 (§9) |
| Stage C panel `r04-stage-c-v1` and scorer `r04-judgment-v1` | Built and updated with review mitigations; key re-derived from observed forms in a test |
| Frozen deployable baselines | R02 rule 13/19; best shallow rule 15/19; stated criterion 19/19 (ceiling by construction) |
| `--stop-after-node` (score only x) | Built and tested through `cli infer`, the launcher and the ledger; exercised live |
| Defect found by rehearsal: a Gemini reply cut off at the cap crashed the node | Reproduced, repaired, red→green tests; approved by the owner (2026-10-28) |
| Frozen launch candidate | `runs/experiments/r04-stage-c-20261029-v2/` (`20261028` superseded, never launched) |
| Independent read-only review | v1 review returned launch-ready with 5 mitigations; v2 review (`review.md`) returned **launch-ready** (§7) |
| Live Gemini trial (`C-gemini-r04`) | **Complete (2026-10-30)**: **19/19** decided, **5/5** pairs, **6/6** on R02 rule's errors, **4/4** ties marked at 0.5, **0** false confident claims, **19/19** concepts' outgroup forms seen; 10 requests (1 rejected), US$0.7603 upper bound (≈US$0.3424 cached), 283.9 s (§9) |
| Live tier-2 local trial (`C-local-qwen38-27b-r04`, R04b) | **Complete (2026-10-30)**: `qwen3.8-27b-splash` (32k cap) scored **19/19** decided, **5/5** pairs, **6/6** on R02 rule's errors, **4/4** ties marked at 0.5, **0** false confident claims, **19/19** concepts' outgroup forms seen; 9 requests (**0 rejected**), peak output 23,668 tokens, peak input 80,200 tokens, 1,577.5 s (§9.4) |
| Live tier-3 local trial (`C-local-qwen36-35b-r04`, R04c) | **Complete (2026-10-30)**: MoE `qwen3.6-35b-a3b-splash` (35B total / 3B active, 32k cap) ended **`no commit`** (`ProtocolStallError` after 3×32,768 thinking-only responses; never called `search_forms`/`get_alignments`/`polarize`, `0` outgroup forms seen [`1/19` vacuous on outgroup-less `y08`]; previewed only 13 of 57 local sets [1 per reflex pair], which assembled only 10/19 concepts and would have scored **4/19**; 666.0 s, §9.5) |
| Tests | Stage C 19, Gemini provider +3; portable suite 852 passed, 41 deselected |

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

**Criterion block** (appended to the packaged text; instructions `0a5d680e…`).
It states unweighted parsimony over the whole tree, including the branches to
the outgroups. Even before higher nodes are reconstructed, the model may
recognize from the outgroups' forms when an outgroup preserves a regularly
corresponding reflex in the same cognate unit and position (even if shifted in
phonetic quality) and treat that as attesting the presence of the segment slot
rather than as an extra branch change—without the block naming any specific
reflex tokens (`g`, `k`, `kʰ`). A form of another cognate unit is no evidence
about this unit. A node with the unit but without the material is one
observation of absence; a node with no form in that unit is no observation.
Where this multi-outgroup weighing and any general instruction above or a note
in a tool result disagree, this criterion governs. Ties are unresolved: the
deciding claim gets confidence ≤ 0.5 and either value is accepted; every other
decision gets a confidence above 0.5. The block names no item, unit, reflex
token or answer.

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
- **Navigation:** calls by tool, rejections, and which outgroup forms or unit
  states appeared in a non-survey tool result (`search_forms`,
  `get_alignments`, or `polarize`), per concept. The survey shows presence
  only.
- **Labels** frozen in code and in the pre-registration (§8), gating on a
  non-fallback model commitment (`no commit`) and a uniform all-retain or
  all-absent output (`uniform (regularity) reading`) before checking rule labels.

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

All R04 files and review mitigations are committed on `r01-contract-repairs`
(your six local-only failure-audit paths remain untracked).

## 6. Frozen manifest and resources

`runs/experiments/r04-stage-c-20261029-v2/` (ignored; supersedes
`runs/experiments/r04-stage-c-20261028/`, which was never launched), regenerated
by `python tools/r04_judgment.py freeze --output-dir <dir>`, never hand-edited:

| Artifact | SHA-256 |
| --- | --- |
| `manifest.stage-c.json` | `ee973d3742dc62dcdd21b78d5797d522f1ee50b5f52637c1a7b173f448e555fc` |
| `plan.json` | `63182413a72dd16e9483d2ec0f5f93d69986ad4178e06736312cbdda99212566` |
| `source_manifest.json` (clean HEAD `dee06a5`, `dirty_paths: []`) | `73b7d77621b8ccb9cf63d5fdc10cbfafe001cc819f3b9637bef8fdd6b970ad0f` |
| `inputs/stage-c.payload.json` | `0d4b669641e7c48d20d86c180ae78afe463c323ac36422a2da81f310f84b0654` |
| `inputs/stage-c.instructions.md` | `0a5d680eabc833d4c71853e2e2e1656e29dbfa3b775e831af1665d9d9f423959` |
| `inputs/gemini-r04.provider-config.json` (`{"max_tokens": 32768}`) | `027bbb0a9e0d8ac63339623ff801caecd5de86d0d5f381feff0775ab5c13b01b` |
| `inputs/price-table.json` | `f07736e17fe8a06a8b4e9a77d0d43577a071d456066aa0d993d161bc1950f521` |

First request at x: node prompt `e5393321…` (2,180 characters). The scripted
criterion session ends near 165k characters (R02 Stage B: 138k).

**Resources.** Cost cap US$2.50 + one response of headroom (the 1,048,576-token
context limit at US$0.75/M plus 32,768 output tokens at US$3.75/M =
US$0.909312) = **US$3.409312 worst case** (plus any retried 5xx/APIConnectionError
attempt of unknown billing under `--max-retries 3`, ~US$0.10–0.30 each in
practice). Paid wall time 1,800 s + 100 s. Approved envelope: **US$3.50 and 35
minutes**, this trial only. R03's scored x session cost about US$0.98 by the
upper-bound table (about US$0.32 at its reported cache share); Stage C is
somewhat larger. No forecast is certified.

**Rehearsal** (exact frozen argv, real CLI and LiteLLM, only HTTP faked; not
model results):

| Scenario | Outcome |
| --- | --- |
| nominal | planned stop after x; x committed, 19/19; `max_output_tokens` 32,768, `thinkingLevel` medium, temperature 1.0 on the wire; system text merged; reasoning history `auto` → `drop` |
| cut-off reply at request 2 | recovered (after §4.4); 5 priced requests; x 19/19 |
| cut-off reply at request 1 (first turn) | recovered; 2 consecutive `user` contents with mode `ANY`, no empty part; 5 priced requests; x 19/19 |
| client timeout at request 3 | lost response, unknown cost, run stopped; labelled `no commit` |
| 900k-token prompts | stopped by the cost cap at US$2.715 ≤ cap + headroom; labelled `no commit` |

## 7. Independent review and v2 mitigations

A read-only Claude Opus 5.5 (medium thinking) reviewed the v1 panel, scorer,
harness changes and frozen manifest (`runs/experiments/r04-stage-c-20261028/review.md`).
It returned on 2026-10-28 with **"launch-ready with mitigations"**: no blocker,
five should-fix findings and three notes.

All five findings and Notes 6–7 are resolved in the v2 freeze:
1. **Outgroup reflex recognition without a cheat-sheet.** The task block now
   states that the model may recognize regularly corresponding outgroup reflexes
   in the same cognate unit and position from the tip forms (without naming `g`,
   `k` or `kʰ`) and treat them as attesting presence without an extra branch
   change; `independent_evidence` is updated to match.
2. **Precedence over packaged instructions.** The precedence clause in the task
   block now covers `"any general instruction above or a note in a tool result"`,
   and `"cites packaged instruction"` is added to pre-registration §5 attribution.
3. **No-commit runs.** Both `labels.value` and `labels.uncertainty` now return
   `"no commit"` when the scored node has no non-fallback model commitment.
4. **Uniform readings.** `primary.uniform_reading` in `("retain", "absent")` is
   checked before rule labels and labelled `"uniform (regularity) reading"`,
   separating daughter-only union (`10/19`) and intersection (`9/19`) from
   `"witness-rule level"`.
5. **Navigation and `polarize`.** `_form_sightings` now credits `polarize`
   `observations[].example_concept_ids` and single-concept `polarize` node
   reports (including `columns_covered: 0` on replacement-unit concepts).
6. **Retries and first-turn truncation (Notes 6–7).** `--max-retries 3` is kept
   for R03 parity with the unknown-billing retry caveat stated in pre-registration
   §4, and `gemini-truncated-first` is rehearsed and tested.

An independent read-only review of the `7e860f9..dee06a5` diff and the v2 freeze
(`runs/experiments/r04-stage-c-20261029-v2/review.md`, subagent
`5fc6c236-cc25-4c90-8dbb-4b5a52685eb1`) verified all 5 findings and Notes 6–7,
all frozen hashes, clean `HEAD` `dee06a5`, and zero evidence or secret leaks,
returning **`launch-ready`** before any live request was made.

## 8. Pre-registered reading and what each outcome selects

The full rules are in the pre-registration (`preregistration.md` in the frozen
directory) and in code. Headline: model-committed correct of 19.
- **Value label:** *no commit* if the scored node has no non-fallback model
  commitment; *uniform (regularity) reading* if every primary opportunity has
  the same `retain` or `absent` reading; *witness-rule level* if at most 2 of
  the 6 items the R02 rule gets wrong are right; *criterion-sensitive on this
  panel* if ≥ 17/19, ≥ 5/6 of those items, each other shallow rule's error set
  at most one short, and ≥ 4/5 pairs; *baseline-level* if ≤ 15/19 or ≤ 1/5
  pairs; else *mixed*.
- **Uncertainty label:** *no commit* if no non-fallback model commitment;
  *warranted* if ≥ 3/4 ties are marked and at most one decided item is hedged;
  *none* if no tie is marked; else *partial*.
- **Attribution first:** each wrong or missing decision is classed as invalid
  submission, tool rejection, truncation, navigation (outgroup forms never
  read), deference to the tool note, cites packaged instruction, uniform
  reading, resource stop, or a valid but poor decision.

| Outcome | Supports | Could reverse it |
| --- | --- | --- |
| Criterion-sensitive | No interface redesign for Gemini; the open uncertainty is validity beyond synthetic stated-criterion panels | A second trial disagreeing; evidence that the block over-cues |
| Failures mainly navigation | The dossier/evidence-presentation comparison becomes R04's question | Rationales showing the forms were known |
| Forms read, note, packaged instruction or label followed | A versioned correction of the presence-only instruction/note, tested as its own arm | The same errors with the note removed |
| Uniform (regularity) or baseline-level with forms read | Model capability on this task: the critic direction (R07) or deferral | Better results with another stated criterion layout |
| No commit through rejections | Protocol/interface study | — |
| Resource or provider stop | Resource outcome only | — |

## 9. Live trial result (`C-gemini-r04`, 2026-10-30)

Launched once, serially, from `runs/experiments/r04-stage-c-20261029-v2/` at
`2026-10-30T13:19:18Z` (`finished` `2026-10-30T13:24:04Z`, exit code `0`).
`grep -rlF "$GEMINI_API_KEY"` over the batch directory returned nothing.

### 9.1 Headline, shallow-rule error sets, pairs, uncertainty and navigation

| Metric | Live `gemini-r04` | Stated criterion (ceiling) | R02 outgroup-witness | Best shallow rule (unanimity) | Union (all retain) |
| --- | --- | --- | --- | --- | --- |
| Decided correct / 19 | **19 / 19** (`1.00`) | 19 / 19 | 13 / 19 | 15 / 19 | 10 / 19 |
| R02 witness-rule errors / 6 | **6 / 6** | 6 / 6 | 0 / 6 | 6 / 6 | 0 / 6 |
| Unanimity errors / 4 | **4 / 4** | 4 / 4 | 4 / 4 | 0 / 4 | 4 / 4 |
| Majority-of-three errors / 5 | **5 / 5** | 5 / 5 | 5 / 5 | 5 / 5 | 5 / 5 |
| Spelling-majority errors / 5 | **5 / 5** | 5 / 5 | 4 / 5 | 5 / 5 | 3 / 5 |
| Matched pairs / 5 | **5 / 5** (`Pa`–`Pe`) | 5 / 5 | 1 / 5 | 3 / 5 | 0 / 5 |
| By basis (`outgroup_majority` / `wrong_scope` / `no_observation`) | **11/11, 5/5, 3/3** | 11/11, 5/5, 3/3 | 6/11, 4/5, 3/3 | 7/11, 5/5, 3/3 | 6/11, 3/5, 1/3 |
| Ties marked (`confidence ≤ 0.5`) / 4 | **4 / 4** (`T1`–`T4` all at `0.5`) | 4 / 4 | 0 / 4 | 0 / 4 | 0 / 4 |
| Decided items hedged (`≤ 0.5`) | **0** (all 19 decided at `0.9`) | 0 | 0 | 0 | 0 |
| False confident claims | **0** | 0 | 10 | 8 | 13 |
| Decided by explicit claim | **19 / 19** | 19 / 19 | 19 / 19 | 19 / 19 | 19 / 19 |
| Raw `task02-v1` top exact at `x` | **19 / 19** (`1.00`) | 19 / 19 | 13 / 19 | 15 / 19 | 10 / 19 |
| Value label | **`criterion-sensitive on this panel`** | `criterion-sensitive on this panel` | `witness-rule level` | `baseline-level` | `uniform (regularity) reading` |
| Uncertainty label | **`warranted uncertainty`** | `warranted uncertainty` | `no uncertainty marking` | `no uncertainty marking` | `no uncertainty marking` |

- **Attribution of wrong or missing decisions (checked before reading labels):**
  **0 wrong and 0 missing decisions.** Every planned primary opportunity
  (`19/19`) and every tied item (`4/4`) was decided by an explicit local claim
  (`csu-*`) with a unit-scoped rationale citing the exact outgroup attestations
  and absences.
- **How the model inferred the outgroup correspondences without a cheat-sheet:**
  Although `task_block` named no reflex tokens (`g`, `k`, `kʰ`), Gemini
  inspected the outgroups' forms and alignments, recognized `c`'s `g`, `d`'s
  `k`, and `f`'s `kʰ` as regular reflexes of the final velar slot (e.g. `K9` /
  `y04`: *"Outgroup c attests voiced velar reflex g in cs379, favoring retention
  of \*k"*; `T2` / `y03`: *"Outgroup evidence in cs311 is evenly split between
  attestation in f (t-a-kʰ) and absence in d (t-a), requiring 2 changes under
  either hypothesis; unresolved, confidence assigned 0.5"*), ignored
  replacement-unit (`w0`, `w1`) and suffix-piece (`s1` on `K8` / `y14`)
  look-alikes, and treated missing outgroup forms (`-`) as no observation.
- **Navigation and tool sequence (10 turns, 10 calls, 1 rejected):**
  1. `list_available_nodes({})` — identified `c`, `d`, `f` as `outgroup` leaves.
  2. `summarize_correspondences({"reading": "recurrence", "min_support": 1})`
  3. `summarize_correspondences({"reading": "local", "min_support": 1})`
  4. `search_forms({"node_ids": ["a", "b", "c", "d", "f"], "limit": 100})` —
     **rejected** (`unknown-node`, because `scope` defaults to
     `active_children`).
  5. `search_forms({"scope": "available_tree", "node_ids": ["a", "b", "c", "d", "f"], "limit": 100})` —
     repaired on the next turn; read all observed forms across all 5 varieties.
  6. `polarize({"child_ids": ["a", "b"], "position": "final", "correspondence": ["k", null]})`
  7. `get_alignments({"concept_ids": ["y01", ..., "y19"], "node_ids": ["a", "b", "c", "d", "f"], "detail": "full"})`
  8. `summarize_correspondences({"reading": "local", "limit": 60, "offset": 0, "min_support": 1})` —
     fetched all 57 local `csu-*` sets.
  9. `test_proto_assembly({"residue_policy": "drop", "choices": <57 choices>, "detail": "summary"})` —
     `commit_ready: true` on the first preview (`hyp-eebd5a959a81840e28b8a8cd`).
  10. `commit_reconstruction` — committed `x`; traversal stopped cleanly via
      `PlannedStop` (`status: interrupted`, `failure_kind: planned_stop`, root
      `r` not attempted).

### 9.2 Resources and why the 32,768 output cap mattered

| Request | Tool called | Input tokens | Cached input | Output tokens | Reasoning tokens | Table cost (USD) |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `list_available_nodes` | 15,986 | 0 | 61 | 49 | 0.012218 |
| 2 | `summarize_correspondences` (recurrence) | 16,338 | 13,934 | 96 | 71 | 0.012614 |
| 3 | `summarize_correspondences` (local, p. 1) | 26,595 | 16,369 | 98 | 74 | 0.020314 |
| 4 | `search_forms` (rejected: default scope) | 40,080 | 26,624 | 78 | 38 | 0.030353 |
| 5 | `search_forms` (`available_tree`) | 40,211 | 38,026 | 73 | 25 | 0.030432 |
| 6 | `polarize` (`["k", null]`, final) | 58,917 | 40,245 | 1,899 | 1,863 | 0.051309 |
| 7 | `get_alignments` (all 19 concepts, full) | 64,949 | 58,920 | 269 | 110 | 0.049721 |
| 8 | `summarize_correspondences` (local, all 57) | 163,551 | 65,037 | 13,859 | 13,826 | 0.174635 |
| 9 | `test_proto_assembly` (57 choices) | 196,361 | 163,569 | **16,718** | 11,530 | 0.209963 |
| 10 | `commit_reconstruction` | 217,882 | 196,368 | 1,422 | 1,065 | 0.168744 |
| **Total** | **10 requests (0 retries, 0 unknown cost)** | **840,870** | **619,092 (73.6%)** | **34,573** | **28,651 (82.9%)** | **0.760301** |

- **Cost and wall time:** Upper-bound uncached table cost **US$0.7603** (versus
  the US$2.50 run cap and US$3.50 batch ceiling); using reported cached input
  tokens at US$0.075/M, estimated spend is **≈US$0.3424**. Wall time **283.9 s**
  (4m 44s, versus 1,800 s cap). AI Studio console balance check is due ≥ 24 h
  after `2026-10-30T13:24:04Z` (alongside R03's pending check).
- **Validation of the 32,768 output cap:** Request 9 (`test_proto_assembly` with
  57 explicit local choices after 11,530 thinking tokens) used **16,718 output
  tokens**—334 tokens above R03's 16,384 cap. Under a 16,384 cap, Request 9
  would have been truncated mid-tool-call. Raising `max_tokens` to 32,768 let
  the preview complete in one turn without truncation.

### 9.3 What this outcome selects next

Per the pre-registered table (§8), **`criterion-sensitive on this panel`** with
**`warranted uncertainty`** supports:
- **No interface redesign for Gemini 3.8 Flash (or dense local Qwen3.8 27B).**
  With the current tool surface, both models navigated multi-outgroup evidence
  across 19 concepts (`search_forms`, `polarize`, `get_alignments`), inferred
  the `g / k / kʰ` reflex correspondence from tip forms without a cheat-sheet,
  overrode the survey's presence-only witness label and general manual defaults
  as instructed, and scored 19/19, 5/5 pairs, and 4/4 marked ties.
- **What could reverse this:** Failure on a multi-node or real-language dataset
  where cognate units, tree topology or parsimony assumptions are not supplied
  as clean ground truth; or high variance across additional seeds.
- **Downstream briefs:** R05 stays **deferred** unless the owner selects a
  specific two-level propagation question (Stage C stopped after `x` by design,
  and both Gemini and local `qwen3.8-27b-splash` now provide clean 19/19,
  4-marked-tie intermediate beams at `x`). R06 and R07 are not selected by the
  pre-registered table.

### 9.4 Owner-requested tier-2 local follow-up: `qwen3.8-27b-splash` (`R04b`, 2026-10-30)

Following Gemini's 19/19 result, the owner loaded `qwen3.8-27b-splash` (27B
dense + speculative draft, 4-bit, 128,000 context window in LM Studio) to test
the next model tier down on the identical Stage C panel and instructions
(`runs/experiments/r04b-local-qwen38-27b-20261030/`, manifest `2ee72c13…`, plan
`76dfa331…`, source `73b7d776…`, provider config `7a5b9b19…`: `max_tokens:
32768`, Qwen thinking-mode sampler `temperature: 0.6, top_k: 20, top_p: 0.95,
min_p: 0.0, repeat_penalty: 1.0, presence_penalty: 0.0`, `--reasoning-history
drop`, `--stop-after-node x`).

- **Judgment (`r04-judgment-v1`):** **`19 / 19`** decided opportunities
  (`explicit_claim` on all 19), **`5 / 5`** matched pairs (`Pa`–`Pe`), **`6 /
  6`** on R02's `outgroup-witness` error set, **`4 / 4`** on `unanimous`, **`5 /
  5`** on `majority-of-three`, **`5 / 5`** on `spelling-majority`, **`4 / 4`**
  tied items (`T1`–`T4`) marked at confidence `0.5`, **`0`** false confident
  claims, and **`19 / 19`** concepts with every outgroup form seen. Labels:
  **`criterion-sensitive on this panel`** / **`warranted uncertainty`**.
- **Error attribution:** **0 wrong and 0 missing decisions, and 0 rejected tool
  calls** across 12 tool calls in 9 turns. Like Gemini, `qwen3.8-27b-splash`
  inferred from the tip forms that `c`'s `g`, `d`'s `k`, and `f`'s `kʰ` are the
  regular reflexes of the final velar slot (e.g. `K9` / `y04`: *"Same-unit
  outgroup c=pag (k-slot present, g reflex)"*), identified `f`'s `kʰ` in `K8`
  (`y14`) as belonging to suffix unit `cs338` rather than `cs312`, ignored
  replacement units (`w0`, `w1`), and graded its confidence by evidence strength
  (`0.85` for 3-of-3 outgroups, `0.70` for 1-of-1, `0.65` for 2-of-3, and `0.50`
  for all 4 ties).
- **Decisive validation of the 32,768 output cap for local models:**

| Request | Tool(s) called | Input tokens | Output tokens | Reasoning tokens |
| --- | --- | --- | --- | --- |
| 1 | `list_available_nodes`, `summarize_correspondences` (recurrence) | 17,285 | 83 | 22 |
| 2 | `list_concepts`, `summarize_correspondences` (local) | 26,058 | 247 | 173 |
| 3 | `search_forms` (`active_children`) | 27,230 | 83 | 40 |
| 4 | `search_forms` (`available_tree`, `c, d, f`) | 36,018 | 403 | 341 |
| 5 | `get_alignments` (`a, b`, 6 concepts, full) | 43,407 | 6,063 | 5,905 |
| 6 | `summarize_correspondences` (`local`, `min_support: 1`, `limit: 60`) | 49,907 | **16,748** | 16,451 |
| 7 | `polarize` (`["k", null]` final) + `polarize` (`[null, "h"]` initial) | 65,742 | **23,668** | 23,214 |
| 8 | `test_proto_assembly` (57 choices, `residue_policy: "drop"`) | 70,655 | 15,016 | 9,956 |
| 9 | `commit_reconstruction` (`hyp-10a376a53df5c842dc9289f6`) | 80,200 | 1,036 | 377 |
| **Total** | **9 requests, 12 tool calls (0 rejected)** | **416,502** | **63,347** | **56,479 (89.2%)** |

  In R03e and R03f, local models failed Stage B by hitting the 16,384 output cap
  while thinking. Here, **Requests 6 (`16,748` tokens) and 7 (`23,668` tokens)
  both exceeded 16,384 tokens** during chain-of-thought analysis of the 19
  concepts, and converged cleanly inside the 32,768 cap without a single
  truncation. Peak prompt size was `80,200` tokens (well inside the 128,000
  context window); wall time was `1,577.5 s` (26m 18s), at US$0.00 paid cost.

### 9.5 Owner-requested tier-3 local follow-up: MoE `qwen3.6-35b-a3b-splash` (`R04c`, 2026-10-30)

To test where model capability degrades along the tier ladder, the owner next
loaded the Mixture-of-Experts `qwen3.6-35b-a3b-splash` (`35B` total parameters,
`3B` active parameters, 128,000 context window in LM Studio) under the identical
Stage C panel, instructions, sampler, and `max_tokens: 32768` cap
(`runs/experiments/r04c-local-qwen36-35b-20261030/`, manifest `a471d7f3…`, plan
`59c24569…`, source `73b7d776…`, provider config `7a5b9b19…`,
`--reasoning-history drop`, `--stop-after-node x`).

- **Outcome:** **`no commit`** (`ProtocolStallError` after three `32,768`-token
  thinking-only responses on Requests 3, 5, and 8; `666.0 s` wall time, `8`
  requests, `6` tool calls, `1` rejected call, `277,395` input tokens, peak
  prompt `47,177` tokens, `115,379` output tokens of which `112,038` [`97.1%`]
  were reasoning tokens).
- **Double failure mode (truncation loop + shallow navigation/representation):**
  1. **Runaway thinking even at `32,768` tokens:** Unlike dense `qwen3.8-27b-splash`
     (which peaked at `23,668` tokens and converged), the `3B`-active MoE model
     hit the `32,768` output cap three times (`32,724`, `32,628`, and `32,768`
     reasoning tokens) without emitting a tool call—including on Request 8
     immediately *after* receiving `commit_ready: true` (`hyp-548d4474d15cd0a3bad6f32c`)
     from `test_proto_assembly`.
  2. **Failure to inspect outgroup forms or commit per-concept sets:** Across its
     8 turns, `qwen3.6-35b-a3b-splash` called only `list_concepts` (1),
     `summarize_correspondences` (3), and `test_proto_assembly` (2). It **never
     called `search_forms`, `get_alignments`, or `polarize`**
     (`outgroup_forms_seen: []` — **0 outgroup forms seen**;
     `concepts_with_every_outgroup_form_seen` is `1 / 19` only because `y08` has
     no outgroup forms in the panel, so the empty subset check is vacuously
     true). In its `test_proto_assembly` preview on Request 7
     (`hyp-548d4474d15cd0a3bad6f32c`), it committed **only 13 of the 57 local
     `csu-*` sets**—selecting one `csu-*` ID per distinct reflex pair (`a:a`,
     `e:e`, `i:i`, `o:o`, `u:u`, `k:Ø`, `Ø:h`, `m:m`, `n:n`, `t:t`, `l:l`,
     `p:p`, `s:s`) and mistaking each single local `csu-*` ID for a global rule
     over all occurrences of that reflex pair (for example, committing only `y01`'s
     `csu-a26f6177f60d0b20f8936d2b` with the rationale *"Nineteen correspondence
     sets show 'k' in child a and null in child b. Outgroups (c, d, f) regularly
     show velar stops (k, kʰ, g)"*), while setting `residue_policy: "drop"` on
     the other 44 local sets. Because 9 of the 19 concepts had *all* of their
     columns in those uncommitted local sets, the preview assembled non-empty
     forms for only `10 / 19` concepts (`unaccounted_column_rate: 0.567`), and
     even had it been committed on Request 8 instead of truncating, it would
     have scored only **`4 / 19` (`21.1%`)** (`retain: 2, absent: 5, other: 1,
     missing: 11`; `0 / 5` pairs; `0 / 4` ties marked).

| Tier | Model | Active params | Primary / 19 | Pairs / 5 | Witness-rule errors / 6 | Ties (`≤ 0.5`) / 4 | Outgroup forms seen | Rejected calls | Peak output tokens | Outcome label |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Tier 1 (Cloud) | `gemini-3.8-flash` | Frontier | **19 / 19** | **5 / 5** | **6 / 6** | **4 / 4** | **19 / 19** | 1 | 16,718 | `criterion-sensitive` / `warranted` |
| Tier 2 (Local Dense) | `qwen3.8-27b-splash` | 27B | **19 / 19** | **5 / 5** | **6 / 6** | **4 / 4** | **19 / 19** | **0** | 23,668 | `criterion-sensitive` / `warranted` |
| Tier 3 (Local MoE) | `qwen3.6-35b-a3b-splash` | 3B (of 35B) | **0 / 19** *(preview: 4/19)* | **0 / 5** | **0 / 6** | **0 / 4** | **0 forms** *(1/19 vacuous)* | 1 (+ 3×32k trunc) | **32,768 (×3)** | `no commit` (`ProtocolStallError`) |

## 10. Limits

- One trial at temperature 1.0: feasibility, not reliability or a ranking.
- Synthetic development material written with known answers. The criterion is
  stated, so a ceiling result shows applying a stated rule to evidence the
  survey does not pre-label, not discovery or real-language competence.
- The confidence convention is self-reported; a marked tie is a reporting
  behaviour, not calibration (R03 §12a).
- The root polytomy is a design simplification; nested outgroups produce many
  more ties under parsimony.
- No real-language outcome: no validated real targets exist (R02 §6).

## 11. Commands

```sh
PY=/opt/anaconda3/envs/llm_reconstruction/bin/python
PYTHONDONTWRITEBYTECODE=1 $PY -m pytest -q -p no:cacheprovider tests/workbench/test_r04_judgment.py tests/workbench/test_gemini_provider.py
PYTHONDONTWRITEBYTECODE=1 $PY -m pytest -q -p no:cacheprovider -k 'not local_run_artifacts'   # 852 passed, 41 deselected
PYTHONDONTWRITEBYTECODE=1 $PY tools/r04_judgment.py controls     # §4.2
PYTHONDONTWRITEBYTECODE=1 $PY tools/r04_judgment.py measure
PYTHONDONTWRITEBYTECODE=1 $PY tools/r04_judgment.py freeze --output-dir runs/experiments/r04-stage-c-20261029-v2
runs/experiments/r04-offline-checks-20261028/rehearsal/run_scenarios.sh nominal gemini-truncated gemini-truncated-first gemini-timeout gemini-costcap
# launch (after the owner's approval and preflight), from the frozen directory:
LITELLM_LOCAL_MODEL_COST_MAP=True PYTHONDONTWRITEBYTECODE=1 $PY /Users/acraev/Work/cognate-reconstruction/tools/experiment_batch.py run --plan plan.json
```

The portable suite count: a clean HEAD collects 826 portable tests; with the
owner's 4 local-only audit tests and the 22 new tests that is 852.
