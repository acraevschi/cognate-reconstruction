# Analysis tools

Six standalone scripts under `tools/`. None needs a model, a provider, or the network:
they exercise the deterministic layer directly, so they run in seconds and can be pointed at
any prepared benchmark input.

They exist because the test suite proves the harness is *mechanically* correct and says
nothing about whether it reconstructs well. These measure the second thing.

Run them with the environment's interpreter:

```bash
/opt/anaconda3/envs/llm_reconstruction/bin/python tools/<script>.py <benchmark-input.json>
```

Each script also takes a **benchmark name** wherever it takes a path, and each has a
`--json` mode so the multi-seed runner can consume the measurement instead of
re-implementing it:

```bash
python tools/oracle_ceiling.py polynesian --json
```

A benchmark input is a `WorkbenchPayload` carrying a `historical_form_bindings` entry with
role `target` — the gold proto-forms, withheld from the model.

The baselines quoted below all come from the Proto-Polynesian benchmark. Build it first:

```bash
python -m cognate_reconstruction.cli build-benchmark --name polynesian
```

That reads `benchmarks/polynesian.json`, loads `data/lexibank/walworthpolynesian`, selects
the 46 concepts where all ten chosen daughters share a cognate set with the Proto-Polynesian
entry, binds the proto variety as a hidden `target`, and writes
`runs/benchmarks/polynesian.json`. The payload is ~1.3 MB and derived, so it is gitignored;
the recipe is the definition plus `examples/polynesian_benchmark_tree.nwk`. See
[benchmarks and evaluation](benchmarks.md) for definitions, the multi-seed runner, and the
synthetic families.

`tools/build_polynesian_benchmark.py` still exists and still works; it is now a thin wrapper
around that subcommand, kept because the documented invocation references it. The selection
logic it used to hold is `cognate_reconstruction/benchmarks/builder.py`, driven by a
declarative file, so a second family is a definition rather than a second script.

## `oracle_ceiling.py` — what a flawless model would score

Gives every branch the best child-to-parent rule set an oracle can write, computed directly
against the withheld gold, then runs the real `RuleBasedReconstructor` bottom-up. Whatever it
reports is the accuracy no model can beat under the current architecture *and that oracle*,
because the model's only job — choosing rules — has been done perfectly.

It prints three exact numbers — the third is the point — and the graded distances beside
them:

```
top  exact   27/46   58.7%   what the beam reports
beam exact   40/46   87.0%   correct form present anywhere in the beam
selection gap                 28.3%   computed but not chosen

graded, against the same gold (lower is better for NED):
  top  NED    0.147   mean normalized edit distance of the reported form
  beam NED    0.030   best any retained candidate reached
  NED gap     0.118   distance recoverable by choosing better
  B-Cubed F1  0.963   structural agreement, higher is better
```

The graded row exists because the exact counts move in steps of 1/46. A change that leaves
every concept in the same match/miss bucket while making the misses worse would not move
them at all, and normalized edit distance would.

**The selection gap is the headline.** The deterministic layer holds the correct proto-form
far more often than it reports one, which means accuracy is being lost after the model has
finished, in how a parent is chosen from the child evidence. Watch this number across
changes to `traversal/reconstructor.py` and `traversal/beam.py`.

Current figures on the 46-concept Polynesian benchmark, beam width 5, at four widths. The
2026-08-18 columns are the branch-support before/after; the last column is the same
context-free oracle after the 2026-08-22 instrument repairs, and the only thing that moved is
beam-exact:

| beam width | top-1 before | top-1 after | beam-exact before | beam-exact after | beam-exact, repaired |
| --- | --- | --- | --- | --- | --- |
| 1 | 32.6% | **47.8%** | 32.6% | 47.8% | 47.8% |
| 3 | 54.3% | **56.5%** | 78.3% | 78.3% | 78.3% |
| 5 | 54.3% | **58.7%** | 84.8% | 84.8% | **87.0%** |
| 10 | 54.3% | **56.5%** | 84.8% | 84.8% | **87.0%** |

Top-1 rose at every width and beam-exact fell at none, which is the shape a *selection* fix
should have: the same candidates, chosen better. Had top-1 risen while beam-exact fell, the
change would have been trading candidates away rather than choosing among them, and would
be a regression however good the headline looked.

