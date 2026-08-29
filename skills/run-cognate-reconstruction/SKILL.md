---
name: run-cognate-reconstruction
description: Run, smoke-test, and triage the cognate-reconstruction LLM harness. Use when asked to run the harness, start or test inference, reconstruct a proto-language, run a model against a fixture via LM Studio or the hosted Gemini API, screenshot/inspect a run, diagnose why an agent run failed, or read trajectories and events from runs/.
---

# Run the cognate-reconstruction harness

`cognate_reconstruction` is a CLI harness: an LLM proposes child-to-parent sound
rules for one internal tree node, deterministic tools validate and apply them.
There is no GUI and no server — the "app" is `cognate-reconstruct infer`, and a
run is judged by the artifacts it leaves in a run directory.

Drive it with the committed driver:

```
.claude/skills/run-cognate-reconstruction/driver.py
```

All paths below are relative to the repo root. Verified on macOS (darwin 25.5.0)
against LM Studio and against the hosted Gemini API. No model is fixed anywhere
in this skill: for a local run you ask LM Studio which models it currently has
loaded and pick one of those (see *Pick a model*); for a hosted run see
*Run: Gemini*.
Where a number below was measured, the model it was measured on is named, and it
is provenance for that number, not an instruction to use that model.

**Why the driver instead of raw `infer`:** `infer` prints "accepted
reconstruction commit" and exits 0 whatever the session cost to get there. The
driver's `triage` reconstructs the turn-by-turn timeline from `events.jsonl` and
reports the failure taxonomy, so a run that committed the right answer after
burning its budget on rejected calls is visibly different from a clean one. That
distinction is the whole reason this skill exists — see Gotchas.

**Which tool for what.** `triage` owns only what `events.jsonl` knows: the
timeline and the live failure taxonomy — the sole source of rejection counts for
runs written before failure accounting. Everything derived from `result.json`
and `trajectories.jsonl` — committed rules, diagnostics, reconstructed forms,
`high_quality` and the exact condition it failed, cross-node observations —
belongs to `cognate-reconstruct inspect-run`, which is a supported CLI
subcommand and which `triage` shells out to. Reach for `inspect-run` directly
when you have a run directory and want to know what it produced; reach for
`triage` when you want to know how the session behaved on the way there.

`cognate-reconstruct visualize-run --run-dir DIR` is the third one, and the one
to reach for when the answer is "look at it": one self-contained HTML page with
the traversal tree and, per node, the session turn by turn — every call, what it
asked, what came back, and each rejection with its code and the remediation the
harness sent back. It is the fastest way to see *where* a session went wrong
rather than that it did. Add `--serve` to watch a run that is still going; the
page renders a finished node from its trajectory and a node in flight from its
events.

## Prerequisites

The `llm_reconstruction` Conda env already exists at
`/opt/anaconda3/envs/llm_reconstruction` (Python 3.11.0, harness 0.2.0, litellm
1.81.16). The driver locates it automatically; override with `$COGNATE_PYTHON`.

Live inference needs LM Studio with a tool-capable model loaded **and its
OpenAI-compatible server running** — loading a model does not start the server:

```bash
~/.lmstudio/bin/lms server start
```

```bash
curl -s --max-time 8 http://127.0.0.1:1234/v1/models
```

The driver runs `lms server start` for you when the endpoint is down.

## Check the environment

```bash
python3 .claude/skills/run-cognate-reconstruction/driver.py preflight
```

Prints the interpreter, harness version, litellm version, and the loaded LM
Studio models; exits nonzero if anything is missing. An empty model list is
*not* one of those failures — the endpoint answering with nothing loaded is a
healthy server, so read the list yourself rather than trusting the `OK`.

## Pick a model

Every live command takes `--model <id>`, and the id has to be one LM Studio
currently has **loaded**: both the driver and the harness preflight it against
`GET /v1/models` and refuse an id the server does not report (`model 'X' is not
reported by LM Studio`). So the first step of any live run is to ask the server
what it is holding and choose from that list — never from memory, and never from
an id written in this file or in an old run directory, since what is loaded
changes whenever someone touches the LM Studio UI.

Ask, cheapest first. The driver, which also starts the server if it is down:

```bash
python3 .claude/skills/run-cognate-reconstruction/driver.py preflight
```

It reports `lm studio  http://127.0.0.1:1234/v1 (N models)` followed by one
`  - <id>` line per loaded model. For the ids alone, one per line:

```bash
/opt/anaconda3/envs/llm_reconstruction/bin/python -m cognate_reconstruction.cli lm-studio-models
```

Both read the same endpoint, so a raw query is the fallback when neither can run:

```bash
curl -s --max-time 8 http://127.0.0.1:1234/v1/models
```

Then choose from what came back:

- **One id** — the usual case, since LM Studio is normally serving a single
  loaded model. Take it and go; there is nothing to ask the user about.
