# Benchmarks and evaluation

What the harness can be measured against, how a new family is defined, and what
each measurement is and is not evidence for.

Three things are called "a benchmark" here and they answer different questions:

| Kind | Gold is | Answers | Leakage |
| --- | --- | --- | --- |
| **Published** (`benchmarks/*.json`) | a proto-form somebody published, or an attested ancestor | how the harness compares to the literature and to published baselines | severe, and not fixable |
| **Synthetic** (`benchmarks/synthetic/*.json`) | a proto-lexicon written in this repository | whether the harness recovers changes it cannot have memorized | none by construction |
| **Oracle ceiling** (`tools/oracle_ceiling.py`) | the same gold, with perfect rules supplied | what a flawless model could score under this architecture | not applicable |

An oracle number bounds the architecture. A live number measures a model. They
are never interchangeable and the sweep report prints them in separate blocks
for that reason.

## Building a published benchmark

A benchmark definition is a small declarative file, not code:

```bash
python -m cognate_reconstruction.cli build-benchmark --name polynesian
```

That reads `benchmarks/polynesian.json`, loads the local CLDF dataset it names,
selects the concepts where every chosen daughter shares a cognate set with the
gold variety, binds the gold variety as a hidden `target`, and writes
`runs/benchmarks/polynesian.json`. The payload is derived and gitignored; the
definition is the thing that lives in the repository.

`--definition <path>` builds a definition that is not checked in, in which case
`--output` is required.

Two definitions ship:

| Definition | Dataset | Gold | Daughters | Concepts selected |
| --- | --- | --- | --- | --- |
| `polynesian` | `data/lexibank/walworthpolynesian` | Proto-Polynesian (**a published reconstruction**) | 10 | 46 |
| `romance` | `data/lexibank/meloniromance` | Latin (**attested**) | 5 | 900 |

The Romance definition is the Ab Antiquo dataset (Meloni, Ravfogel & Goldberg
2021), so published neural baselines exist to compare against. Its 5,419 Latin
forms shrink to 900 concepts under the fully-cognate selection, because Romanian
attests only 1,506 forms and the selection requires every daughter.

Further candidates, not yet defined, all present in the local corpus:

- `hillburmish` — 9 varieties including `ProtoBurmish`, plus Old Burmese, so it
  would give **two gold nodes in one tree** and exercise the per-node accuracy
  curve on real data rather than only on a synthetic family;
- `mcd` — 60 varieties, several proto nodes at different depths
  (`protochuukic`, `protooceanic`, `protomalayopolynesian`);
- `acd` — 1,064 varieties, Proto-Austronesian, by far the largest and the one
  most likely to need `max_concepts`.

A definition for any of them is a file, not code. What is *not* mechanical is
deciding which should carry a claim, which is a research-owner question — see
README, "Decisions that require research-owner input".

### Selection is a design decision, not a filter

`concept_selection: fully_cognate_with_target` requires each daughter to share a
cognate set with the gold entry, not merely to have a form for the concept.
That is what makes the benchmark a test of *reconstruction*: the model is asked
to recover the ancestor of forms already known to be related. Selecting on
presence alone would silently mix in lexical replacement — Proto-Polynesian
`*f a n o` against Hawaiian `h a e l e` — which no phonological method recovers,
and would score a reconstruction system on a semantics problem.

### The one failure that is fatal and silent

If the gold variety stays in the lexicons, the model can read the answer and
every number the run produces is meaningless. `prepare_payload` removes bound
source varieties unconditionally and `assert_targets_are_hidden` refuses the
payload if one survived, per binding rather than for the first only —
a second target added to an existing definition is exactly when this gets
forgotten. The definition schema refuses a gold variety listed as a daughter
before any data is read.

### Every published benchmark has a leakage problem

The harness deliberately keeps directionality judgement in the model's own
knowledge rather than in a table in this repository. That is the right division
of labour and it means a model that has read the literature on Polynesian can
produce `*ʔ` from memory instead of from the correspondence set. Latin is worse,
not better: it is attested, and it is also in everyone's training data.

What the artifact supports is a **check**, not a proof. A trajectory records
every `polarize` call with its arguments and results, and the
`directionality_rationale` that a contrast-reducing rule cannot be committed
without, so a reviewer can ask whether the session consulted the out-groups
before committing. `inspect-run` reports the structural part of that under
`directionality` in each node's session block:

- a contrast-reducing rule committed with no `polarize` call at all;
- every `polarize` call returning **no out-group**, which is what the root looks
  like — nothing lies outside it, so every available node is a descendant and
  therefore inside the proposition under test;
- evidence retrieved and out-groups found.

