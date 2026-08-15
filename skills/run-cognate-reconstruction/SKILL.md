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

Fastest way to confirm the core still works. Runs the unit suite (84 fixed
tests, plus one backward-compatibility check per `runs/*/trajectories.jsonl`
you have locally) and the CLDF fixture ingestion:

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

Reports the per-turn timeline with token growth and per-call ok/ERR, the failure
taxonomy, committed rules with scope, diagnostics, reconstructed forms, and the
`high_quality` flag with its protocol-failure rate. A failing run looks like:

```
FAILED TOOL CALLS: 3 of 7  (43% of tool budget wasted)
    1x  commit_reconstruction
        ValidationError: rules.0.confidence Field required; ...
```

Trajectories written before 2026-08-15 have no failure counters, so the
per-node line shows `failed=n/a` while the taxonomy above it still counts the
errors from `events.jsonl`. That is the expected reading of an older artifact,
not a bug.

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
`prepare-lexibank`, `validate-trajectories`, `summarize-trajectories`,
`export-trajectories`.

```bash
/opt/anaconda3/envs/llm_reconstruction/bin/python -m cognate_reconstruction.cli summarize-trajectories --input runs/google-gemma-4-e4b-20260814-184836/trajectories.jsonl
```

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
- **`high_quality` still is not a linguistic grade.** It now also fails a
  trajectory whose rejected share of tool calls exceeds
  `MAX_PROTOCOL_FAILURE_RATE` (0.25, in
  `cognate_reconstruction/agent/trajectory.py`), and `AgentNodeMetrics` carries
  `failed_tool_call_count` / `tool_failures_by_type`. Passing that gate means
  the workflow was clean, not that the reconstruction is right.
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
  elsewhere. Nodes restored from a checkpoint by `--resume` never ran in the
  process, so their hypotheses are not retrievable even though their lexicons
  are.
- **A repeated identical tool error now ends the node.** After
  `max_repeated_tool_failures` (default 3) rejections with the same error text
  anywhere in the node — not necessarily back to back — the orchestrator injects
  one targeted correction carrying the tool's remediation; one further
  recurrence raises `ProtocolStallError` instead of burning the turn budget. A
  model whose malformed arguments keep *changing* the error text still escapes
  this. `finish_reason="length"` is handled separately and also stalls after
  `max_truncated_responses` (default 3) truncated no-tool responses. Both are
  orchestrator constructor parameters with no CLI flag, and `infer` supplies its
  own `configuration_sha256` that excludes them — so changing either is *not*
  detected on `--resume`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `__conda_exe:6: permission denied` | Use `/opt/anaconda3/envs/llm_reconstruction/bin/python`, not `conda run` / `make`. |
| `curl` to :1234 returns nothing, exit 000 | LM Studio server is off: `~/.lmstudio/bin/lms server start`. |
| `model 'X' is not reported by LM Studio` | Model is not loaded. Check `driver.py preflight` for loaded IDs. |
| `litellm MISSING` in preflight | Install the agent extra into the env (`pip install -e '.[agent]'` with the env's python; `make install` will not work here). |
| Run ends in `AgentLoopLimitError` | Model never produced a valid commit and never repeated one error verbatim. Triage it; raise `--max-turns` or use a stronger model. |
| Run ends in `ProtocolStallError` | Either the same tool call was rejected identically after a targeted correction, or output was truncated repeatedly with no tool call. Read the message: the first case is a tool-contract problem, the second needs a larger `max_tokens` in the `--provider-config` JSON. |
| `PydanticSerializationUnexpectedValue` warnings | Known nonfatal LiteLLM/Pydantic noise. Tool execution and trajectories still succeed. |