- **Several ids** — pick a tool-capable chat model. `/v1/models` reports no
  capabilities, so nothing in the list tells you which those are: exclude the
  obvious non-chat entries by id (anything named `*-embed*`/`embedding`, a
  reranker, a whisper/TTS model) and, among the rest, prefer an
  instruct/chat-tuned model over a base one. If two plausible chat models
  remain, ask the user which to run rather than guessing — a run costs minutes
  and the choice is theirs.
- **No ids** — nothing is loaded. Neither the driver nor the CLI can load a
  model, so this is a stop-and-report: tell the user to load one in the LM
  Studio UI (or `~/.lmstudio/bin/lms load <id>`), then re-run `preflight`.

Pass the id **verbatim**, vendor prefix included (`google/…`, `qwen/…`), and
without an `openai/` prefix — the `lm-studio` preset adds that itself, which is
why trajectories show a longer id than you typed (see Gotchas). Capture it once
and reuse it for the run and its follow-ups:

```bash
MODEL=$(/opt/anaconda3/envs/llm_reconstruction/bin/python -m cognate_reconstruction.cli lm-studio-models | head -1)
```

That one-liner is only correct once you have looked at the list and know it has
a single usable entry; with several loaded it silently picks whichever LM Studio
happened to list first. If the model you picked turns out not to support tool
calls, the run does not fail cleanly — it burns turns producing prose with no
tool call and ends in `ProtocolStallError` or `AgentLoopLimitError`, so triage
that shape as a model-choice problem before reading it as a prompt problem.

## Run: deterministic path (no model, no network)

Fastest way to confirm the core still works. Runs the unit suite (276 fixed
tests, plus one opportunistic backward-compatibility case per
`runs/*/trajectories.jsonl` you have locally, so the total you see is higher and
drifts as you do runs) and the CLDF fixture ingestion. The fixed 276 is the
number to quote: run
`pytest -q -k "not local_run_artifacts"` for it. The guarantee those extra cases
used to carry alone is now pinned by a checked-in real pre-change trajectory, so
an empty `runs/` no longer quietly removes it:

```bash
python3 .claude/skills/run-cognate-reconstruction/driver.py smoke
```

Ends with `SMOKE OK`. Use this after touching schemas, rules, ingestion, or
traversal — it needs no provider.

## Run: live inference (agent path)

```bash
python3 .claude/skills/run-cognate-reconstruction/driver.py run --model "$MODEL" --input examples/lm_studio_smoke_input.json --quiet
```

Creates `runs/<model>-<timestamp>/` containing `result.json`,
`trajectories.jsonl`, `events.jsonl`, `checkpoint.json`, and `console.log`,
then triages it automatically. `runs/` is gitignored.

Inputs, cheapest first:
- `examples/lm_studio_smoke_input.json` — 2 languages, 1 concept (~60s on
  `google/gemma-4-e4b`)
- `examples/reconstruction_input.json` — 3 languages, 2 concepts (~45s on
  `google/gemma-4-e4b` in a clean 4-call session; it was ~4.5 min when the
  commit protocol ate the turn budget, so a slow run is itself a signal —
  triage it)

Both timings are that one model's; a larger model is slower per turn, so read
them as shapes, not deadlines.

Drop `--quiet` to stream the harness's own verbose event log. Use
`--max-turns` / `--max-tool-calls` to bound a model that will not converge.

## Run: Gemini (hosted)

Same harness, same artifacts, same triage — only the provider differs. Nothing
local is needed: do **not** start or preflight LM Studio for a Gemini run.

```bash
. ~/.config/cognate-reconstruction/env
python3 .claude/skills/run-cognate-reconstruction/driver.py run --preset gemini --model gemini-3.7-flash --input examples/lm_studio_smoke_input.json --quiet
```

**Source the key file first, in the same command.** The key lives in
`~/.config/cognate-reconstruction/env` (mode 600, outside the repo) and is
sourced from `~/.zshrc`, which a non-interactive tool call does not read. Without
the leading `. ~/.config/...` the run stops with `API-key environment variable
'GEMINI_API_KEY' is unset or empty` before spending anything.

The model id is passed bare. The preset prefixes it with `gemini/` for LiteLLM,
which is why trajectories show the longer id — the same rewrite the `lm-studio`
preset does with `openai/`. Ask the API which ids the key may call:

```bash
. ~/.config/cognate-reconstruction/env && /opt/anaconda3/envs/llm_reconstruction/bin/python -m cognate_reconstruction.cli gemini-models
```

That list is the preflight the run itself performs, so an id absent from it fails
before the first call rather than mid-session.

Two flags matter more here than locally:

- `--reasoning-effort {minimal,low,medium,high}`. **Gemini 3 thinks at `low`
  unless told otherwise**, which is not a defensible default for the comparative
  method. It is hashed into the configuration digest, so it must be chosen before
  the first node and cannot be changed on a `--resume`.
- `--temperature`. **Leave it unset here.** Google documents, and LiteLLM warns
  on every call, that a Gemini 3 model sampled below 1.0 can loop, reason worse,
  and fail outright on hard tasks. Unset resolves to 1.0 under this preset and
  to 0.1 everywhere else, and the digest records the resolved value, so a
  `--temperature 1.0` typed out by hand hashes the same as leaving it off.

