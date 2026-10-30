# R02 — Diagnostic instruments and bounded model-comparison manifests

2026-10-25, branch `r01-contract-repairs`, starting HEAD `815a0b6`. Offline only:
no model requests, model-server discovery or loading, paid calls, dataset
downloads or dependency changes. Public documentation was read for model
identifiers and prices. Environment: `llm_reconstruction`, Python 3.11.0,
Pydantic 2.13.4, LiteLLM 1.81.16. The work is uncommitted.

## 0. Status at a glance

| Item | Status |
| --- | --- |
| Offline instruments (Stage A fixture/checker, Stage B panel/scorer/baselines, price table, Gemini thinking-level transport, ledger/launcher) | **Ready.** Tested with scripted providers and the real LiteLLM adapter on fake completion functions |
| Candidate manifests and launch plan | **Written** under `runs/experiments/r02-model-diagnostic-20261025/` (ignored); hashes in section 11 |
| Independent read-only review of the final manifest | **Pending (R03 gate).** R02 ran a read-only validity audit of the instruments (section 13); that is not the R03 manifest review |
| Launch authorization | **Not given by R02.** Models and the paid ceiling are owner decisions already recorded (section 8); R03 checks them and launches |

## 1. What R01 delivered, as verified here

R01's focused command gives **246 passed** at this branch (section 15). The
model-visible digests are unchanged and were recomputed by the freeze step:
instructions `0b9d91cf…`, default (stored-hypothesis) tool schemas `dd58d427…`,
node commit notes `1ddfc0fc…`, evidence contract `b1f459e7…`. Token-conditioned
claims commit through the native JSON path in both profiles: the Stage A operator
below commits a shared claim with `{"right":{"tokens":["i"]}}` through
`cli infer`, the real `LiteLLMProvider` with JSON-string arguments, the request
journal, JSONL, checkpoint and result readback. The journal and run summary feed
the new ledger (section 10). R01's open items owned by R02 are closed: the
whole-batch ledger exists and `inspect_run` now shows `effort_counts_known`,
`unrecorded_requests` and `usage_accounting_version`.

## 2. The question and the separation of A and B

**Question.** Can a stronger model use the repaired harness to (A) execute an
explicitly supplied, nonempty, unit-scoped and token-conditioned hypothesis, and
(B) propose evidence-sensitive linguistic decisions that simple copying or
uniform policies do not make? The comparison is one local baseline and one
stronger candidate, each conditional on this harness and its configuration.

| | Stage A — supplied-hypothesis usability | Stage B — evidence-sensitive judgment |
| --- | --- | --- |
| Definition | `benchmarks/diagnostic/r02-stage-a-v1.json` | `benchmarks/diagnostic/r02-stage-b-v1.json` |
| Tree / scored node | `(a,b)r;` / `r` | `((a,b)x,c)r;` / `x` (the root session runs but is not scored) |
| Who decides | The instruction text supplies every choice | The model proposes every choice |
| Model-visible instructions | Packaged text + the Stage A block, sha256 `543e3f32…` | Packaged text + a criterion block (no items or answers), `5b4c7aef…` |
| Scorer | `evaluation/usability.py`, `r02-usability-v1` | `evaluation/decisions.py`, `r02-decisions-v1`, beside task02-v1 |
| Evidence role | Protocol only; references are executions of supplied claims | Conditional judgment under stated identification assumptions |

Isolation is by construction and tested: A and B share no concepts (q01–q06
versus w01–w16), no unit IDs (u01–u07 versus c04–c72), no decision type
(conditioned p:f and a suffix drop versus witness-gap retention) and no
instruction text; each stage appends its own block to the packaged text. A
scripted B run with a sentinel planted in its hidden target binding sends
byte-identical requests to the run without it, and no request contains the Stage A block, `u07`, or any opportunity or design label
(`test_scorer_only_targets_never_reach_a_request`). The B block contains no
concept, unit or opportunity identifier.

## 3. Stage A — supplied-hypothesis usability

Two children, six concepts, every word a core unit and four words a shared
suffix unit `u07`. Child b shows `f` before `i` where a shows `p`. The supplied
hypothesis, rendered verbatim into the instruction block:

- a shared claim over the `[p, f]` recurrence pattern (both members) → `p`,
  confidence 0.8, conditioning `{"right":{"tokens":["i"]}}`;
- a shared claim over the `[+, +]` pattern → null (no dangling boundary);
- local choices for the `cog:u07` sets `[m, m]` and `[a, a]` → null — the
  **source-unit decision**: the `[m, m]` recurrence pattern also holds core
  `u05`/`u06` members, so nulling the pattern instead deletes core `m`;