Top-1 was flat at 54.3% for every width of 3 or more before the change, and beam-exact still
saturates by width 5 — so the remaining 28.3 points do not close by widening the beam either.
Note that width 10 scores *below* width 5 on top-1: an ordinary beam-search artifact, where a
wider beam keeps a distractor that accumulates enough mass to win.

**These figures are now pinned in the test suite.**
`tests/workbench/test_oracle_ceiling_regression.py` asserts top-1, beam-exact, *and the gap
between them* at beam width 5, plus the whole width curve, for **both** oracles, against a
checked-in fixture that is the real benchmark with per-form provenance stripped — the oracle
reads only segments, the tree, and the gold binding, so the fixture reproduces the
full-dataset numbers exactly, and a skipped test verifies that against
`runs/benchmarks/polynesian.json` when the local corpus is present. The gap is asserted and
not only the accuracies: a change that raises top-1 while lowering beam-exact has traded
candidates away rather than chosen better among them, and an accuracy-only assertion would
call that a win. The test imports `measure()` from this script, so the number the suite pins
and the number the script prints come from one implementation.

Why a regression test rather than a habit: prompt 04 edited `traversal/reconstructor.py` — it
added `contrast_reducing_rule_count` to the diagnostics — and the only thing that showed the
score was untouched was a human remembering to run this script.

The oracle is honest about what it cannot express: rules whose ordering would form a cycle
are dropped with a warning, and morphological boundaries are skipped because the DSL forbids
them as rule targets.

### Two oracles, and the second never replaces the first

`--oracle context_free` (the default) assigns one target per source segment, **globally**. The
rule language does not: it has left and right contexts and word edges. So a form the
context-free oracle cannot produce is *not* evidence that the architecture cannot produce it.
Tongan `ʔ e l e l o` reaches gold `ʔ a l e l o` with the single rule `e > a / ʔ_`, which the
DSL expresses and that oracle cannot write.

`--oracle contextual` is the rule writer as strong as the rule language. Per branch, per
aligned column against the withheld gold, it records the source segment, the gold target and
the child-side neighbours; per source segment it searches the environments the DSL can spell —
word-initial, word-final, a single left token, a single right token, and the four two-part
combinations — for environments that **purely** separate one target from another; it emits the
conditioned rules before the unconditioned default, orders sources by the same feeding
argument `order_rules()` uses, and **falls back to the context-free cascade on any branch it
would make worse**, which is what makes it ≥ the first measure per branch by construction
rather than by argument.

Polynesian, beam width 5, both columns from the same run of the same reconstructor:

| Measure | context-free (the pinned baseline) | context-sensitive |
| --- | --- | --- |
| top-1 exact | 27/46 — 58.7% | **33/46 — 71.7%** |
| beam exact | 40/46 — 87.0% | 40/46 — 87.0% |
| exact selection gap | 13 concepts, 28.3 pts | **7 concepts, 15.2 pts** |
| mean top NED | 0.147 | **0.097** |
| mean beam-best NED | 0.030 | **0.024** |
| mean top B-Cubed F1 | 0.963 | 0.963 |
| rules written | 52 over 16 branches | **249 over 16 branches**, 1 branch fell back |

| beam width | top-1 cf | top-1 ctx | beam-exact cf | beam-exact ctx |
| --- | --- | --- | --- | --- |
| 1 | 22 | 22 | 22 | 22 |
| 3 | 26 | **32** | 36 | **39** |
| 5 | 27 | **33** | 40 | 40 |
| 10 | 26 | **33** | 40 | 40 |

**Six concepts of top-1 were being attributed to the architecture and belong to the oracle.**
Nothing regressed at any width, which is the shape the fallback guarantees.

**The context-free measure keeps its identity and stays the default**, because every recorded
baseline on this page was taken with it and silently redefining it would make every
before/after uncomparable — the failure `tools/_bootstrap.py` exists to prevent at one remove.
New measures land beside it, never in place of it.

**Neither number is a target.** The contextual oracle writes 249 rules across 16 branches,
roughly sixteen per branch and many of them conditioned on a single word. That is a perfect
rule writer, not a plausible analysis, which is exactly what an oracle is for: it bounds the
architecture. Quoting 33/46 as "what a good model should get" is the same category error as
quoting a context-free miss as a structural limit.

### Which node's gold, stated rather than assumed