Measured on `gemini-3.7-flash` against the 2-language, 1-concept smoke fixture:
~64s and ~$0.05 at the default thinking level, ~275s at `--reasoning-effort
high`, 6–7 tool calls either way. Read these as shapes, not deadlines.

### What a hosted run costs, and why

Almost none of a prompt is the linguistic data. The first call of that smoke run
was 20,880 tokens: 11,660 for the thirteen tool schemas, 8,344 for the agent
instructions, 876 for the node payload. The API is stateless, so that
20,004-token preamble is re-sent on every call. Cost scales as
`(instructions + tool schemas) x turns x nodes` and is nearly independent of how
much lexicon you feed it — so bound a long run with `--max-total-cost-usd`
rather than by trimming concepts.

Gemini caches that preamble implicitly. `inspect-run` reports the share, and the
driver's triage prints it:

```
tokens   in 129474 (69225 cached, 53%) / out 528 / total 130002 / $0.0524
```

Measured: the first two calls of a session are cold, then 74–91% per call. Read
it as a subset of the input, not an addition. `not reported` is not zero — LM
Studio reports nothing, and a cold Gemini run reports nothing either.

Thinking is metered the same way, as a share of the output rather than an
addition to it, so `--reasoning-effort` can be priced instead of guessed:

```
tokens   in 129474 (69225 cached, 53%) / out 528 (400 reasoning, 76%) / ...
```

LM Studio reports neither, so both stay `not reported` on a local run — which is
silence about the counter, not a claim that the model did no thinking.

### The key is a free-tier key

Two consequences, and the second is the one that matters for this project.

**Rate limits are low and shared across the day.** Expect `429` and `503
UNAVAILABLE` ("high demand") mid-session. The harness classifies both as
transient and retries with backoff — a run recovered from a 503 on its first
node without operator action — but a multi-seed `run-benchmark` will exhaust a
free daily quota long before it exhausts the science. Check the current limits
at <https://aistudio.google.com/rate-limit> before launching a sweep, and treat
a run that dies in repeated `provider_retry` events as a quota problem, not a
model problem.

**Free-tier prompts and responses are used by Google to improve its products,
and human reviewers may read them.** Paid-tier traffic is excluded from that.
For this harness that is a benchmark-integrity question rather than a privacy
one: every free-tier run sends the agent instructions, the tool schemas, and the
benchmark payload to a training pipeline, so a benchmark exercised heavily on
the free tier may be inside a future model's training data — and this repo's
whole purpose is measuring models against it. Gold answers are never sent (the
harness never shows them to the model), so the leak is the task, not the answer
key. Use the free tier for smoke tests and plumbing checks; raise it with the
user before running a published benchmark on it.

## Triage an existing run

```bash
python3 .claude/skills/run-cognate-reconstruction/driver.py triage --run-dir runs/google-gemma-4-e4b-20260814-184836
```

Reports the per-turn timeline with token growth and per-call ok/ERR and the
failure taxonomy, then prints `inspect-run` for the same directory — committed
rules with scope, diagnostics, reconstructed forms, the `high_quality` verdict
with the exact condition it failed, and the cross-node observations. A failing
run looks like:

```
FAILED TOOL CALLS: 3 of 7  (43% of tool budget wasted)
  3 protocol, 0 exploratory
    3x  commit_reconstruction  [protocol]  schema:rules[].confidence=missing
        ValidationError: rules.0.confidence Field required; ...
```

The code is the countable part and the message below it is the readable part.
Three calls that omitted `confidence` on different rules share one code even
though Pydantic wrote three different messages, which is what makes the tally
mean something.

Trajectories written before 2026-08-15 have no failure counters, so the artifact
report says `0 recorded, unsplit` and tells you to read `events.jsonl` while the
taxonomy above it counts the real rejections. That disagreement is the expected
reading of an older artifact, not a bug — and it is exactly why `triage` keeps
the event-derived taxonomy instead of deferring everything to `inspect-run`.

The same input on the same model after the commit-protocol work:

```
FAILED TOOL CALLS: 0 of 4  (0% of tool budget wasted)
```

## Run: human path

The underlying command the driver wraps:

```bash
/opt/anaconda3/envs/llm_reconstruction/bin/python -m cognate_reconstruction.cli infer --preset lm-studio --model "$MODEL" --input examples/reconstruction_input.json --output runs/manual/result.json --trajectories runs/manual/trajectories.jsonl --events runs/manual/events.jsonl --temperature 0 --max-turns 16 --max-tool-calls 32
```

Other subcommands: `lm-studio-models`, `list-lexibank-varieties`,
`prepare-lexibank`, `build-benchmark`, `run-benchmark`, `build-synthetic`,
`score-synthetic`, `inspect-run`, `validate-trajectories`,
`summarize-trajectories`, `export-trajectories`.

