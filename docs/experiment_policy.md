# Experiment and testing policy

Research-owner preferences recorded 2026-09-15. Applies to every implementation
prompt. These are resource defaults for future work, not an instruction to start
inference during documentation or review tasks.

## Test in this order

1. **Offline checks first.** Inspect banked results, run pure deterministic probes,
   exercise typed tools with scripted/fake providers, and add small regression
   fixtures for demonstrated failures. No server is necessary.
2. **Focused tests after edits.** Select the relevant existing test modules. Test
   behavior and invariants, not source wording or a copy of the implementation.
3. **One full portable suite at completion of a substantive change.**
   `conda run -n llm_reconstruction python -m pytest -q -k 'not local_run_artifacts'`.
   The excluded cases opportunistically read local runs; checked-in fixtures must
   cover required compatibility. Run local-artifact cases only when relevant.
4. **A bounded local smoke if model behavior changed.** Prove the interface works,
   not that reconstruction quality improved. Pure metrics, schema migrations and
   retry logic normally need no live model.
5. **Controlled local experiments only for a stated unresolved question.** A
   repeated full-family sweep is not routine regression testing.

Do not insist that test totals increase, or rerun all tests without a new change
or unresolved failure. Record actual commands and outcomes. Historical “535” or
“276” totals are not current expectations. A failed environment check is not a
linguistic finding; do not silently rebuild the environment or change dependencies.

## Local models and hardware

Prefer a currently loaded, tool-capable **Gemma 4 26B** or **Qwen3.6 35B MoE-class**
model. These are the practical upper range specified for this Mac, not exact
served identifiers. Qwen3.8 27B is too slow for routine use here; do not choose it
merely because it is available. A smaller local model is fine for protocol smoke
checks, with its narrower evidentiary role stated.

Discover identifiers via `cognate-reconstruct lm-studio-models`, the operator
preflight, or `/v1/models`; confirm loaded status/context with LM Studio/lms.
When both preferred models are loaded, choose one and record why; no new approval
is needed for an ordinary bounded local check within the assigned task. If none
is usable, report the missing prerequisite and continue offline work. Do not
silently switch to a paid API, download a model, or displace a user's loaded model.

Read `skills/run-cognate-reconstruction/SKILL.md` for operational details, but use
this policy for current model preferences, budgets and testing scope. Its old
machine/version/test-count observations are historical. The tracked driver is
`skills/run-cognate-reconstruction/driver.py`; a `.claude/` installed copy may
exist, but is not the source of truth and may lag. Verify CLI help before use.

Keep local inference **serial**. Before launching, check for existing harness
jobs/server traffic. Never kill unrelated processes or launch competing sweeps.
Memory, context capacity and tokenizer differ between models: do not infer that a
prompt fitting one fits another, and do not universally force a 131K context.
Prefer a representative small fixture that fits, record quantization/context,
and monitor swap and generation speed in the first pilot.

## Default local run envelope

For implementation smoke checks: one representative node/fixture, one run,
`--max-run-seconds 1800`, at most 36 turns and 80 tool calls per node. These are
caps, not targets or promises that a run completes. Start smaller when sufficient.
The optional reminder experiment must distinguish the turn cap from the call cap.

For prompt 06: begin with one baseline and one candidate run on the same small
fixture. Plan at most **two hours total local inference** for the first pilot
batch, serially. Only use remaining time for a prespecified replication if it
can answer the question. A larger study requires a concrete expanded plan with
estimated runtime; do not keep appending seeds because results are disappointing.

Check current `infer --help` and `run-benchmark --help`. Some controls must be
forwarded through repeated `--infer-arg=...` values. Per-run time/cost caps in a
sweep apply to individual subprocesses, not the entire experiment: enforce the
overall envelope in the launch plan as well. A hard cap ending a run is a resource
outcome and should not be described as evidence of model incapability.

## Gemini Flash: optional, sparse and bounded

The user permits sparing Gemini Flash use; do not demand approval again merely
because a task uses a paid API within this scope. It is not a test-suite dependency
or the automatic fallback when local inference is inconvenient.

Only prompt 06 (or an explicitly authorized later experiment) should spend API
money under this plan, after offline/local evidence identifies a specific question
that a stronger/different model could resolve. Default ceiling: **one small pilot,
up to US$2 total across requests and retries**, with a 30-minute wall-clock cap.
Use existing credentials through their environment variable; never print keys,
inspect secret files in logs, or record them in manifests. Confirm the currently
available Flash identifier and pricing before estimating a run; old costs and
historical billing balance are not current facts.

Before starting, state the question, expected cost and cap. If the adapter does
not report usable costs, bound the worst case through explicit input/output token
limits and current pricing or do not start. The harness cost check acts between
requests: reserve enough headroom for one maximum-size in-flight response so the
whole experiment respects its budget. Missing cost metadata is not zero cost.

Stop on the budget, repeated provider unavailability or a completed answer to the
pilot question. Do not queue further paid seeds or change models automatically.
If more than this default envelope would be useful, finish the offline analysis
and propose a concrete expansion; no permission is required for that analysis.
Do not enable search or grounding: target retrieval would change the task.

## Freeze the comparison

Before live inference record a compact manifest under `runs/experiments/<name>/`:

- question, hypothesis, primary metric and secondary diagnostics;
- code revision plus dirty-state/diff identity, input/tree hashes, evaluation version;
- target bindings and whether they are valid targets, provisional proxies, or synthetic;
- actual model ID, quantization, context, sampler, reasoning settings, instruction
  and tool-schema hashes, seed policy, commit shape/selection policy;
- per-node and whole-run budgets, retry policy, maximum runs and total resources;
- which runs/fixtures are controls, exact stopping rules, and exclusions;
- how a null, improvement, regression, infrastructure failure or inconclusive
  result will be interpreted.

A sampler in `examples/sampling/` is a starting point with provenance, not a
universal optimum. Inspect effective request settings. Preserve the same sampling
within each comparison; explain unavoidable cross-model differences.
Provider seeds do not reproduce multi-turn agent histories. Pair by the same
input/node/model/configuration except the intervention, not by an assumed shared
random trajectory. Never mix instruction hashes in a resumed run without a
schema-supported, explicitly justified compatibility policy.

## Report honestly

Report per node and dataset, and distinguish:

- success at the protocol and successful linguistic outcomes;
- model failures, infrastructure interruptions, missing data and identity fallbacks;
- quality conditional on a model commit versus end-to-end outcomes on the intended
  evaluation set (including separately labelled fallback results and missing outputs);
- ordinary exact/NED, graded diagnostics, and outside-selection exact hits;
- development cases used to guide edits versus held-out evaluation cases.

Do not drop copying commits to inflate scores. Do not count absent outputs as
correct or silently change denominators. Preserve all gold alternatives and label
proxy gold. Report runs/concepts as repeated or nested observations; tiny samples
support a pilot, not causal claims about all models. Standard deviation is not a
confidence interval. Do not require non-overlapping SD ranges to declare any
possible improvement. For larger comparisons, predefine an uncertainty method
that respects the sampling unit and a practically meaningful effect.

Store raw artifacts in ignored `runs/`, compact conclusions in tracked
`docs/research/`, and only necessary redacted fixtures in tests. Never overwrite
the old experiments or quietly rescore them under a new name without preserving
the evaluator version and original measurement.
