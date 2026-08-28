# Changelog

## Unreleased

### Cached prompt tokens, because the preamble is most of the bill

A two-form fixture cost 130,778 input tokens. Neither the lexicon nor the tool
results explain that: the first call was 20,880 tokens, of which 11,660 were the
thirteen tool schemas and 8,344 the agent instructions, against 876 for the node
payload. The API is stateless, so that 20,004-token preamble was re-sent on all
six calls. Cost scales as `(instructions + tool schemas) x turns x nodes`, very
nearly independent of corpus size — which is not what anyone would guess from
the outside, and is the number that decides a sweep budget.

The preamble is byte-identical across every call and every node, so providers
cache it. The harness was throwing that evidence away: `ProviderUsage` kept
input, output, total, and cost, and nothing read the cached-token count, so a
run could be hitting cache and the trajectory would not say. Since `cost_usd`
comes from LiteLLM's own arithmetic rather than from the provider, nothing else
would have shown it either.

`ProviderUsage.cached_input_tokens` and `NodeMetrics.cached_input_tokens` now
record it, read from both spellings — Gemini's `prompt_tokens_details`, and the
`cache_read_input_tokens` the Anthropic-shaped backends use. It is a **subset**
of `input_tokens`, never an addition: the provider counts a cached token as
prompt input and discounts its price, so summing them would double-count.
`inspect-run` prints it as a share, and `visualize-run` carries it per node.

`null` is kept distinct from zero throughout. A backend without caching and a
cold run both report nothing, and only the cost tells them apart; a column of
zeroes would have claimed a cold cache the provider never reported. Trajectories
written before the field existed read as `null` and still validate.

Measured on `gemini-3.7-flash`: the first two calls of a session are cold, then
74-91% of each prompt is served from cache, 53% across the session. The
practical consequence is that editing the agent instructions mid-sweep, or a
tool schema that varies per node, discards the prefix and roughly doubles the
bill without changing a single result.

### A Gemini preset, and the three things Gemini does not share with a local server

The harness already spoke to Gemini in principle: every backend is reached
through LiteLLM, and `--model gemini/gemini-3.7-flash` was always a legal
identifier. In practice three things stood between that and a run.

The first is silent and would have corrupted the audit trail. Gemini 3 returns
an encrypted thought signature with every tool call and rejects a replayed
tool-call turn that arrives without it. LiteLLM has nowhere in the OpenAI
contract to put one, so it appends it to the tool-call ID. The harness echoes
IDs verbatim, so the signature would have round-tripped — and would also have
become the ID the model reads back. A committed hypothesis quotes the
`validation_call_id` of the `test_sound_law` call that licensed it, so every
commit would have required the model to reproduce a kilobyte of base64 exactly,
and every trajectory would have recorded it as evidence. `LiteLLMProvider` now
splits the signature off on arrival, keeps the short ID everywhere the model,
the tools, and the trajectories can see, and restores it on the way out through
the field LiteLLM reads first. Backends that send no signature send no extra
field, so the local path is unchanged byte for byte.

The second is loud but late. `--provider-seed-base` writes a `seed` into each
repetition's provider config, and the Gemini API has no seed: LiteLLM rejects
every call unless the option is dropped, and dropping it would leave a sweep
reporting spread across repetitions it only appeared to seed. Both `infer` and
`run-benchmark` now refuse the combination before spending a run on it, and say
that the honest reading is provider nondeterminism.

The third is quiet and would have gone unnoticed. Gemini 3 thinks at `low`
unless told otherwise, which is not a defensible default for the comparative
method. `--reasoning-effort {minimal,low,medium,high}` sets it, `run-benchmark`
passes it to every repetition, and it enters the configuration digest, because
a run at `low` and a run at `high` are not the same experiment.

`--preset gemini` supplies the rest: it routes the model under `gemini/` unless
it is already routed, reads `GEMINI_API_KEY` unless `--api-key-env` names
another variable, and checks the model against `models.list` before the run
starts. `gemini-models` prints that list. Both send the key in the
`x-goog-api-key` header rather than the `?key=` query parameter Google's
examples show, because query strings are what proxies and access logs retain.

The thirteen tool schemas needed no change. They are Pydantic JSON Schema —
`$defs`, `$ref`, `additionalProperties` — and Gemini accepts only an OpenAPI
subset, but LiteLLM's rewrite is total. `tests/workbench/test_gemini_provider.py`
asserts that, and assembles a complete Gemini request body offline from the real
tools and a signed tool-call turn, so a LiteLLM upgrade that moves the signature
or the schema dialect fails in the suite rather than on the first call of a run.


### `visualize-run`: the session, not just its conclusion

`inspect-run` answers what a run concluded. Nothing answered how the agent got
there. The turn-by-turn timeline existed only in the run-triage skill's
`driver.py`, derived from `events.jsonl`, which is a developer tool and which
never sees a tool call's arguments or the remediation the harness sent back.

`cognate_reconstruction/visualize_run.py` adds `visualize-run`: one
self-contained HTML page — no external CSS, JS, fonts or images — with the tree
the traversal walked on the left and the selected node's session on the right.

The session shape is a ribbon, one cell per tool call in order, coloured by
stage: survey, inspect, test, commit. A rejected call keeps its stage colour and
gains a red ring, so three amber rings followed by two clean amber cells reads
as "three refused assembly previews, then it fixed them" before a word is read.
**The stages group tool names for display and carry no linguistic content**; a
tool the module does not know renders as "other" rather than being guessed into
a stage, and a test asserts every shipped tool is mapped so the ribbon cannot
quietly go grey as tools are added.

Each timeline row names what the call asked for in the tool's own terms —
`polarize · ʔ ~ Ø · Tongan, Niuean` — and what came back — `columns 12 ·
concepts 10`. Both are retrieval from fields the tool itself wrote, never
interpretation. Rows expand to the full arguments and full result; a rejection
expands to its structural error code, its protocol/exploratory classification,
and the remediation text, which is what explains why the *next* attempt failed
too.

Everything the text report already states — committed rules, diagnostics,
reconstructed forms, `high_quality` and the condition it failed — comes from
`inspect_run.build_report` rather than being recomputed, so the two views cannot
disagree about a fact.

**It reports and gates nothing.** No trajectory is filtered, no candidate
weighted, no run judged valid or not. A session the workflow filter rejected
renders in full with the reason attached, and a test holds that line.

Two things the tree is for. A node whose descendants include a failed session is
marked *built on an identity fallback*: a node is reconstructed from its direct
children, so a session that never committed low in the tree removes evidence
from every node above it. And an internal node the walk reached that left no
record — a resumed run's earlier nodes, or a run that died mid-walk — renders as
`unrecorded`, never as a leaf, because drawing a reconstructed node as a leaf
tells a reader it was an input language.

`--serve` binds the loopback interface and rebuilds per request. `JsonlEventSink`
flushes one line per event and `JsonlTrajectorySink` appends one record per
finished node, so a finished node renders from its trajectory at full fidelity
and a node in flight renders from its events, labelled as such. The page keeps
your selection and whatever you had expanded across polls, and a directory the
run has not written to yet is a waiting page rather than an error — `load_run`
still refuses such a directory, and `build_live_state` falls back rather than
weakening it.

22 tests in `tests/workbench/test_visualize_run.py`. The ones worth naming: an
answer is matched to its call by call id rather than by position, because a
provider may answer out of order and a zipped view would attribute one call's
result to another while still looking plausible; an unanswered call does not
read as a success; and model text reaching the page cannot close the script tag
it is embedded in.

### The manual now teaches the inventory, and the checklist covers both shapes

Stage 3's flip. `agent/system_prompt.md` led with a workflow — survey, polarize,
align, write a rule, test it, cascade it, commit — that produced a branch
cascade, and mentioned `test_proto_assembly`, `commit_reconstruction`'s
`inventory` argument, `realign` and restorations nowhere at all. The tools have
existed since stage 2; nothing told a session they were there.

It now teaches §6.6's loop — survey, polarize, align, assign a value per set,
preview, read the unaccounted columns, refine, preview, commit — and says why
the loop closes: the preview a refinement is tested by *is* the preview a commit
is checked against, so there is no object that exists only inside a test and
then needs a second one. Four sections are new: the residue policy, conditioning
and complementary splits, restorations with §6.9's three refusals and the root's
structural limit, and `realign` with §6.1's framing — an edge case for a compound
against a simplex or two lexemes in one concept, never a routine step, and a
session realigning a large share of its concepts is fitting the evidence rather
than reading it.