For evaluation work, prefer the benchmark path over a hand-assembled run:
`build-benchmark --name polynesian` builds the input, `run-benchmark` runs N
seeds into one aggregate that reports spread rather than a single quotable
number, and `build-synthetic --name synthetic_regular` gives a leakage-free
family whose changes and direction can be scored with `score-synthetic`. See
`docs/benchmarks.md`.

```bash
/opt/anaconda3/envs/llm_reconstruction/bin/python -m cognate_reconstruction.cli summarize-trajectories --input runs/google-gemma-4-e4b-20260814-184836/trajectories.jsonl
```

## Read a run's artifacts directly

```bash
/opt/anaconda3/envs/llm_reconstruction/bin/python -m cognate_reconstruction.cli inspect-run --run-dir runs/google-gemma-4-26b-a4b-20260816-125837
```

Add `--html runs/<dir>/report.html` for one self-contained file (no external
CSS, JS, fonts, or images; readable light and dark) or `--all-forms` to list
every reconstructed form instead of the first 40 per node. Works on a run
directory with no `events.jsonl`, and on one with no `result.json` — the forms
then come from the beams in the trajectories.

The last section compares committed rules across nodes and prints observations:
one DSL committed at several nodes with materially different confidence,
adjacent nodes mapping the same target in the same environment two ways, and a
correspondence established below a node that the node never mentions. **These
are observations, not findings.** Nothing scores them, they never reach
`high_quality` or the beam, and the third one fires on perfectly correct runs —
a parent that committed identity because the change was already complete below
it looks exactly like a parent that forgot. Read them as prompts to look, not as
errors.

## Gotchas

- **`conda run` fails under this sandbox** with `__conda_exe:6: permission
  denied`. Every `make` target uses it (`PYTHON := conda run -n
  llm_reconstruction python`), so `make test`, `make smoke-lexibank`, and
  `make install` are all unusable here. Call the env's python directly —
  that is exactly what the driver does.
- **LM Studio applies its own sampling panel to anything you do not send, and
  `configuration_sha256` cannot see it.** The harness sends `model`, `messages`,
  `tools`, `tool_choice`, `api_base`, `temperature`, `timeout`, and whatever is
  in `--provider-config`. Everything else — `top_k`, `top_p`, `repeat_penalty`,
  `min_p` — comes from the Developer tab's Inference panel for the loaded model.
  Two runs with an identical configuration hash can therefore have been produced
  under different samplers, with nothing in the artifact saying so.

  Measured 2026-08-24 against `google/gemma-4-26b-a4b`, comparing greedy output
  at `temperature 0`:

  | sent | effect |
  | --- | --- |
  | nothing (panel default `repeat_penalty` 1.1) | baseline |
  | `repeat_penalty: 1.0` | **different output** |
  | `repeat_penalty: 2.0` | different again |
  | `top_k: 0`, `top_p: 1.0` | identical to baseline |

  `top_k` and `top_p` truncate a distribution that is then argmax'd, so they are
  no-ops at temperature 0 — but not above it. `repeat_penalty` is a *logit
  modifier applied before selection*, so greedy decoding is not immune to it,
  and 1.1 is LM Studio's default rather than the model's: Gemma's published
  `generation_config` specifies `temperature 1.0`, `top_k 64`, `top_p 0.95` and
  no repetition penalty at all.

  **Send them instead of inheriting them.** Every one is overridable per request
  and none needs the UI. `--provider-config` carries them, LiteLLM forwards them
  to a custom-base `openai/` provider both top level and via `extra_body`, and
  they land in `configuration_sha256` and the trajectory's `provider_options`:

  ```bash
  printf '{"top_k": 64, "top_p": 0.95, "repeat_penalty": 1.0}\n' > sampling.json
  ```

  Pass `--temperature` as the flag, not in that file: `_provider_and_configuration`
  sets `options["temperature"]` *after* loading the provider config, so the flag
  wins. `repeat_penalty` is not an OpenAI parameter and survives only as a
  LiteLLM passthrough — verified, but worth re-checking after a LiteLLM upgrade.

- **`run-benchmark --infer-arg` needs `=`, not a space.** The value it forwards
  is itself a flag, so `--infer-arg --timeout --infer-arg 600` makes argparse
  read `--timeout` as the *next option* rather than as the argument, and the
  sweep dies with `argument --infer-arg: expected one argument` before a single
  seed runs. Write `--infer-arg=--timeout --infer-arg=600`. It fails fast and
  costs nothing, unlike the traps above, but it fails identically for both
  conditions of a paired sweep and is easy to misread as an environment problem.

- **A "before" sweep runs the code of whatever directory you launch it from.**
  `_command_run_benchmark` spawns each seed as `python -m
  cognate_reconstruction.cli infer`, and `-m` resolves from the *current working
  directory* first. Pointing `--benchmark` at an old checkout's payload is
  therefore not enough — the payload comes from the old tree and the harness
  from the installed one, and the sweep is silently an "after" sweep with an
  "after" instruction hash. `cd` into the old checkout before launching, and
  **verify rather than assume**: the first seed's `checkpoint.json` carries
  `configuration_components["the agent instructions"]`, which must equal the
  hash the historical run recorded. That check costs one minute and catches the
  failure that otherwise costs the whole sweep.