- residue `retain_from_witness`, witness `b` — so the condition is observable:
  without an applied `right:i` claim the output keeps b's `f`;
- then exactly one revision (confidence 0.8 → 0.9), a new preview, and a commit
  of the revised handle (full-payload: the revised inventory).

Reference output at `r`: `p i`, `p i n`, `p a`, `p u n`, `m a n`, `m i`.

**Checker.** Claims are compared after expansion to local sets, with conditions
canonicalized (an all-default `{}` condition equals none), so equivalent shared
and local spellings are one hypothesis; the shape is reported separately and
rationale prose is never compared. Any preview of the revised claims after the
original counts, so reworded prose or a not-yet-commit-ready preview fixed in
a new one is the documented path, not a deviation; a commit may use any such
preview's handle or (as both profiles allow) the revised full inventory. Criteria:
model commit (not fallback); committed claims equal the supplied revised set
exactly (extra/missing claims listed); residue as supplied; original previewed;
revision previewed after it; commit of the revised preview's handle; output
equals the reference; output pieces carry the expected units; every output piece
has sources and column IDs; JSONL, checkpoint and result agree.

**Gate for Stage B** (`stage_gate.usable`): commit, exact supplied claims and
residue, reference output and units, intact provenance and readback. The
revision protocol is reported (`success` requires it) but does not gate B,
because B never needs a specified revision; it needs a correct
preview → commit of an executable unit-scoped inventory. Outcomes:
`success`, `usable_revision_protocol_deviation`,
`committed_supplied_hypothesis_output_defect`, `committed_other_hypothesis`,
`no_commit`, `fallback`, `no_session`.

**Proof before any live model.** The scripted operator succeeds in both
profiles through `cli infer` with the Stage A instruction file, the real
adapter, a price table and a cost cap; the ledger agrees with the run summary.
Scripted deviations are separated correctly: skipped original preview →
`usable_revision_protocol_deviation`; nulling the pooled `[m, m]` pattern →
`committed_other_hypothesis` with `m a n` → `a n`; condition `right:a` →
`f i` survives; identity commit → `committed_other_hypothesis`. The audit's
false-fail cases (`{}` conditioning; reworded then fixed revision; full
inventory commit in the stored profile) are now `success`.

## 4. Stage B — evidence-sensitive retention in the correct unit

### Decision type, identification and the criterion block

One primary decision type: **at node `x`, keep or drop material present in
exactly one active child, inside one supplied cognate unit.** The outgroup `c`
is reachable only through the ordinary tools (the default local survey's
outgroup profiles, `polarize`, `search_forms(scope=available_tree)`).
Assumptions: the supplied tree and cognate units are correct; unweighted
parsimony (gain and loss of a segment or piece cost one event each on a
branch); `c`'s `g` corresponds to `k`. Then: `c` shows the material in the same
unit → present at `x` (one loss beats two gains); `c`'s same-unit form lacks it
→ absent (one gain beats two losses); no `c` form → tie, **unresolved**. Values
at `x` come from the daughter that has them. Without parsimony any mixture of
gains and losses fits; proto-symbol relabelings are always equivalent.

The packaged instructions say that gaps alone do not establish innovation, so
a model following them would be scored against an assumption it never saw (an
audit finding, section 13). Stage B therefore appends a **criterion block**
(`task_block` in the definition) that states the parsimony criterion, asks the
model to inspect evidence outside the active children, treats a gap as one
observation to combine with the tree, accepts either value on a tie and asks
for each etymon and unit to be decided on its own evidence. It names no item,
unit or answer. This makes the arm a stated-criterion task: the instructions
hash changes (`5b4c7aef…`), the packaged text is otherwise unchanged.

### The panel (16 etyma; design labels are operator-only; concept and cognate IDs are shuffled)

History used to write the forms: r→x `a>o`; x→a `h>Ø/#_`, loss of the
inherited suffix, then `k` added after every word-final vowel; x→b a suffix
`-ko` added to two words, before b's loss of word-final `k`; r→c `p>b`,
`k>g/_#`. So **a ends every core in `k` (retained or added) and b never does**:
in the daughters the two kinds of a-only `k` look identical.

