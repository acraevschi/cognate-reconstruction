# Cognate Reconstruction Harness

An experimental workbench for LLM-assisted historical language reconstruction.
The model proposes linguistic hypotheses; deterministic tools expose evidence,
validate commitments, assemble candidate proto-forms, and preserve an audit trail.

**Status, 2026-10-05:** both rule cascades and proto-inventories are implemented.
Tasks 01–04 delivered diagnosis, evaluation and evidence repairs; task05 delivered
offline instruction/protocol changes but its local smoke failed. Substantive live
commit usability and reliable historical reconstruction remain unverified.
Task06 provider recovery is delivered offline with completed-node resume and
explicit interruption accounting. Review the final interface/manifest and verify
substantive live usability before comparative work.

## Start here

- [Current state](docs/current_state.md): what exists, the last results, known
  limitations, and which older decisions have been superseded.
- [Research plan](docs/research_plan.md): implementation order and decision points.
- Session handoff (`docs/session_handoff.md`, local and untracked): live task
  status, decisions, unfinished work and amendments carried into the next agent
  session. Absent from other checkouts.
- [Experiment policy](docs/experiment_policy.md): local-first testing, budgets,
  provenance, and interpretation of results. Read before any live run.

## How it works

1. Supply tokenized lexicons and a classification tree in Newick. CLDF ingestion
   retains source identity, cognacy memberships, partial slices, and provenance.
2. The harness traverses every internal node in post-order, preserving polytomies.
3. A node session examines its direct children and available evidence. Children
   may themselves be reconstructed candidate beams, not observed languages.
4. The model tests and commits either an ordered, child-scoped rewrite cascade
   or a proto-inventory mapping correspondence patterns to proto-segments.
5. Deterministic code executes the commitment, builds the parent beam, records
   diagnostics and trajectories, and checkpoints completed nodes.

Both commitment types remain supported. Inventories assemble a form across
aligned children; cascades transform each child's string. Rules can replace
segments with new symbols: inventories do not have an exclusive ability to emit
unattested proto-segments. Neither representation guarantees linguistic truth.

Historical targets are withheld evaluation data; anchors are explicitly visible
supplementary evidence with a declared policy. A supplied classification is
recommended; lexical tree induction is exploratory. A failed node may receive an
explicit identity fallback, which must be distinguished from a model commitment.

## Documentation map

| Document | Purpose |
| --- | --- |
| [Running inference](docs/running_inference.md) | CLI, inputs, tools, providers, checkpoints, reports |
| [Benchmarks](docs/benchmarks.md) | Dataset definitions, metrics, recorded experiments |
| [Analysis tools](docs/analysis_tools.md) | Offline probes, answer-key-assisted measurements, baselines |
| [Evidence contract](docs/research/evidence_contract.md) | units-v2 counts/bindings and units-v1 inherited pieces |
| [Evidence migration](docs/research/evidence_migration.md) | Current typed tools, trajectory 5.0 and checkpoint 3.0 compatibility |
| [Protocol revision](docs/research/protocol_revision.md) | Task05 corrected guidance, commit readiness and immutable preview handles |
| [Provider recovery](docs/research/provider_recovery.md) | Task06 bounded retries, safe resume and incomplete-outcome accounting |
| [Report, reject, or score](docs/report_reject_or_score.md) | Separate mechanical validity, workflow quality, and linguistic judgment |
| [Operator skill](skills/run-cognate-reconstruction/SKILL.md) | Operational recipes; use the experiment policy for current budgets and model preferences |
| [Runtime model prompt](cognate_reconstruction/agent/system_prompt.md) | Corrected model instructions; measured and tested in task05 |
| [Inventory design history](docs/proto_inventory_design.md) | Original design and dated experiment notebook; not the active task queue |
| [Shared-innovation proposal](docs/shared_innovation_note.md) | Deferred report design, not an implemented feature |
| [Previous README](docs/history/README-before-2026-09-15.md) | Preserved technical and decision history before this documentation reset |
| [Migration](MIGRATION.md) | Boundary with the predecessor corpus-generation project |

## Repository map

```text
cognate_reconstruction/
  schemas/       strict serialized contracts
  ingestion/     JSON/CLDF, provenance, tree preparation
  alignment/     LingPy alignment, correspondences, environments
  rules/         literal DSL parser, execution, contrast diagnostics
  traversal/     tree walk, beams, inventory assembly, checkpoints
  agent/         provider adapters, tools, model loop, trajectories
  evaluation/    exact and graded target comparisons
  benchmarks/    benchmark builder and repeated-run aggregation
  synthesis/     synthetic families and answer-key scoring
benchmarks/      published and synthetic definitions
examples/        fixtures, trees, sampler configurations
skills/         operator instructions and driver
tests/workbench/ supported product tests
tools/          offline research probes
```

`runs/` and local corpus checkouts under `data/` are ignored. Never commit keys,
large corpus checkouts, or raw live runs. Small redacted regression fixtures and
compact research summaries may be committed when a task needs them.

## Development and first checks

Python 3.11+; the existing local environment is `llm_reconstruction`.

```bash
conda run -n llm_reconstruction python -m cognate_reconstruction.cli --help
conda run -n llm_reconstruction python -m pytest -q -k 'not local_run_artifacts'
```

For a new environment, see `environment.yml` and `make install`. Do not rebuild a
working environment just to inspect it. Historical test totals are provenance,
not quotas: add tests for failure modes, not to make the count rise.

Before running an LLM, follow [experiment policy](docs/experiment_policy.md).
Prefer a loaded Gemma 4 26B or Qwen3.6 35B MoE-class model. Discover the actual
served identifier; do not assume a historical run directory names a loaded model.
Paid Gemini Flash is optional and sparing, never a routine test dependency.

## Development invariants

- Keep strict typed tools; no arbitrary model-supplied code execution.
- Preserve tokenization, dataset-scoped IDs, cognacy provenance and polytomies.
- Require exact same-session validation of the hypothesis being committed.
- Keep targets and synthetic answer keys outside model-visible evidence.
- Preserve uncertainty and distinguish observed evidence from reconstructed claims.
- Keep linguistic metrics report-only unless a later decision explicitly changes
  their role; workflow acceptance is not a linguistic grade.
- Preserve both commit paths and backward readability of recorded trajectories.
- Record failed and fallback nodes; never silently select them out of a comparison.
- Version behavior changes and compare frozen configurations. A repeated provider
  seed does not make an entire agent trajectory reproducible.
- Update the current-state summary when a task changes behavior or conclusions.