- **`--provider-seed-base` does nothing at `--temperature 0`.** Greedy decoding
  never consults a seed, so five "seeds" become five identical configurations
  differing only by whatever MoE-routing and batching nondeterminism the server
  has. An unset `--temperature` resolves to 0.1 for exactly this reason (1.0
  under `--preset gemini`, where the floor is higher).
  A multi-seed sweep wanting real spread needs a temperature above zero, and at
  that point the `top_k`/`top_p` row above stops being a no-op.

- **A seed makes turn 0 reproducible and nothing after it.** The provider
  generates the `call_id` on every tool call, and the harness echoes it back into
  the next prompt as the tool message's `tool_call_id`, so from turn 1 onward the
  context carries a random nine-digit number that differs between runs. Measured
  2026-08-25 across three shared seeds of two `synthetic_hard` sweeps at an
  identical `configuration_sha256`: turn 0 was identical every time — same tool,
  same arguments — and turn 1 already diverged, on one seed from `polarize` to
  `get_alignments`. So `--provider-seed-base` buys **independent** samples, not
  **reproducible** ones, and **an identical `configuration_sha256` never implies
  an identical trajectory.** Two consequences when comparing sweeps: a run cannot
  be replayed to debug it, and two sweeps at the same configuration are poolable
  as independent draws rather than being a reproduction and a failure to
  reproduce. The same two sweeps differed by 2.67 against 1.40 nodes committed a
  seed, which reads as a broken environment and is ordinary spread at n=3.

- **Thinking mode is most of the output budget, and it is not a sampler.**
  `google/gemma-4-26b-a4b` with LM Studio's "Enable Thinking" custom field on
  spent **897 of 899 completion tokens** on `reasoning_content` when asked to
  write one digit thirty times, and never emitted visible content. That is the
  explanation for both the multi-minute turns below and for a `max_tokens` cap
  stalling a node. It is chat-template machinery rather than a sampling
  parameter, so unlike the table above it has not been shown to be settable per
  request.

- **LM Studio keeps models loaded while its server is off.** `lms server
  status` said "The server is not running" while `google/gemma-4-e4b` was
  loaded. Port 41343 belongs to the LM Studio app and answers HTTP but is not
  the API; the API is 1234.
- **`litellm` exposes no `__version__` attribute.** `import litellm;
  litellm.__version__` raises even though 1.81.16 is installed. Use
  `importlib.metadata.version("litellm")`.
- **The `lm-studio` preset rewrites the model ID.** You pass
  `google/gemma-4-e4b`; trajectories record
  `openai/google/gemma-4-e4b`. Don't treat that as a mismatch.
- **The commit protocol used to be the dominant failure mode.** Before
  2026-08-15 gemma reached the correct rule on turn 3 and then failed 10 of 14
  (and 3 of 7) subsequent calls on commit-schema errors. `validation_call_id`
  and `supporting_form_ids` are now optional and resolved from the matching
  same-session validation, every field is described, and a rejected commit
  returns a `remediation` listing each recorded
  `(validation_call_id, dsl, source_child_ids)` triple. If you still see a
  cluster of `commit_reconstruction` errors, read the `remediation` in the
  triage output before blaming the model — it names exactly what was missing.
- **A multi-rule commit now needs a `rationale` per rule.** Single-rule commits
  do not; that asymmetry is deliberate, since one `summary` can carry the
  reasoning for one rule but not for several. A commit missing any is rejected
  with `missing-rule-rationale` and a remediation naming the exact `rule_id`s,
  which counts as a protocol failure. If a model that used to commit two rules
  cleanly starts failing once and then succeeding, this is why.
- **A rule that deletes or merges now needs a `directionality_rationale`.**
  Applying the committed cascade either removes material or sends two of a
  child's distinct segments to one output; both are detected mechanically, and a
  commit whose flagged rules omit the field is rejected with
  `missing-directionality-rationale` naming the exact `rule_id`s, which counts
  as a protocol failure. **The harness never judges what the rationale says** —
  only that it is there — so a cluster of these means the model is not stating
  which branch innovated, not that its linguistics were graded. The remediation
  carries the count of nodes that still attest the discarded material, and
  points at `polarize`, which is the tool for answering it. A rule that shifts a
  segment into one the child does not otherwise have is not flagged.
- **`contrast reduction` and `held out` are reports, not gates.** `inspect-run`
  prints `contrast_reducing_rule_count` directly under `rule coverage`, because
  coverage rises when rules fire and the cheapest way to make a rule fire is to
  delete a distinction — read the block, not the headline. The trajectory's
  `held_out_convergence_rate` measures the committed cascade on concepts the
  session did not select; a low value is informative and disqualifies nothing.