The rule cascade keeps a section of its own, because it stays an accepted commit
shape through this stage. What changed is which one the manual leads with, and
that it now says what the cascade cannot do: a rule rewrites one child's own
segments, so a parent segment no single child preserves is unreachable by any
cascade. `⟨language_a v : language_b Ø⟩` reconstructs `*w` in one commitment and
in no rule.

`COMMIT_REQUIREMENT_NOTES` covered only the rule shape and was therefore wrong
for half the sessions it was shown to. It now covers both, leading with which to
prefer.

**This changes `instruction_sha256`.** Every checkpoint written before it
refuses to resume, naming the instructions as the part that moved — which is the
mechanism working, not a regression: a resumed run must not mix nodes
reconstructed under two different manuals.

`docs/running_inference.md`'s tool table was missing `test_proto_assembly` and
`realign` outright; both are there now.

### An oracle for the architecture, not only for the rule writer

`tools/oracle_ceiling.py --oracle assembly` gives every *node* a perfect
proto-inventory — one proto-phoneme per correspondence set, voted against the
withheld gold — and runs the real `ProtoInventoryAssembler` bottom-up. Until now
nothing computed it, so `docs/proto_inventory_design.md` §7 conditions 1 and 2
could not be evaluated at all: both are stated in terms of a number that did not
exist.

Polynesian, beam width 5, 46 concepts, 2026-08-24:

| Measure | context-free | context-sensitive | **assembly** |
| --- | --- | --- | --- |
| top-1 exact | 27/46 | 33/46 | **39/46** |
| beam exact | 40/46 | 40/46 | 39/46 |
| selection gap | 13 concepts | 7 concepts | **0** |
| mean top NED | 0.147 | 0.097 | **0.031** |
| `cross_branch_assembly_rate` | — | — | 0.957, non-zero at 7 of 7 nodes |

**The beam-exact column is not comparable by subtraction and the docs say so
three times.** Under a branch cascade the beam holds one whole string per branch
and beam-exact measures the selection slack; under assembly one candidate tuple
assembles into exactly one form, so top-1 and beam-exact converge by
construction. §7.3 already listed that comparison under "what is *not*
evidence", and condition 2 has to be read against it.

The oracle is given the two claims an inventory makes about a *language* — a
value per set, optionally conditioned, and a residue policy chosen per node by
running each — and is given neither `restorations` nor `residue_dispositions`,
which are claims about one concept. §7.4 records `1028` YAWN and `778` SMOKE as
concepts the ceiling cannot promise; they stay unpromised and are still misses.

`test_oracle_ceiling_regression.py` pins the third block beside the two it
already pinned, including §9.3's gap assertion in the new architecture's terms
(`MAX_ASSEMBLY_SELECTION_GAP = 2`, currently 0) and the fixture/real-benchmark
agreement under all three oracles.

### A rule cascade may no longer delete a whole word

Found by the oracle above, and reachable from both commit shapes. `RuleEngine`
built the next `LexicalForm` from a rule's output without checking it was
non-empty, so a cascade that consumed a form raised a bare pydantic
`ValidationError` from inside `traversal/reconstructor.py` naming no rule, no
form and no node. Under `rules` that needs a cascade of deletions; under
`inventory` it needs only a *derived* view where enough sets reconstruct
nothing, which is how it turned up — at Proto-Tongic the oracle's inventory
derives `l > Ø` for Niuean, and `k i l i` had already lost `k` and both `i`.

The refusal is per (rule, form): the form is carried through unchanged, the rest
of the cascade still runs, and the report carries the new
`ApplicationStatus.WOULD_EMPTY_FORM` with no match locations — applicable and
not applied, so `rule_coverage` sees a rule that could have fired and did not.
Every other layer already refused an empty form; only this one discovered it by
crashing.

Suite: **401 passed** (393 before).

### Pin that the assembly ceiling still bounds the thing it measures

`tools/assembly_ceiling.py` keeps its own `align_rows` and the harness runs
`LingPyAligner.align_multiple`. That separation is deliberate — an instrument
that imported the thing it measures would agree with it by construction — and
its cost is that the two can drift with nothing saying so. They did: the
instrument reported a node-local ceiling of 44/46 for an implementation that
could only reach 38/46, and no test in the suite could see it, because no test
compared them.

Walking the tree bottom-up and comparing column structure at every
(node, concept), on the checked-in Polynesian fixture:

| | identical column structure | node-local, instrument | node-local, harness |
| --- | --- | --- | --- |
| boundaries stripped | 225 of 322 — 69.9% | 44/46 | **38/46** |
| boundaries included | **322 of 322 — 100%** | 44/46 | **44/46**, same two missed |

`test_the_ceiling_instrument_and_the_harness_align_the_same_columns` pins the
*property* — every column the instrument sees is a column the harness sees —
rather than those counts, and fails against the pre-fix aligner naming the first
concept that diverges. It is what turns "44/46 is the ceiling" from an inference
into a statement about the code that runs. `docs/proto_inventory_design.md`
§12.5 and `docs/analysis_tools.md` carry the measurement.

Suite: **393 passed** (392 before).

### §7's falsification thresholds, re-derived against the repaired instruments

`docs/proto_inventory_design.md` §7 decides whether stage 4 happens, and every
number in it was written before stage 0 — before prompt 07 repaired four defects
in `tools/oracle_ceiling.py` and landed `tools/assembly_ceiling.py`. It carried a
banner saying so. The banner is gone because the numbers under it are now true.
No behaviour changed; this is measurement and documentation, plus one flag on one
analysis script.

| condition | as written | re-derived |
| --- | --- | --- |
| 1, expect | top-1 ≥ 39/46 | **≥ 44/46**, the node-local assembly ceiling |
| 1, stop if | top-1 < 32/46 | **< 33/46**, the context-sensitive oracle |
| 2, expect | `assembly_beam_exact` ≥ 41/46 | **≥ 40/46** — as phrased it was unsatisfiable, since both oracles report 40 |
| 3, watch | `1212`, `1408`, `1439` convert; `1217` and `1443` cannot | **`1212`, `1217`, `1408`, `1439`, `1443`** convert; `1028` and `778` cannot |
| 4, stop if | mean top NED > 0.110 | **> 0.097** |

The questions are untouched. The shape check — top-1 up, reachability not down —
and the mechanism check — `cross_branch_assembly_rate` > 0 somewhere — are the
ones this section was written with.

- **`tools/branch_recoverability.py` gains `--method {map,cascade}`** and
  `--oracle`. Condition 3's "unreachable from any single branch under a
  context-sensitive oracle" was measured by a script that is not in the
  repository, and a threshold nothing can reproduce is not a threshold. The
  cascade method now lives in the script that owns the question: 37/8/1 under the
  segment map, **39/6/1** under the real cascade, **40/5/1** with
  `--oracle contextual`. The lists are not nested — `branch_rules` keeps whichever
  cascade scores better on a branch *as a whole*, so a branch can lose one concept
  while gaining several — and §7.4 says so rather than hiding it.
- **`1217` and `1443` moved off the "cannot convert" side**, for different
  reasons. `1217` is reachable node-locally because the bottom-up pass aligns
  `m a t u a` against `t a m a` in smaller groups than the flat ten-way alignment,
  which gets it wrong; it is the one concept where node-local scores above flat.
  `1443` became reachable when the assembly ceiling was repaired, so §1.2's
  four-concept flat-unreachable list is a pre-repair figure.
- **§7.2's residue threshold now states its floor.** "Above ~0.3 at most nodes"
  means nothing without knowing what a *complete* inventory leaves behind. On
  Polynesian that is **0.125** — 42 unaccounted columns of 336, in 11 of 46
  concepts, and all 11 carry more than one cognate set — so the real headroom is
  0.18, not 0.3, and §7.2 says how to re-measure the floor for another family.
- **§7.5 lists every command**, so every figure in the section is reproducible
  from a line in the document, and the appendix table names them.
- **§7.2 gained one caution**, earned twice over: `cross_branch_assembly_rate = 0`
  is the design's own stop condition and also the signature of the survey and the
  assembler seeing different columns. Suspect the instrument first.
- `docs/analysis_tools.md` and `docs/benchmarks.md` carry the same figures, and
  §§1.2–1.3 gained a banner marking them as the pre-stage-0 argument rather than
  current measurements.

The oracle rows did not move for the boundary fix that landed immediately before
this, which was checked rather than assumed: `tools/oracle_ceiling.py` never
calls the shared aligner.

### Morphological boundaries are aligned material