`measure()` took `bindings[0]` and scored the **root** beam against it. On a family carrying
gold at several nodes that is whichever binding was written first — `east` on
`synthetic_hard`, not `proto` — so the published figure was the root beam scored against a
sister's gold, under the root's name. It now defaults to the root's own binding, refuses to
guess where the root has none, scores the beam at whichever node it was given, and carries
`gold_node_id` in the text output and in `--json`. `measuring:` already stopped a figure being
quoted from the wrong checkout; nothing stopped one being quoted from the wrong node.

```bash
python tools/oracle_ceiling.py runs/benchmarks/synthetic_hard.json --gold-node east
```

### Every gold alternative is scored, not only the last

The gold used to be built with a dict comprehension over `binding.forms`, so a concept whose
binding carries alternatives kept whichever was written last. Two Polynesian concepts do, and
`1443` WALK carries four — `r oː`, `ʔ a l u`, `s a ʔ e l e`, `f a n o` — of which only
`f a n o` survived. `HistoricalTargetEvaluation` has always scored through
`compare_to_nearest` over `target_segment_alternatives`, so the harness honoured all four and
the instrument bounding it did not. Scoring through `compare_to_nearest` moves context-free
beam-exact **39 → 40** and the graded means with it (top NED 0.158 → 0.147, beam-best NED
0.043 → 0.030, B-Cubed F1 0.960 → 0.963); top-1 does not move, and the contextual oracle does
not move at all.

### The rule ordering was backwards, and fixing it moved the ceiling by zero

`order_rules()` documents the feeding argument correctly — "a rule whose target is another
rule's replacement must therefore run first" — and from `febf03b` (2026-08-17) to 2026-08-22
implemented the opposite, emitting a source once nothing mapped *into* it. On its own worked
example it returned `[(k,t), (t,s)]` where the docstring says `[(t,s), (k,t)]`.

It fired on the real benchmark. Hawaiian merges nothing but chain-shifts twice — `*t > k` and
`*k > ʔ` — so its oracle map is `{ʔ: k, k: t, …}` and the emitted order was `ʔ > k` before
`k > t`:

```
Hawaiian  ʔ a k a   --[ʔ > k]-->  k a k a  --[k > t]-->  t a t a     reported
Hawaiian  ʔ a k a   --[k > t]-->  ʔ a t a  --[ʔ > k]-->  k a t a     gold
```

Per branch, applying each daughter's own context-free cascade to its own forms and counting
exact matches against the root gold:

| branch | before | after |
| --- | --- | --- |
| **Hawaiian** | **15/46** | **22/46** |
| every other daughter | unchanged | unchanged |
| total over ten daughters | 214 | **221** |

Only Hawaiian moves, because only Hawaiian has a chain shift. (Counting against every gold
alternative rather than the last-listed one, the same figures are 215 → 222: Tongan's
`ʔ a l u` for `1443` was always correct and was always scored a miss.)

**And the tree-level ceiling does not move at all.** With the ordering corrected and nothing
else changed, top-1 is 27/46, beam-exact 39/46, mean top NED 0.158, and the whole width curve
is identical to the figure pinned before the fix. A branch that produces seven more correct
forms changes nothing about what the root reports, which is the most direct evidence on this
page that the accuracy this harness loses is not lost in the rules — it is lost in the step
that picks one whole string out of a beam. It is also why the pinned figure survived the
defect: reassuring about the pin, alarming about the instrument.

On `synthetic_hard`, which was generated with a chain shift on purpose, the same fix is worth
seven concepts *at the root*: scored against `proto`, top-1 goes **15/25 → 22/25**, beam-exact
25/25 throughout, mean top NED 0.098 → 0.030.

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

`--json` carries the same field. A machine consumer is exactly the reader least able to
notice that a number came from the wrong checkout, so `measuring` is in every JSON object
these scripts emit, alongside `benchmark`.

## `assembly_ceiling.py` — what a flawless *assembler* would reach

The companion to `oracle_ceiling.py`, answering the other half of the question. The oracle
asks what a perfect rule writer reaches when a proto-form has to be one branch's whole output,
selected from a beam. This asks what a perfect assembler reaches when each column of the
multiple alignment contributes one proto-phoneme, or nothing — the shape
`docs/proto_inventory_design.md` proposes. That makes reachability decidable rather than
searchable: it is a subsequence problem over the columns, so the script computes an exact
bound in one pass, with no beam, no rules and no model.

Polynesian, 46 concepts:

| assembly variant | reachable | cannot reach |
| --- | --- | --- |
| flat — align all ten daughters at the root, assemble once | **43/46 — 93.5%** | `1028`, `1217`, `778` |
| node-local — assemble at each internal node from its children, bottom-up | **44/46 — 95.7%** | `1028`, `778` |
| free choice — any proto-phoneme, not only an attested reflex | 46/46 | — |

**The free-choice row is printed to be dismissed.** The alignment always has enough columns,
so the bound is vacuous; it is computed only so nobody re-derives it and believes it. The
informative rows are the reflex-restricted ones, and they are a **lower** bound, because a
proto-phoneme genuinely need not be one of its reflexes:

- `1028` YAWN, gold `m a w a + w a` — **no daughter shows `w` anywhere.** EastFutuna and
  Samoan show `v`, the rest a gap.
- `778` SMOKE, gold `ʔ a h u + a f i` — the same: `f` appears in no daughter (Samoan `s`, the
  rest `h` or `ʔ`).
- `1217` FATHER, gold `t a m a + n a` — the daughters carry two lexemes (`m a t u a` against
  `t a m a`), and the ten-way SCA alignment puts them in non-overlapping columns. That is an
  alignment failure, not an assembly one, and it is exactly why node-local scores *above*
  flat: the same material aligned in smaller groups on the way up is aligned correctly, and
  `t a m a + n a` assembles at the root.

**node-local is the honest number for the proposed design**, because assembly would happen at
each node over that node's active children, exactly as rules do now. That it comes out above
flat rather than below is a finding about the aligner: a single ten-way alignment is not the
best view of the evidence, and the bottom-up one repairs a case it gets wrong. Both variants
are reported; neither should be quoted alone.

Read against the oracle table above, per-set assembly raises the *top-1* ceiling by eleven
concepts over the context-free oracle and by six over the context-sensitive one, and raises
reachability by four. It is overwhelmingly a **selection** fix wearing a generation change's
clothes: the answer stops having to be chosen out of a beam because it is constructed.

`--gold-node` works as it does for the oracle. On `synthetic_hard` scored at `east`, both
variants reach 22/25 and miss exactly `leaf`, `tooth` and `tree` — the three concepts whose
`*ʔ` both of `east`'s children lost, so the correspondence set is `⟨Ø : Ø⟩` and assembly is as
stuck there as a cascade is. Scored at `proto`, where `west` still attests the segment, all
three come back and every variant reaches 25/25.

**Like the oracle, this is a bound and not a target.** The assembled intermediate forms are
what a perfect column-wise chooser with full knowledge of the gold would produce, not
plausible reconstructions, and a miss here is no more a structural limit than an oracle miss
is.

### `--boundaries`, and what the instrument was measuring that the harness was not

This script has always aligned `form.segments`, boundaries included, and said so in
`align_rows`: gold proto-forms carry them — `ʔ a h u + a f i` — and a column that could never
contribute a `+` would make those concepts unreachable *by construction rather than by
measurement*. Until 2026-08-23 the harness's own aligner stripped them, so the ceiling was
measured one way and the implementation ran the other way, and the two shared no alignment
code that could disagree out loud.

`--boundaries strip` makes that gap a number instead of an argument. Polynesian, same run,
both readings:

| variant | `--boundaries include` (default) | `--boundaries strip` |
| --- | --- | --- |
| flat | 43/46 | 38/46 |
| **node-local** | **44/46** | **38/46** |
| free choice | 46/46 | 44/46 |
| node-local cannot reach | `1028`, `778` | `1028`, `1212`, `1217`, `1239`, `1439`, `1741`, `2105`, `778` |

**Six concepts, and they are not a random six.** `1212`, `1217`, `1239`, `1439`, `1741` and
`2105` carry a morphological boundary in every gold alternative, so under `strip` no assembly
over those columns can reach them however good the analysis is. `1028` and `778` stay out of
reach either way, for the reasons above — a segment no daughter shows — which is what makes
the six attributable to the boundary and to nothing else.

`--boundaries strip` is kept for exactly one purpose: reproducing a figure recorded before the
harness's aligner was repaired. It is not a variant of the measurement worth taking on new
work.

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

By the root only one concept is still an exact tie, yet 13 of its 19 misses have the correct
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
and morphology-first are stated in the tool description and in `agent/system_prompt.md`; the
two losing policies stay in this probe as the runnable form of why. If the aggregation
in `polarize` changes, re-run this: the probe is the independent check that the
per-clade, presence-only reading is still what the numbers support.