- **`high_quality` still is not a linguistic grade.** It fails a trajectory
  whose *protocol*-failure share exceeds `MAX_PROTOCOL_FAILURE_RATE` (0.25, in
  `cognate_reconstruction/agent/trajectory.py`) — unless it had at most one
  protocol failure, a floor that keeps a three-call identity commit from being
  disqualified at 0.33 by a single slip. Not every rejection counts: a
  `dsl-parse-error`, `no-op-rule`, or `empty-scope` is *exploratory* — the model
  proposed a rule and the parser refused — and only `protocol` rejections reach
  the gate. Triage prints both tallies. Passing means the workflow was clean,
  not that the reconstruction is right.
- **`tool_failures_by_type` keys on the structural error code**, not the
  exception class, so it now reads `{"schema:rules[].confidence=missing": 4}`
  instead of the useless `{"ValidationError": 4}`. The vocabulary is closed and
  documented in `cognate_reconstruction/agent/error_codes.py`. Runs recorded
  before codes existed have none, and triage shows those under a `legacy:`
  prefix derived from the message — that prefix is the old unstable signature,
  so do not compare its counts across runs.
- **`rule_coverage` is applied / applicable, not applied / evaluated.** Forms
  that never contained the rule's target are excluded from the denominator, so
  `f > p / #_` scoped to three children scores the same 1.0 as the same rule
  scoped to the one child that shows `f`. `target_absent` and
  `applicable_rule_results` are reported separately; use them, not coverage, to
  judge whether a scope was wider than the evidence.
- **Nodes share reconstructions, not conversations.** Every node starts a fresh
  message list. A later node can pull an already-reconstructed descendant's
  committed rules with `get_node_reconstruction`, and `list_available_nodes`
  flags which nodes have one. That is read-only and does not affect scoring, so
  it will not change a beam or a diagnostic — if a run's numbers move, look
  elsewhere. **This survives `--resume` now:** the resumed run reads
  `trajectories.jsonl` back and reseeds the hypotheses of checkpoint-restored
  nodes, printing `seeded N prior committed hypotheses`. A record is seeded only
  if it is completed with its commit, names a node in the checkpoint, and
  carries both the current `configuration_sha256` **and** the checkpoint's
  `run_id`. If that line says 0 when you expected more, check those four before
  suspecting the tool — a trajectory file from a different model, a different
  `agent/system_prompt.md`, or a different invocation is filtered out by design. The
  run-ID filter is the one that surprises people: two runs over the same input
  with the same settings hash identically and both default to
  `trajectories.jsonl` in the working directory, so without it one run's rules
  would be paired with another run's forms. A missing file warns and continues;
  a corrupt one stops the run.
- **A repeated tool error now ends the node, even if its wording changes.**
  After `max_repeated_tool_failures` (default 3) rejections sharing one
  `(tool, error code)` signature within the trailing window of
  `stall_window_calls` calls (default 9, successes included), the orchestrator
  injects one targeted correction carrying the tool's remediation; one further
  recurrence raises `ProtocolStallError` instead of burning the turn budget.
  Repeats need not be consecutive, and varying the arguments no longer helps —
  the signature is the code, not the message. The window is what forgives a
  session that hit one mistake three times far apart and recovered in between.
  A model cycling through many *different* malformed shapes is caught by a
  second condition on the same window: `max_window_protocol_failures` (default
  6 of 9) protocol rejections of any codes draw one correction naming them, then
  stall. Exploratory rejections — a malformed DSL, a no-op rule, an empty
  scope — never count toward either condition, so a session that tests bad sound
  laws all day is bounded only by the turn limit, on purpose.
  `finish_reason="length"` is handled separately and also stalls after
  `max_truncated_responses` (default 3) truncated no-tool responses.
- **Truncation now has a real remedy, and triage says when it was used.** After
  a truncated response with no tool call, the *next* request goes out with
  `tool_choice="required"` — on every such truncation, until the backend
  refuses the option outright. Optionally, `--allow-truncation-backoff` with
  `--truncation-max-tokens-ceiling` doubles the effective `max_tokens` for the
  rest of the node; it is **off by default** because `max_tokens` is your
  `--provider-config` option, not the harness's. Triage prints
  `truncation_recovery forced_tool_choice=N max_tokens_backoff=N` on any node
  where either fired, so a run that only committed because the harness
  intervened does not read as clean. Two things to know: `high_quality` does
  *not* currently penalise a node that needed either recovery — that is an open
  calibration question, not a verdict — and `--max-truncated-responses` caps how
  far backoff can escalate, so at the defaults you get at most two doublings
  before the node stops.
