# Analysis tools

Four standalone scripts under `tools/`. None needs a model, a provider, or the network:
they exercise the deterministic layer directly, so they run in seconds and can be pointed at
any prepared benchmark input.

They exist because the test suite proves the harness is *mechanically* correct and says
nothing about whether it reconstructs well. These measure the second thing.

Run them with the environment's interpreter:

```bash
/opt/anaconda3/envs/llm_reconstruction/bin/python tools/<script>.py <benchmark-input.json>
```

A benchmark input is a `WorkbenchPayload` carrying a `historical_form_bindings` entry with
role `target` — the gold proto-forms, withheld from the model.

The baselines quoted below all come from the Proto-Polynesian benchmark. Rebuild it first:

```bash
/opt/anaconda3/envs/llm_reconstruction/bin/python tools/build_polynesian_benchmark.py
```

That reads `data/lexibank/walworthpolynesian`, selects the 46 concepts where all ten chosen
daughters share a cognate set with the Proto-Polynesian entry, binds the proto variety as a
hidden `target`, and writes `runs/benchmarks/polynesian.json`. The payload is ~1.3 MB and
derived, so it is gitignored; the recipe is the script plus
`examples/polynesian_benchmark_tree.nwk` and `examples/polynesian_benchmark_bindings.json`.

## `oracle_ceiling.py` — what a flawless model would score

Gives every branch the best child-to-parent segment map the DSL can express, computed
directly against the withheld gold, then runs the real `RuleBasedReconstructor` bottom-up.
Whatever it reports is the accuracy no model can beat under the current architecture,
because the model's only job — choosing rules — has been done perfectly.

It prints three numbers. The third is the point:

```
top  exact   25/46   54.3%   what the beam reports
beam exact   39/46   84.8%   correct form present anywhere in the beam
selection gap            30.4%   computed but not chosen
```

**The selection gap is the headline.** The deterministic layer holds the correct proto-form
far more often than it reports one, which means accuracy is being lost after the model has
finished, in how a parent is chosen from the child evidence. Watch this number across
changes to `traversal/reconstructor.py` and `traversal/beam.py`.

Baseline on the 46-concept Polynesian benchmark, recorded 2026-08-16, beam width 5. Top-1
is flat at 54.3% for any beam width of 3 or more, and beam-exact saturates at 84.8% by
width 5 — so the gap does not close by widening the beam.

The oracle is honest about what it cannot express: rules whose ordering would form a cycle
are dropped with a warning, and morphological boundaries are skipped because the DSL forbids
them as rule targets.

## `tiebreak_probe.py` — does branch support decide anything?

Three synthetic nodes, no arguments. Four children agreeing against one dissenting, with and
without a rule that reconciles them.

Case B is the one to read. It is case A with the minority segment renamed to one that sorts
earlier in Unicode. If A and B disagree about which form wins, the winner is being chosen by
string ordering rather than by evidence.

## `correspondence_inventory.py` — the view the agent cannot ask for

Builds the complete correspondence-set inventory over every cognate set at once, sorted by
support: the n-tuple of aligned segments across all daughters, how often it recurs, and
example concepts. This is the object the comparative method actually operates on, and the
shape a `summarize_correspondences` tool should return.

For ten Polynesian daughters it produces 216 sets in about 22 KB — smaller than a single
`get_alignments` call for six concepts across two languages. Most of the tail is
compound-boundary noise, which is why `--min-support` defaults to 2: a correspondence
occurring once is residue, not evidence.

## `branch_recoverability.py` — what the DSL cannot reach

The DSL has no empty-target insertion, so a branch that deleted a segment can never restore
it. This counts, per branch, how many gold forms are therefore out of reach, and splits the
concepts three ways: reachable from a single branch, needing evidence mixed across branches,
or unreachable from every branch.

Polynesian baseline: 37 of 46 reachable from some single branch, 8 needing a mix, 1 reachable
from none; per-branch deletion losses run from 7/46 (Tongan) to 17/46 (North Marquesan).

The middle number bounds what any amount of better *selection* can achieve. Closing it needs
proto-forms assembled from several branches at once.

## When to re-run

- **Any change to the beam, the scorer, or rule application** → `oracle_ceiling.py`, and say
  what happened to the selection gap in the change description.
- **Any change to tie-breaking or candidate merging** → `tiebreak_probe.py`.
- **Any change to alignment or evidence tools** → `correspondence_inventory.py`, to check the
  inventory is still coherent and still small.
- **Any change to the DSL** → `branch_recoverability.py`, since expressiveness changes move
  the reachability split directly.