## `correspondence_inventory.py` — the independent check on the survey tool

Builds the complete correspondence-set inventory over every cognate set at once, sorted by
support: the n-tuple of aligned segments across all daughters, how often it recurs, and
example concepts. This is the object the comparative method actually operates on.

It began as the prototype for the view the agent could not ask for. The agent can ask for it
now, so what the script is *for* has changed: it is the second implementation, reading nothing
but `LingPyAligner.align_multiple`, that the tool can be checked against when the aggregation
or the aligner changes.

**The two stopped producing identical sets when the per-correspondence-set commit protocol
landed, and `--reading` is how they are compared.** `summarize_correspondences` now keeps one
form per node per (concept, cognate set) before aligning, because a set ID it hands a model
has to name columns the assembler can reproduce from one candidate per child, and at an
internal node a child's lexicon is *every* retained beam candidate.

**`--boundaries` is the second axis, and it moved every figure on this page's row.** Until
2026-08-23 `LingPyAligner` stripped `+` and `-` before aligning, for every caller. That was
free while a parent form was a child's whole string rewritten by rules and stopped being free
the moment forms were assembled column by column: there is no column for a token the aligner
never saw, so the assembler dropped boundaries the rule path kept. It now includes them, and
`--boundaries strip` is kept here so the pre-change baselines stay reproducible rather than
merely remembered. See `docs/proto_inventory_design.md` §12.5.

Measured on Polynesian, `--min-support 1`, all four combinations:

| `--reading` | `--boundaries` | distinct sets | at support ≥ 2 | singletons | inventory |
| --- | --- | --- | --- | --- | --- |
| `all` | `strip` (pre-2026-08-23 baseline) | 216 | 41 | 175 | 21.9 KB |
| `all` | `include` | 237 | 60 | 177 | 24.1 KB |
| `reported` | `strip` | 218 | 39 | 179 | 22.0 KB |
| `reported` (what the tool does) | `include` (default) | **246** | **50** | 196 | 24.9 KB |

Every recorded baseline elsewhere in this document that predates 2026-08-23 was measured at
`--reading all --boundaries strip`, the first row — the two figures long quoted as "216 sets,
41 at support ≥ 2". **Quote a set count with both flags or not at all**; the same benchmark
gives 216 or 246 depending on them.

What including boundaries buys is not the extra 28 sets but which ones they are. Boundary
correspondences recur, so `sets_at_min_support` rises by more than a quarter — 39 to 50 — and
a `⟨+ : Ø⟩` set is the morphology signal `polarize`'s own documentation calls decisive:
material added at a morph boundary is innovation however well its segments are attested
elsewhere. Under `strip` the harness had no way to *show* a session that one child carries a
boundary another lacks.

Under `strip`, 188 sets are identical between the two readings; 28 exist only under `all` and
30 only under `reported`. The difference is larger than the ~11 leaf cases where one node
genuinely contributes two forms to one cognate set, because dropping a row re-aligns the
whole concept and shifts neighbouring columns too.

None of the four is wrong. `all` is what SCA does over the raw lexicons; `reported` is a
correspondence between the languages' reported forms. They are kept apart rather than merged
so this script stays an independent check: `--reading reported --boundaries include`
reproduces the tool exactly, and both the reduction and the boundary handling are
re-implemented or re-flagged here rather than imported, because importing the thing under
test would make the check vacuous.

For ten Polynesian daughters it produces 246 sets in about 25 KB — still smaller than a
single `get_alignments` call for six concepts across two languages. Much of the tail is
compound-boundary noise, which is why `--min-support` defaults to 2: a correspondence
occurring once is residue, not evidence.

## `branch_recoverability.py` — what the DSL cannot reach

The DSL has no empty-target insertion, so a branch that deleted a segment can never restore
it. This counts, per branch, how many gold forms are therefore out of reach, and splits the
concepts three ways: reachable from a single branch, needing evidence mixed across branches,
or unreachable from every branch.

Polynesian baseline, `--method map`: 37 of 46 reachable from some single branch, 8 needing a
mix, 1 reachable from none; per-branch deletion losses run from 7/46 (Tongan) to 17/46 (North
Marquesan). The deletion losses do not depend on `--method`.

The middle number bounds what any amount of better *selection* can achieve. Closing it needs
proto-forms assembled from several branches at once.

