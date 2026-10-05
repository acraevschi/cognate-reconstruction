---
name: run-cognate-reconstruction
description: Operate and inspect the cognate-reconstruction harness: deterministic checks, bounded local interface smokes, separately authorized experiments, and evidence-based triage of rules or proto-inventory runs.
---

# Run the cognate-reconstruction harness

The harness gives each internal tree node a model session over its direct children.
The model commits a proto-inventory or ordered child-to-parent rules; deterministic
tools validate and construct parent beams. Execution and protocol completion do
not establish linguistic correctness. There is a CLI and artifact reporting;
local inference additionally needs a model server.

The source of truth is `skills/run-cognate-reconstruction/driver.py` and this
tracked skill. `.claude/skills/run-cognate-reconstruction/` is an installed copy
and can lag. Prefer the tracked paths. Read `docs/session_handoff.md`,
`docs/current_state.md` and `docs/experiment_policy.md` before live work.
The latest direct user instruction takes precedence. Do not infer permission to
run a broad comparison from permission for a smoke.

## Offline checks first

Use the existing `llm_reconstruction` environment; the driver locates its Python,
with optional COGNATE_PYTHON override. Verify the actual environment rather than
assuming historical machine/version observations still apply. Do not install or
rebuild dependencies merely because an environment check fails.

Run relevant semantic tests after changes. One portable suite at completion is:

```sh
conda run -n llm_reconstruction python -m pytest -q -k 'not local_run_artifacts'
```

The deterministic driver additionally checks the small CLDF fixture:

```sh
python3 skills/run-cognate-reconstruction/driver.py smoke
```

It runs the portable suite, so do not invoke it after the same suite has already
passed unless a new change/failure justifies repetition. There is no fixed expected
test count. If conda fails in the current environment, use the env interpreter
directly; an old sandbox failure is not a permanent property of conda.

Task04 ordinary evaluator controls and task05 stored-hypothesis controls:

```sh
conda run -n llm_reconstruction python tools/evidence_repair_controls.py --output-dir /tmp/task04-controls-new
conda run -n llm_reconstruction python tools/protocol_revision_probe.py --output-dir /tmp/task05-controls-new
```

Use a fresh directory. These are operator-scripted controls, not live ability.
Current evidence is units-v2/count independent-etyma-v1, piece representation
units-v1, raw evaluator task02-v1 and explicit piece evaluator task04-units-v1.
Preserve scorer-only targets and all alternatives. No source-backed tone category
mapping is licensed. Read the evidence/evaluation contracts for denominators,
proxy gold, unresolved units and failure/fallback readings.

## Discover and select a local model

Check availability when ready for live use. Never choose an ID from memory:

```sh
python3 skills/run-cognate-reconstruction/driver.py preflight --no-autostart
conda run -n llm_reconstruction python -m cognate_reconstruction.cli lm-studio-models
curl -s --max-time 8 http://127.0.0.1:1234/v1/models
~/.lmstudio/bin/lms ps --json
```

The first checks dependencies and API reachability without starting the server.
The endpoint may list downloaded models; confirm loaded status, quantization,
context and idle state with lms/current metadata. An answering endpoint with zero
loaded models is insufficient for a smoke. If unavailable, finish offline work
and report the missing prerequisite; the owner can prepare the model. Do not load,
download or displace models or switch to a paid provider automatically.

Prefer a currently loaded tool-capable Gemma 4 26B or Qwen3.6 35B MoE-class model,
as the experiment policy specifies. Qwen3.8 27B is too slow for routine work here.
If both preferred choices are loaded, select one and record why. A smaller model
can check protocol with that limited interpretation. Pass the actual served ID
verbatim, including vendor prefix; lm-studio adds openai/ in trajectory metadata.
The driver also confirms actual loaded local instances and refuses catalogue-only or
busy models before creating a run. Its lms loaded-state check is local; remote
instances require their own loaded-state preflight.
Keep inference serial; inspect existing harness processes and server traffic first.
Do not kill unrelated jobs or assume a model's context fits another model.

Read current help before launch:

```sh
python3 skills/run-cognate-reconstruction/driver.py run --help
conda run -n llm_reconstruction python -m cognate_reconstruction.cli infer --help
conda run -n llm_reconstruction python -m cognate_reconstruction.cli run-benchmark --help
```

## Bound and freeze a smoke

A smoke asks whether an interface works on one representative fixture. The default
policy envelope is one node/run, at most 36 turns/80 calls and 1800 seconds; start
smaller when sufficient. These are caps, not a promise of completion. Time/cost
checks occur between requests and cannot interrupt a call in flight. State request
timeout/retries and allow for provider-side retries. Do not launch repeated broad
sweeps because one smoke fails.

Freeze a manifest before inference: question, stopping/interpretation rules,
code revision and dirty diff identity, input/tree hashes, target validity,
evidence/evaluator versions, actual model/quantization/context, effective sampler
and thinking settings, instruction/tool-schema/node-checklist hashes, protocol,
selection/filter policy and per-node/run resources. A success needs the actual
survey, inspected preview and nonempty commit followed by execution; a failed
or identity-only shortcut does not demonstrate that workflow.

