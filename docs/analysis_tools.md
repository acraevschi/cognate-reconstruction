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
top  exact   27/46   58.7%   what the beam reports
beam exact   39/46   84.8%   correct form present anywhere in the beam
selection gap            26.1%   computed but not chosen
```

**The selection gap is the headline.** The deterministic layer holds the correct proto-form
far more often than it reports one, which means accuracy is being lost after the model has
finished, in how a parent is chosen from the child evidence. Watch this number across
changes to `traversal/reconstructor.py` and `traversal/beam.py`.

Current figures on the 46-concept Polynesian benchmark, beam width 5, recorded 2026-08-18
after branch-support weighting landed. Before and after, at four widths:

| beam width | top-1 before | top-1 after | beam-exact before | beam-exact after |
| --- | --- | --- | --- | --- |
| 1 | 32.6% | **47.8%** | 32.6% | 47.8% |
| 3 | 54.3% | **56.5%** | 78.3% | 78.3% |
| 5 | 54.3% | **58.7%** | 84.8% | 84.8% |
| 10 | 54.3% | **56.5%** | 84.8% | 84.8% |

Top-1 rose at every width and beam-exact fell at none, which is the shape a *selection* fix
should have: the same candidates, chosen better. Had top-1 risen while beam-exact fell, the
change would have been trading candidates away rather than choosing among them, and would
be a regression however good the headline looked.

Top-1 was flat at 54.3% for every width of 3 or more before the change, and beam-exact still
saturates at 84.8% by width 5 — so the remaining 26.1 points do not close by widening the
beam either. Note that width 10 now scores *below* width 5: an ordinary beam-search artifact,
where a wider beam keeps a distractor that accumulates enough mass to win.

The oracle is honest about what it cannot express: rules whose ordering would form a cycle
are dropped with a warning, and morphological boundaries are skipped because the DSL forbids
them as rule targets.

**It is also weaker than the DSL, which matters when reading a miss.** `oracle_map()` assigns
one target per source segment, globally — it is context-free — while the rule language has
left/right contexts and word edges. A form the oracle cannot produce is therefore *not*
evidence that the architecture cannot produce it. Tongan `ʔ e l e l o` reaches gold
`ʔ a l e l o` with the single rule `e > a / ʔ_`, which the DSL expresses and the oracle
cannot write. Treat the ceiling as a bound on *this oracle*, not on the harness, and never
quote a miss as proof of a structural limit without checking whether a context-sensitive rule
would reach it.

### Every run says which source it measured

`python tools/oracle_ceiling.py` puts `tools/` on `sys.path[0]`, **not** the repository root,
so `import cognate_reconstruction` used to resolve through the editable install — which points
at whatever checkout was installed, regardless of where the script lives. Running the script
from a `git worktree` of an older commit therefore measured the *working tree*, silently, and
reported a before/after difference of zero. That happened while branch-support weighting was
being measured, and it took a per-node beam diff to catch.

`tools/_bootstrap.py` now puts the script's own repository root first, so each script measures
the source next to it, and the output names it:

```
benchmark: runs/benchmarks/polynesian.json
measuring: /path/to/the/checkout/cognate_reconstruction
```

Check that line before quoting a number. A before/after comparison across two worktrees is now
just running the script in each, and the two `measuring:` lines prove they were different.

## `tiebreak_probe.py` — does branch support decide anything?

Three synthetic nodes, no arguments. Four children agreeing against one dissenting, with and
without a rule that reconciles them.

Case B is the one to read. It is case A with the minority segment renamed to one that sorts
earlier in Unicode. If A and B disagree about which form wins, the winner is being chosen by
string ordering rather than by evidence.

Expected output since branch support reached the score: the four-branch form wins both cases
at p=0.80 against p=0.20, and case C — where a rule reconciles the dissenter — collapses to a
single candidate at p=1.00. Before the change every candidate in A and B scored p=0.50 and
case B reported `a W a`, which is the bug in one line.

### How much of a reported beam is arbitrary

`ReconstructionDiagnostics.tie_broken_concept_count` records how many of a node's reported
forms were chosen by `TIE_BREAK_POLICY` — segment order — rather than by mass, and
`inspect-run` prints it. Under oracle rules on the Polynesian benchmark it is concentrated at
the leaf-adjacent binary nodes, which is where the losses in the selection gap originate:

| node | children | top-1 decided by the tie-break |
| --- | --- | --- |
| tongic | 2 leaves | 22/46 |
| marquesic | 2 leaves | 18/46 |
| futunic | 2 leaves | 16/46 |
| tahitic | 3 leaves | 5/46 |
| nuclear_polynesian | 3 | 3/46 |
| central_eastern | 2 | 1/46 |
| proto_polynesian | 2 | 1/46 |

By the root only one concept is still an exact tie, yet 12 of its 19 misses have the correct
form somewhere in the beam. The coin-flips happen low in the tree and harden into accumulated
mass on the way up, so a node reporting no ties is not evidence that its inputs were chosen on
evidence. This is a report and nothing consumes it: a tie is the honest output when the
evidence does not separate two reconstructions.

## `outgroup_probe.py` — could evidence break the ties instead of Unicode?

Scores four tie-break policies against the withheld gold on every tie the scorer currently
resolves by segment order, at every node, and prints the ceiling — the ties where the correct
form is one of the two candidates at all.

```
python tools/outgroup_probe.py runs/benchmarks/polynesian.json --node tongic
```

Polynesian baseline, 66 ties across seven nodes, 29 winnable: alphabetical order 18,
out-group similarity averaged over daughters 18, out-group presence per clade 23, and 25 with
the morph-boundary rule applied first.

The two losing policies are kept in the tool deliberately, because each is the obvious
implementation and each fails for a reason worth keeping visible. Averaging over daughters
degenerates into a majority vote over shared innovations and scores exactly what alphabetical
order scores. Counting a candidate's *absence* of a segment as out-group evidence scores below
alphabetical order, since an empty set of distinctive segments is trivially "attested"; the
presence-only asymmetry is the cladistic argument, and retention-over-loss falls out of it
rather than being assumed.

`--granularity subclade` splits each out-group sibling into its own children. It does not
change the score on this benchmark but structurally collapses into daughter-counting — five of
seven nodes end up with one clade per daughter — so `sibling` is the default. Run both when
adding a family; a divergence between them is the interesting case.

Nothing here is wired into the scorer. Changing which candidate wins the beam is a
research-owner decision; see README, "Decisions that require research-owner input".

The same evidence is now exposed to the *model*, through the `polarize` tool, and the
three findings above are its design. Counting per clade, the presence-only asymmetry,
and morphology-first are stated in the tool description and in `agent/SKILL.md`; the
two losing policies stay in this probe as the runnable form of why. If the aggregation
in `polarize` changes, re-run this: the probe is the independent check that the
per-clade, presence-only reading is still what the numbers support.

## `correspondence_inventory.py` — the independent check on the survey tool

Builds the complete correspondence-set inventory over every cognate set at once, sorted by
support: the n-tuple of aligned segments across all daughters, how often it recurs, and
example concepts. This is the object the comparative method actually operates on.

It began as the prototype for the view the agent could not ask for. The agent can ask for it
now — `summarize_correspondences` produces the same sets through the typed tool surface — so
what the script is *for* has changed: it is the second implementation, forty lines long and
reading nothing but `LingPyAligner.align_multiple`, that the tool can be checked against
when the aggregation or the aligner changes.

For ten Polynesian daughters it produces 216 sets in about 22 KB — smaller than a single
`get_alignments` call for six concepts across two languages. Most of the tail is
compound-boundary noise, which is why `--min-support` defaults to 2: a correspondence
occurring once is residue, not evidence. The tool agrees: 216 distinct sets, 41 at support
≥ 2, 175 singletons.

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
- **Any change to tie-breaking or candidate merging** → `tiebreak_probe.py`, and
  `outgroup_probe.py` if the change claims to use evidence rather than segment order.
- **Any change to alignment or evidence tools** → `correspondence_inventory.py`, to check the
  inventory is still coherent and still small, and that `summarize_correspondences` still
  agrees with it set for set.
- **Any change to how out-group evidence is aggregated**, in the scorer or in the
  `polarize` tool → `outgroup_probe.py`, and say what happened to the per-clade and
  per-daughter numbers. A change that makes them converge has probably reintroduced the
  majority vote.
- **Any change to the DSL** → `branch_recoverability.py`, since expressiveness changes move
  the reachability split directly.