`LingPyAligner` aligned `phonetic_segments`, which strips `+` and `-`, for every
caller. Under branch cascades that cost nothing — `make_leaf_beam` carries
`form.segments` and `RuleEngine` passes a boundary through untouched — and under
assembly it silently lost a token, because a parent form is built out of
alignment columns and there is no column for a token the aligner never saw.
`m a n u + l e l e` and `m a n u + r e r e` assembled to `m a n u l e l e`. That
was a regression against the shipped path, and nothing rejected or counted it.

- **`align_multiple` and `align` take `include_boundaries`, defaulting to
  `True`.** The choice is named once, at the shared input, so the survey, the
  preview, the commit-time re-derivation and the assembler read the same
  columns. Fixing it in `traversal/assembler.py` alone would have re-opened the
  survey/assembler column mismatch `docs/proto_inventory_design.md` §12.3
  records, whose failure signature is `cross_branch_assembly_rate = 0` — the
  design's own stop condition fired by a bug.
- **A `-` boundary is re-spelled for LingPy and restored positionally**, because
  LingPy writes an alignment gap as `-` too. It does not arise on any benchmark
  checked in here — all 148 Polynesian boundaries are `+` — which is why it has
  a test.
- **A boundary is a correspondence, argued in `docs/proto_inventory_design.md`
  §12.5 rather than assumed.** A `⟨+ : Ø⟩` set is the signal `polarize`'s own
  documentation calls decisive, and until now the harness could not show one.
  The alternative — restoring a `+` where most children had one — is the harness
  placing morphs on a majority vote, which §11.1 settled. No heuristic was added
  and nothing is proposed: the model names the value.
- **The DSL is untouched, deliberately.** `rules/parser.py` still refuses `+` and
  `-` as rule targets and as insertions, so `derive_branch_rules` gains a fifth
  case: either side a boundary → no rule, and the child reported in
  `boundary_change_child_ids`. Same shape as `non_invertible_child_ids` — a fact
  about what the derived *view* cannot spell, never a rejection, because the form
  assembles from its columns either way. `⟨+ : +⟩ → *+` is an identity
  correspondence and derives nothing.
- **Two adjacent readings moved with it.** `realign`'s "the rows must be the
  children's own forms" check compares against `form.segments`, or an override on
  a boundary-bearing concept could pass and then match no candidate tuple in the
  assembler; and a restoration may cite a boundary an out-group still shows.
- **`tools/correspondence_inventory.py` and `tools/assembly_ceiling.py` gain
  `--boundaries`**, so every baseline recorded before this change stays
  reproducible. Both remain independent implementations; neither imports the tool
  it checks.

**Measured on `runs/benchmarks/polynesian.json`, before and after in one
checkout.** Correspondence sets 218 → **246** under the tool's own reading, and
39 → **50** at support ≥ 2, because boundary correspondences recur. The default
survey page grew 17.5 → 17.9 KB; the `test_proto_assembly` preview a session
reads *shrank*, 23.5 → 21.7 KB, and its non-compactable half went 1.4 → 1.6 KB;
`get_alignments` over 3 concepts × 10 nodes grew 17%, the one figure that got
worse. A complete inventory now assembles all 46 concepts with
`unaccounted_column_rate` **0.125** (was 0.141) and `cross_branch_assembly_rate`
**0.761** (was 0.783), and **29 of 46 assembled forms carry a boundary where none
could before**. Node-local assembly reachability, measured with
`tools/assembly_ceiling.py --boundaries`, is **44/46 with boundaries against
38/46 without**: six of the eight gold concepts that carry a boundary in every
alternative — `1212`, `1217`, `1239`, `1439`, `1741`, `2105` — were unreachable
by construction and are not any more. `tools/oracle_ceiling.py` is unchanged at
27/46 and 40/46, as predicted, because it never calls the shared aligner.

Suite: **392 passed** (387 before), including a test that pins the assembled
parent form against the rule path's on the same children, so the two commit paths
can never again disagree about a token.

### Reconstructing per correspondence set — the deterministic core and the tools

Stages 1 and 2 of `docs/proto_inventory_design.md`. A node may now commit a
**proto-inventory** — a proto-phoneme for each correspondence set over its active
children — and deterministic code assembles each parent form column by column
out of it. The branch-cascade commit path is untouched and still the one the
instructions teach; `system_prompt.md` is rewritten and the change is measured in
a separate session, and nothing here is a default.

The reason it exists, in one case: a set `⟨Tongan ʔ : Niuean Ø⟩` reconstructs
`*ʔ`, so Proto-Tongic `*ʔ a l e l o` assembles from a form neither daughter
produces. As a branch-scoped rule that needs an insertion the DSL cannot write —
a live `tongic` node proposed `Ø > ʔ / #_` three times, was refused
`dsl-parse-error` three times, and fell back to identity.

**Everything this adds is a report.** Nothing new filters a trajectory, weights a
candidate, or decides whether a run was valid. `confidence` is the only quantity
that reaches the beam and it already did, now attached to a correspondence
rather than to a rewrite.

- **`schemas/inventory.py`** — `CorrespondenceCommitment`, `ResiduePolicy`,
  `ResidueDisposition`, `SegmentRestoration`, `AlignmentOverride`, and the commit
  and result models, with `derive_set_id` naming a set by its content: the reflex
  tuple, the child order, and **both** overlays, because a segmentation overlay
  changes what a segment is and an alignment overlay changes which columns
  exist.
- **`traversal/assembler.py`** — the assembly algorithm of §4.4, implemented
  deliberately rather than incidentally in four places. An unaccounted column
  *carries through* rather than vanishing, which makes assembly monotonic;
  an inventory that asserts nothing short-circuits to the existing identity path
  bit-for-bit, so `_fallback_step` is unchanged; conditioning is evaluated in
  proto terms in two passes; and assembly runs over the children's **full
  beams**, because 43 of 46 concepts carry more than one candidate at the
  Polynesian root and assembling from top candidates alone would make every
  intermediate error permanent. Alignments are cached by candidate tuple, which
  the design calls a requirement rather than an optimisation.
- **`alignment/environments.py`** — one definition of "the environment of an
  aligned column", used by the complementary-pair report, the
  `non-complementary-split` rejection, and the assembler's pass 2. A model handed
  a distinguishing token must not then be refused for using it.
- **Three new tools.** `test_proto_assembly` previews what an inventory
  assembles and is the call a commit is checked against; its result is *split*
  so the bulky half can be dropped from the live prompt while the validation ID
  and the verdict stay — which had to be right in the first version, because a
  result schema enters trajectories the moment a tool ships. `realign` re-lays
  one concept's columns under four constraints, of which the load-bearing one is
  that a realignment must name the correspondence set it joins and the harness
  verifies the set actually gains that support. And restorations let a node
  reconstruct a segment every active child lost on cited out-group evidence,
  with three arithmetic refusals.
- **`summarize_correspondences` gains `set_id` and `complementary_candidates`.**
  The pair report carries the tokens observed beside each set, because a report
  that states a conclusion and withholds the evidence for it is the shape §6.2
  exists to avoid. It is retrieval and not phonology: no feature table, no
  natural class, nothing ranked.
- **`commit_reconstruction` takes `rules` xor `inventory`.** A call carrying both
  is refused. Every commitment cites a set the harness re-derives from the node's
  own forms with the support it counted itself — stronger than the per-rule
  validation invariant, not weaker.
- **`schema_version` widens to `["2.0", "3.0"]`**, stamped per record rather than
  per build, because `committed_reconstruction.request.rules` is what every
  downstream reader indexes and some records no longer have it.
  `summarize-trajectories` reports `commit_shapes` — the migration's daily
  progress signal.
- **The `high_quality` gate dispatches on commit shape.** This is the one place
  the change could have done irreversible damage: three of the gate's five
  conditions read counters an inventory session leaves at zero, so left alone
  every such session would have passed all three unconditionally, the suite would
  have stayed green, and the loosened corpora could not be un-selected. A test
  pins equivalent workflow behaviour to the same verdict under either protocol
  and catches the equivalent defect under either.
  `docs/report_reject_or_score.md` gained a section on gates that loosen.
- **`child_convergence_rate` and `divergent_concept_count` are retired, not
  reimplemented.** One candidate tuple assembles into exactly one parent form, so
  branch divergence about the parent is structurally impossible — the metric's
  subject is gone. They stay `None`-defaulted and 2.0 records keep their real
  values. Two numbers replace them because the one was doing two jobs:
  `cross_branch_assembly_rate` and `unaccounted_column_rate`.