Use the source driver, with an actual served ID substituted:

```sh
python3 skills/run-cognate-reconstruction/driver.py run --model ACTUAL_SERVED_ID --input FROZEN_INPUT --provider-config MODEL_SAMPLING_JSON --temperature 0.1 --max-turns 24 --max-tool-calls 60 --max-run-seconds 1800 --timeout 300 --max-retries 0 --no-autostart
```

Choose sampler and temperature for the stated question, not by copying this example
across models. `examples/sampling/README.md` records model-specific provenance:
Gemma's stored config uses top_k=64, top_p=.95, repeat_penalty=1;
Qwen's uses top_k=20, top_p=.95, min_p=0, repeat_penalty=1. The files omit
temperature; the CLI flag determines it. Historical Qwen sweeps used 1.0 rather
than the documented thinking-mode .6; retain that deviation with their results.
Task03's Gemma smoke used .1 and max_tokens=8192; it stalled without a commit.
Neither sampler is a demonstrated universal optimum.

LM Studio panel defaults fill omitted request settings and are invisible to the
configuration hash. Send intended settings through provider-config, and record
unobservable server/template thinking settings separately. Check safe request
metadata after adapter changes. max_tokens must allow reasoning plus the proposed
tool payload; a stored handle reduces final retranscription but does not eliminate
preview output or reasoning. Seeded multi-turn histories are not exact replays.

## Inventory protocol and exact linkage

Default `--inventory-protocol stored-hypothesis` offers compact local choices
(set_id, explicit proto_segment/null, confidence and explanations) and resolves
only harness-owned reflexes/support. Shared claims explicitly select pattern members.
`test_proto_assembly` reports executable versus commit_ready and missing explanations.
A ready hypothesis_id freezes the exact inventory for commit with node_id, summary
and anomalies. Handle commits reject payload/overlay edits; changed choices,
collections, explanations or evidence need a new preview. Handles are session-local,
not checkpoint state. The persisted commitment is the full validated inventory;
trajectory preview calls retain submitted choices and approved_shared_claims retains
shared selections.

`--inventory-protocol full-payload` disables compact choices/handles while keeping
the full inventory and rule paths. `--agent-instructions PATH` independently selects
system text by its content hash. Node commit notes and tool descriptions still
belong to the runtime package; changing only that file is a system-text comparison,
not an isolated ablation of every linguistic instruction. Freeze actual schemas
and note hashes. No countdown is implemented: task01 had no 36-turn failure.

Instruction/schema/evidence/node-checklist hashes are strict resume boundaries.
New trajectories remain 5.0 and checkpoints 3.0; old trajectory/checkpoint audit
readers remain supported, but checkpoints 1.0/2.0 cannot resume under units-v2.
Changing semantic arms needs a new checkpoint/run. Give-up thresholds may have
separate advisory handling; they do not waive a validation or schema check.

## Inspect and triage

```sh
python3 skills/run-cognate-reconstruction/driver.py triage --run-dir RUN_DIR
conda run -n llm_reconstruction python -m cognate_reconstruction.cli inspect-run --run-dir RUN_DIR
conda run -n llm_reconstruction python -m cognate_reconstruction.cli visualize-run --run-dir RUN_DIR
```

Triage reads event rejection counts and the timeline. inspect-run reads stored
hypotheses, beams and diagnostics; visualize-run shows requests/results together.
Old records without counters require events; missing metadata is not zero usage
or proof of provider cause. high_quality is a protocol/export diagnostic, not a
linguistic grade. Report cumulative request tokens separately from the largest
request/context size and cached subsets; character counts are not token counts.

ProtocolStallError means recorded repeated/mixed protocol failures or truncation;
inspect exact codes/remediation before changing a budget. AgentLoopLimitError is
a limit outcome. Provider interruptions, abstention, model commits, direct identity
fallbacks and ancestors consuming failed nodes have different readings. A slow
live request is not distinguishable from a stuck request by an idle process alone;
use events and the stated timeout envelope. Do not silently retry a whole smoke.
Preserve incomplete trajectories/checkpoints before any authorized recovery.

## Comparative or hosted experiments

Task07 requires instrument/cap/manifest checks, task05 usability, relevant task06
completion or its bounded exception, and a focused independent interface/manifest
review unless the owner scopes it out. Begin with one baseline and one candidate
on identical small inputs, serially, within the policy's two-hour initial pilot.
Identify an evidence/instruction package wherever pure isolation is unavailable.
A shorter prompt or successful commitment alone is not better reconstruction.

Hosted Gemini is optional only for task07 or a later explicitly authorized question;
it is not a smoke fallback. Current default is one small pilot, US$2 total and
30 minutes, with current model/pricing discovery and explicit worst-case bounds.
Use existing credentials via the environment without displaying/reading secrets.
Do not enable search/grounding or retrieve target reconstructions. Unknown costs
are not zero and historical provider IDs, quota causes and caching percentages
are not current facts. See experiment_policy.md for the full budget requirements.
