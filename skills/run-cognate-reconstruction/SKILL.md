---
name: run-cognate-reconstruction
description: Run, smoke-test, and triage the cognate-reconstruction LLM harness. Use when asked to run the harness, start or test inference, reconstruct a proto-language, run a model against a fixture via LM Studio, screenshot/inspect a run, diagnose why an agent run failed, or read trajectories and events from runs/.
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
against `google/gemma-4-e4b` served by LM Studio.

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
Studio models; exits nonzero if anything is missing.

## Run: deterministic path (no model, no network)

Fastest way to confirm the core still works. Runs the unit suite (178 fixed
tests, plus one opportunistic backward-compatibility case per
`runs/*/trajectories.jsonl` you have locally, so the total you see is higher and
drifts as you do runs) and the CLDF fixture ingestion. The fixed 178 is the
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
python3 .claude/skills/run-cognate-reconstruction/driver.py run --model google/gemma-4-e4b --input examples/lm_studio_smoke_input.json --quiet
```

Creates `runs/<model>-<timestamp>/` containing `result.json`,
`trajectories.jsonl`, `events.jsonl`, `checkpoint.json`, and `console.log`,
then triages it automatically. `runs/` is gitignored.

Inputs, cheapest first:
- `examples/lm_studio_smoke_input.json` — 2 languages, 1 concept (~60s on gemma)
- `examples/reconstruction_input.json` — 3 languages, 2 concepts (~45s on gemma
  in a clean 4-call session; it was ~4.5 min when the commit protocol ate the
  turn budget, so a slow run is itself a signal — triage it)

Drop `--quiet` to stream the harness's own verbose event log. Use
`--max-turns` / `--max-tool-calls` to bound a model that will not converge.

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
/opt/anaconda3/envs/llm_reconstruction/bin/python -m cognate_reconstruction.cli infer --preset lm-studio --model google/gemma-4-e4b --input examples/reconstruction_input.json --output runs/manual/result.json --trajectories runs/manual/trajectories.jsonl --events runs/manual/events.jsonl --temperature 0 --max-turns 16 --max-tool-calls 32
```

Other subcommands: `lm-studio-models`, `list-lexibank-varieties`,
`prepare-lexibank`, `inspect-run`, `validate-trajectories`,
`summarize-trajectories`, `export-trajectories`.

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
  `agent/SKILL.md`, or a different invocation is filtered out by design. The
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
  `tool_choice="required"` — once per node, then it gives up and behaves as
  before. Optionally, `--allow-truncation-backoff` with
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
  3. **Make the bound tighter, before the first node.** Lower `--timeout` so a
     genuine hang surfaces in minutes rather than a quarter of an hour. Note
     `--max-run-seconds` does *not* help: `_check_run_budget()` runs before and
     after an attempt and never during it, so no harness budget interrupts a call
     in flight.
  4. **Both knobs are hashed, so they are up-front decisions.**
     `--provider-config` and `--timeout` feed `configuration_sha256`: you cannot
     add a cap or shorten the timeout and still resume a checkpoint written
     without them. `driver.py run` sets neither, so use the human `infer` path
     when you want them.
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
- **Thresholds are CLI flags and *are* covered by the resume hash.**
  `--max-repeated-tool-failures`, `--stall-window-calls`,
  `--max-truncated-responses`, and both truncation-backoff flags are hashed into
  `configuration_sha256`, along with the `agent/SKILL.md` text, the tool
  schemas, and any `--anchors` file. Changing any of them makes an existing
  checkpoint refuse to resume, and the error names which one
  ("the agent instructions", "the tool schemas", "the anchor file", "the
  provider and limit settings"). Checkpoints written before 2026-08-15 refuse
  too, but can only say "the configuration" — they never recorded the parts.
  `max_window_protocol_failures` still has no flag; the CLI never sets it and
  its default derives from two flags that are hashed.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `__conda_exe:6: permission denied` | Use `/opt/anaconda3/envs/llm_reconstruction/bin/python`, not `conda run` / `make`. |
| `curl` to :1234 returns nothing, exit 000 | LM Studio server is off: `~/.lmstudio/bin/lms server start`. |
| `model 'X' is not reported by LM Studio` | Model is not loaded. Check `driver.py preflight` for loaded IDs. |
| `litellm MISSING` in preflight | Install the agent extra into the env (`pip install -e '.[agent]'` with the env's python; `make install` will not work here). |
| Run makes no progress but the process is alive | Almost certainly a slow turn, not a hang — this model returned after 5–7 minutes repeatedly. **Wait.** A real hang surfaces as `provider_retry` with `litellm.Timeout` after ~15 min per attempt with `--timeout 300`. Only investigate past that: `find runs/<dir>/events.jsonl -mmin +16 -print`. Prevent long turns next run with `max_tokens` in `--provider-config` and a lower `--timeout`; both are hashed, so they must be set before the first node. See the gotcha above. |
| Run ends in `AgentLoopLimitError` | Model never produced a valid commit and never failed densely enough to trip either stall condition — typically a session that keeps exploring, since exploratory rejections never count. Triage it; raise `--max-turns` or use a stronger model. |
| Run ends in `ProtocolStallError` | One of three things: a `(tool, error code)` signature recurred after a targeted correction; the trailing window filled with protocol rejections of mixed codes; or output was truncated repeatedly with no tool call. Read the message — the first two are tool-contract problems. For the third, the message states what the harness already tried (forcing a tool call, and any `max_tokens` backoff steps); what is left is raising `max_tokens` in the `--provider-config` JSON, or `--allow-truncation-backoff --truncation-max-tokens-ceiling N` to let the harness raise it for you. |
| `checkpoint cannot be resumed because these changed: ...` | Expected after editing `agent/SKILL.md`, the tool schemas, an `--anchors` file, or any hashed flag. The named part is the one to restore — or start a new checkpoint path. |
| `could not load prior hypotheses from ...` | `trajectories.jsonl` is present but does not validate. Do not delete it; a missing file only warns, so this is telling you the artifact is corrupt at the named line. |
| `PydanticSerializationUnexpectedValue` warnings | Known nonfatal LiteLLM/Pydantic noise. Tool execution and trajectories still succeed. |
| `[driver] inspect-run ... failed; the artifact sections are missing` | The timeline above it is still valid. Run the printed command yourself for the full error — usually a run directory holding neither `result.json` nor `trajectories.jsonl`, or a harness too old to have the subcommand. |
| `1 of 2 committed rules omit 'rationale'` | Expected on a multi-rule commit without per-rule reasoning. The remediation names the `rule_id`s; single-rule commits still need none. |