- **A slow provider call looks exactly like a wedged one. Do not kill it.**
  Measured 2026-08-17 on `google/gemma-4-26b-a4b` over the 7-node Polynesian
  benchmark: individual `model_turn` → `model_response` gaps of 1.2, 1.3, 1.4,
  2.3, 5.1, 6.3, 6.6 and 7.3 minutes, **all of which returned normally.** On the
  widest nodes this model simply takes minutes per turn, and while it does the
  process sleeps, CPU sits near zero, `netstat` shows an ESTABLISHED socket to
  :1234 with empty queues both ways, and LM Studio still answers a fresh `curl`
  in under a second because it serves requests concurrently. **None of those
  observations distinguish slow from stuck** — a mistake worth not repeating: a
  10-minute silence was read as an unbounded hang and killed 5 minutes before it
  would have resolved itself.

  A call that really does hang is bounded, and the harness handles it:

  ```text
  16:28:19Z model_turn      tahitic
  16:43:20Z provider_retry  tahitic | Timeout: litellm.Timeout: APITimeoutError
  ```

  901 seconds against `--timeout 300` — about 3×, consistent with LiteLLM
  retrying internally before surfacing anything. The harness classifies
  `litellm.Timeout` as transient, emits `provider_retry`, and retries
  `--max-retries` times (default 2) before the node fails. So the real bound with
  default flags is roughly **15 minutes per attempt, ~45 minutes per turn**, not
  infinity. **The most efficient strategy, in order:**

  1. **Wait, unless the silence exceeds the bound.** Compare event staleness
     against ~15 minutes per attempt, not against your patience. Anything
     shorter is a slow generation, and killing it throws away the node.

     ```bash
     find runs/<dir>/events.jsonl -mmin +16 -print   # prints = past one timeout
     ```

  2. **Make turns shorter, before the first node.** Cap `max_tokens` in
     `--provider-config` (2048–4096 leaves room for one tool call). A reasoning
     model with no cap can generate until the context is exhausted; a cap turns a
     15-minute turn into `finish_reason="length"`, which the harness already
     recovers from by forcing a tool call.

     **Size the cap for an inventory commit, not for a rule commit.** A
     `commit_reconstruction` carrying `rules` is a handful of short objects; one
     carrying an `inventory` is one object per correspondence set, each with a
     `set_id`, a reflex per child, a value, a support count, a confidence and a
     rationale. Measured 2026-08-24 on `google/gemma-4-26b-a4b` over an
     eight-set node: 3072 was ample under the cascade protocol and stalled the
     same node under the inventory protocol with
     `ProtocolStallError: model output was truncated 3 times`, all three
     responses reporting exactly 3071 output tokens. Uncapped, the same node
     committed. If a node stalls on truncation while the tool it was calling was
     `commit_reconstruction` or `test_proto_assembly`, raise the cap rather than
     reading it as a model that cannot converge.
  3. **Make the bound tighter, before the first node.** Lower `--timeout` so a
     genuine hang surfaces in minutes rather than a quarter of an hour. Note
     `--max-run-seconds` does *not* help: `_check_run_budget()` runs before and
     after an attempt and never during it, so no harness budget interrupts a call
     in flight.
  4. **Both knobs are hashed, so they are up-front decisions.**
     `--provider-config` and `--timeout` feed `configuration_sha256`: you cannot
     add a cap or shorten the timeout and still resume a checkpoint written
     without them. `driver.py run` sets neither, so use the human `infer` path
     when you want them. The give-up thresholds are the exception and can be
     changed across a resume.
  5. **If you must stop it, `kill -INT` and verify before resuming.** The
     checkpoint costs you only the current node, but a truncated JSONL line
     becomes `could not load prior hypotheses` and stops the resume:

     ```bash
     /opt/anaconda3/envs/llm_reconstruction/bin/python -c "
     from cognate_reconstruction.traversal.checkpoint import CheckpointStore
     from cognate_reconstruction.agent.trajectory import TrajectoryDatasetBuilder
     print([s.parent_node_id for s in CheckpointStore('runs/<dir>/checkpoint.json').load().completed_steps])
     print(len(TrajectoryDatasetBuilder.read_jsonl('runs/<dir>/trajectories.jsonl')))"
     ```
- **The give-up thresholds are CLI flags and are deliberately *not* in the
  resume hash.** `--max-repeated-tool-failures`, `--stall-window-calls`,
  `--max-truncated-responses`, both truncation-backoff flags, `--fail-fast`,
  and `--max-failed-nodes` decide only how long the harness keeps trying, so
  loosening them and resuming is allowed — the resume prints a note that "the
  give-up thresholds changed" and proceeds. Everything semantic *is* hashed:
  the `agent/system_prompt.md` text, the tool schemas, any `--anchors` file, the model,
  temperature, timeout, beam width, and the turn/tool-call budgets. Changing
  one of those makes an existing checkpoint refuse to resume, and the error
  names which ("the agent instructions", "the tool schemas", "the anchor file",
  "the provider and limit settings"). Checkpoints written before 2026-08-15
  refuse too, but can only say "the configuration" — they never recorded the
  parts.
  `max_window_protocol_failures` still has no flag; the CLI never sets it and
  its default derives from two flags that are hashed.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `__conda_exe:6: permission denied` | Use `/opt/anaconda3/envs/llm_reconstruction/bin/python`, not `conda run` / `make`. |