**One defect found while implementing that the design does not name, and it was
load-bearing.** `summarize_correspondences` aligned the child *lexicons*, which
at an internal node means every retained beam candidate; the assembler aligns one
candidate per child. Two different alignments, two different column boundaries,
so a model would have committed values for sets the assembler never sees and
`cross_branch_assembly_rate` would have read 0 everywhere — the design's own stop
condition, fired by a bug rather than by the mechanism being useless.
`one_reading_per_node` fixes it in both paths: one form per node per (concept,
cognate set). `tools/correspondence_inventory.py` gains `--reading` so it can
reproduce either view and stay the independent check;
`docs/analysis_tools.md` records where the two now differ (188 of 216 sets
identical on Polynesian). Three smaller corrections are in
`docs/proto_inventory_design.md` §12.3, kept with their reasoning rather than
deleted.

**Measured, not predicted.** `test_proto_assembly` costs **23.5 KB** for all 46
Polynesian concepts at `detail="summary"` — inside the 27.8 KB §6.8 budgeted,
against the 399 KB across three calls that `test_rule_cascade` cost at one live
node — and the half that cannot be dropped from the live prompt is **1.4 KB**.
A complete inventory over all 218 sets assembles all 46 concepts with
`unaccounted_column_rate` 0.141 and `cross_branch_assembly_rate` 0.783; **all**
of that residue is in the 11 concepts whose daughters carry more than one cognate
set, which is a floor imposed by multi-etymon glosses rather than by the
inventory, and §7.2's 0.3 threshold has to be read against it. These are
structural figures about the mechanism, not oracle or live accuracy numbers, and
no accuracy number is recorded here: `system_prompt.md` still teaches the rule
workflow, so there is nothing yet to measure. `docs/proto_inventory_design.md`
§12.4 carries all of it.

**And a live model drove the whole surface.** Against LM Studio
`google/gemma-4-26b-a4b` on a two-daughter Tongic fixture, with a throwaway
instruction, the model surveyed, previewed, refined and committed an inventory,
and the harness assembled `*ʔ a l e l o` — the form the recorded live `tongic`
failure could not express. It cost three protocol rejections, one of which was
writing `"reflexes": ["∅", "ʔ"]` where `null` was meant; `Ø` and `∅` are now
accepted, which is what `GAP_SEGMENT_TOKENS` already promised elsewhere. That is
a usability check, not a measurement — one node, one seed, four concepts, and an
instruction that is not the one session C will write.

**Two findings that block stage 3 and are deliberately not fixed here**, both in
`docs/proto_inventory_design.md` §12.5. First, **the assembler drops
morphological boundaries and the rule path does not** — assembly builds a form
out of alignment columns and the aligner strips `+` from every input, so
`m a n u + l e l e` assembles as `m a n u l e l e`. That is a silent regression
against the shipped path. On Polynesian, 8 of 46 gold concepts carry a boundary
in every gold alternative and are unreachable by assembly by construction,
capping top-1 at 38/46 — and two of the three concepts §7 names as proof the
mechanism fired, `1212` and `1439`, are among them. The fix reaches
`_alignment_inputs`, which every evidence tool shares, so it wants its own diff.
Second, **§7's thresholds all quote the instrument prompt 07 repaired**: the
node-local ceiling is 44/46 rather than 39/46, the context-sensitive oracle
33/46 rather than 32/46, beam-exact 40/46 for both, and `1217` is now reachable.
The questions §7 asks are right; its numbers need re-deriving before any live
seed is run.

Suite: 328 → 387 (`pytest -q -k "not local_run_artifacts"`).

The evaluation that makes the other changes provable. Held-out comparison used
exact token equality only, so a reconstruction one segment from
Proto-Polynesian `ʔ a l e l o` and one sharing nothing with it both scored zero
— the metric could not say whether a change helped. There was also no
multi-seed runner and no regression test on reconstruction quality, so a change
to the beam scorer could make every reconstruction worse while all 279 tests
passed.

**Everything added here is a report.** None of it filters a trajectory, weights
a candidate, or decides whether a run was valid. These are the closest this
repository has come to grading linguistic truth, which is exactly why they are
the most tempting numbers to gate on and exactly why they do not; see
`docs/report_reject_or_score.md`, which gained a fourth worked example for this.

- Added graded metrics to `HistoricalTargetEvaluation` and
  `TargetConceptEvaluation`, all defaulted so older artifacts still load: edit
  distance and normalized edit distance against the nearest gold alternative,
  B-Cubed F1 over the columns of the alignment, and a beam-aware best NED beside
  the top candidate's. Distances are over segment tokens, never characters —
  `a ː` is one sound. The exact B-Cubed variant implemented is documented in
  `cognate_reconstruction/evaluation/metrics.py`, because there are several and
  an undocumented one is comparable to nothing. Aggregates are `MetricDistribution`s
  — mean, standard deviation, quartiles, range — not pooled means, so a family
  with a good root and bad lower nodes is distinguishable from a uniformly
  mediocre one.
- **Reported the graded selection gap.** Mean top NED against mean beam-best NED
  is the graded form of the exact selection gap, and it is large under oracle
  rules (0.158 against 0.043) *and* under a live model (0.214 against 0.081), so
  it separates a selection problem from a generation problem in both regimes
  rather than only in the idealized one.
- Evaluated **every** node carrying gold, not only a bound root, and marked an
  evaluation computed over a `failure_fallback` node as what it is. A node that
  failed is not a node that reconstructed, and its beam is the harness's
  identity commit.
- Put the accuracy inside `inspect-run`'s per-node `DETERMINISTIC OUTCOME`
  block, below rule coverage, contrast loss, convergence, the held-out concept
  split, branch support, and the tie-break count — because an accuracy is the
  number most likely to be quoted alone. Renamed that block's concept-split line
  to `held-out concepts`, since **"held out" now means two different things**:
  a split of the session's own concepts that never leaves the node, and the gold
  answer key. `summarize-trajectories` keeps them apart as
  `held_out_convergence_rate` and `gold_target_evaluation`.
- Added `GoldEvidenceKind` — `attested`, `reconstructed`, `synthetic` — carried
  from the binding through to every score. A published proto-form is somebody's
  reconstruction, not an observation; Latin is the exception; a synthetic gold
  is a third thing. `None` is not defaulted to `attested`: silence must not read
  as the stronger claim.
- Added `build-benchmark`, driven by a declarative definition rather than a
  script, and reduced `tools/build_polynesian_benchmark.py` to a wrapper around
  it. Two definitions ship: `polynesian` (Walworth's Proto-Polynesian, a
  published reconstruction, 10 daughters, the same 46 fully-cognate concepts the
  old script selected) and `romance` (Latin, **attested**, 5 daughters, 900
  concepts — the Ab Antiquo dataset, so published neural baselines exist).
  Selection requires each daughter to share a cognate set with the gold entry
  rather than merely to attest the concept, which is what makes the benchmark a
  test of reconstruction instead of one of cognate judgement. A payload whose
  gold variety survives in the lexicons is refused loudly, per binding, and a
  definition naming its gold as a daughter is refused before any data is read.
  Extracted `ingestion/preparation.py` so `prepare-lexibank` and
  `build-benchmark` share one implementation of that removal.
- Added `run-benchmark`: N repetitions of one benchmark, each in its own
  subprocess and directory so a crash costs one seed, aggregated into
  `aggregate.json` and `aggregate.txt`. Every rate carries its spread and the
  per-seed table sits beside it, which makes a single number from a single run
  hard to quote by accident. A run that **finished with losses** and one that was
  **abandoned** — `--max-failed-nodes` exhausted, no `result.json` written at
  all — are counted apart, and a fallback node is never a completion. The
  aggregate carries `contrast_reducing_rules_per_node` and
  `held_out_convergence_rate_per_node` beside the accuracies, because those say
  *how* a node reached its coverage, and folds in the oracle ceiling for the same
  payload in a separate block: an oracle number bounds the architecture, a live
  number measures a model.
- Promoted the oracle ceiling to a regression test. It pins top-1 (27/46), beam
  exact (39/46), **and the gap between them**, at a stated beam width, plus the
  whole documented width curve. The gap is asserted because a change that raises
  top-1 while lowering beam-exact has traded candidates away rather than chosen
  better, and an accuracy-only assertion would call that a win. The width is
  pinned because width 10 scores *below* width 5 on this benchmark. Its
  docstring states what the oracle can and cannot express: `oracle_map()` is
  context-free while the DSL has contexts, so its misses bound *that oracle*,
  never the rule language. The test imports `measure()` from
  `tools/oracle_ceiling.py`, so the suite and the script report one number, and
  runs against a checked-in fixture — the real benchmark with per-form
  provenance stripped, which reproduces the full-dataset figures exactly because
  the oracle reads only segments, the tree, and the gold.