The middle case is what the first live run produced at `proto_polynesian`, where
a rationale cited out-group support that `polarize` had not returned. Nothing
here reads the rationale's prose and nothing gates on it: a memorised answer
dressed in a citation of real evidence is indistinguishable from a derived one,
and whether a particular rationale is *wrong* still needs a human. See
[report, reject, or score](report_reject_or_score.md).

A benchmark definition records `provenance.publication_date`, because the other
leakage-controlled option needs no new code: a gold set published after a
model's training cutoff is a `build-benchmark` definition plus a recorded date.

## Running a benchmark several times

The same input fails differently on every run. Single runs are not comparable
and any number quoted from one is noise.

```bash
python -m cognate_reconstruction.cli run-benchmark \
  --benchmark polynesian --model google/gemma-4-26b-a4b --preset lm-studio \
  --seeds 5 --out-dir runs/sweep-polynesian
```

Each repetition runs in its own subprocess and its own directory, so a seed that
crashes costs one seed rather than the sweep. The aggregate is written as
`aggregate.json` and `aggregate.txt` and is the artifact a human should read:
every rate comes with its spread across seeds, and the per-seed table sits
beside it, which makes a single number from a single run hard to quote by
accident.

Two shapes of seed are reported separately and never conflated:

- **finished with losses** — `result.json` exists, some nodes were walked over
  as identity fallbacks, and `node_failures` names them;
- **abandoned** — `--max-failed-nodes` was exhausted, the run raised
  `TooManyNodeFailuresError`, and no `result.json` was written at all, so its
  losses are not in `node_failures` either. The taxonomy counts it under
  `run-abandoned-no-result`.

A fallback node is never counted as a completion and never scored against gold.
A run that scores seven nodes when two of them are fallbacks is exactly the
false number this harness exists to avoid.

The aggregate also carries the two numbers that say *how* a node reached its
coverage — `contrast_reducing_rules_per_node` and
`held_out_convergence_rate_per_node` — so a seed that scored well by discarding
distinctions is visible across seeds rather than only inside one report. With
`--provider-seed-base`, each repetition gets a provider config carrying an
explicit `seed`; without it, repetitions differ by whatever nondeterminism the
provider has, and the aggregate says so.

## Synthetic families: gold by construction

The one evaluation a model cannot have memorized.

```bash
python -m cognate_reconstruction.cli build-synthetic --name synthetic_hard
```

Writes `runs/benchmarks/synthetic_hard.json` (the payload) and
`runs/benchmarks/synthetic_hard.answer-key.json` (the truth), **never the same
file**. The generator runs `RuleEngine.apply_rules` forward — parent to child —
down the tree, so the daughters fall out of a proto-lexicon and a per-branch
cascade written in the same DSL the model commits in.

A branch is named by its *lower* end, so a cascade on an internal node is a
shared innovation inherited by everything below it, and subgrouping becomes
recoverable from the data rather than only asserted by the tree.

Three families ship:

| Family | Daughters | Concepts | What it contains |
| --- | --- | --- | --- |
| `synthetic_regular` | 4 | 16 | One shared innovation per subgroup, one private innovation per daughter, every branch invertible. The control. |
| `synthetic_hard` | 5 | 25 | A merger only a sister disambiguates; a segment lost everywhere except one branch; a chain shift whose rules must be ordered; a conditioned split. Gold at three nodes. |
| `synthetic_noisy` | 4 | 16 | `synthetic_regular` with two irregular forms, a loan, and a semantic mismatch. |

Under oracle rules `synthetic_regular` scores 16/16 top-1 and
`synthetic_hard` 22/25 top-1 with 25/25 in the beam — which is the property that
says these are sound benchmarks rather than hard ones: the gold is reachable,
and what is lost is lost in selection.

### Noise is a knob, off by default

`noise` takes `irregular_forms`, `loans`, and `semantic_mismatches` with a seed.
A benchmark with no residue is not a test of the anomaly machinery, and a model
that only ever sees perfect regularity learns the wrong lesson about what a
comparative argument looks like. Every perturbation is recorded in the answer
key, so what a run put in `anomalies` can be compared against what was actually
done. The answer key's lexicons are the **regular** output of the cascade,
before noise: a rule cannot be expected to undo a perturbation the definition
introduced on purpose.

### One case the DSL cannot express, and why that is stated rather than fixed

There is no empty-target insertion, so a branch that lost a segment can never
restore it. A generated family whose gold required one would be *unreachable*
rather than hard. The answer key therefore records `invertible: false` for every
branch containing a deletion and gives it no inverse cascade, so scoring never
charges the model for a rule it cannot write. `synthetic_hard` uses this
deliberately: `*ʔ` survives in exactly one daughter, and the harness reaches it
through that daughter's own candidate in the beam rather than through any rule.
See `tools/branch_recoverability.py` and `prompts/06-proto-inventory.md`.