| Design | a | b | c | x | Opportunities (expected) |
| --- | --- | --- | --- | --- | --- |
| R1–R4 | `p o k`, `m i k`, `n u k`, `t e k` | k lost | `b a g`, `m i g`, `n u g`, `t e g` | with k | final k: retain (4) |
| A1–A4 | `t o k`, `p i k`, `m u k`, `n e k` (k added) | `t o`, `p i`, `m u`, `n e` | `t a`, `b i`, `m u`, `n e` | no k | final k: absent (4) |
| C1, C2 | `u k`, `i k` (h lost) | `h u`, `h i` | `h u g`, `h i g` | `h u k`, `h i k` | onset h, coda k: retain (4) — no daughter has the word |
| S1 | `l i k` | `l i k + k o` | `l i g` | `l i k` | suffix: absent |
| S2 | `s e k` | `s e + k o` | `s e` | `s e` | core k: absent; suffix: absent |
| S3 | `l e k` | `l e + k o` | `l e + k a` | `l e + k o` | core k: absent; suffix: retain |
| S4 | `s o k` | `s o k + k o` | `s a k + k a` | `s o k + k o` | suffix: retain |
| U1 | `k u k` | `k u` | — | both accepted | unresolved: b's k-loss and a's k-addition tie |
| U2 | `k e n` | `k e` | — | both accepted | unresolved: no regular account either way |

