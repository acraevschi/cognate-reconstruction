# Benchmarks and evaluation

> **Current reading, 2026-09-15:** see [current state](current_state.md) and
> [experiment policy](experiment_policy.md). This guide mixes implemented
> interfaces with dated measurements. The September evaluation improvements are
> planned, not yet reflected in the schemas or aggregate behavior below.
> Outside-selection hits are evidence beyond literal selection, not a proof of
> historical inference. Old Burmese at `burmic` is a provisional proxy target.
> Existing per-word B-Cubed measures aligned repetition structure, not consistency
> of a phoneme mapping across a lexicon. Always read it beside exact match/NED.


What the harness can be measured against, how a new family is defined, and what
each measurement is and is not evidence for.

Three things are called "a benchmark" here and they answer different questions:

| Kind | Gold is | Answers | Leakage |
| --- | --- | --- | --- |
| **Published** (`benchmarks/*.json`) | a proto-form somebody published, or an attested ancestor | how the harness compares to the literature and to published baselines | severe, and not fixable |
| **Synthetic** (`benchmarks/synthetic/*.json`) | a proto-lexicon written in this repository | whether the harness recovers changes it cannot have memorized | none by construction |
| **Oracle ceiling** (`tools/oracle_ceiling.py`) | the same gold, with perfect rules supplied | what a flawless model could score under this architecture | not applicable |
| **Assembly ceiling** (`tools/assembly_ceiling.py`) | the same gold, assembled column-wise | what a flawless *assembler* could reach if a proto-form were built per correspondence set rather than selected whole | not applicable |

An oracle number bounds the architecture. A live number measures a model. They
are never interchangeable and the sweep report prints them in separate blocks
for that reason. The two ceilings are likewise not interchangeable with each
other: both are bounds on a perfect chooser, and neither is a target.

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

Three definitions ship:

| Definition | Dataset | Gold | Daughters | Concepts selected |
| --- | --- | --- | --- | --- |
| `polynesian` | `data/lexibank/walworthpolynesian` | Proto-Polynesian (**a published reconstruction**) | 10 | 46 |
| `romance` | `data/lexibank/meloniromance` | Latin (**attested**) | 5 | 900 |
| `burmish` | `data/lexibank/hillburmish` | Proto-Burmish (**reconstructed**) *and* Old Burmese (**attested**) — two gold nodes | 7 | 54 |

The Romance definition is the Ab Antiquo dataset (Meloni, Ravfogel & Goldberg
2021), so published neural baselines exist to compare against. Its 5,419 Latin
forms shrink to 900 concepts under the fully-cognate selection, because Romanian
attests only 1,506 forms and the selection requires every daughter.

The Burmish definition is the one with two gold nodes; see *Burmish: the family
with two gold nodes* below for what it is, and §7.19 of
[the design document](proto_inventory_design.md) for the argument that the live
before/after comparison should be read there rather than on `polynesian` or
`romance`.

Further candidates, not yet defined, both present in the local corpus:

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

The same input can produce different trajectories on repeated runs. A single
run is useful for debugging or a labelled pilot, but cannot establish a stable
quality difference. Plan repetition according to the question and budget, not a
mandatory seed count. See the experiment policy before launching this example.

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

Current sweep aggregates exclude fallback evaluations from the committed-node
quality distribution and count them separately. A fallback may still have a
labelled target evaluation in its result. This conditional view is not an
end-to-end success rate; prompt 02 adds explicit intended-set outcomes without
counting a fallback as a model commitment.

The aggregate also carries the two numbers that say *how* a node reached its
coverage — `contrast_reducing_rules_per_node` and
`held_out_convergence_rate_per_node` — so a seed that scored well by discarding
distinctions is visible across seeds rather than only inside one report. With
`--provider-seed-base`, each repetition gets a provider config carrying an
explicit `seed`; without it, repetitions differ by whatever nondeterminism the
provider has, and the aggregate says so.

## Synthetic families: gold by construction

Generated families separate their answer keys from the model payload. Fresh,
withheld synthetic cases reduce memorization risk; repeatedly tuning against the
same checked-in family still overfits the benchmark. Synthetic truth also needs
an identifiability check: daughters do not always determine a unique ancestor.

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