The script names the concepts in each class rather than only counting them, in text and in
`--json`: under `--method map` the 8 are `1028, 1212, 1217, 1221, 1408, 1439, 1443, 646` and
the unreachable one is `778`. That list is the concrete prediction any change to the combination model has to
move — see `prompts/06-proto-inventory.md`, which uses it as a falsification condition.
Note what this measures: a property of the gold and the daughters' forms under the current
DSL, **not** of the harness. A better scorer cannot move it; a different representation of
what gets committed is what would.

**Quote it beside the cascade-based split, never alone — and since 2026-08-23 the script
produces both.** `--method map` applies a segment map by dictionary lookup and is the
original measure; `--method cascade` builds each branch's real ordered rule set through
`oracle_ceiling.py` and runs it through `RuleEngine`, which is what the harness would do, and
`--oracle contextual` makes that rule writer as strong as the DSL. The cascade reaches more.

| `--method` | reachable from some single daughter | needs mixing | reachable from none |
| --- | --- | --- | --- |
| `map` (default; every figure before 2026-08-23) | 37/46 | 8 | 1 |
| `cascade --oracle context_free` | **39/46** | 6 | 1 |
| `cascade --oracle contextual` | **40/46** | **5** | 1 |

The middle class is the falsification list. Under `map` it is
`1028, 1212, 1217, 1221, 1408, 1439, 1443, 646`; under the context-free cascade
`1212, 1217, 1221, 1408, 1439, 646`; under the contextual cascade
`1212, 1217, 1408, 1439, 1443`. `778` is out of reach from every branch in all three.
`1028`, `1221` and `646` are reachable from a single branch once the rule writer is as strong
as the rule language, so the falsification list is shorter than the map-based one — which is
the difference between the instrument and the architecture, and the reason a miss under either
measure is not a structural limit.

**The lists are not nested, and that is not a defect.** The contextual oracle is `>=` the
context-free one *per branch*, by construction — `branch_rules` keeps whichever cascade scores
more exact forms on that branch as a whole — but not per concept, so a branch can lose one
concept while gaining several. That is why `1443` is on the contextual list and not on the
context-free one.

The third class is deliberately method-independent: "some branch still retains every gold
segment" is a property of the aligned forms, so all three rows partition the same 46 concepts
and only the boundary between the first two moves.

`docs/proto_inventory_design.md` §7.4 reads this table together with the assembly ceiling,
which is what turns it into the design's mechanism check.

## When to re-run

- **Any change to the beam, the scorer, or rule application** → `oracle_ceiling.py`, both
  oracles, and say what happened to the selection gap in the change description. Report the
  two columns separately: the context-free one is what every baseline on this page was
  measured with, and a new measure that replaced it rather than landing beside it would make
  every recorded before/after uncomparable.
- **Any change to the DSL's environment vocabulary** → `oracle_ceiling.py --oracle
  contextual`, since the contextual builder searches exactly that space and its ceiling moves
  with it. The context-free column is the control: if it moves too, something other than the
  environment vocabulary changed.
- **Any change to alignment, or to what a node may commit** → `assembly_ceiling.py`. Both
  variants: node-local currently scores *above* flat, and a change that makes them converge
  has probably changed how the aligner groups a concept.
- **Any change to tie-breaking or candidate merging** → `tiebreak_probe.py`, and
  `outgroup_probe.py` if the change claims to use evidence rather than segment order.
- **Any change to alignment or evidence tools** → `correspondence_inventory.py`, to check the
  inventory is still coherent and still small, and that `summarize_correspondences` still
  agrees with it set for set. State `--reading` and `--boundaries` beside the number: the same
  benchmark gives 216 or 246 sets depending on them.
- **Any change to how out-group evidence is aggregated**, in the scorer or in the
  `polarize` tool → `outgroup_probe.py`, and say what happened to the per-clade and
  per-daughter numbers. A change that makes them converge has probably reintroduced the
  majority vote.
- **Any change to the DSL** → `branch_recoverability.py` and `assembly_ceiling.py`, since
  expressiveness changes move the reachability split directly. State `--method` and
  `--oracle` beside the number; the same benchmark gives 37, 39 or 40 depending on them.
- **Any change to benchmark selection or preparation** → rebuild both definitions with
  `build-benchmark` and check the concept counts here still hold (46 for Polynesian, 900 for
  Romance). A silent change in selection would move every baseline on this page at once.