### Scoring the changes, and the direction

```bash
python -m cognate_reconstruction.cli score-synthetic \
  --answer-key runs/benchmarks/synthetic_hard.answer-key.json \
  --run-dir runs/my-run
```

Three measurements, in increasing order of how much they mean:

- **rule precision and recall** — committed rules matched structurally against
  the true child-to-parent cascade. Deliberately literal: `e > a / ʔ_` and
  `ʔ e > ʔ a` do not match. Read it as a lower bound.
- **functional recovery** — apply the committed cascade for a branch to that
  branch's gold forms and ask whether the parent's gold forms come back. This
  survives a different spelling of the same change.
- **directionality** — free here and checkable nowhere else. The branch that
  innovated is the branch the definition gave a rule to, so a rule scoped to a
  branch the answer key left empty is a rule pointed at a branch that did not
  change, whatever its `directionality_rationale` asserts. That is the one
  measurement that speaks directly to the failure prompt 04 exists to prevent.

All three are reports. Nothing here gates a trajectory, weights a candidate, or
decides whether a run was valid.

**Read `misdirected_rule_count` against `failed_nodes`.** When a node below the
committing one was walked over as an identity fallback, its children's forms
reach the parent unchanged, and a rule the model then scopes to that fallback
node may be attributing a real change to the wrong *level* rather than to a
branch that did not change. A live two-seed sweep on `synthetic_regular` shows
both shapes at once: the seed that committed all three nodes put `p > f` on
`inner_b`, which genuinely did not innovate, and scored 10/16 at the root; the
seed that lost both inner nodes committed the whole cascade at the root
instead, scoped to the two fallback nodes, and scored **16/16** — the right
forms, attributed to the wrong branches, with a rule precision of 0.25. Nothing
but an answer key separates those two runs, and a single accuracy would have
called the second one the better of the two.

## Graded metrics

Exact token equality cannot distinguish a reconstruction one segment off from an
unrelated one, so it says almost nothing about whether a change worked. Every
`HistoricalTargetEvaluation` now carries three graded measures beside the exact
counts, per concept and aggregated, with distributions rather than pooled means:

- **edit distance** and **normalized edit distance** between the top candidate
  and the nearest gold alternative, over segment tokens rather than characters.
  Lower is better — the opposite polarity to every accuracy in this repository,
  which is why every printed line says so.
- **B-Cubed F1** over the columns of the alignment, following the SIGTYP 2022
  shared task. The exact variant implemented is documented in
  `cognate_reconstruction/evaluation/metrics.py`; it measures *structural*
  agreement, so `p a` against `b e` scores 1.0 while its NED is also 1.0. That
  is the point of having both: a wrong-but-consistent correspondence is a
  different failure from a guess.
- **the beam-aware variant** — the best NED any retained candidate reached,
  beside the top candidate's. The distance between them is the graded selection
  gap and is the single most useful number for deciding whether selection or
  generation is the bottleneck.

They appear in `result.json`, in `inspect-run` (inside each node's
`DETERMINISTIC OUTCOME` block, never above it), and in
`summarize-trajectories --result <result.json>`.

**"Held out" means two different things and they are named apart.**
`held_out_convergence_rate` is a per-node split of the *session's own* concepts
and makes no claim about correctness; it never leaves the node.
`HistoricalTargetEvaluation` is the answer key. `inspect-run` prints the first
as `held-out concepts` and the second as `gold exact` / `gold distance` /
`gold b-cubed`; `summarize-trajectories` keeps the second under
`gold_target_evaluation`.

## Recorded baselines

Polynesian, 46 concepts, beam width 5. The oracle bounds the architecture; the
live figures measure one model on one seed.

| Measure | Oracle ceiling | Live `google/gemma-4-26b-a4b` |
| --- | --- | --- |
| top-1 exact | 27/46 — 58.7% | 21/46 — 45.7% |
| beam exact | 39/46 — 84.8% | 31/46 — 67.4% |
| exact selection gap | 26.1 points | 21.7 points |
| mean top NED | 0.158 | 0.214 |
| mean beam-best NED | 0.043 | 0.081 |
| NED selection gap | 0.115 | 0.133 |
| mean top B-Cubed F1 | 0.960 | 0.950 |

The live row is `runs/google-gemma-4-26b-a4b-20260820-212424`, one seed, seven
nodes attempted, five committed and two walked over as identity fallbacks. It is
a starting point, not a result: one seed is not a measurement, which is what
`run-benchmark` exists to fix.

The oracle-ceiling figures are pinned in the suite by
`tests/workbench/test_oracle_ceiling_regression.py`, including the gap between
them, so a change to the beam cannot quietly make reconstructions worse while
every test passes.