| `curl` to :1234 returns nothing, exit 000 | LM Studio server is off: `~/.lmstudio/bin/lms server start`. |
| `model 'X' is not reported by LM Studio` | That id is not loaded — the message lists what is. Re-pick from the loaded set (*Pick a model*); do not reuse an id from an older run. |
| `preflight` says `(0 models)` | Server is up with nothing loaded. Ask the user to load a model in LM Studio; neither the driver nor the CLI can load one. |
| `API-key environment variable 'GEMINI_API_KEY' is unset or empty` | The key file was not sourced. Prefix the command with `. ~/.config/cognate-reconstruction/env &&` — `~/.zshrc` sources it, but a non-interactive tool call does not read `~/.zshrc`. |
| `model 'X' is not served by the Gemini API` | Preflight rejected the id before any spend. The message lists what the key may call; re-pick from `gemini-models`. Not the same failure as the LM Studio row above. |
| Gemini run dies in repeated `provider_retry` (`429`, or `503 UNAVAILABLE`) | Free-tier quota, not a model fault. A stray 503 is retried and recovers on its own; a run that keeps hitting them has exhausted the daily allowance. See <https://aistudio.google.com/rate-limit>. |
| `provider config must not give the model a source outside the harness` | A `--provider-config` asked for web search or grounding (`web_search_options`, `search_parameters`, `google_search`, …). Refused on every provider, not just Gemini: a grounded model can retrieve a published reconstruction instead of deriving one, and the trajectory would look identical. If the model genuinely needs a source, it belongs behind a typed tool. |
| `the Gemini API does not support 'seed'` | Refused up front, by design: Gemini has no seed, so `--provider-seed-base` (or a `seed` in `--provider-config`) would have produced repetitions that only looked seeded. Drop it and read the sweep's spread as provider nondeterminism. |
| Gemini run points at `localhost` and cannot connect | An `--api-base` was passed with `--preset gemini`. The preset needs none; omit it unless you are deliberately routing through a proxy. |
| `litellm MISSING` in preflight | Install the agent extra into the env (`pip install -e '.[agent]'` with the env's python; `make install` will not work here). |
| Run makes no progress but the process is alive | Almost certainly a slow turn, not a hang — this model returned after 5–7 minutes repeatedly. **Wait.** A real hang surfaces as `provider_retry` with `litellm.Timeout` after ~15 min per attempt with `--timeout 300`. Only investigate past that: `find runs/<dir>/events.jsonl -mmin +16 -print`. Prevent long turns next run with `max_tokens` in `--provider-config` and a lower `--timeout`; both are hashed, so they must be set before the first node. See the gotcha above. |
| A node ends in any error | The run continues by default: the node is recorded in `result.json:node_failures`, its parent is an identity fallback, and neither it nor anything above it is checkpointed. `inspect-run` names them at the top. Triage the node, then `--resume` — the give-up thresholds are not hashed, so you may loosen them on the way. `--fail-fast` restores the old abort; `--max-failed-nodes` (default 3) stops a run that is failing everywhere. |
| Run ends in `TooManyNodeFailuresError` | More nodes failed than `--max-failed-nodes` tolerates, and the message names each one. `result.json` was *not* written. The checkpoint holds every node below the first failure; triage before resuming. |
| Run ends in `AgentLoopLimitError` | Model never produced a valid commit and never failed densely enough to trip either stall condition — typically a session that keeps exploring, since exploratory rejections never count. Triage it; raise `--max-turns` or use a stronger model. |
| Run ends in `ProtocolStallError` | One of three things: a `(tool, error code)` signature recurred after a targeted correction; the trailing window filled with protocol rejections of mixed codes; or output was truncated repeatedly with no tool call. Read the message — the first two are tool-contract problems. For the third, the message states what the harness already tried (forcing a tool call, and any `max_tokens` backoff steps); what is left is raising `max_tokens` in the `--provider-config` JSON, or `--allow-truncation-backoff --truncation-max-tokens-ceiling N` to let the harness raise it for you. |
| `checkpoint cannot be resumed because these changed: ...` | Expected after editing the model's system prompt (`cognate_reconstruction/agent/system_prompt.md`), the tool schemas, an `--anchors` file, or any hashed flag. The named part is the one to restore — or start a new checkpoint path. **Not this file:** `SKILL.md` here is the operator skill for a coding agent and is hashed by nothing. |
| `could not load prior hypotheses from ...` | `trajectories.jsonl` is present but does not validate. Do not delete it; a missing file only warns, so this is telling you the artifact is corrupt at the named line. |
| `PydanticSerializationUnexpectedValue` warnings | Known nonfatal LiteLLM/Pydantic noise. Tool execution and trajectories still succeed. |
| `[driver] inspect-run ... failed; the artifact sections are missing` | The timeline above it is still valid. Run the printed command yourself for the full error — usually a run directory holding neither `result.json` nor `trajectories.jsonl`, or a harness too old to have the subcommand. |
| `1 of 2 committed rules omit 'rationale'` | Expected on a multi-rule commit without per-rule reasoning. The remediation names the `rule_id`s; single-rule commits still need none. |