- Made `tools/branch_recoverability.py` name the concepts in each class rather
  than only counting them, in text and in `--json`. The 8 Polynesian concepts
  needing evidence mixed across branches are the concrete prediction any change
  to the combination model has to move, and a count is not a list.
- Gave every analysis script a `--json` mode and benchmark-name resolution, so
  the multi-seed runner consumes them instead of re-implementing the
  measurements. Every JSON object carries `measuring` alongside `benchmark`:
  `sys.path` used to resolve the package through the editable install rather
  than the checkout beside the script, and a machine consumer is the reader
  least able to notice a number from the wrong worktree. Baselines are
  unchanged — 66 ties, 29 winnable, 18/18/23/25 across the four tie-break
  policies; 216 correspondence sets, 41 at support ≥ 2; 37/8/1 on branch
  reachability.
- **Added synthetic benchmarks: gold, and the sound changes, by construction.**
  `build-synthetic` runs `RuleEngine.apply_rules` *forward*, parent to child,
  down a tree from a proto-lexicon and a per-branch cascade written in the same
  DSL the model commits in, and writes the payload and a **separate** answer key
  — never the same file, and writing one over the other is refused. A branch is
  named by its lower end, so a cascade on an internal node is a shared
  innovation and subgrouping is recoverable from the data rather than only
  asserted by the tree. Three families ship: `synthetic_regular` (the control,
  every branch invertible), `synthetic_hard` (a merger only a sister
  disambiguates, a segment lost everywhere except one branch, a chain shift whose
  rules must be ordered, a conditioned split, gold at three nodes), and
  `synthetic_noisy` (two irregular forms, a loan, a semantic mismatch, from a
  seed). Noise is off by default: a benchmark with no residue is not a test of
  the anomaly machinery. Under oracle rules the two clean families score 16/16
  and 22/25 top-1 with 25/25 in the beam, which is how a generated family is
  known to be sound rather than merely hard.