**18 primary opportunities** (10 retain, 8 absent), 2 unresolved, and **6
matched pairs** that are alike in every daughter-visible feature (piece counts,
vowel before the final `k`, whether a's stem-final `k` is shared with b) and
differ only in `c`: R1/A1 (o), R2/A2 (i), R3/A3 (u), R4/A4 (e), S1/S4 (suffix
after a shared stem `k`), S2/S3 (suffix after an a-only `k`). Onsets and vowels
are balanced across retain and absent items. Recurrence is meaningful and not
decisive: the a-only final `k` is one recurrence pattern holding four
retentions and six innovations. The suffix items carry the unit hazard: b's
suffix `k` sits beside the position of a's core-final `k`, and retaining it in
the wrong unit is visible in the analysis.

### Primary outcome and denominators

**Primary (headline): `model_committed_correct` among the 18 planned primary
opportunities**, read from the committed top candidate's analysis; fallback
output never counts as a model decision. Each reading is `retain`, `absent`,
`other` (unit piece present with neither edge, e.g. `g` copied from `c`),
`unit_missing` (an edge opportunity whose unit piece is gone or relabelled),
`unscorable` (no analysis, or unknown pieces that could hide the unit) or
`missing` (no output). Only `retain`/`absent` can be correct; everything else
stays in the denominator, so deleting output or analysis cannot raise the rate.

**Secondary, all reported:** matched pairs with both members correct (of 6);
the presence (10) and absence (8) subtotals (`by_basis`); reading distribution
and uniform-reading flag; explicit claim versus residue default per
opportunity (`decided_by`, from assembly reports); unresolved readings with the
deciding claim's confidence and rationale; and the ordinary task02-v1 report —
raw exact against all alternatives (16 concepts), NED over available outputs,
target validity (`validated_target`, conditional note), outside-selection hits
(C1/C2 only), coverage, fallback and missing outputs. Response to
counterevidence is read from the matched pairs; an unresolved item never
requires a particular answer. Root (`r`) outputs are descriptive only.

### Baselines and controls (all through the scorer; none is a model result)

| Policy | Primary /18 | Pairs /6 | Readings | Raw exact /16 | Role |
| --- | --- | --- | --- | --- | --- |
| Identity commit (`rules=[]`; also any empty inventory) | 10 | 0 | 4 retain, 14 absent | 8 | existing identity output |
| Fixed daughter a | 8 | 0 | 12 retain, 6 absent | — | diagnostic |
| Fixed daughter b | 10 | 0 | 6 retain, 12 absent | — | diagnostic |
| Fixed outgroup c | 11 | 2 | 7 `other` (g for k) | — | diagnostic; c is not an active child |
| Union (keep all one-sided material) | 10 | 0 | all retain | 9 | uniform policy |
| Intersection (drop it all) | 8 | 0 | all absent | 8 | uniform policy |
| Audit's no-outgroup cue rules | ≤12 | ≤3 | — | — | tested to stay at chance on the pairs |
| **Outgroup-witness rule** | **18** | **6** | 10 retain, 8 absent | 16 | **deployable evidence-only baseline** |
| Gold-assisted oracle | 18 | 6 | — | 16 | scorer control only |

Every daughter is reported and none is deployable as "best", because choosing
it would read gold. The deployable rule is frozen from observed data only:
keep one-sided material when the survey reports an outgroup witness in that
exact column, otherwise null, a missing `c` form counting as no witness. **It
is the identification rule itself and therefore the ceiling.** The default
local survey already labels every one-sided column with a `c` witness or none,
so Stage B is a **necessary-condition test**: does the model go from pooled
recurrence patterns to per-etymon, per-unit decisions that agree with the
stated criterion, and execute them in the right unit, including b-only
material and boundaries? A perfect score cannot be told apart from rule
following, and the task is conditional inference, not autonomous discovery.

Normal-evaluator controls (`test_decision_scorer_controls_through_the_normal_evaluator`):
perfect 18/18 and raw 16/16; analysis removed 0/18, all unscorable, raw
unchanged; nine concepts missing → `missing` readings, planned stays 18;
suffix moved before the core → 18/18 while raw exact drops to 14; an extra
wrong-unit suffix → 17; `g` for `k` → 17 with one `other`; a relabelled unit →
17 with one `unit_missing`. A fallback node's correct outputs do not count as
model decisions.

### What was not built

No untuned application split: the harness can hide observations only by
removing them from the payload, and the visible `concept_holdout` partition is
not hidden. No second general benchmark framework: the explicit definitions
are two JSON files read by about 70 lines in `synthesis/diagnostics.py`;
task02-v1 and its generator, fixtures and readings are untouched.

## 5. Exposure

The panel and baselines were designed in this session, with the answers known
to the designer, and run only with scripted providers. No model has seen
either stage. The model-visible instructions for B are the unchanged packaged
text: nothing was tuned toward the panel. The scripted controls and the
deployable rule were frozen before any live run. All of Stage A and B is
**development material** for any later study (R04 may reuse it as such).

## 6. Real-language outcome

None is used; Stage B is synthetic by a recorded pre-run rule. The read-only
audit checked four actual bindings in existing local material
(`benchmarks/burmish.json`, `data/lexibank/hillburmish/cldf/forms.csv`):

- **NEEDLE, Old Burmese at `burmic`** (provisional proxy): source value `ap`,
  segments `a p ⁴` — the `⁴` is in neither the source value nor the form. Old
  Burmese is in cognate set 932 with Achang `a p ⁵⁵`; Xiandao's identical
  `a p ⁵⁵` and Rangoon `ɑ ʔ ⁴` are in set 930. The one banked `burmic` hit
  matched Rangoon's contour-like `⁴` to an Old Burmese category digit by
  spelling, across mixed units.
- **NEEDLE, Proto-Burmish root:** alternatives `ˀŋ a p ⁴` (set 930) and
  `ʔ a p ⁴` (set 932), from `*ʔŋap` and `*ʔap` with no tone mark; any-alternative
  exact credits either etymon.
- **I (1209):** Proto-Burmish `ŋ a ¹`; Old Burmese `ṅa` becomes `ŋ a`, tone unmarked.
- **OLD MAN (406):** root `dz a ²` from `*dzaH`, one morpheme (set 93) against
  2–3-morpheme daughter compounds, no Old Burmese form, and set-93 slices that
  look misaligned (tso/tsɔ/ta in four daughters but mwaŋ, mɔ̃, pʰo in others).

Proto-Burmish rows cite Huang 1992 while the benchmark attributes the
reconstructions to Hill & Gong 2020, and the prepared
`runs/benchmarks/burmish.json` (29 August) carries no `target_validity` on any
binding: rebuild it before any reuse, or the proxy label is lost. None of
these is ready as a primary outcome; all stay diagnostic.

## 7. Fixture measurements (scripted sessions, both profiles)

| Session | System chars | Tool schema chars | Node prompt chars | Largest tool result | Transcript at end | Local sets / patterns | Projected columns / tuples |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A at `r`, stored | 15,061 | 52,998 | 2,007 | 21,533 | 89,793 | 21 / 8 | 54 / 6 |
| A at `r`, full | 15,073 | 50,592 | 2,007 | 21,533 | 91,296 | 21 / 8 | 54 / 6 |
| B at `x`, stored | 13,579 | 52,998 | 2,141 | 48,856 | 138,009 | 60 / 17 | 92 / 16 |
| B at `x`, full | 13,579 | 50,592 | 2,141 | 48,856 | 147,356 | 60 / 17 | 92 / 16 |

Caps: 4,096 tuples per unit, 65,536 per node, 250,000 projected columns; both
fixtures are far below them. Default `min_support=2` recurrence surveys show 59
of B's 60 local sets and 27 of its 28 one-sided sets (A: 20/21); concept
coverage is 16/16 at `x`; the sparse remainder is reachable with
`min_support=1`. A live model's first request is about 70k characters
before any tool result. The B root session's evidence depends on the model's
`x` beam, so it is **not certified**: the per-trial cost and time caps are its
stop condition. These are scripted-session sizes, not predictions of a
model's cumulative tokens.

## 8. Models and settings

The owner selected both arms on 2026-10-25 (recorded in the shared handoff).
Official pages read 2026-10-25: `gemini-3.8-flash` is "Stable", input limit
1,048,576, output limit 65,536, thinking levels low/medium/high (default
medium; `minimal` errors); `max_output_tokens` caps thinking plus text;
paid standard tier US$0.75 input, US$3.75 output including thinking, US$0.075
cached, through 2026-12-31, doubling on 2027-01-01; no long-context tier.

| | Local baseline | Stronger candidate |
| --- | --- | --- |
| Model | `google/gemma-4-26b-a4b` (LM Studio, `--preset lm-studio`) | `gemini-3.8-flash` (`--preset gemini`, harness `gemini/gemini-3.8-flash`) |
| Reasoning | none sent | `--reasoning-effort medium` → `thinkingConfig.thinkingLevel="medium"` |
| Temperature | 0.1 (harness default) | 1.0 (Gemini preset default, documented) |
| `max_tokens` | 16,384 | 16,384 (caps thinking + text) |
| Request timeout | 600 s | 300 s |
| Profile, tools, instructions, inputs, evaluator | identical | identical |
| Pricing | not paid | `examples/pricing/gemini-3.8-flash.price-table.json` |

Different temperatures, reasoning and providers mean the comparison is
model/provider/configuration-conditional. Equal numerical limits do not make
the conditions equivalent. Context length, quantization and competing jobs of
the local server are checked only at R03 launch.

**Found while freezing: `medium` was not reaching Gemini 3.8 Flash.** LiteLLM
1.81.16 refuses `reasoning_effort` for a model missing from its cost map
(`UnsupportedParamsError` with the bundled map), and the runtime-fetched map
(which does list `gemini/gemini-3.8-flash` at the official prices today) makes
LiteLLM translate `medium` into `thinkingLevel: "high"` for every Gemini 3 name
it does not special-case (only `gemini-3-flash*` and `gemini-3.1-pro-preview`).
The owner's medium arm would therefore have failed or run at high. The CLI now
sends `thinkingConfig={"thinkingLevel": <effort>, "includeThoughts": true}` for
Gemini 3+ models on LiteLLM's Gemini routes, adds `reasoning_transport =
"gemini-thinking-level-v1"` to the configuration digest only then, and keeps
`reasoning_effort` for every other model. A test runs the CLI's actual options
through LiteLLM's `get_optional_params` and sees `medium` arrive unchanged. The
same LiteLLM logic would have sent `high` for `gemini-3.7-flash` with
`medium`; whether banked runs set an effort is not re-examined here.

**Pricing gate.** LiteLLM's per-call pricing kwargs cannot pass
`--provider-config`: its secret filter refuses every key ending in `_token`.
The new `--price-table` takes a versioned `price-table-v1` JSON naming one exact
model, prices, tier, source URL, read date and validity dates; it refuses to
start outside those dates (so the 2027 price change cannot slip in) and its
SHA-256 joins the configuration digest only when used. Cost is an upper bound:
every prompt token is charged at the uncached input rate; output includes
reasoning. `ProviderUsage` gains `cost_source` and
`provider_reported_cost_usd` (additive), so LiteLLM's own figure stays
comparable. Without token counts the response stays unpriced (unknown, never
zero). The harness checks the cost cap only after each response
(`test_cost_cap_is_checked_after_each_response_so_one_response_of_headroom_is_needed`),
so one maximum response of headroom is reserved.

## 9. Resource calculation

One-response headroom = 1,048,576 input tokens (the context limit, since no
harness input cap exists) × US$0.75/M + 16,384 output × US$3.75/M =
**US$0.847872**. Each trial can exceed its cap by at most one response: the cap
is checked before every attempt and after every response, a request with
unknown cost stops a cost-capped run, and only one request is in flight.

| Trial | Turns (node / total) | Cost cap | Worst case | Reservation | Time cap | Wall reservation |
| --- | --- | --- | --- | --- | --- | --- |
| A-gemini | 24 / 24 | US$0.75 | US$1.597872 | US$1.60 | 900 s | 1,000 s |
| B-gemini | 30 / 60 | US$2.25 | US$3.097872 | US$3.10 | 1,800 s | 1,900 s |
| A-local | 24 / 24 | — | — | — | 1,800 s | 1,900 s |
| B-local | 30 / 60 | — | — | — | 5,000 s | 5,100 s |

Gemini total worst case **US$4.695744 ≤ US$5.00** (margin US$0.30, plus the
rest of the prepaid credit against unknown or lost cost); paid wall
reservations 2,900 s ≤ 3,600 s. Local 7,000 s ≤ 7,200 s. The brief's token
formula is also recorded: worst-case output ≤ total turns × 16,384 (393,216 for
A, 983,040 for B) and input ≤ total turns × maximum request; the cost cap
binds long before either. Expected spend is far lower (A's scripted transcript
ends near 90k characters), but no forecast is certified. Retries: at most 3
per request within the request timeout (300 s Gemini, 600 s local); every attempt
counts. The harness clips each request's timeout to the remaining retry budget,
so the budget equals the timeout: a smaller budget would silently replace it. `--max-failed-nodes 0` stops B
at the first failed node instead of paying for a root over a fallback.

## 10. Ledger and launcher

`cognate_reconstruction/benchmarks/ledger.py` (delegated, reviewed here) reads
each run directory: the run summary, the request journal (every attempt,
including abrupt loss) reconciled exactly as a resume would, and trajectories
as fallback. It reports turns, tool calls, provider requests, known cost,
unknown-cost requests, unrecorded requests, elapsed (with a lower-bound flag),
cumulative and maximum-request tokens, and one of six distinct outcomes
(`committed`, `fallback`, `interrupted`, `abandoned`, `void`, `not_run`).
Unknown cost makes `total_cost_usd` null; it is never summed as zero. VOID runs
keep their resources and lose only their linguistic standing.

`tools/experiment_batch.py run --plan PLAN.json` launches trials strictly in
order, one subprocess each, and before each one refuses (recorded, not
raised) on: a non-empty run directory (no reruns or doubled outputs), an
unusable `requires_usable` trial, an unreadable ledger, unknown arm cost under
a cost ceiling, a missing reservation, known spend + reservation over the
ceiling, or wall time over its ceiling. It writes an append-only
`batch_events.jsonl` and an atomic `batch_ledger.json` after every trial. No
retries or seeds.

Offline demonstrations: the delegated fake-batch tests cover priced runs,
unpriced responses, abrupt loss, a whole-batch cost stop, A→B gating, VOID,
duplicate trajectory records, relaunch refusal, an unaffected local arm and
token reporting. Here, the **actual frozen plan** was run end-to-end through
the launcher with scripted providers on the real CLI: A-gemini → B-gemini
launched, A-local committed identity → `committed_other_hypothesis` → B-local
refused; the ledger reports known cost under the ceiling, request sizes and
cumulative tokens; a second invocation launches nothing. A Stage B run stopped
by its cost cap during the root session is `interrupted` with no
`result.json`, yet `x` stays scored from the checkpoint (18/18).

## 11. Frozen candidate artifacts and commands

Directory `runs/experiments/r02-model-diagnostic-20261025/` (ignored):
`inputs/` (both payloads, the Stage A instruction file, the price table, one
provider config per arm), `manifest.stage-a.json`, `manifest.stage-b.json`,
`plan.json`, `source_manifest.json`. They are regenerated, not hand-edited:

```sh
PYTHONDONTWRITEBYTECODE=1 /opt/anaconda3/envs/llm_reconstruction/bin/python tools/r02_diagnostics.py freeze \
  --output-dir runs/experiments/r02-model-diagnostic-20261025
```

**Superseded before commit.** The pre-commit review found that the trial
commands passed `--max-retry-seconds 120`, which the harness uses to clip every
request's timeout, so the documented 300 s and 600 s timeouts would never have
applied. The commands now set the retry budget equal to the timeout. The hashes
below are of the draft freeze; R03 re-freezes into a new directory after the
commit and reviews those hashes.

Frozen 2026-10-25 (SHA-256; the tracked copy is
[model_diagnostic_design_manifest.json](model_diagnostic_design_manifest.json)):

| Artifact | SHA-256 |
| --- | --- |
| `manifest.stage-a.json` | `d8a532c840f9c1ed3272569720f180964ebfcd8c5f6924e38269818a3c5176cb` |
| `manifest.stage-b.json` | `d5d2824fd8cb6ac29caf59c9cce539661bfddbe509939b6e869ee465d2a5e7ec` |
| `plan.json` | `0ef7da9554c2b63db70f4a9cc2074aa0c0b8729ac2efaa8853c5e7be8182aa83` |
| `source_manifest.json` (220 files; HEAD `815a0b6` plus code diff `03f798f2…`) | `1a5bd7b46981cdcc8cc4952eaccf5373c57529f388959c9a795b207d20a1cd5b` |
| `inputs/stage-a.payload.json` | `703b8d9051b69ed1cbcd2d2a9766f7c5a04230ee7917a8407d4c01475f62a6d8` |
| `inputs/stage-b.payload.json` | `e84851120913d6ba8ef91a9bd67a06a321cd851adad4bfcb5b5937b1233fd93b` |
| `inputs/stage-a.instructions.stored-hypothesis.md` | `543e3f320d18d455f27f943f862ee1da9527beb810a2032b7d4e53fab48dcadb` |
| `inputs/stage-b.instructions.md` | `5b4c7aefaee21c543d10f523c3da91e4c52e57867ed63287b73ab57611fba4ff` |
| `inputs/price-table.json` | `f07736e17fe8a06a8b4e9a77d0d43577a071d456066aa0d993d161bc1950f521` |
| `inputs/{gemini,local}.provider-config.json` (`{"max_tokens": 16384}`) | `4bd88ce8ccd5f4397d45e97b0848615054b7003934deb6d64301a48df3cac8cf` |

First requests: Stage A node prompt `11d958dc…` (2,007 chars); Stage B `x`
node prompt `fecbdfcd…` (2,141 chars); the Stage B root prompt depends on the
model's committed `x` beam and is not frozen. The source identity covers
`cognate_reconstruction/`, `tools/`, `tests/`, `skills/`, `benchmarks/`,
`examples/` (local-only audit files excluded), so documentation edits do not
stale it; any code change does.

R03 launches (after its review and preflight) with:

```sh
cd runs/experiments/r02-model-diagnostic-20261025
PYTHONDONTWRITEBYTECODE=1 /opt/anaconda3/envs/llm_reconstruction/bin/python \
  /Users/acraev/Work/cognate-reconstruction/tools/experiment_batch.py run --plan plan.json --dry-run
PYTHONDONTWRITEBYTECODE=1 /opt/anaconda3/envs/llm_reconstruction/bin/python \
  /Users/acraev/Work/cognate-reconstruction/tools/experiment_batch.py run --plan plan.json
```

Each trial's `infer` argv is in `plan.json`; each evaluation is
`tools/r02_diagnostics.py evaluate --stage A|B --run-dir <run> --protocol
stored-hypothesis`, which writes `evaluation.json` with `stage_gate`. Trials
run in the order A-gemini, B-gemini, A-local, B-local: the stronger arm does
not wait for the local one.

## 12. Interpretation, rivals and discriminating observations

| Possible result | Strongest alternative explanation | Observation that discriminates |
| --- | --- | --- |
| A success | Transcribing supplied values is easier than using the interface for one's own decisions | B: are the model's own choices executed as cleanly (rejected calls, previews before commit)? |
| A fails | A specific element (handles, shared claims, pattern versus unit) rather than general capability | Which checker criterion failed; tool error codes; whether the committed claims were close (extra/missing lists) |
| A fails only on the revision protocol | Instruction-following lapse, not interface incapacity | `usable_revision_protocol_deviation`: B still runs |
| B high (≥16/18 and ≥5/6 pairs) | A shallow "follow the outgroup" heuristic — which is the correct evidence use here — or copying `c` | `other` readings (copied `g`), explicit claims rather than residue, outgroup/polarize calls, unresolved items not forced with high confidence |
| B ≈ union or identity (10/18, pairs 0) | Conservative retention or abstention as a default, not evidence use | Pairs 0/6; uniform readings; empty inventory |
| B ≈ a fixed daughter (8 or 10) | Residue-policy copying | `decided_by = residue_policy`; output equals one daughter |
| B low with commits | Navigation failure (outgroup never inspected) rather than judgment | Absence of `include_outgroup`/`polarize`/`search_forms` calls |
| Stronger succeeds, local fails | Configuration (temperature, reasoning, context) or provider serialization, not model "capability" alone | Failure type in A; truncation counts; rejected-call codes; local context check at launch |
| A cap or outage stops a trial | Resource limit, not incapability | Ledger outcome `interrupted`, unknown cost, provider failure kind |

Prespecified reading (descriptive; one trial per model supports a next-step
decision, not reliability or a ranking): "evidence-sensitive on this panel"
needs ≥16/18 `model_committed_correct` **and** ≥5/6 pairs with explicit claims;
"baseline-level" is ≤11/18 or ≤2/6 pairs (copying, uniform and cue policies
reach 8–12 and 0–3). Results in between are reported as mixed. Presence and
absence subtotals are always shown, since only the absence items depend on the
gain/loss symmetry the criterion block states.

## 13. Independent validity audit (read-only)

A Claude Opus 5.5 subagent (medium thinking), read-only, audited the
instruments before the freeze. It re-derived all primary items by hand, found
no leakage of operator fields, design labels, Stage A content or targets into
Stage B requests, and confirmed every Stage A field name against the stored
schemas. Its defects were fixed here before freezing:

| Finding | Fix |
| --- | --- |
| A1: the five absence items and every pair rested on a parsimony assumption the model never saw, while the packaged text says gaps do not establish innovation | Stage B criterion block states the criterion (section 4); presence/absence subtotals always reported |
| A2: pairs were confounded with visible cues (vowel `u` before added `k`; suffix decisions tracked a's stem shape); a no-outgroup rule scored 15/16 and 5/5 | Panel rebuilt: a ends every core in `k`, vowels/onsets/stem kinds balanced, 6 pairs alike in all daughter-visible features; the audit's cue rules are tested to stay ≤12/18 and ≤3/6 |
| A3: `conditioning: {}` made a correct run `committed_other_hypothesis` and blocked B | An all-default environment equals no condition |
| A4: a reworded or fixed revision preview, the documented path, was a protocol deviation | Any revised-claims preview after the original counts; handle or full revised inventory accepted |
| Risk: a relabelled or lost unit was credited as `absent` | New incorrect reading `unit_missing` |
| Risk: two primary rates | `model_committed_correct` is the headline |

Recorded, not changed: the default survey pre-computes the outgroup witness
per column (B is a necessary-condition test); unresolved items look like
absence items in the survey and need `search_forms(scope=available_tree)` to
tell apart; an empty inventory executes as identity (10/18); the `k o` vowel at
`x` in S3/S4 rests on "values come from the daughter" (raw exact only); the
visible holdout partition is skewed toward retain items; Stage A `success`
accepts local choices instead of shared claims (`shape_matches_supplied` is
reported) and ignores harmless extra dispositions if the output matches;
temperature 1.0 versus 0.1 and one trial per arm cannot separate a model from
sampling noise.

## 14. Evidence limits and decisions still missing

- One trial per model and stage; no replication is prespecified. A single
  success establishes feasibility, not reliability.
- Stage B's ceiling is the deployable rule; it measures evidence-sensitive use
  of a supplied outgroup under parsimony, not discovery, and its synthetic
  forms are development material known to the designer.
- The B root session and any model's cumulative tokens are not certified by
  the scripted measurements; caps are the stop condition.
- Effort lost together with its journal remains undetectable (R01 limit).
- The price table's cost is an upper bound; LiteLLM's own figure is kept for
  comparison. Gemini's billing console is the external check.
- **Gates for R03:** (1) the required read-only review of these manifests;
  (2) launch preflight: GEMINI key variable present, `gemini-3.8-flash` served,
  date ≤ 2026-12-31 (else re-read prices and write a new table), local model
  loaded with adequate context and no competing jobs; (3) a re-freeze if any
  source file changes (the manifest pins the dirty working tree, so a commit
  alone changes `head` and requires a re-freeze to keep identities exact).
- **No owner decision is missing**: models, the US$5 / 60-minute paid ceiling
  and the two-hour local ceiling are recorded; R02 chose caps inside them.

## 15. Verification

```sh
PY=/opt/anaconda3/envs/llm_reconstruction/bin/python
# R01's focused command (14 modules): 246 passed
# R02 modules: 99 passed
PYTHONDONTWRITEBYTECODE=1 $PY -m pytest -q -p no:cacheprovider tests/workbench/test_r02_instruments.py \
  tests/workbench/test_price_table.py tests/workbench/test_experiment_ledger.py \
  tests/workbench/test_gemini_provider.py tests/workbench/test_diagnostic_suite.py tests/workbench/test_inspect_run.py
# Portable suite: 797 passed, 41 deselected before the audit fixes; final run: 800 passed, 41 deselected
# (unchanged after the pre-commit review fixes)
PYTHONDONTWRITEBYTECODE=1 $PY -m pytest -q -p no:cacheprovider -k 'not local_run_artifacts'
PYTHONDONTWRITEBYTECODE=1 $PY tools/r02_diagnostics.py controls   # baseline tables above
PYTHONDONTWRITEBYTECODE=1 $PY tools/r02_diagnostics.py measure    # section 7
```

New and changed files: `agent/providers/pricing.py`, `agent/providers/litellm_provider.py`,
`agent/schemas.py` (`ProviderUsage.cost_source`, `provider_reported_cost_usd`),
`cli.py` (`--price-table`, Gemini 3+ thinking level), `synthesis/diagnostics.py`
(explicit definitions), `evaluation/usability.py`, `evaluation/decisions.py`,
`benchmarks/ledger.py`, `inspect_run.py` (usage keys), `tools/r02_diagnostics.py`,
`tools/experiment_batch.py`, the two definitions, the price table and five test
modules (`test_r02_instruments.py`, `test_price_table.py`,
`test_experiment_ledger.py`, plus additions to `test_gemini_provider.py` and
`test_inspect_run.py`). One existing assertion changed deliberately: the Gemini
3.7 reasoning test now expects the explicit `thinkingConfig`. Local-only audit
files were preserved untouched.