Under oracle rules `synthetic_regular` scores 16/16 top-1 and `synthetic_hard`
22/25 top-1 with 25/25 in the beam — which is the property that says these are
sound benchmarks rather than hard ones: the gold is reachable, and what is lost
is lost in selection. `synthetic_noisy` scores 16/16.

**Read `synthetic_hard`'s figure as re-derived, not as unchanged.** Until
2026-08-22 `oracle_ceiling.py` took the first `target` binding rather than the
root's, and this family carries gold at three nodes with `east` written first —
so the published 22/25 was the *root* beam scored against `east`'s gold, under
the root's name. Against `proto`'s own gold the same oracle scored 15/25, and
the seven missing concepts were the chain shift this family was built to contain,
mis-ordered by `order_rules()`. Both defects are fixed; the root now scores
22/25 against its own gold, and the two 22/25 figures are different
measurements that coincide. Per node, beam width 5, context-free oracle:

| `synthetic_hard`, `--gold-node` | top-1 | beam exact |
| --- | --- | --- |
| `proto` (the default: the root's own binding) | 22/25 | 25/25 |
| `west` | 22/25 | 25/25 |
| `east` | 22/25 | 22/25 — misses `leaf`, `tooth`, `tree` |

`east` is the interesting row and it is the one §1.4 of
`docs/proto_inventory_design.md` is about: both of `east`'s children lost `*ʔ`,
so no rule and no assembly recovers it there. The segment survives the run only
because `west` retains it and the root can still see it.

`--oracle contextual` reaches the same 22/25 on this family — the changes are
regular and unconditioned, so there is nothing for an environment to buy.

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

## What a live number was sampled with

A live figure is a measurement of one model *under one sampling configuration*,
and until 2026-08-24 this repository did not record the second half. The harness
sends `temperature`, `timeout` and `--provider-config` and nothing else about
sampling, so `top_k`, `top_p`, `repeat_penalty` and `min_p` were being supplied
by whatever the LM Studio Developer tab happened to hold. `configuration_sha256`
hashes what the harness sends; it cannot see a server-side panel. Two runs with
the same hash could therefore have been sampled differently, with nothing in the
artifact saying so.

It is not a theoretical gap. At `temperature 0`, sending `repeat_penalty: 1.0`
produces different output from letting LM Studio's default 1.1 apply — a
repetition penalty is a logit modifier applied *before* selection, so greedy
decoding is not immune to it — while `top_k` and `top_p` genuinely are no-ops
there, because truncating a distribution that is then argmax'd cannot remove the
argmax. Above temperature 0 they are live again.

**Every sweep from 2026-08-24 pins the model's own published configuration and
sends it explicitly**, so it lands in `configuration_sha256` and in the
trajectory's `provider_options`:

```bash
printf '{"top_k": 64, "top_p": 0.95, "repeat_penalty": 1.0}\n' > runs/sweeps/gemma-sampling.json
```

with `--temperature 1.0` on the command line. Those are Gemma's published
`generation_config` values — `do_sample: true`, `temperature 1.0`, `top_k 64`,
`top_p 0.95`, and no repetition penalty, which is why 1.0 rather than LM
Studio's 1.1 is the setting that matches the model rather than the client.

Temperature 1.0 is also what makes `--provider-seed-base` mean anything: greedy
decoding never consults a seed, so a five-seed sweep at temperature 0 is one
configuration run five times and its "spread" is server nondeterminism. That is
why `run-benchmark` defaults to a non-zero temperature, and why a sweep quoted
without its sampling configuration is a number whose reading is not stated —
the same objection §7.3 of `docs/proto_inventory_design.md` makes to a
correspondence count quoted without its flags.

## Burmish: the family with two gold nodes

`benchmarks/burmish.json` is the second published family, and its point is
condition 6 — *does a reconstructed child make a usable parent?* Answering that
needs two gold nodes, one above the other, and Polynesian has one. Of the nine
`hillburmish` varieties, only `ProtoBurmish` is a reconstruction; Old Burmese is
an *attested* older stage, and it is the only other candidate.

Seven daughters, 54 concepts, two gold nodes:

| gold node | source variety | evidence | gold forms | assembly ceiling, top-1 | mean top NED |
| --- | --- | --- | --- | --- | --- |
| `proto_burmish` | `hillburmish:ProtoBurmish` | reconstructed | 92 | **42/54 — 77.8%** | 0.070 |
| `burmic` | `hillburmish:OldBurmese` | attested | 38 | **25/37 — 67.6%** | 0.090 |

Both measured with `tools/oracle_ceiling.py --oracle assembly --gold-node …` at
beam width 5. They characterize an answer-key-assisted construction, not a live
model or an exhaustive architectural bound, and they are not
comparable to a branch-cascade oracle by subtraction — §7.3 of the design
document says why. `burmic` scores over 37 concepts rather than 54 because Old
Burmese does not attest all of them.

**The Old Burmese binding is temporary and approved as such.** Old Burmese is
the ancestor of Burmese; `burmic` under Nishi (1999) also contains Achang and
Xiandao, of which it is not the ancestor. Scoring it there is a convenience, in
the same way `benchmarks/romance.json` scores classical Latin against daughters
descended from Vulgar Latin. `provenance.note` records it in that shape.

**Removing it is one deletion**, and that is a property of the file rather than
a hope. Delete the second entry of `targets`; the concept selection does not
move, because `concept_selection_source_variety_id` names ProtoBurmish
explicitly instead of following `targets[0]`, and `burmic` stays a traversed
node either way. `test_dropping_the_temporary_binding_changes_nothing_else`
pins it.

**Two alternatives were rejected and are recorded so they are not
re-discovered.** Old Burmese as a sister of Rangoon is historically false. Old
Burmese as an anchor costs no linguistic claim and is genuinely supported, but
an anchor is never scored, so it gives no second gold node and no answer to
condition 6.

**Why the node is `burmic` and not `SouthernBurmish`.** Rangoon is the only
Burmese variety in the dataset, so any node written above Rangoon alone has one
child: `normalize_tree` removes it silently and `postorder_groups` refuses it if
it survives. Lama's (2012) Northern/Southern split puts Rangoon alone under
Southern Burmish and is therefore unusable here. Nishi's (1999) Burmic/Maruic
split, on the treatment of Proto-Burmish pre-glottalized initials, is the
division the Burmish reconstruction literature works in and puts Achang and
Xiandao with Burmese, giving a node with three children. Both subgroups are left
as polytomies; each refinement added would be another traversal node and another
session's cost, and neither is needed for a node this benchmark scores.

**Live figures, three seeds per arm, `google/gemma-4-26b-a4b`** — the paired
sweep of §7.21, and the first real-data reading condition 6 has ever had:

| gold node | before (rule cascade) | after (inventory) | copy baseline |
| --- | --- | --- | --- |
| `proto_burmish` | committed 2/3, top-1 **0.000 ± 0.000** | committed 2/3, top-1 **0.000 ± 0.000** | **0.000** |
| `burmic` | committed 2/3, top-1 **0.000 ± 0.000** | committed 2/3, top-1 **0.000 ± 0.000** | **0.000** |

The initial exact-match zero has a strong benchmark component: every daughter copied
unchanged also scores 0.000, because the gold writes tone as a category and
writes pre-glottalized initials no daughter preserves. **That is the reason to
keep the family despite the result.** A live 0.5 on Polynesian does not
distinguish reconstruction from copying East Futuna; here nothing is hidden.
Relaxing the reading — tone marks dropped from both sides, or any single
morpheme of the candidate accepted — moves both arms by the same two to four
concepts of 54, which is why neither relaxation was adopted. A seed costs
43.8 ± 18.4 minutes in the after arm and 67.1 ± 62.7 in the before arm.

`hillburmish` is also the first benchmark whose cognacy is coded one morpheme at
a time — see `Partial_Cognacy` in [running inference](running_inference.md).
That makes the morpheme reading its evidence view by default, while assembly
still aligns whole candidate strings. This mismatch is unresolved. §7.18 of
[the design document](proto_inventory_design.md) measures what that costs, the
family's `unaccounted_column_rate` floor included. **Read that floor before
quoting any rate from this family**: it is 0.280 and 0.338 at the two
leaf-child nodes, which is at or above §7.2's own warning threshold.

### One defect this family found, which was not this family's

Building the ceiling crashed, and not because of `hillburmish`. `pylexibank`
spells a grapheme/phoneme pair with a literal slash inside a single segment, as
in `ṅ/ŋ`, and the rule DSL reads `/` as its environment separator. So
`derive_branch_rules` raised a bare `ValueError` while rendering a derived rule,
which ended the node and, through `_fallback_step`, the run.

Measured over the 174 local CLDF datasets, **104 carry at least one segment
holding a DSL-reserved character**. `meloniromance` is one of them, at 2146
occurrences — so `benchmarks/romance.json` could not be assembled either, and
had not been able to since the assembler existed. It went unnoticed because the
only families ever run under it, `walworthpolynesian` and the synthetic ones,
carry none.

The fix is the same shape as the three advisories beside it: the child is
recorded in `unspellable_reflex_child_ids` and the derived rule is dropped.
Nothing linguistic is decided, and the parent form is unaffected because it is
assembled from columns rather than from these rules. Romance now has its first
assembly ceiling: **90/900 — 10.0%**, mean top NED 0.228.

### Reading the phoneme, and what it did and did not move

The advisory kept the harness alive. It did not make the gold reachable. Old
Burmese wrote 142 of its 219 forms with tokens like `ṅ/ŋ`, and **24 of the 37
`burmic` gold concepts had no alternative any daughter could produce**. On
`romance` the same was true of **182 of 900**. The adapter now reduces such a
token to its phoneme — see `Grapheme/phoneme tokens` in
[running inference](running_inference.md) for the rule and for why it is a
reading rather than a choice.

| gold node | concepts with gold | unmatchable before | unmatchable after |
| --- | --- | --- | --- |
| `burmish:proto_burmish` | 54 | 0 | 0 |
| `burmish:burmic` | 37 | **24** | **0** |
| `romance:latin` | 900 | **182** | **0** |

**The oracle ceilings barely moved, and that is the expected result rather than
a disappointment.** The assembly oracle writes its rules against the withheld
gold, so it could already spell `ṅ/ŋ`. A live model never can: it does not see
the gold, and no daughter carries the token.

| ceiling | before | after |
| --- | --- | --- |
| `burmish:proto_burmish` top-1 | 42/54 | 42/54 |
| `burmish:burmic` top-1 | 25/37 | 25/37 |
| `romance:latin` top-1 | 90/900 | **88/900** |

Romance lost two forms and 22 correspondence sets. Reducing `ɪ/j` to `j` merges
it with the `j` already there, so the oracle loses a distinction only an oracle
could have used. **The ceiling did not rise. The gold became reachable by
something other than an oracle**, which is what these benchmarks are for.

`unaccounted_column_rate` did not move at all — 0.280 at `maruic` and 0.338 at
`burmic`, unchanged. That floor is the survey/assembler grouping mismatch of
§7.18 and has nothing to do with tokens.

**Polynesian is untouched**, which is checked rather than assumed:
`walworthpolynesian` carries no such token, so every recorded baseline in this
document and every number pinned by
`tests/workbench/test_oracle_ceiling_regression.py` stands under the same
reading it always did.

**What is still unmeasured.** On the `meloniromance` shape both sides are
sounds, so a model that reconstructs `*ɪ` where the gold realizes `j` is now
scored as wrong. Whether that is unfair, and whether a gold alternative should
carry both sides, is not measured. The question is how many Latin gold forms
differ between the two readings, and whether a live model ever produces the
left side. Nothing here settles it.

## Recorded baselines

Read live results beside a single-daughter copy baseline and a gold-assisted
per-concept selection diagnostic. On Polynesian these are 0.587 and 0.826.
The second uses the answer key and is not an executable gold-free competitor.
A correct output matching an observed daughter can be a legitimate reconstruction;
an unattested exact hit exceeds literal selection but need not prove inference.

Gemini's three Polynesian runs reached 0.630 ± 0.022 (sample SD), clearing the
single-daughter baseline. Their exact hits were all already daughter-attested.
The preceding Gemma and Qwen runs also returned zero outside-selection hits.
Do not pool different instruction hashes/models as independent identical trials.

The last valid Burmish experiments used 36 turns and produced these results:

| Target | r2 seed 0 | r2 seed 1 | r3 seed 0 | r3 seed 1 |
| --- | --- | --- | --- | --- |
| `proto_burmish`, 54 concepts | 0 | 0 | 0 | 0 |
| `burmic`, 37 concepts, provisional proxy | 0 | 1 | 0 | 0 |

Cells are exact hit counts. No daughter attests the one hit (`a p ⁴`, NEEDLE).
The final two runs committed all nodes. Across the four runs the counts are
0/216 and 1/148 repeated concept evaluations, not independent word samples.
See [current state](current_state.md) for artifact paths, caveats and the last
stopping point. Earlier 24-turn and void provider-failure runs do not supersede
this result.

### A second model, 2026-08-31

`qwen3.6-35b-a3b`, three seeds, current instructions, same tree. It exists to
remove the confound that every live observation in this repository came from one
model. Sampling was `top_k 20, top_p 0.95, min_p 0.0, repeat_penalty 1.0` at
temperature 1.0 — the Qwen family's published values, not Gemma's, and verified
in the server's own request log. Qwen publishes 0.6 for thinking mode; 1.0 is
the sweep pin and the deviation is stated wherever the figure is.

| | `qwen3.6-35b-a3b` | `google/gemma-4-26b-a4b` |
| --- | --- | --- |
| top-1 at `proto_polynesian` | **0.533 ± 0.046** (n=2) | 0.543 best seed |
| nodes committed of 7 | 5.67 ± 0.58 | 5.33 ± 0.58 |
| verbatim copies among committed nodes | 3 of 17 | 4 of 16 |
| concepts outside the selection bar | **0** | **0** |
| first-call prompt, every node | **22,960 tokens** | 13,760 tokens |
| reasoning share of output | 77% | not reported |

Three things a reader of this family should take from it. The two models land in
the same place, below the 0.587 copy baseline and well below the 0.826 selection
bar. They copy at rates that cannot be told apart (Fisher two-sided p = 0.688),
so the observations do not isolate copying to Gemma. They do not establish
that commit shape causes it or that the two model populations are equivalent. And
the identical content costs Qwen **67% more prompt tokens** — same instructions,
same schemas, same payload, different tokenizer — so any per-node budget on this
page is a Gemma figure and understates Qwen by about two thirds.

§7.24 of [the design document](proto_inventory_design.md) has the full reading,
including the seed whose root fell back to the harness's identity commit and
would have scored **0.609**, above both seeds that actually committed.

### A frontier model, 2026-08-31

`gemini-3.7-flash`, hosted, three seeds, `--reasoning-effort medium`, same tree
and same budgets. No `--provider-config` (no local sampler panel to defend
against) and no `--provider-seed-base` (Gemini has no seed).

| | `gemini-3.7-flash` | `qwen3.6-35b-a3b` | `gemma-4-26b-a4b` |
| --- | --- | --- | --- |
| top-1 at `proto_polynesian` | **0.630 ± 0.022** (n=3) | 0.533 ± 0.046 (n=2) | 0.543 best seed |
| scored seeds / excluded | 3 / 0 | 2 / 1 | 2 / 1 |
| nodes committed of 7 | 4.33 ± 0.58 | 5.67 ± 0.58 | 5.33 ± 0.58 |
| verbatim copies | **1 of 13** | 3 of 17 | 4 of 16 |
| **concepts outside the selection bar** | **0** | **0** | **0** |
| cost | $8.42 (91% cached) | — | — |

**0.630 is the first live figure on this page to clear the 0.587 copy
baseline**, in this small sample. It also exceeds the context-free cascade oracle figure
of 0.587; this is a different reconstruction procedure, not a violation of a
universal bound. It remains below the 0.826 selection diagnostic, and
**outside-selection exact hits are zero on all three seeds**: 87 correct proto-forms, not one of them a
form no daughter attests.

Two caveats a reader of this family needs. The commit rate of 4.33 is the
lowest of the three and is **confounded by the budget** — all 8 failures are
`AgentLoopLimitError` at exactly 24 of 24 turns, and Gemini averages 21.9
turns per node against Gemma's 12.7. And the cost held at $8.42 only because
implicit caching hit **91%**; the same sweep at full input price is about $28.

§7.26 of [the design document](proto_inventory_design.md) has the full reading.

Historical baseline table: Polynesian, 46 concepts, beam width 5. The oracle
columns characterize the named procedures; the live column is one earlier run.

| Measure | Oracle ceiling, context-free | Oracle ceiling, context-sensitive | Live `google/gemma-4-26b-a4b` |
| --- | --- | --- | --- |
| top-1 exact | 27/46 — 58.7% | 33/46 — 71.7% | 21/46 — 45.7% |
| beam exact | 40/46 — 87.0% | 40/46 — 87.0% | 31/46 — 67.4% |
| exact selection gap | 28.3 points | 15.2 points | 21.7 points |
| mean top NED | 0.147 | 0.097 | 0.214 |
| mean beam-best NED | 0.030 | 0.024 | 0.081 |
| NED selection gap | 0.118 | 0.073 | 0.133 |
| mean top B-Cubed F1 | 0.963 | 0.963 | 0.950 |

The two oracle columns are two measures and not a before/after. The context-free
one is what every earlier baseline in this repository was taken with and is the
default; the context-sensitive one is a rule writer as strong as the DSL and
lands beside it. See `docs/analysis_tools.md` for both and for why quoting either
as "what a good model should get" is a category error.

**Nothing in this table has moved for the per-correspondence-set commit
protocol, and that is correct.** Stages 1 and 2 added the assembler and the
tools without changing a default, so every figure here was produced by the same
path that produced it before, and it stays the recorded before.

The oracle assembly ceiling now exists — `tools/oracle_ceiling.py --oracle
assembly`, top-1 **39/46** on Polynesian at width 5 against 27/46 and 33/46 for
the two branch-cascade oracles, with the full table in `docs/analysis_tools.md`.
It characterizes that oracle procedure and is not a live number.

`agent/system_prompt.md` now teaches the inventory workflow, which is the flip
stage 3 is named for. Live inventory experiments subsequently ran and are
recorded above and in
inventory design §7.7–§7.29. The historical staged migration is no longer the
active experiment plan; both commitment shapes remain supported.

The oracle rows were re-recorded 2026-08-22 when four defects in the instrument
were repaired. Beam-exact moved 39 → 40 and the graded means with it, because the
oracle now scores against every gold alternative through `compare_to_nearest`, as
`HistoricalTargetEvaluation` always did. Top-1 did not move — not even under a
rule-ordering fix worth seven forms to Hawaiian, which is the finding
`docs/analysis_tools.md` records at length.

The live row is `runs/google-gemma-4-26b-a4b-20260820-212424`, one seed, seven
nodes attempted, five committed and two walked over as identity fallbacks. It is
a labelled single-run observation, not a stable estimate of quality. It was measured before the alternatives fix, so
its beam-exact and graded figures are on the stricter last-alternative-only
reading and are not exactly comparable to the oracle columns; re-running the
sweep re-records them.

The oracle-ceiling figures are pinned in the suite by
`tests/workbench/test_oracle_ceiling_regression.py` — both oracles, including the
gap between top-1 and beam-exact — so a change to the beam cannot quietly make
reconstructions worse while every test passes.

The oracle rows did not move again on 2026-08-23, when `LingPyAligner` stopped
stripping morphological boundaries. That is the expected result and was checked
rather than assumed: `tools/oracle_ceiling.py` runs `RuleBasedReconstructor` over
`make_leaf_beam` and never calls the shared aligner, so a movement here would
have meant something unintended had changed.

The assembly ceiling for the same benchmark is 44/46 node-local and 43/46 flat,
with boundaries included — which is what the instrument has always done and what
the harness now does too. Stripping them takes both to 38/46, and the script
takes `--boundaries strip` so that comparison is reproducible. It answers a
different question from the oracle and is documented in
[analysis tools](analysis_tools.md).

`tools/branch_recoverability.py` reports the third measure in this family: how
many concepts no single branch can reach, which is what per-set assembly exists
to move. It takes `--method`, and the answer depends on it — 37/8/1 under the
segment map, 39/6/1 under the real cascade, 40/5/1 under the cascade with
`--oracle contextual`. §7.4 of `docs/proto_inventory_design.md` reads all three
together; none should be quoted alone.