- **Scored the changes and the direction, not only the forms.** `score-synthetic`
  reports rule precision and recall against the true child-to-parent cascade
  (structural, deliberately literal, a lower bound), functional recovery per
  branch (apply the committed cascade to that branch's gold forms and ask
  whether the parent's come back), and the measurement that exists nowhere else:
  a rule scoped to a branch the answer key gave **no** rule is a rule pointed at
  a branch that did not change. Prompt 04 forced the model to state that claim
  and the harness deliberately never grades it; here it is checkable without
  reading a word of prose. The first live run on `synthetic_regular` got all
  four leaf branches exactly right and then committed `p > f` on `inner_b`, the
  branch that did not innovate, instead of `f > p` on `inner_a` — 0.75 precision,
  0.75 recall, one misdirected rule, and root top-1 down to 10/16 as a result.
- Recorded which branches **cannot** be undone by any rule. The DSL has no
  empty-target insertion, so a branch that deleted a segment can never restore
  it; the answer key marks those non-invertible and gives them no inverse
  cascade, and scoring never charges the model for a rule it cannot write. Every
  derived inverse is verified against the real forms before it is recorded — if
  it does not reproduce the parent, the branch is not invertible, because a
  family whose answer key is wrong makes every number built on it meaningless.
- Reported, in each node's session block, whether a directionality claim rested
  on retrieved evidence: how many `polarize` calls the session made, how many
  returned an out-group at all, and how many committed rules carry a rationale.
  Entirely structural — `polarize` tags every node it reports with a `relation`
  — and never a reading of the prose. The recorded live run flags exactly one
  node, `proto_polynesian`, where a rationale cited out-group support that
  `polarize` had not returned; the root has no out-group, which is a property of
  the tree. It gates nothing, and whether that rationale is *wrong* still needs a
  human.
- Added distributions and per-node rows to `summarize-trajectories` —
  per-trajectory protocol-failure rate, child convergence, held-out convergence,
  contrast-reducing rule count, rule coverage — and an optional `--result` that
  folds in the graded gold accuracy. A threshold cannot be calibrated against a
  number that has already been averaged, which closes the cheap enabling half of
  the `high_quality` calibration item in README, "Research validity next".
- Removed `examples/polynesian_benchmark_bindings.json`, superseded by
  `benchmarks/polynesian.json`. `examples/historical_bindings.json` remains the
  documented example of that file format.
- Documented all of it: a new `docs/benchmarks.md` covering what each kind of
  gold is evidence for, a new README section on evaluation and benchmarks, a
  quick-start step that starts from a benchmark rather than a hand-assembled
  payload, `jq` recipes for the graded scores and the worst misses, the two
  senses of "held out" named apart wherever both appear, and five new
  development invariants — evaluation stays a report, a failed node is never a
  reconstructed one, the answer key stays out of the payload, a bound `target`
  stays out of the lexicons, and a reported score always says what its gold is.
- Repaired every multi-line shell command in `README.md`. Twelve blocks carried
  a literal `+  ` where a `\` line continuation belongs, so none of them could
  be pasted into a shell; the documented `infer`, `prepare-lexibank`, resume,
  curation, and `jq` invocations all run now. A syntax check over every fenced
  `bash` block in the repository is how they were found.

Directionality and discipline. Rules are child-to-parent, so "make the children
agree" is satisfiable by rewriting either child, and nothing ever asked which
branch innovated. A live Proto-Polynesian run scoped every rule it committed to
exactly one daughter, and three of the seven were backwards — `ʔ > Ø / #_` on
the Tongic branch that *preserves* `*ʔ`, `f > h` and `t > k` on North Marquesan
when Hawaiian innovated both. It reproduced after the correspondence survey and
branch-support weighting landed, because better evidence does not help with a
question nothing asks.

**No sound-change table, typology data, or naturalness score was added, and none
will be.** That knowledge lives in the model's weights; the harness's job is to
make sure it is used and recorded. See README, "Directionality: which branch
innovated", for the reasoning.

- Added `polarize`. Given one correspondence — the active children and the
  segment each shows — it reports what every node outside them shows in the same
  aligned columns, with counts, its relation, and whether it is observed or
  reconstructed. Data retrieval, not a prior: it never names the original value.
  The evidence was already in the harness and the live run consulted it once.
  Its design carries the three findings `tools/outgroup_probe.py` measured —
  count per clade, presence is evidence and absence is not, morphology first —
  and states the two limits it cannot report around: the argument inherits the
  supplied classification, and the root has no out-group.
- Added `directionality_rationale` to `CommittedSoundRule`, **required on every
  rule that deletes a segment or merges two of a child's distinct segments into
  one**. Detection is mechanical, over the mapping the committed cascade induces
  on the forms (`rules/contrast.py`), and the rejection —
  `missing-directionality-rationale`, naming the exact `rule_id`s — is on
  *absence only*. The harness never evaluates what the rationale says. Stated in
  the prompt payload's new `commit_requirements` as well as in `SKILL.md`, so it
  is not discovered through a rejection.
- Reported what a commit discards. `test_sound_law`, `test_rule_cascade`, and
  the commit result name each contrast-reducing rule and count how many
  available nodes still attest the material — *"removes `ʔ`, attested in 3 of 10
  available nodes"* — split by observed and reconstructed. Reported and scored,
  never rejected: contrast loss is ordinary sound change.
- Added `contrast_reducing_rule_count` to `ReconstructionDiagnostics` and
  printed it directly beneath `rule_coverage` in `inspect-run`. Coverage rises
  when rules fire and the cheapest way to make a rule fire is to delete a
  distinction, so a node that scored well by discarding contrasts no longer
  reads as the best node in the run. README, "Quality and scoring", names the
  incentive.
- Split each node's concepts ~70/30 into a development and a held-out set,
  ordered by the digest of the node ID and the concept ID, so it is reproducible
  across runs, resumes, and re-runs, and differs between sibling nodes. Rule
  reports carry a held-out summary — applications, context mismatches, and the
  held-out convergence rate — the commit result carries it, and the trajectory
  records `held_out_convergence_rate`. Nothing rejects on it: a rule generalised
  from one word should *look* bad, not be forbidden. The split is shown in the
  prompt payload rather than hidden.
- Rewrote the comparative-method section of `agent/SKILL.md` around direction of
  change, and asked the model explicitly for its own knowledge of sound-change
  typology — in the rationale, named, where a reviewer can check it. Placed
  `polarize` in the required workflow after the correspondence survey, with the
  explicit warning that a rule scoped to a child which *preserves* a contrast,
  deleting it, is almost always the wrong direction.
- Unified rule-ID derivation across `test_sound_law`, `test_rule_cascade`, and
  `commit_reconstruction`, so a rejection naming a `rule_id` names one the
  session has already seen.
- Stopped a descendant reading as out-group support in the `polarize` summary.
  Only an out-group can polarize: a descendant lies inside the node's subtree
  and shows what its own children became. At the root *every* available node is
  a descendant, so the limit does not present as an empty result — the live run
  at `proto_polynesian` got 14 back under a note reading "14 node(s) outside the
  active children were inspected", which is true and reads exactly like support.
  The summary now counts the two apart and says when there is no out-group.
- Separated the finding from the ask in the directionality rejection. A live run
  pasted the harness's own count back as its rationale — *"ʔ is attested in 8 of
  11 available nodes"* — which satisfies the field and answers nothing, and the
  old remediation rendered that note immediately after the `rule_id`, inviting
  the copy. The counts are now labelled "What the harness found", the request
  for the claim is separate and explicit, and it says restating them is not an
  answer. **The fix is in what is asked for, not in what is checked**: a
  rationale that still restates the counts is still accepted, because content is
  never judged.
- **The new tool and the new committed-rule field each invalidate existing
  checkpoints on their own**, through the tool-schema and instruction digests.
  The held-out share is deliberately not part of that hash set — it changes no
  committed rule — but the split it produces is recorded in every payload.

Loop resilience, driven by a 7-node Polynesian benchmark that failed three ways
in three attempts and never reached the root.

- Let a `test_rule_cascade` preview satisfy the per-rule validation
  requirement. The cascade applied the rule to real forms *and* in its
  committed order, which is strictly more evidence than a standalone test. The
  workflow `SKILL.md` prescribes — test, cascade, refine, commit — previously
  had no legal path through the commit contract. The bound record and its
  `validation_kind` are stored in the commit.
- Derived the validation match key from the parsed rule instead of the DSL
  source string, so `t > k` and `t > k / _` — identical to the engine — no
  longer reject each other. `rule_id` stays lexical; it is persisted.
- Narrowed `validation-ambiguous` to matches that disagree about which forms
  the rule applied to. Matches that agree are one experiment run twice and now
  resolve deterministically, preferring a cascade record and then the most
  recent.
- Made a rule-specific rejection answer the question it raised: the remediation
  names that rule's own DSL, the near matches that differ only in environment
  (the refinement case), and the call that would unblock the commit, before the
  session catalogue.
- Made a node failure non-fatal. The failure is recorded in
  `result.json:node_failures`, an identity fallback is committed so the walk
  continues, and the step is marked `diagnostics.failure_fallback` — distinct
  from `identity_reconstruction`, which it does not overload. Fallback nodes are
  excluded from the reconstructed-node counts, from `high_quality`, and from
  trajectory export, and are surfaced by `inspect-run` at the top of its report.
  Added `--fail-fast` and `--max-failed-nodes` (default 3). A run-budget failure
  is never absorbed into a fallback.
- Kept a fallback node, and every node above it, out of the checkpoint, so
  `--resume` re-runs exactly the nodes whose reconstruction a failure cost.
- Removed the give-up thresholds from `configuration_sha256`. They cannot change
  a committed rule or a beam, and hashing them meant the one change a stall
  invites — loosen and resume — was the change that invalidated the checkpoint.
  They stay recorded, and a resume reports that they moved. **This and the added
  `validation_kind` field invalidate existing checkpoints.**
- Forced a tool call after *every* truncated no-tool response rather than once
  per node, stopping only if the backend refuses `tool_choice="required"`, and
  named the observed output token counts in the truncation stall so a new
  `max_tokens` is not a guess.

Reliability work driven by live `google/gemma-4-e4b` runs in which every
reconstruction was linguistically correct but 43–71% of tool calls were
rejected commit-schema errors.

- Described every `CommittedSoundRule`, `CascadeRuleSpec`, and
  `CommitReconstructionArgs` field, including `validation_call_id`, which
  previously had no description at all.
- Added `remediation` to `ToolError`. A rejected `commit_reconstruction` now
  returns every recorded `(validation_call_id, dsl, source_child_ids)` triple,
  including when the rejection came from schema validation before the handler
  ran.
- Made the per-rule `validation_call_id` optional: an omitted ID is resolved
  from the unique same-session `test_sound_law` validation whose DSL, child
  scope, and segmentation overlay match exactly, and the resolved ID is stored
  in the commit request. Zero or multiple matches are rejected. The
  exact-same-session-validation invariant is unchanged.
- Made `supporting_form_ids` default to the resolved validation's forms, and
  `rationale` optional. A supplied form list must still be a subset, and a rule
  supported by no form is still rejected. `confidence` remains required.
- Added `failed_tool_call_count`, `tool_failures_by_type`, and
  `truncated_response_count` to `AgentNodeMetrics`, all defaulted so existing
  trajectories stay loadable, and surfaced them in `summarize-trajectories` and
  the run-triage skill.
- Gated `high_quality` on a protocol-failure rate of at most 0.25. This is a
  workflow heuristic, not a linguistic judgement; it previously returned true
  for a session that failed 10 of 14 tool calls.
- Added `ProtocolStallError`. Three identical rejections of one tool within a
  node — counted per error signature across the node, not only back to back,
  since a live session alternated between two commit errors — now trigger one
  targeted correction carrying that tool's remediation, and one further
  recurrence ends the node instead of exhausting the turn budget.
- Handled `finish_reason="length"` explicitly with a `response_truncated` event
  and a specific instruction to reply with a smaller tool call, stalling after
  three truncated no-tool responses.
- Added `max_repeated_tool_failures` and `max_truncated_responses` as
  orchestrator parameters, included in the orchestrator's own
  `public_configuration`. `infer` computes and supplies its own configuration
  hash (`cli._provider_and_configuration`), which overrides the orchestrator's;
  it now contains both thresholds, and both are CLI flags. See the checkpoint
  entry below — this is the change that invalidates existing checkpoints.
- Changed `rule_coverage` to `successful_applications /
  applicable_rule_results`, excluding results whose form never contained the
  rule's target, and added `applicable_rule_results` to the diagnostics. A
  correct rule scoped to a whole polytomy no longer scores 0.33 where the same
  rule scoped to one child scores 1.0. Historical diagnostics keep their
  recorded values.
- Kept `schema_version` at `2.0`: the new fields are additive and defaulted,
  and `trajectory_schema_sha256` already records the exact schema per record.
- Added a structural `code` to every tool rejection, drawn from a closed
  vocabulary documented in the new `agent/error_codes.py`. Schema rejections
  derive theirs from the sorted set of `(field location, error type)` pairs with
  list indices normalized, so `rules.0.confidence` and `rules.1.confidence`
  collapse to `schema:rules[].confidence=missing`. `message` is unchanged and
  still carries the full explanation; the code exists only for counting and
  matching.
- Changed the stall signature from `(tool, error type, error message)` to
  `(tool, code)`. Pydantic embeds input values in its messages, so a model whose
  malformed arguments kept changing produced a fresh signature for one
  unchanging mistake and looped until the turn limit. It now stalls.
- Keyed `tool_failures_by_type` on the code rather than the exception class
  name: a real run reported `{"ValidationError": 4}`. The field name is
  deliberately unchanged, since `extra="forbid"` would make existing records
  carrying it unloadable.
- Bounded the stall detector's memory with a trailing window of
  `stall_window_calls` tool calls, default `3 * max_repeated_tool_failures`, with
  successful calls occupying slots. A long, mostly-productive session is no
  longer killed by three well-separated repeats it recovered from each time,
  while the interleave that defeats reset-on-success — bad commit, good test, bad
  commit — still trips. Added to the orchestrator's `public_configuration` and
  exposed as `--stall-window-calls`.
- Added a second stall condition on the same window: when
  `max_window_protocol_failures` of the last `stall_window_calls` calls were
  protocol rejections, whatever their codes, the node draws one correction
  naming them and then raises `ProtocolStallError`. The per-signature rule needs
  the *same* code N times, so a model producing a differently-shaped protocol
  error every turn spent its whole budget and ended in `AgentLoopLimitError`
  with no diagnosis. Defaults to `min(2 * max_repeated_tool_failures,
  stall_window_calls)`; exploratory rejections are excluded from the count.
- Coded the alignment backend's refusals at the tool boundary
  (`alignment-failed`), closing the last path by which a model-reachable
  rejection arrived as `unclassified`.
- Documented in `CascadeRuleSpec` and the `test_rule_cascade` description that a
  cascade rule carries no `validation_call_id`. A live `google/gemma-4-26b-a4b`
  run sent one and was rejected; the schema is unchanged, since accepting the
  field would weaken validation to paper over a documentation gap.
- Added a `tool_failures_by_code` read-only view of `tool_failures_by_type`, so
  new code reads the name that describes the key while the persisted field stays
  where append-only auditability needs it.
- Reported the number of distinct messages behind each code in triage. Two
  unrelated mistakes sharing a code cannot be prevented in general; this makes
  the over-collapse visible so a code can be split on evidence.
- Guarded the triage driver's hand-copied exploratory code set against the real
  classification, and the two checked-in skill copies against each other, with
  tests rather than by removing the duplication — the driver is stdlib-only by
  design so it runs without the harness installed.
- Split rejections into `exploratory` (`dsl-parse-error`, `no-op-rule`,
  `empty-scope`) and `protocol` (everything else, including all `schema:*`
  codes), with anything unclassified failing closed as protocol, and gated
  `high_quality` on the protocol rate alone. A `test_sound_law` rejection for a
  malformed DSL is the hypothesis loop working; counting it like a commit
  reference error scored a model that explores below one that never explores.
- Added `protocol_failure_count` to `AgentNodeMetrics`, defaulting to `None`
  rather than `0` so records written before the split fall back to
  `failed_tool_call_count / tool_call_count` and keep the exact `high_quality`
  verdict they already had. `failed_tool_call_count` remains the total.
- Added a floor of one protocol failure to the `high_quality` gate: a three-call
  identity commit was disqualified at 0.33 by a single slip it recovered from.
  The 0.25 threshold is unchanged and still uncalibrated.
- Surfaced the code in `tool_result` events, in `summarize-trajectories` (which
  now reports `total_protocol_failures` and `total_exploratory_failures`), and in
  the run-triage skill's failure taxonomy.
- Added `NoOpRuleError` to the rule parser so a rule that does nothing can be
  told from one that does not parse without matching on prose.
- Recovered from truncation instead of only naming it. `LLMProvider.complete`
  gained keyword-only `tool_choice` and `max_tokens_override`; the turn after a
  truncated response that carried no tool call is now requested with
  `tool_choice="required"`. This crosses no configuration boundary — the
  request shape is the harness's own responsibility — and is attempted once per
  node, falling back to the ordinary request if the provider raises or still
  returns no tool call. Every scripted provider in `tests/workbench/` accepts
  and ignores both keywords.
- Added `--allow-truncation-backoff` and `--truncation-max-tokens-ceiling`,
  **off by default**, letting the harness double the effective `max_tokens` for
  the rest of a node after a truncated no-tool response, never above the
  ceiling. `max_tokens` is a user-supplied `--provider-config` option, which is
  why this is opt-in and why the adapter merges the override into a copy rather
  than mutating stored options. The base for doubling is the truncated
  response's reported output length; a provider that reports no usage gets no
  backoff, since there would be no way to guarantee the raised value stays
  above what the user configured.
- Added `forced_tool_choice_count` and `truncation_backoff_applied` to
  `AgentNodeMetrics` and a `truncation_recovery` event, both defaulted, so a
  session that only reached a tool call because the harness intervened is not
  silently identical to a clean one. The `ProtocolStallError` message now says
  which recoveries were already tried.
- Made `trajectories.jsonl` a readable input on `--resume`. Committed
  hypotheses lived only in `AgenticNodeReconstructor.prior_reconstructions` for
  one process, so after a resume `get_node_reconstruction` returned nothing for
  checkpoint-restored nodes even though their lexicons were fully available —
  two kinds of cross-node information with different durability and no way to
  tell from outside. `seed_prior_reconstructions` replays completed
  trajectories through the same `summarize_commit` the live path uses.
  `infer --resume` seeds only records that are completed with a commit, name a
  node in the checkpoint, and carry both the current `configuration_sha256` and
  the checkpoint's `run_id`, and prints how many. A missing or unreadable file
  warns and continues; a file that fails schema validation stops the run.
- Filtered seeding on `run_id` as well as the configuration hash. The hash
  cannot separate two invocations — the same model over the same input with the
  same settings hashes identically — and `--trajectories` defaults to one file
  in the working directory, so two runs append to it. Reproduced before fixing:
  a checkpoint from `run-A` seeded node X's hypothesis from `run-B`, pairing one
  run's checkpointed lexicon with another run's rules, decided by which line was
  written last. `--run-id` cannot change during `--resume`, so the filter
  excludes nothing legitimate.
- Documented, without changing behaviour: that `--max-truncated-responses`
  bounds how far `--allow-truncation-backoff` can escalate (two doublings at the
  defaults); that `--stall-window-calls 9` and omitting the flag hash
  differently despite identical behaviour; and that `high_quality` does not
  currently penalise a node that needed truncation recovery. The last is left
  open as part of the threshold-calibration item rather than settled in code.
- Recorded `TrajectoryDatasetBuilder.read_jsonl`'s whole-file materialization
  under "Trajectory and training boundary", now that seeding makes it four
  callers rather than three. Measured rather than estimated: a 434 KB record
  costs 1.5 MB resident and 2.8 MB peak, of which seeding uses 2.4 KB. Left
  unoptimised deliberately — a 30-node family peaks around 85 MB beside a local
  model holding gigabytes — with the fix specified as a streaming variant of the
  reader serving all four callers, and the conditions that should trigger it
  written down. Seeding would need no API change for that: the reconstructor
  already accepts an `Iterable` and retains only the summary.
- Passed the seeds through `ReconstructionService.reconstruct_family` rather
  than setting them beforehand: `clear_run_results` at the top of that method
  also clears prior hypotheses, so anything seeded earlier was silently wiped.
  A test pre-seeds, clears, and fails if that ordering is ever inverted.
- **Existing CLI checkpoints do not resume after this release.** Verified, not
  assumed: a checkpoint written by `infer` before this change was replayed
  against the new code and refused with `checkpoint cannot be resumed because
  these changed: the configuration`. The earlier note in this section claiming
  such checkpoints remain resumable described the state before this change and
  has been corrected. `cli._provider_and_configuration` now hashes
  `instruction_sha256`, the tool-schema hash, and a digest of the `--anchors`
  file, using the same derivations as `AgentOrchestrator._trajectory` so the two
  artifacts report identical values.
- Exposed `--max-repeated-tool-failures`, `--stall-window-calls`, and
  `--max-truncated-responses` as CLI flags and included them, with the two
  truncation-backoff flags, in the configuration hash. `max_window_protocol_failures`
  remains orchestrator-only; the CLI never sets it and its default derives from
  two hashed values, so it cannot change independently from the command line.
- Added `configuration_components` to `FamilyCheckpoint`, defaulted, holding
  named digests of the parts of the configuration hash. A refused resume now
  reads "these changed: the agent instructions" instead of "these hashes
  changed: configuration". `configuration_sha256` is still the decision; a
  checkpoint written without components refuses correctly and keeps the generic
  wording rather than guessing.
- Added a ninth tool, `get_node_reconstruction`, returning the rules, child
  scopes, confidences, anomalies, and summary committed at one node already
  reconstructed in this run, and flagged those nodes with
  `has_committed_hypothesis` in `list_available_nodes`. Each node still gets a
  fresh conversation; a prior rule is exposed as a hypothesis, is never
  citable as support, and has no effect on scoring. Visibility follows the
  traverser's post-order reconstructed-evidence set, so nothing leaks from a
  node that has not been reconstructed yet. Hypotheses from nodes restored by
  `--resume` are not retrievable, since those nodes never ran in the process.
- Added `inspect-run --run-dir`, the supported artifact-facing report over
  `result.json` and `trajectories.jsonl` (`events.jsonl` when present). Plain
  text on stdout; `--html PATH` writes one self-contained file with no external
  CSS, JS, fonts, or images, readable in light and dark, with rule tables
  scrolling inside their own container; `--all-forms` lifts the 40-form cap. Per
  node it reports the session shape, the committed hypothesis, the deterministic
  diagnostics, the best lexicon, and `high_quality` **with the condition it
  failed**. A missing `events.jsonl` drops only the event counts; a missing
  `result.json` falls back to the trajectories' own beams.
- Added a report-only cross-node consistency section: one DSL committed at
  several nodes with materially different confidence, adjacent nodes mapping the
  same target in the same environment to different things, and a correspondence
  established below a node that the node never mentions. Worded as observations,
  headed by a line saying the harness does not judge historical correctness, and
  scored by nothing — a test asserts a contradictory family and a consistent one
  get identical `high_quality` verdicts. Penalising any of it changes what counts
  as a valid reconstruction and stays a research-owner decision.
- Made `driver.py triage` shell out to `inspect-run` for the artifact sections
  instead of keeping its own copy of them. Triage keeps what only `events.jsonl`
  knows: the turn-by-turn timeline and the failure taxonomy, which is still the
  only source of rejection counts for runs written before failure accounting.
- Added `AgentTrajectory.high_quality_failure_reasons`, and defined
  `high_quality` as that tuple being empty. The report states why the gate
  failed rather than describing the gate, so the two cannot drift.
- Required a per-rule `rationale` on commits carrying more than one rule, with a
  new `missing-rule-rationale` code and a remediation naming the exact
  `rule_id`s. The schema keeps the field optional, so existing records stay
  loadable, and single-rule commits are unaffected — the measured transcription
  friction that made `rationale` optional was entirely on those. One `summary`
  cannot attribute reasoning to one of several rules, and a corpus filter that
  discards every multi-rule commit for missing reasoning is the worse outcome.
- Added `schema_variants` and `current_trajectory_schema_sha256` to
  `summarize-trajectories`: record counts grouped by `trajectory_schema_sha256`
  with the current digest marked. `schema_version` stays `2.0` — the rule, now
  written down in the README, is to bump it when a reader must behave
  differently, never merely because fields were added. A regression test widens
  the literal to `Literal["2.0", "2.1"]` and asserts a real 2.0 file still loads
  and still says 2.0.
- Committed `tests/workbench/fixtures/trajectory_real_pre_change.jsonl`, a
  genuine pre-change live run copied verbatim out of `runs/`, and asserted
  against it that the record loads and keeps its exact `high_quality` verdict.
  The claim previously rested only on globbing gitignored `runs/`: clearing that
  directory reduced the parametrization to zero cases and left the suite green
  with the guarantee gone. The glob stays as opportunistic extra coverage, so
  `pytest -q -k "not local_run_artifacts"` is now the authoritative count.
- Noted, without changing it, that `result.json` is written with computed fields
  included and therefore does not round-trip through its own `extra="forbid"`
  model. `inspect-run` reads it as JSON and validates the fragments it uses.
- Added `docs/report_reject_or_score.md`, recording the reasoning the
  mechanical/workflow/linguistic invariant compresses into one line: the three
  questions a run can be asked, why a report is reversible and a gate is not,
  and the rule for deciding which a new signal belongs to. The worked example is
  the cross-node observation that fires on a perfectly correct run — report it
  and a human reads a line; score it and a correct reconstruction is excluded
  from the corpus.

### Making linguistic evidence affordable to look at

Driven by a 10-language, 46-concept Polynesian benchmark that could not be
completed in three attempts. One `get_alignments` call for six concepts across
two languages returned 31 KB and moved a session from 5,003 to 34,286 tokens; the
same call across ten languages returned 2,885 KB. Inspecting evidence cost more
context than reasoning about it, so the model committed on 5, 12, 12 and 8 of 46
concepts.

- Stopped re-embedding the alignments in every pairwise view.
  `CorrespondenceMap.alignments` became `alignment_ids`, with the alignments held
  once on `MultipleAlignmentMap` and a validator that keeps every reference —
  pairwise IDs and example columns alike — resolvable against them. With N nodes
  the alignments were previously serialized `1 + N·(N−1)/2` times.
- Added `detail` to `GetAlignmentsArgs`, defaulting to `"summary"`: correspondence
  records carry a true occurrence `count` plus at most three
  `(alignment_id, column_index)` references into alignments that are in the
  payload anyway. `"full"` still returns every column occurrence with its
  contexts.
- Renamed `CorrespondenceSummary.observations` to `example_observations`, added
  `example_columns`, and relaxed `validate_counts` from `count == len(...)` to
  bounding the samples by the count. The old field name and the old validator
  together were what *forced* the full trace to be present; `count` is the true
  count under both renderings, and no sample is ever passed off as complete.
- Shortened `alignment_id` from every participating variety spelled out to
  `msa-<selection digest>:<concept>:<cognate set>`. The selection stays in the ID
  because the same cognate set aligned against different daughters is different
  aligned material, but 308 characters repeated once per reference was 700 KB of a
  single ten-node call.
- Raised the `get_alignments` concept cap from 12 to 24 on measurement, not
  preference: 24 concepts cost 41 KB across two nodes and 82 KB across three. The
  docstring states what the cap does not do — it bounds concepts, not bytes, since
  the pairwise term is quadratic in the node count.
- Added `summarize_correspondences`, the tenth tool: correspondence sets over the
  whole evidence set at once — the n-tuple of aligned segments across the selected
  nodes with its support count — ordered by support, with `min_support` defaulting
  to 2, an optional `segment`/`segment_node_id` filter (`Ø` for a gap, as in the
  DSL), and `list_concepts`-style pagination. It deliberately takes no batching
  bound on its input, because recurrence is invisible in a batch; the output is
  bounded instead. `total_set_count`, `matched_set_count`, and
  `suppressed_below_min_support` are reported so a page of thirty rows says
  whether there is a tail. 216 sets over ten Polynesian daughters and all 46
  concepts, 28 KB, matching `tools/correspondence_inventory.py` set for set.
- Populated `ReconstructionStep.correspondence_maps`, which had been declared,
  serialized as `[]` into every artifact by every run, and populated by nothing.
  It uses the compact rendering and is recorded only when the traverser supplies
  an evidence context, so the analysis scripts in `tools/` still pay nothing.
  448 KB of a 10,017 KB `result.json` on the seven-node Polynesian benchmark
  (+4.5%), which is twice the 232 KB the snapshot alone shows: a step is
  serialized both in `snapshot.steps` and as the trajectory's
  `reconstruction_step`. Nothing in it reaches a rule, a candidate, or the beam.
- Dropped superseded evidence results from the live prompt. When a read-only
  evidence call re-requests a selection an earlier call covered in full, the
  earlier tool message content is replaced by a `{"compacted": true, ...}`
  placeholder naming the tool, its call ID, and the call that superseded it;
  `compacted_tool_results` counts it per node and a `context_compaction` event
  records it. Supersession requires full coverage, not overlap, and every
  non-selection argument must match exactly. The most recent result for a tool,
  rejections, validations, cascade previews, overlays, and commits are never
  eligible. **The trajectory keeps the full content**: only the live prompt
  shrinks, and the two are allowed to diverge because a record edited to fit is
  worthless as a record.
- Rewrote the required workflow in `SKILL.md`: survey the correspondence
  inventory, read it by support, narrow it by segment, and only then pull
  alignments for the concepts a set names — and said plainly that a correspondence
  with support 1 is residue rather than evidence. The instruction text and the
  tool schemas are both hashed into checkpoint compatibility, so **every existing
  checkpoint refuses to resume**. That is correct: a resumed run would otherwise
  finish its remaining nodes under a different workflow from the ones already in
  the checkpoint.

## 0.2.0

- Refocused the installed project on `cognate_reconstruction`.
- Migrated CLDF ingestion and Newick traversal out of the legacy generator.
- Added strict historical-anchor files and CLI policies.
- Added provider-neutral LiteLLM configuration, safe secret handling, request
  normalization tests, retry controls, run budgets, and LM Studio as an
  optional preset.
- Added structured event JSONL, provider/usage metadata, per-node metrics,
  failed trajectories, and atomic checkpoint/resume.
- Added ordered cascade preview, mechanical quality diagnostics, and visible
  identity-without-inspection/testing flags.
- Rejected mechanically empty sound laws such as `p > p`; historical
  trajectories containing them remain auditable but are excluded from
  high-quality exports.
- Versioned trajectories at 2.0 and added validation, summary, filtering, and
  generic training-example export commands.
- Archived the former Stage-1/Stage-2 generator, commands, tests, and metadata
  in the [predecessor repository](https://github.com/acraevschi/llm_cognate_reflexes);
  only the curated lineage CSV is carried forward, as
  `data/historical_lineages.csv`.

## 0.1.0

- Initial Lexibank corpus-generation and reconstruction workbench experiments.
