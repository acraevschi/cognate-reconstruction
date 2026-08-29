# Reconstructing per correspondence set

> Design document. Nothing here is implemented. Written 2026-08-21 against
> commit `ce52d87`, suite at **320 passing**
> (`pytest -q -k "not local_run_artifacts"`).
>
> Every number below was measured in this checkout. Where a figure is quoted
> from an existing document rather than re-measured, it says so.
>
> **All four research-owner decisions in §11 have been taken.** The governing
> one is §11.1, and it is a statement about the division of labour rather than
> about accuracy: *reading a correspondence set and naming the proto-phoneme
> behind it is the linguist's work, and it is the work this harness exists to
> have a model do.* Several smaller choices in §6 follow from it and say so —
> the residue policy that counts daughters is removed, column ties are shown to
> the model instead of being resolved by a sort key, and the out-group tie-break
> is measured rather than merged.

The proposal: stop committing per-branch rewrite rules, and commit instead a
mapping from **correspondence sets to proto-phonemes**. Derive the per-branch
rules from it. Assemble proto-forms segment by segment out of the reconstructed
phonemes rather than selecting one whole string from one branch's output.

The first section is the re-derivation `prompts/06-proto-inventory.md` asks for
before anything else, because it changes the argument the rest of the document
has to make.

---

## 0. The re-derivation, and what it did to the case

### 0.1 What was asked

`tools/oracle_ceiling.py` builds each branch's map with `oracle_map()`, which
assigns **one target per source segment, globally**. It is context-free. The DSL
is not. So every "the architecture cannot reach this form" conclusion drawn from
the oracle is a statement about the oracle, and the prompt asks for the ceiling
to be re-derived with a rule writer as strong as the rule language before the
accuracy argument is quoted again.

### 0.2 What was built

A context-sensitive oracle. Per branch, per aligned column against the withheld
gold, it records the source segment, the gold target, and the child-side
neighbours; then per source segment it searches a bounded environment space —
word-initial, word-final, single-token left, single-token right, and the four
two-part combinations the DSL can spell — for environments that **purely**
separate one target from another. It emits conditioned rules before the
unconditioned default, orders sources by the same feeding argument
`order_rules()` already uses, applies the cascade with the real `RuleEngine`,
and **falls back to the context-free cascade for any branch it would make
worse**. It is therefore ≥ the context-free oracle per branch by construction.

It is a *second* measure. It does not redefine `oracle_map()`, because every
recorded baseline in `docs/analysis_tools.md` was measured with the context-free
one and silently redefining it would make the before/after uncomparable — the
failure `tools/_bootstrap.py` exists to prevent at one remove.

The measurement scripts for this session live in the session scratchpad —
`contextual_oracle.py`, `assembly_ceiling.py`, `node_mixing.py`,
`miss_detail.py`. They are deliberately **not** committed, because this session
is a design review and landing analysis code is stage 0 of the plan rather than
part of the review. Stage 0 lands the first as
`tools/oracle_ceiling.py --oracle contextual` and the second as
`tools/assembly_ceiling.py`.

### 0.3 The result: the cap moved, substantially

> **These are the figures as this session measured them, before the four defects
> §0.5 goes on to name were repaired.** They are kept because §0.5's argument is
> about them. The current values are in `docs/benchmarks.md` and in §7: the
> context-sensitive oracle is 33/46 top-1, 40/46 beam-exact and 0.097 mean top
> NED, and the context-free one is 27/46, 40/46 and 0.147.

Polynesian, 46 concepts, beam width 5,
`measuring: /Users/acraev/Work/cognate-reconstruction/cognate_reconstruction`.
The context-free column reproduces the pinned regression numbers exactly, which
is how the new measure is known to be running the same reconstructor.

| Measure | context-free oracle (pinned) | **context-sensitive oracle** |
| --- | --- | --- |
| top-1 exact | 27/46 — 58.7% | **32/46 — 69.6%** |
| beam exact | 39/46 — 84.8% | **41/46 — 89.1%** |
| exact selection gap | 12 concepts, 26.1 pts | **9 concepts, 19.6 pts** |
| mean top NED | 0.158 | **0.110** |
| mean beam-best NED | 0.043 | **0.020** |
| NED selection gap | 0.115 | **0.090** |
| mean top B-Cubed F1 | 0.960 | **0.965** |

The whole width curve moves, and moves in the shape a genuine capability gain
has — top-1 up at every width, beam-exact down at none:

| beam width | top-1 cf | top-1 ctx | beam-exact cf | beam-exact ctx |
| --- | --- | --- | --- | --- |
| 1 | 22 | **24** | 22 | **24** |
| 3 | 26 | **32** | 36 | **38** |
| 5 | 27 | **32** | 39 | **41** |
| 10 | 26 | **32** | 39 | **41** |

**So the answer to the addendum's question is: the cap moved, and by a lot.**
Five concepts of top-1 and two of beam-exact were being attributed to the
architecture when they belonged to the oracle. `1209`, `1221`, `1500`, `646` and
`937` are reachable under a context-sensitive cascade and were not under a
context-free one; nothing regressed.

Per the addendum's own instruction, this means **the accuracy argument for this
change is thinner than `prompts/06-proto-inventory.md` states, and the case
rests substantially on correctness and auditability.** Section 1.3 says how much
accuracy is genuinely left on the table, and it is not zero — but it is not 24%
either.

**One honest caveat on the new oracle.** It writes **282 rules across 16
branches** where the context-free one writes 52 — roughly eighteen rules per
branch, many of them conditioned on a single word. That is a perfect rule
writer, not a plausible analysis, which is exactly what an oracle is for: it
bounds the architecture and is not a target. Quoting 32/46 as "what a good model
should get" would be the same category error as quoting 27/46 as a structural
limit.

### 0.4 The perfect-selector cap, re-derived

`prompts/06-proto-inventory.md` states that "even a perfect selector over the
branch outputs caps at 35/46 (76.1%)". That figure could not be reproduced here
and its measurement procedure is not recorded anywhere in the repository, so it
should stop being quoted. The nearest well-defined thing — **for each concept,
does any single daughter, transformed by its own oracle cascade against the root
gold, reach the gold form?** — measures:

| | context-free | context-sensitive |
| --- | --- | --- |
| reachable from some single daughter | 38/46 — 82.6% | **40/46 — 87.0%** |
| needs evidence mixed across branches | 7 | **5** |
| reachable from no daughter | 1 | 1 |

`tools/branch_recoverability.py` reports **37 / 8 / 1** for the same split. The
difference is method, not disagreement: that script applies a segment *map* by
dictionary lookup, while this applies the real ordered *cascade* through
`RuleEngine`, and the cascade reaches `1028` where the map does not. Both are
legitimate; they should be reported together and neither should be quoted alone.

The concrete falsification list therefore shrinks. Under a context-sensitive
oracle the concepts that no single branch can reach are

```
1212  1217  1408  1439  1443
```

with `778` reachable from none — not the eight
`1028, 1212, 1217, 1221, 1408, 1439, 1443, 646` the prompt names. `1028`,
`1221` and `646` are reachable from a single branch once the rule writer is as
strong as the rule language.

### 0.5 Four measurement defects found while re-deriving

All four are in `tools/oracle_ceiling.py`, and they matter to this design
because the oracle is the falsification instrument. None of them changes the
Polynesian top-1 figure the suite pins; one changes its beam-exact; the last one
does not change the tree-level number at all, and that turns out to be the most
informative fact in this document.

**`bindings[0]` is not the root's gold on a multi-gold family.** `measure()`
takes the first `target` binding and evaluates the **root** beam against it. On
`synthetic_hard` the first binding is `east`, not `proto`. The tool prints
`root node: proto` and `22/25`, and `docs/benchmarks.md` quotes that as the
family's oracle score. Against the root's *own* gold the same oracle scores:

| synthetic_hard, gold at `proto` | context-free | context-sensitive |
| --- | --- | --- |
| top-1 exact | **15/25 — 60.0%** | **16/25 — 64.0%** |
| beam exact | 25/25 — 100% | 25/25 — 100% |
| mean top NED | 0.098 | 0.088 |

The published 22/25 is "with rules fitted to reach `east`'s forms, the root beam
reports `east`'s forms 22 times out of 25". That is a coherent measurement with
the wrong label. Stage 0 fixes it: default to the root's binding where one
exists, require `--gold-node` otherwise, and re-record `docs/benchmarks.md`.

**The oracle has no way to say which node it scored.** `--gold-node` and a
`gold_node_id` field in `--json` are part of the same fix. `measuring:` already
prevents quoting a number from the wrong checkout; nothing prevents quoting one
from the wrong node.

**A concept with several gold alternatives silently keeps one.** `measure()`
builds `gold = {form.concept_id: form.segments for form in binding.forms}`, so a
concept whose binding carries alternatives keeps whichever is written last. On
Polynesian two concepts do — `1920` with two, and `1443` WALK with **four**
(`r oː`, `ʔ a l u`, `s a ʔ e l e`, `f a n o`) — and the dict keeps `f a n o`.
That contradicts the harness's own contract: `HistoricalTargetEvaluation` carries
`target_segment_alternatives` and scores through `compare_to_nearest`, so the
real evaluation honours all of them and the oracle does not.

Measured impact, evaluating against every alternative while leaving rule
construction unchanged: context-free beam-exact **39 → 40**, everything else
unmoved; context-sensitive unmoved entirely. Small, and worth fixing anyway,
because the defect is silent and grows with any benchmark whose gold carries
variants. Stage 0 fixes it and re-pins beam-exact at 40.

It also undercuts a claim the prompt makes in passing. `1443` is described there
as "lexical replacement, which no phonological method recovers" — but `ʔ a l u`
is one of its four gold alternatives and is exactly Tongan's form, and
EastFutuna retains `a n o`, the cognate of `f a n o` minus its initial. The
concept is hard for a different reason (§1.2), not unrecoverable in principle.

#### `order_rules()` orders the cascade backwards, against its own docstring

The docstring is right and the code does the opposite. It says "a rule whose
target is another rule's replacement must therefore run first"; the
implementation emits a source when nothing remaining maps *into* it, which is
the other direction. On its own worked example:

```
order_rules({"k": "t", "t": "s"})  ->  [("k", "t"), ("t", "s")]
                     the docstring says  [("t", "s"), ("k", "t")]
```

It fires on the real benchmark, on exactly the case §2.2 is about. Hawaiian
merges nothing but chain-shifts twice — `*t > k` and `*k > ʔ` — so its oracle map
is `{ʔ: k, k: t, …}` and the emitted order is `ʔ > k` before `k > t`:

```
Hawaiian  ʔ a k a   --[ʔ > k]-->  k a k a  --[k > t]-->  t a t a     reported
Hawaiian  ʔ a k a   --[k > t]-->  ʔ a t a  --[ʔ > k]-->  k a t a     gold
```

Per branch, with the order corrected, exact matches against the root gold:

| branch | current | ordering fixed |
| --- | --- | --- |
| **Hawaiian** | **15/46** | **22/46** |
| every other daughter | unchanged | unchanged |
| total over ten daughters | 214 | **221** |

Only Hawaiian moves, because only Hawaiian has a chain shift. And now the part
that matters:

> **The tree-level ceiling does not move at all: 27/46 top-1, 39/46 beam-exact,
> mean top NED 0.158, all identical.**

A branch that produces seven more correct forms changes nothing about what the
root reports. That is the single most direct piece of evidence in this document
for the claim §1.3 makes: under the current architecture the accuracy is not
lost in the rules, it is lost in the step that picks one whole string. It is
also the reason the pinned figure survives all four defects unchanged, which is
reassuring about the pin and alarming about the instrument.

Stage 0 fixes the ordering, re-records the per-branch figures, and — since the
tree-level numbers do not move — leaves the pinned assertions alone except for
beam-exact.

---

## 1. What the measurements actually say

### 1.1 The three claims in the prompt, checked

**"A proto-form can only ever be one daughter's output."** True, and it is the
real structural fact. But the accuracy it costs is 6 concepts on Polynesian
(40/46 reachable from a single daughter under a context-sensitive oracle), not
11.

**"The DSL cannot insert."** True and unchanged. `branch_recoverability.py`
re-run 2026-08-21 still reports 7/46 (Tongan) to 17/46 (North Marquesan) gold
forms out of reach per branch for exactly this reason. The live `tongic`
failure in `runs/google-gemma-4-26b-a4b-20260817-180220` — `Ø > ʔ / #_`,
`∅ > ʔ / #_`, `Ø > ʔ` rejected `dsl-parse-error` three times, then identity —
is the cleanest single piece of evidence this prompt has, and it survives the
re-derivation untouched. No context-sensitive rule reaches an insertion.

**"Rules at one node cannot be checked against each other."** True, unchanged,
and not measurable as accuracy at all. `f > p / _eː` scoped to Tongan alongside
`p > f / _e` scoped to Niuean, both validated, both at confidence 1.0, is a
representational defect whether or not it costs a concept.

### 1.2 The ceiling of the proposed architecture

> **The figures in §§1.2–1.3 are pre-stage-0 and are kept as the argument that
> made the case, not as current measurements.** Prompt 07 repaired four defects
> in `tools/oracle_ceiling.py` and landed `tools/assembly_ceiling.py`, and §12.5
> then made the harness's own aligner see morphological boundaries. Node-local
> assembly is **44/46**, not 39/46; flat is 43/46, not 42/46; the
> context-sensitive branch-cascade oracle is 33/46 top-1 and 40/46 beam-exact.
> §7 carries the current numbers with the commands that produce them, and
> `docs/benchmarks.md` is the authority for the oracle rows.

A proto-form assembled per correspondence set is a **column-wise choice over the
aligned daughters**: for each column of the multiple alignment, one
proto-phoneme, or nothing. So "is gold reachable by assembly?" is decidable
exactly — it is a subsequence problem over the columns, not a search.

Measured on Polynesian, where a column may contribute **only a segment some
daughter actually shows there**:

| assembly variant | reachable |
| --- | --- |
| flat — align all ten daughters at the root, assemble once | **42/46 — 91.3%** |
| node-local — assemble at each internal node from its children, bottom-up | **39/46 — 84.8%** |
| free choice — any proto-phoneme, not only an attested reflex | 46/46 |

The free-choice row is in the table to be dismissed: the alignment always has
enough columns, so the bound is vacuous and says nothing. The informative bound
is the reflex-restricted one, and it is a **lower** bound, because a
proto-phoneme genuinely need not be one of its reflexes — see 1.4.

**The node-local row is the honest number for this design**, because assembly
will happen at each node over that node's active children, exactly as rules do
now. 39/46 with a single candidate per node; a beam of alternatives can only
raise it.

The four concepts flat assembly cannot reach are `1028`, `1217`, `1443` and
`778`, and they are worth naming because three of them are *not* what one
expects:

- `1028` YAWN, gold `m a w a + w a` — **no daughter shows `w` anywhere**.
  EastFutuna and Samoan show `v`, the rest a gap. The proto-phoneme is not among
  its reflexes.
- `778` SMOKE, gold `ʔ a h u + a f i` — the same: `f` appears in no daughter
  (Samoan `s`, the rest `h` or `ʔ`).
- `1217` FATHER, gold `t a m a + n a` — the daughters carry two different
  lexemes (`m a t u a` against `t a m a`) and SCA aligns them into
  non-overlapping columns. An alignment/cognacy failure, not an assembly one.
- `1443` WALK, gold `f a n o` — most daughters replaced the etymon with a
  `haele`-type form; EastFutuna retains `a n o` but has lost the initial, so no
  daughter shows `f` in that column. Partly lexical replacement, partly a
  proto-phoneme absent from every reflex.

### 1.3 What per-set assembly is worth, and what kind of gain it is

Putting the two ceilings side by side, on the same benchmark, at the same beam
width, against the same gold:

| | branch cascades, context-free oracle | branch cascades, context-sensitive oracle | **per-set assembly, node-local** |
| --- | --- | --- | --- |
| top-1 exact | 27/46 | 32/46 | **39/46** |
| the answer exists somewhere | 39/46 (beam) | 41/46 (beam) | 42/46 (flat assembly) |

**Read that carefully, because it is the finding that should decide this
review.** Per-set assembly raises the *top-1* ceiling by seven concepts over the
strongest branch-cascade oracle, and raises *reachability* by one. It is
overwhelmingly a **selection** fix wearing a generation change's clothes: the
answer stops having to be chosen out of a beam because it is constructed.

§0.5's fourth defect is the independent confirmation. Correcting the oracle's
rule ordering takes Hawaiian from 15/46 to 22/46 correct forms and moves the
root's ceiling by **zero**. Seven correct forms entered the tree and none of
them reached the top of the root beam. Whatever is throwing away accuracy in
this harness, it is not the rules.

That has three consequences the rest of this document has to live with.

1. It is still a large gain. Seven concepts is 15.2 points of top-1 at the
   ceiling, and the graded selection gap — 0.090 NED under the context-sensitive
   oracle — is recovered by construction rather than by a better sort key.
2. **The falsification condition the prompt states is mis-specified.** "If it
   moves only the top-1 count while beam-best NED is unchanged, the improvement
   came from selection and the argument has not been demonstrated" — under
   assembly, top-1 and beam-best converge *by construction*, because there is no
   longer a whole-string selection step to lose the answer in. Applying that
   condition literally would reject a change that did exactly what it promised.
   Section 7 replaces it.
3. The honest headline is therefore **not** "this breaks the 76% ceiling". It is
   "this removes the step in which 9 of 46 correct answers are computed and then
   discarded, and makes three defects unrepresentable that are currently
   representable".

### 1.4 What per-set assembly does *not* fix

**It does not recover a segment every active child has lost.** This is the most
important correction to the prompt's framing and it is directly measurable on
`synthetic_hard`, where every node's truth is in the answer key:

| node | children | single-child reachable | not reachable |
| --- | --- | --- | --- |
| `west` | d1, d2 | 25/25 | — |
| `east_a` | d3, d4 | 25/25 | — |
| **`east`** | east_a, d5 | 22/25 | **`leaf`, `tooth`, `tree`** |
| `proto` | west, east | 25/25 | — |

At `east` both children lost `*ʔ`, so the correspondence set is `⟨Ø : Ø⟩` and
reconstructs nothing. Per-set assembly over the active children is exactly as
stuck there as a cascade is. The segment survives the run only because `west`
retains it through `d1` and the root can still see it — which is the current
architecture's beam doing the work, not the new mechanism.

**§6.9 lifts this limit**, and it is worth reading as the direct answer to this
paragraph: a node may restore a segment every active child lost, by citing an
out-group that still attests it, with the citation verified mechanically. On
`east` that is exactly `d1`, and it is worth the three concepts this paragraph
gives up.

The distinction `benchmarks/synthetic/synthetic_hard.json` was built to preserve
— **hard, not unreachable** — therefore cuts against the prompt's reading of it.
`synthetic_hard` is *not* a controlled testbed for cross-branch assembly:
measured over the whole family, **0 of 100 node-concepts need evidence mixed
across the sisters**. It is a testbed for the *selection* half of this change,
which is the half the measurements say is load-bearing anyway.

**It does not make the proto-phoneme derivable from the reflexes.** `1028` and
`778` above reconstruct segments no daughter shows. The committed object must
therefore let the model name **any** proto-phoneme for a set, and the harness
must not restrict it to the observed column values. That is a schema decision
falling straight out of the data (§4).

**It does not fix alignment.** `1217` is unreachable by assembly because SCA put
the material in the wrong columns. Under the current architecture a bad
alignment costs the model an evidence view; under assembly it costs the model
the answer. §6.1.

---

## 2. What is actually broken

Restating the prompt's four defects with the measurements attached, since two of
them changed size and one changed character, plus two the prompt does not name.

| Defect | Still real? | Measured cost | Fixed by this change? |
| --- | --- | --- | --- |
| A proto-form is one daughter's whole string | yes | 6/46 unreachable; **9/46 computed and discarded** | the second, fully; the first, partly |
| No empty-target insertion | yes | 7–17 of 46 per branch; one live node killed | yes, where some active child retains the segment |
| Two rules at one node cannot contradict each other | yes | not an accuracy | yes, by construction |
| No proto-phoneme inventory exists anywhere | yes | not an accuracy | yes, that is the object |
| **A merged reflex cannot be split by any branch-scoped cascade** (§2.1) | yes | North Marquesan, 18/46 under a perfect context-sensitive rule writer | yes — the sets *are* the split |
| **Rule order carries the reconstruction, unstated** (§2.2) | yes | not an accuracy | yes — sets are independent |

The second row's qualifier is the one to keep in view: **insertion becomes
unnecessary rather than possible.** A set `⟨Tongan ʔ : Niuean Ø⟩` reconstructs
`*ʔ` because the parent segment comes from the set, not from any child's string.
A set `⟨Ø : Ø⟩` still reconstructs nothing, and no representation of the active
children's evidence can change that.

The last two rows are the ones that make this a **correctness** change rather
than an accuracy one, which — per §0.3 — is where the case now has to rest.

### 2.1 A merger makes a branch cascade strictly less expressive, on real data

This is not in the prompt and it is the strongest correctness argument
available, because it is a case the current representation cannot express at
all rather than one it expresses awkwardly. Three rows of the real Polynesian
inventory, column order `EFut EUve Haw Mri Niu NMq Rar Sam Tah Ton`:

```
n   EFut EUve  Haw  Mri  Niu  NMq  Rar  Sam  Tah  Ton
8      l    l    l    r    l    ʔ    r    l    r    l      *l
4      k    k    ʔ    k    k    ʔ    k    ʔ    ʔ    k      *k
3      ʔ    ʔ    Ø    Ø    Ø    Ø    Ø    Ø    Ø    ʔ      *ʔ
```

**North Marquesan shows `ʔ` in two of them.** Its `ʔ` reflects `*l` in one set
of words and `*k` in another; only what the sisters show distinguishes them.
Written as a branch-scoped cascade, North Marquesan needs

```
ʔ > l          and          ʔ > k
```

— same target, same empty environment, two different replacements, scoped to the
same child. The parser accepts both, the engine applies whichever comes first to
every `ʔ` in the language, and the second is dead. There is no conditioning
environment that separates them, because the conditioning is not in North
Marquesan at all: it is in Hawaiian and Maori. A cascade scoped to one child can
only look at that child.

**Measured, not argued.** The context-sensitive oracle of §0.2 is free to search
every environment the DSL can spell, and for North Marquesan it writes
`ʔ > n / e_e` and then `ʔ > l` — it takes `*l` as the default and never recovers
`*k` from `ʔ` at all. Its branch score is 18/46 against Tongan's 29/46. A
perfect rule writer with the full rule language cannot split that merger,
because the information needed to split it is not in North Marquesan.

The same commitment as two correspondence sets is unambiguous and needs no
order, no environment, and no argument: `⟨…NMq ʔ…⟩` with nine other columns is
one set, `⟨…NMq ʔ…⟩` with nine *different* other columns is another, and each
carries one value.

This is the merger case `synthetic_hard` builds deliberately on `d1` — "*b and
*p both surface as p here, and no rule scoped to d1 can undo it. Only d2, which
keeps them apart, can disambiguate" — and it is present in the real benchmark,
unremarked, in the two most frequent *consonant* correspondence sets it has
after `*t`.

### 2.2 Rule ordering stops being load-bearing

Concept `1355` LAUGH, gold `k a t a`:

```
EastFutuna  k a t a      Maori       k a t a      Tahitian    ʔ a t a
EastUvea    k a t a      Niuean      k a t a      Tongan      k a t a
Hawaiian    ʔ a k a      NorthMarq   ʔ a t a
Rarotongan  k a t a      Samoan      ʔ a t a
```

Hawaiian needs `k > t` (from the `*t` set, support 9) **and** `ʔ > k` (from the
`*k` set, support 4). Committed as a cascade, `ʔ > k` first turns `ʔ a k a` into
`k a k a` and then `k > t` into `t a t a`. The order is the whole reconstruction
and nothing in the commit contract makes the model state why it is that order.
Committed as two correspondence sets, there is no order at all: column 1 is the
`*k` set and column 3 is the `*t` set, and they are independent. `synthetic_hard`
has this by construction on the `east` branch and the answer key's own note says
the reverse order "turns t a s i into k a k i".

**This is not a hypothetical hazard, and the evidence is embarrassing.** The one
piece of code in this repository that writes a cascade automatically — the
oracle whose numbers the suite pins — gets this exact ordering wrong, on this
exact branch, and has done since it was written (§0.5). A representation whose
ordering trap catches its own tooling is a representation worth removing.

---

## 3. The shape of the change

At each internal node the model commits a **proto-inventory**: an explicit set
of correspondence sets over that node's active children, each assigned a
reconstructed proto-phoneme, with support, conditioning, confidence and
rationale. It is carried as a tuple for serialization determinism, and its order
carries no meaning — sets are independent, which is the whole of §2.2.

Deterministic code then:

1. **Assembles** each parent form column-wise. For each concept, the children's
   forms are aligned; each column is matched against the committed sets; the
   matched set's proto-phoneme is emitted (or nothing, if the set reconstructs
   nothing); columns matching no set are resolved by the commit's stated
   residue policy and counted.
2. **Derives** a per-branch reflex cascade as a *view*: for each child and each
   committed set where that child's reflex differs from the proto-phoneme, a
   rule `reflex > proto` with the set's conditioning environment. Derived rules
   are reported, recorded, and consumed by `score-synthetic` and `inspect-run`.
   They are never the mechanism, which is why insertion never needs to exist.
3. **Reports the inventory** as a first-class object: the set of proto-phonemes
   at this node, their support, and which children attest which reflex.

The contradiction case becomes unrepresentable because one set has one
proto-phoneme: `f > p / _eː` on Tongan and `p > f / _e` on Niuean are two claims
about one correspondence, and a correspondence carries exactly one value.

---

## 4. Schemas

New module `cognate_reconstruction/schemas/inventory.py`. All models are
`WorkbenchModel` (`extra='forbid'`), as everything else in `schemas/`.

### 4.1 The committed unit

```python
class CorrespondenceCommitment(WorkbenchModel):
    set_id: NonEmptyStr
    """Deterministic ID of the correspondence set this commits a value for.

    Produced by `summarize_correspondences` and by `test_proto_assembly`, and
    derived from content alone, so it is stable within a session and
    reproducible outside one. The harness re-derives the set from the node's own
    forms and rejects a commitment whose cited set it cannot reproduce.

        GAP = "\x1e"        # cannot be a segment, so None never collides with "Ø"
        SEP = "\x1d"

        def derive_set_id(
            reflexes: Sequence[str | None],
            child_node_ids: Sequence[str],
            *,
            segmentation_overlay_id: str | None,
            alignment_overlay_id: str | None,
        ) -> str:
            material = "\0".join(
                [
                    *(GAP if r is None else r for r in reflexes),
                    SEP, *child_node_ids,
                    SEP, segmentation_overlay_id or "",
                    alignment_overlay_id or "",
                ]
            )
            return "cs-" + hashlib.sha256(material.encode()).hexdigest()[:12]

    **Both overlays are in the digest**, and that is the resolution of an
    inconsistency in an earlier draft, which named only the segmentation one. An
    alignment overlay changes which columns exist, so it changes what a set *is*.

    The consequence has to be stated where a model will read it: **a `realign`
    call invalidates every set ID derived under the previous overlay.** A commit
    must cite IDs derived under the overlays it names. That is exactly the
    discipline `segment_morphemes` already imposes — "use the returned overlay ID
    consistently in later alignment and rule tests" — and the same rejection
    (`unknown-correspondence-set`) catches a stale one.
    """

    reflexes: tuple[str | None, ...] = Field(min_length=2)
    """Positional against the inventory's `child_node_ids`; None is a gap.

    The same shape as `alignment.CorrespondenceSet.segments`. Required even
    though `set_id` determines it: a commit a human cannot read without
    re-running a tool is not an audit record.
    """

    proto_segment: NonEmptyStr | None
    """The reconstructed proto-phoneme, or None for "this set reconstructs
    nothing" — every branch showing material here innovated it.

    Deliberately NOT restricted to the segments in `reflexes`. Proto-Polynesian
    *w in concept 1028 is attested as `v` or as nothing in every daughter, and
    *f in 778 as `s` or `h`; a schema that could only emit an observed reflex
    would make those two unreconstructable by construction.
    """

    conditioning: RuleEnvironment | None = None
    """The environment in which this commitment holds.

    Reuses `schemas.rules.RuleEnvironment` unchanged — left, right,
    word_initial, word_final — so a conditioned split is expressed in exactly
    the vocabulary the DSL already has and the derived rules render back into it
    without a second notation.
    """

    merges_with_set_id: NonEmptyStr | None = None
    """This set and that one are one phoneme in complementary distribution.

    Asserted by the model, checked mechanically by the harness (§6.2). Both
    commitments must name the same `proto_segment` and both must carry a
    `conditioning`.
    """

    support: int = Field(ge=1)
    """Aligned columns showing this set, copied from the harness's own
    inventory. Re-derived and rejected on mismatch: it is the one number that
    separates a correspondence from residue and it must not be a model claim."""

    confidence: float = Field(gt=0.0, le=1.0)

    rationale: NonEmptyStr | None = None
    """Required when the inventory carries more than one commitment, exactly as
    per-rule `rationale` is today."""

    directionality_rationale: NonEmptyStr | None = None
    """Which branch innovated. Required on any commitment that discards material
    — see §6.6 for what "discards" means for a set rather than a rule. Rejected
    on absence, never on content, unchanged in kind from today."""
```

### 4.2 The commit

```python
class ResiduePolicy(StrEnum):
    RETAIN_FROM_WITNESS = "retain_from_witness"
    """An unmatched column contributes whatever `residue_witness_child_id`
    shows in it, recorded as unexplained rather than as reconstructed.

    **An unaccounted column carries through; it does not vanish.** That is the
    load-bearing semantics and §4.5 gives the reasoning: it makes assembly
    monotonic, so committing more sets refines a reconstruction and committing
    none leaves it where the children are.
    """
    DROP = "drop"
    """An unmatched column contributes nothing to the parent: the material is
    treated as branch-specific innovation.

    The opt-in, not the default reading. A model choosing this is asserting that
    everything its inventory does not explain is innovation — which is a strong
    claim and usually a wrong one on a partial inventory.

    A `majority_reflex` option was drafted here and removed. See section 6.3:
    counting daughters votes for shared innovations, which this repository has
    already measured, and a majority vote in the residue path would reintroduce
    the exact error `polarize` exists to prevent.
    """


class ResidueDisposition(WorkbenchModel):
    """One named exception to the policy, for a column the model has looked at."""
    concept_id: NonEmptyStr
    column_index: int = Field(ge=0)
    proto_segment: NonEmptyStr | None
    explanation: NonEmptyStr


class CommitProtoInventoryArgs(WorkbenchModel):
    node_id: NonEmptyStr
    child_node_ids: tuple[NonEmptyStr, ...] = Field(min_length=2)
    """Column order for every commitment. Must be exactly the active children."""

    segmentation_overlay_id: NonEmptyStr | None = None
    assembly_validation_call_id: NonEmptyStr | None = None
    """A successful test_proto_assembly call covering this inventory. Optional
    only in the sense that the harness resolves it when omitted; the
    same-session preview itself is not optional (§6.6)."""

    commitments: tuple[CorrespondenceCommitment, ...]
    """The node's correspondence-set commitments.

    **Order carries no meaning.** It is a tuple for serialization determinism
    and nothing reads the sequence: sets are independent, which is the whole of
    §2.2. A validator rejects duplicate `set_id`s.

    **May be empty, and an empty inventory is an identity reconstruction** —
    the same claim `rules: []` makes today, with the same deterministic result.
    §4.5 specifies exactly what the assembler does with it, because the naive
    reading (every column unaccounted, every form empty) is a crash rather than
    an identity.
    """

    residue_policy: ResiduePolicy
    """Required, with no default. What happens to a column no committed set
    explains. A model that can silently drop unexplained material is worse than
    one that cannot; a stated policy is the cheapest thing that prevents it."""

    residue_witness_child_id: NonEmptyStr | None = None
    """Required by `RETAIN_FROM_WITNESS`, refused otherwise: the child whose
    material is carried through where nothing explains it.

    Naming one is a linguistic claim — *this branch is the most conservative* —
    made once, recorded, and readable by a reviewer. That is the point: it is a
    judgement the model makes rather than a count the harness takes."""

    residue_dispositions: tuple[ResidueDisposition, ...] = ()
    restorations: tuple[SegmentRestoration, ...] = ()
    """Segments every active child lost, restored on cited out-group evidence.
    Per position rather than per set, and verified; see §6.9."""

    anomalies: tuple[AnomalyReport, ...]
    summary: NonEmptyStr
```

`CommittedProtoInventory` mirrors `CommittedReconstruction`:

```python
class CommittedProtoInventory(WorkbenchModel):
    request: CommitProtoInventoryArgs
    proto_phonemes: tuple[NonEmptyStr, ...]
    """The node's inventory, derived: sorted distinct non-None proto_segments.
    The first-class object the prompt asks for, and what `inspect-run` prints."""
    derived_rules: tuple[ReconstructionRule, ...]
    """The per-branch reflex cascade, derived and verified (§4.3). A view, never
    a mechanism."""
    non_invertible_child_ids: tuple[NonEmptyStr, ...] = ()
    """Children for which the derived cascade cannot be written, because some
    committed set assigns them a gap against a non-null proto_segment. Exactly
    the `invertible: false` convention `schemas/synthetic.py` already uses, so
    `score-synthetic` compares like with like across the migration."""
```

### 4.3 Derivation and verification

For each child `c` and each commitment with `proto_segment = p` and reflex
`r_c`:

- `r_c is None and p is not None` → **no rule**; `c` joins
  `non_invertible_child_ids`. This is the insertion the DSL cannot write, and it
  is now a recorded fact rather than a rejected call.
- `r_c is not None and p is None` → `r_c > Ø` with the set's conditioning.
- `r_c != p`, both present → `r_c > p` with the set's conditioning.
- `r_c == p` → no rule.

Two rules for one child with the same target and the same environment cannot
arise, because a target/environment pair belongs to one set and a set has one
value. That is the contradiction case becoming unrepresentable, stated as an
invariant a test can assert directly.

The derived cascade is **verified, not trusted**, and the definition has to be
stated non-circularly, because the obvious phrasing assumes what it measures.

> A concept is **cross-branch assembled** when *no* single child's derived
> cascade, applied to that child's own form, reproduces the assembled parent
> form.

`cross_branch_assembly_rate` is the share of a node's concepts for which that
holds. It is decidable in one pass over the children — apply each child's
derived cascade, compare — with no prior knowledge of which concepts mixed. It
is the number that says whether the new capability did anything at all (§7), and
its converse doubles as the verification: on every concept where *some* child
reproduces the assembled form, that child's derived rules are confirmed against
the assembler rather than assumed to agree with it.

### 4.4 Assembly, precisely

This is the specification an implementer works from. Everything here was
underspecified in an earlier draft, and the first item was a defect rather than
an omission.

#### The empty inventory, and why the fix is not where the bug looks

The naive reading of assembly — walk the columns, emit the matched set's value,
resolve the rest by `residue_policy` — turns an empty inventory plus `drop` into
an empty form for every concept, which `normalize_and_prune` refuses outright
(`ValueError: no viable candidates`). That breaks two shipped things: a
legitimate conservative identity commit, and `agent/reconstructor.py`'s
`_fallback_step`, which walks a failed node over by calling `reconstruct()` with
no rules at all.

**The bug is not really about the empty case.** A node committing *one* set
suffers identically: one column reconstructed, every other column dropped,
proto-form `ʔ`. So the fix is at the residue level:

> **An unaccounted column carries through. It does not vanish.**

That makes assembly **monotonic**: committing more sets refines the
reconstruction, committing none leaves it where the children are, and there is
no cliff between the two. `drop` remains available for a column the model
positively believes is innovation, and is now what it should always have been —
an assertion, not a default.

On top of that, one deliberate short-circuit:

> **When `commitments`, `residue_dispositions` and `restorations` are all
> empty, the assembler is not invoked.** The parent beam is the children's
> candidates combined, exactly as today, and `identity_reconstruction` is
> `True`.

That is not an ugly special case. *Asserting nothing* is a categorically
different act from *asserting something*, and the alternative was measured and
is worse: letting each uncommitted column branch into one candidate per distinct
reflex manufactures recombinations **no child ever attested** — hundreds of them
on a six-column form — where today's identity only ever emits forms some child
actually produced. `_fallback_step` therefore keeps its current behaviour
bit-for-bit and needs no special-casing of its own.

The guard against a model dropping most of its columns is the one already in the
design: `test_proto_assembly` shows it the assembled forms, so it *sees* `ʔ` as
its proto-form. Show, don't gate.

#### Matching a column to a set

1. Build the node's inventory under the committed segmentation and alignment
   overlays. Each alignment column yields a reflex tuple positional against
   `child_node_ids`.
2. **A child with no form for the concept and a child with a gap in the column
   are both `None`.** This is what `build_correspondence_sets` already does
   (`rows[node][column] if node in rows else None`) and it is right on the
   evidence: neither attests anything, and the presence-is-evidence asymmetry
   the whole repository runs on says absence is not a claim.
3. Then, per column:
   - **no commitment matches** → residue, resolved by `residue_policy` or by a
     `ResidueDisposition` naming that concept and column;
   - **exactly one matches** → its `proto_segment` (which may be `None`, meaning
     the column reconstructs nothing);
   - **more than one matches** → they differ only by `conditioning`, which is
     the conditioned split of §6.2, resolved below.

Restorations (§6.9) are applied after column resolution, inserting their
`proto_segment` before the named column index. Indices are into the alignment
under the committed overlays and are unaffected by other restorations, so the
insertion order is deterministic and independent of how many are committed.

#### Conditioning is evaluated in proto terms, in two passes

A conditioned split is conditioned by the **proto**-environment — the
neighbouring proto-phonemes — not by any one child's segments. So:

- **Pass 1** assigns every unambiguously matched column its value.
- **Pass 2** resolves conditioned columns against pass-1 neighbours. `#` is the
  column being first or last among the non-empty assembled positions.
- A conditioned column whose deciding neighbour is *itself* still ambiguous
  after pass 1 stays unresolved, falls to residue, and is reported. Two passes
  terminate; there is no fixpoint to chase and no cycle to detect.

**This diverges from the DSL's current semantics and the divergence has to be
handled, not elided.** A `ParsedSoundRule` environment matches against the
*child's* form. A commitment's `conditioning` is in proto terms. So when §4.3
derives a rule for child `c`, the environment it renders is the neighbouring
columns' **reflexes in `c`** — not their proto values:

- the derived rule stays applicable to `c`'s own forms, which is what makes the
  verification in §4.3 meaningful;
- it stays structurally comparable to a synthetic answer key, whose
  `inverse_rules` are verified by applying them to child forms (§9.2);
- and one commitment can therefore derive **differently spelled environments for
  different children**, which is correct rather than a wart.

In `synthetic_hard`'s `d4` (`a > e / _ i`) the proto and child spellings
coincide, which is why the distinction does not surface there and would have
been easy to miss.

Edge case, stated so nobody invents behaviour: if a deciding neighbour column is
a **gap** in child `c`, the derived rule for `c` falls back to its unconditioned
form and `c` is flagged in the assembly report. It does not reach past the gap
for the next segment, because that would be a non-local environment the DSL
cannot express.

#### Anchors

Unchanged in kind, relocated. Today `_transform` computes anchor matches per
transformed candidate and `AnchorPolicy.SCORED` adds `log(anchor_match_factor)`
per unique match before pruning. Under assembly the same thing happens one step
later: after a candidate tuple is assembled into a form, it is compared to the
concept's anchors, and a unique exact match takes the boost before
`normalize_and_prune`. `ApplicationStatus.ANCHOR_MISMATCH` disappears with the
rule reports; anchor match and mismatch counts move into the assembly report.

### 4.5 Diagnostics

`ReconstructionDiagnostics` gains, all `None`-defaulted so steps written before
them read as "not recorded":

| field | meaning |
| --- | --- |
| `committed_set_count` | commitments in the inventory |
| `proto_phoneme_count` | distinct reconstructed phonemes at this node |
| `assembled_column_count` | alignment columns the assembly resolved |
| `unaccounted_column_count` / `_rate` | columns resolved by `residue_policy` rather than by a committed set. **This is what replaces `rule_coverage`**, and it is a better shape: coverage is now over alignment columns rather than over (rule × in-scope child) pairs, so the scoping defect prompt 04 had to fix — `f > p / #_` scoped to three children scoring 0.33 against the identical reconstruction scoped to one scoring 1.0 — cannot recur. A column is explained or it is not, and how many children the set names does not enter the fraction |
| `cross_branch_assembly_rate` | share of concepts whose assembled form no single child's derived cascade produces |
| `columns_decided_by_residue_policy` | per node, the successor to `tie_broken_concept_count` (§6.7) |
| `mean_set_support` | mean support of the committed sets, so a node that reconstructed from residue is legible |
| `restored_segment_count` | commitments restoring a segment every active child lost, on cited out-group evidence (§6.9) |
| `alignment_overrides` / `override_singleton_sets_created` | realignments, and how many bypassed the join-a-set check (§6.1) |
| `held_out_unaccounted_column_rate` | the committed inventory applied to the concepts this node withheld: the share of *their* columns no committed set explains |

**And two existing fields are retired rather than reimplemented.**

`child_convergence_rate` and `divergent_concept_count` measure "the share of
concepts on which every attesting active child, contributing its highest-scoring
candidate transformed by its own scoped cascade, produced the identical parent
form". There are no scoped cascades any more — but the deeper point is that
**the failure they were built to detect can no longer happen.** One candidate
tuple assembles into exactly one parent form, so branch divergence about the
parent is structurally impossible. The metric does not need a new
implementation; its subject is gone.

They are already `None`-defaulted, so a 3.0 step reading as "not recorded" is
honest rather than lossy, and every printer already handles absence. What
replaces them is not one number but two, because they were measuring two things
at once: `cross_branch_assembly_rate` (did assembly actually mix branches) and
`unaccounted_column_rate` (how much of the evidence the inventory explained).

`docs/report_reject_or_score.md` uses child convergence as its second worked
example and will need a paragraph saying the case became unrepresentable —
which is a better outcome than the one that document argues for, and worth
recording as such.

**`held_out_convergence_rate` is *not* retired**, and the distinction matters.
Convergence was the wrong instrument, but the held-out *idea* — does this
inventory work on concepts it was not fitted to? — survives intact.
`held_out_unaccounted_column_rate` is its direct analogue and catches exactly
what prompt 04 added it for: an inventory fitted to five concepts explains
nothing on the concepts it never saw. Reported, never enforced, unchanged.

#### `ReconstructionStep.rule_reports`

Kept, and left empty. It is `tuple[RuleApplicationReport, ...] = ()`, already
defaulted, and it is serialized into every existing `result.json` and
`checkpoint.json`; removing it would make those unloadable under
`extra="forbid"` for no gain — the same argument that kept
`tool_failures_by_type` under a name that no longer describes it.

A sibling field carries the new evidence:

```python
    assembly_reports: tuple[ConceptAssemblyReport, ...] = ()
    """Per concept: the alignment ID, the matched set ID per column, the
    assembled form, the unaccounted columns, and any anchor matches.

    The compact rendering only — set IDs, never the alignment rows. The
    `correspondence_maps` measurement is the precedent and the warning: 448 KB
    of a 10,017 KB result for something no reader had asked for.
    """
```

Both defaulted, so a 2.0 step and a 3.0 step both load, and a reader tells them
apart by which one is populated.

### 4.6 The new tool surface

Sketched to the level the rest of `agent/schemas.py` is written at. Field
descriptions are omitted here and are not optional in the implementation: every
tool argument in this repository carries one, because the description is what
the model reads.

```python
# schemas/alignment.py — one field added, additive and backward compatible.
class CorrespondenceSet(WorkbenchModel):
    set_id: NonEmptyStr = ""       # derive_set_id(...); "" only for records
    segments: tuple[str | None, ...] = Field(min_length=2)   # written before it existed
    support: int = Field(ge=1)
    concept_count: int = Field(ge=1)
    example_concept_ids: tuple[NonEmptyStr, ...] = ()


class ComplementaryCandidate(WorkbenchModel):
    """Two sets whose occurrences never share an environment. A report."""
    set_ids: tuple[NonEmptyStr, NonEmptyStr]
    distinguishing_node_ids: tuple[NonEmptyStr, ...]
    shared_environment_count: Literal[0] = 0
    # Extended after approval: see section 12.1. The pair also reports the
    # tokens that distinguish it, because a report that states a conclusion and
    # withholds the evidence for it is the shape section 6.2 exists to avoid.
    left_context_tokens: tuple[tuple[str, ...], tuple[str, ...]] = ((), ())
    right_context_tokens: tuple[tuple[str, ...], tuple[str, ...]] = ((), ())


class AssemblyDetail(StrEnum):
    SUMMARY = "summary"     # assembled forms and counts; the default
    FULL = "full"           # plus per-column resolutions and alignment rows


class TestProtoAssemblyArgs(WorkbenchModel):
    commitments: tuple[CorrespondenceCommitment, ...]
    restorations: tuple[SegmentRestoration, ...] = ()       # §6.9
    residue_policy: ResiduePolicy
    residue_witness_child_id: NonEmptyStr | None = None
    residue_dispositions: tuple[ResidueDisposition, ...] = ()
    concept_ids: tuple[NonEmptyStr, ...] = ()      # empty = every concept
    segmentation_overlay_id: NonEmptyStr | None = None
    alignment_overlay_id: NonEmptyStr | None = None
    detail: AssemblyDetail = AssemblyDetail.SUMMARY


class ColumnResolution(WorkbenchModel):
    column_index: int = Field(ge=0)
    reflexes: tuple[str | None, ...]
    set_id: NonEmptyStr | None          # None when the column fell to residue
    proto_segment: NonEmptyStr | None
    resolved_by: Literal["set", "conditioned_set", "residue_policy",
                         "residue_disposition", "restoration"]


class ConceptAssemblyReport(WorkbenchModel):
    concept_id: NonEmptyStr
    alignment_id: NonEmptyStr
    assembled_segments: tuple[str, ...]
    columns: tuple[ColumnResolution, ...] = ()     # detail="full" only
    unaccounted_column_count: int = Field(ge=0)
    matched_anchor_ids: tuple[NonEmptyStr, ...] = ()


class TestProtoAssemblyResult(WorkbenchModel):
    # --- the part a commit is checked against; never compactable, tiny ---
    validation_call_id: NonEmptyStr
    covered_set_ids: tuple[NonEmptyStr, ...]
    unaccounted_column_rate: float = Field(ge=0.0, le=1.0)
    cross_branch_assembly_rate: float = Field(ge=0.0, le=1.0)
    ambiguous_columns: tuple[ColumnResolution, ...] = ()
    # --- the bulky, re-derivable part; shaped so it can be dropped (§6.8) ---
    concepts: tuple[ConceptAssemblyReport, ...] = ()
    derived_rules: tuple[ReconstructionRule, ...] = ()
    non_invertible_child_ids: tuple[NonEmptyStr, ...] = ()


class RealignArgs(WorkbenchModel):
    overrides: tuple[AlignmentOverride, ...] = Field(min_length=1)
    base_alignment_overlay_id: NonEmptyStr | None = None
    segmentation_overlay_id: NonEmptyStr | None = None
    rationale: NonEmptyStr


class RealignResult(WorkbenchModel):
    alignment_overlay_id: NonEmptyStr
    joined_set_support_delta: dict[str, int]
    invalidated_set_ids: tuple[NonEmptyStr, ...]
    override_concept_count: int = Field(ge=0)
    node_concept_count: int = Field(ge=0)
    advisory: NonEmptyStr          # the soft §6.1 line, always present
```

Two things in there are load-bearing rather than decorative.

**`TestProtoAssemblyResult` is split at the comment.** Everything above it is
what a commit is checked against and must survive for the session; everything
below is re-derivable by calling the tool again. That is what makes the §6.8
constraint implementable rather than aspirational, and it has to be the shape
from the first version, because a result schema is recorded in trajectories the
moment the tool ships.

**`RealignResult.invalidated_set_ids` is the answer to the staleness hazard
§4.1 names.** A realignment changes which columns exist, so every set ID derived
under the previous overlay is dead; returning them by name is cheaper for the
model than discovering it through `unknown-correspondence-set` at commit time.

---

## 5. Worked example: `*ʔ` and `*t` on the real benchmark

Real rows from `tools/correspondence_inventory.py` on
`runs/benchmarks/polynesian.json` — 56 cognate-set alignments, 216 distinct sets,
41 at support ≥ 2.

### 5.1 `*ʔ`, concept 1205 TONGUE

The alignment (SCA, ten daughters):

```
EastFutuna   ʔ  a  l  e  l  o        NorthMarq    -  a  ʔ  e  ʔ  o
EastUvea     ʔ  a  l  e  l  o        Rarotongan   -  a  r  e  r  o
Hawaiian     -  a  l  e  l  o        Samoan       -  a  l  e  l  o
Maori        -  a  r  e  r  o        Tahitian     -  a  r  e  r  o
Niuean       -  a  l  e  l  o        Tongan       ʔ  e  l  e  l  o
                                     GOLD         ʔ  a  l  e  l  o
```

Column 1 is the set the README quotes, at support 3 over the whole benchmark:

```
n   EFut EUve  Haw  Mri  Niu  NMq  Rar  Sam  Tah  Ton
3      ʔ    ʔ    Ø    Ø    Ø    Ø    Ø    Ø    Ø    ʔ     1205,1654,658
```

**The committed object** (abbreviating node IDs; the real ones are
`walworthpolynesian:EastFutuna` and so on):

```json
{
  "set_id": "cs-3f9a1c…",
  "reflexes": ["ʔ", "ʔ", null, null, null, null, null, null, null, "ʔ"],
  "proto_segment": "ʔ",
  "support": 3,
  "confidence": 0.9,
  "directionality_rationale":
    "Both primary branches attest it: Tongan in Tongic, EastFutuna/EastUvea in
     Futunic inside Nuclear Polynesian — and that pair is one witness, not two.
     Loss is shared by Samoan and all of Central Eastern, and independently by
     Niuean. Debuccalisation then loss. Not the reverse: nothing conditions
     inserting a glottal stop word-initially in two branches that separated at
     the root."
}
```

The tree is
`((Ton,Niu)tongic,(Sam,(EFut,EUve)futunic,((Haw,NMq)marquesic,(Mri,Tah,Rar)tahitic)central_eastern)nuclear_polynesian)`,
which is what makes that a two-clade argument rather than a three-daughter one —
the distinction `polarize` and `system_prompt.md` both insist on.

Column 2 is `⟨a a a a a a a a a e⟩` — Tongan alone dissents, and over the whole
benchmark that set occurs **once**, so it is residue under
`min_support = 2`. The model has two defensible dispositions and both are
expressible:

```json
{ "set_id": "cs-…", "reflexes": ["a","a","a","a","a","a","a","a","a","e"],
  "proto_segment": "a", "support": 1, "confidence": 0.5,
  "conditioning": null,
  "rationale": "Support 1. Nine daughters against one; committed as *a with low
                confidence and Tongan's e recorded as an anomaly." }
```

or, conditioned, which is what the addendum's `e > a / ʔ_` amounts to:

```json
{ "conditioning": { "left": { "tokens": ["ʔ"] } }, ... }
```

Committing a support-1 set is legal and deliberately so — the whole benchmark has
175 singletons against 41 recurrent sets, and refusing them would make most
concepts unassemblable — but it is **visible**: `mean_set_support` in the
diagnostics is what separates an inventory built on recurrence from one built on
one word each. That is the same treatment `min_support` already gives the survey
tool, carried through to the commit.

**The derived per-branch rules**, for the two sets together:

Rules are child-to-parent, so each is written *reflex > proto*:

```
Tongan          (none from the *ʔ set — its reflex already is ʔ)
                e > a / ʔ_        from the vowel set, conditioned
EastFutuna      (none)
EastUvea        (none)
Hawaiian        non-invertible: gap against *ʔ
Maori           non-invertible: gap against *ʔ;  r > l   from the *l set
Niuean          non-invertible: gap against *ʔ
NorthMarquesan  non-invertible: gap against *ʔ;  ʔ > l   from the *l set
Rarotongan      non-invertible: gap against *ʔ;  r > l
Samoan          non-invertible: gap against *ʔ
Tahitian        non-invertible: gap against *ʔ;  r > l
```

`NorthMarquesan ʔ > l` is worth pausing on, because North Marquesan's `ʔ` also
reflects `*k`, and that turns out to be a case the current representation cannot
express at all. §2 takes it up.

**The assembled proto-form**: `ʔ` + `a` + `l` + `e` + `l` + `o` =
`ʔ a l e l o` = gold. No branch produced it: `ʔ` comes from three daughters,
`a` from nine, and the two are not the same nine.

**At the `tongic` node**, where the live failure happened, the same set has
**support 12** over the 47 Tongan/Niuean alignments — as frequent as `t : t`,
and more frequent than `f : f` (10), `l : l` (10), `k : k` (8) or `m : m` (8).
This is `build_correspondence_sets` over a two-node selection, which is exactly
what `summarize_correspondences` returns to the model at that node:

```
Tongan  Niuean
  12      ʔ    Ø        1205,1237,1430
```

Tongan `ʔ e l e l o`, Niuean `a l e l o`, Proto-Tongic `*ʔ a l e l o`. Neither
daughter's string is the answer. The model got this right in
`runs/google-gemma-4-26b-a4b-20260817-180220` and was rejected three times for
saying it. Under this design it commits `⟨ʔ : Ø⟩ → *ʔ` at support 12 and the
form assembles.

### 5.2 `*t`, concept 1355 LAUGH

```
n   EFut EUve  Haw  Mri  Niu  NMq  Rar  Sam  Tah  Ton
9      t    t    k    t    t    t    t    t    t    t     1217,1248,1355
4      k    k    ʔ    k    k    ʔ    k    ʔ    ʔ    k     1215,1336,1355
4      k    k    ʔ    k    k    k    k    ʔ    ʔ    k     1392,1439,670
```

Concept 1355 uses the first two. Both commit trivially — `*t` and `*k` — and
the assembled form is `k a t a` = gold. **There is no rule order**, which is the
whole point of §2's fifth defect: the same reconstruction as a Hawaiian cascade
requires `k > t` strictly before `ʔ > k`, and nothing in the current commit
contract asks the model to say so or checks that it did.

Rows two and three differ **only in North Marquesan** (`ʔ` against `k`) and are
the natural candidate for a conditioned split or a merger claim — which is
§6.2's machinery, and which the model asserts rather than the harness detecting.

### 5.3 `*l` against `*r`: the case that decides §11.1

This is the sharpest example in the document, because it is the one where the
two live options — *fix the selection* and *change what gets committed* — give
different answers, and the evidence says which.

Proto-Polynesian distinguishes `*l` from `*r`. Eight of the ten daughters
merged them. Tongic did not. Three real alignment columns, in canonical node
order:

| concept | EFut | EUve | Haw | Mri | Niu | NMq | Rar | Sam | Tah | Ton | gold |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1205 TONGUE | l | l | l | **r** | l | ʔ | **r** | l | **r** | l | `*l` |
| 1408 HEAR | l | l | l | **r** | **n** | ʔ | **r** | l | **r** | **n** | `*r` |
| 646 ASH | l | l | l | **r** | Ø | ʔ | **r** | l | **r** | Ø | `*r` |

The `*l` row and the `*r` row are **identical in all eight non-Tongic
daughters** and differ only in Tongan and Niuean, which show `n` where the
others have merged. That is the entire evidence for `*r`, and it is exactly the
kind of evidence the comparative method exists to read.

**What the branch-cascade architecture does with it.** Maori shows `r` for both
`*l` and `*r`, so any rule scoped to Maori must pick one value. The oracle picks
the majority — `r > l` — and so do Rarotongan's and Tahitian's oracles. Here is
what then happens to concept 1408, under **oracle** rules, traced node by node:

```
Maori          r o ŋ o  (1.00)          <- the gold form, verbatim
Rarotongan     r o ŋ o  (1.00)          <- the gold form, verbatim, independently
tahitic        l o ŋ o  (0.67) | f a k a + l o k o (0.33)
central_east   l o ŋ o  (0.33) | ...
nuclear_poly   l o ŋ o  (0.44) | ...
proto_poly     l o ŋ o  (0.27) | f + n o ŋ o (0.26) | f e + n o ŋ o (0.24) | ...
```

**Two daughters independently attest the correct proto-form exactly, and it is
destroyed at the first internal node above them.** It is not outranked; it does
not appear in any beam at any node above `tahitic`. No tie-break policy, no beam
width, no scoring change anywhere in `traversal/` can recover it, because by the
time selection runs the candidate no longer exists.

**What per-set assembly does with it.** The two columns are two sets. The
`⟨l l l r n ʔ r l r n⟩` set reconstructs `*r` and the `⟨l l l r l ʔ r l r l⟩` set
reconstructs `*l`; Maori needs no rule at all, because its reflex equals the
proto-phoneme in one set and the other set's value is read off the same column.
The assembled form is `r o ŋ o`.

**The honest limit.** `*r` occurs in 2 of the 46 gold forms against `*l` in 10,
so the `*r` set has low support and reconstructing it is a real judgement on
thin evidence — assembly makes the answer *reachable*, not *automatic*. But
"reachable" is the whole question here: under the current architecture the model
can be entirely right about Polynesian and still not be able to say so.

---

## 6. The questions the design has to answer

### 6.1 Alignment

Alignment becomes load-bearing in a way it is not today. Under branch cascades a
bad alignment costs the model a confusing evidence view; under assembly it costs
the model the answer, because the columns *are* the reconstruction. Concept
`1217` is the measured case: SCA aligns `m a t u a` against `t a m a` into
non-overlapping columns and no assembly over those columns can reach
`t a m a + n a`.

**What happens when SCA aligns badly.** Three things, in order:

1. It is **visible**. `test_proto_assembly` returns the alignment it used, per
   concept, with the columns numbered, so the model sees the columns it is
   committing values for rather than inferring them.
2. It is **counted**. A concept whose assembly leaves columns unaccounted, or
   whose assembled form is shorter than every child's form, is reported in
   `unaccounted_column_rate` and in the per-concept assembly report.
3. It is **correctable**, under a bounded mechanism.

**The correction mechanism, and what stops it forcing a result.** The precedent
is `segment_morphemes`: an immutable, ID'd overlay that may not change phonetic
tokens. The same shape applies.

```python
class AlignmentOverride(WorkbenchModel):
    concept_id: NonEmptyStr
    rows: tuple[tuple[str | None, ...], ...]   # positional against child_node_ids
    joins_set_id: NonEmptyStr | None
    """The correspondence set this realignment claims the moved column joins.

    Not optional in spirit: `None` selects `new_set` mode, which is legal, is
    counted separately, and is the mode that bypasses the check below. Naming a
    set turns an edit into a claim the harness can verify.
    """
    rationale: NonEmptyStr
```

`realign(concept_ids, overrides, rationale) -> alignment_overlay_id`, immutable,
session-local, ID'd, recorded in the trajectory. Four constraints, in increasing
order of how much they do:

**1. The rows must be the children's own forms.** Dropping the gaps from each
row must reproduce that child's form under the current segmentation overlay,
token for token. The model may move material between columns; it may not
invent, delete, or reorder a segment. Same discipline as `segment_morphemes`,
one level up, and checkable arithmetic rather than judgement.

**2. An override is per concept, never a rule about the evidence.** There is no
way to say "always align `ʔ` against a gap". Overrides are session-local, never
cross a node boundary, never enter the checkpoint, and never persist into
another run. Nothing the model does to an alignment is permanent.

**3. A realignment must say which set it joins, and the claim is verified.**
This is the constraint that does the real work. After the override, the harness
re-derives the inventory; the named `joins_set_id` must gain support by exactly
the number of columns the override claimed for it. If it does not, the call is
refused (`realignment-does-not-join-set`) naming the concept and the column.

The reason this is the right lever and a bare count is not: **forcing a
convenient answer and repairing a misalignment look different to this check.**
A genuine repair moves a column into an already-recurrent correspondence — that
is what noticing a correspondence *is*. Fitting the alignment to a desired
proto-form almost always produces a column pattern nothing else in the lexicon
shows. The check therefore lets the model realign *toward established evidence*
and makes realigning *away* from it expensive, which is the same asymmetry the
comparative method itself runs on.

`joins_set_id = None` (`new_set` mode) stays legal, because the first attestation
of a real correspondence has to be expressible. It is reported separately as
`override_singleton_sets_created`, because it is the mode that bypasses the
check above and a reader should see how much of a node's realigning went through
it.

**4. No cap. A soft advisory in the tool result, and an instruction.** An
earlier draft of this design proposed a hard budget,
`max(3, ceil(0.10 × concepts_at_node))`. It is not in the design, and the reason
is worth recording because the argument against it is better than the argument
for it.

**How many realignments a node legitimately needs is a property of the aligner
on that family, not of the family's size.** SCA handles some phonologies and
some morphologies better than others; a family where it does badly needs more
repairs than a family where it does well, and neither the concept count nor any
other quantity the harness can see predicts which. A fixed cap would therefore
be tight exactly where repairs are most needed and slack where they are not, and
its number would be a guess dressed as a bound.

Two attempts to derive a principled cap both failed on measurement. Scaling by
*apparent difficulty* does not work: 30 of 46 Polynesian concepts show a
structural alignment-difficulty signal — some daughter carrying a morph boundary
the others lack, or a three-token length spread — including all four concepts
flat assembly cannot reach, but also 26 that assemble perfectly. The signal does
not separate the cases, so it cannot license anything.

What replaces it:

- **Constraint 3 already adapts.** The join-a-set check is not a fixed number;
  it scales with the evidence. A family where SCA aligns badly is a family where
  many columns genuinely belong to recurrent sets they were not put in, so the
  legitimate repairs pass and the fitted ones do not — which is precisely the
  behaviour a cap was trying to approximate and could not.
- **A soft advisory in the tool result**, modelled on `contrast_reduction`.
  `realign` returns, every time, how many of this node's concepts now carry an
  override and out of how many — *"18 of 46 concepts at this node now carry an
  alignment override"* — with no refusal attached. That is the repo's existing
  pattern for "this is legitimate, common, and worth your attention before you
  commit": `test_sound_law` already reports that a rule discards `ʔ` attested in
  3 of 10 nodes and refuses nothing.
- **An instruction in `system_prompt.md`**, saying plainly that `realign` is for the
  case where SCA has misaligned a form — a compound against a simplex, two
  lexemes in one concept — and not a routine step; that the default is to accept
  the aligner's output; and that a session realigning a large share of its
  concepts is fitting the evidence rather than reading it.
- **Prominent reporting**, unchanged: `alignment_overrides`,
  `override_singleton_sets_created`, per node, in the diagnostics and in
  `inspect-run`.

**What this gives up, stated plainly.** The README records the opposite call in
a neighbouring case: `rule_coverage` was fixed rather than the instruction,
because "telling the model in `agent/system_prompt.md` to scope rules only to children
that exhibit the target would depend on the model complying". That reasoning
applies here too, and the honest answer is that this design accepts the
dependency for one specific reason — the mechanical constraint that *can* be
stated (constraint 3) is stated and enforced, and the residual is a matter of
degree rather than of kind. A model that realigns 40 concepts, each one
legitimately joining a recurrent set, has done something a reviewer should look
at and nothing a deterministic check can call wrong.

The share is therefore a **`high_quality` candidate for later**, once a corpus
of graded trajectories exists to calibrate a threshold — the same holding
pattern `docs/report_reject_or_score.md` puts every "bad needs judgement"
signal in. §7.2 carries the stop condition that would force a cap back.

**What is reported and not enforced.** `alignment_overrides`,
`override_singleton_sets_created`, and the per-concept list, in the diagnostics
and in `inspect-run`. "Was this realignment *right*?" is question three; the
counts are rule 2. A node that reconstructed 40 of 46 concepts through
hand-aligned overlays is a node whose reconstruction is the model's alignment,
and a reader must be able to see that in one line.

**The residual risk, stated rather than engineered away.** Constraint 3 makes it
hard to fit an alignment to a preferred answer — a fitted column usually joins
no recurrent set — but nothing makes it impossible, and without a cap nothing
bounds how often it is attempted. That is the accepted cost of not pretending to
know how many repairs a family needs. One hand-aligned concept with a stated
rationale is what a linguist does, and it is recorded where a reviewer sees it;
forty of them is a different object, and the advisory, the counters and the
`system_prompt.md` wording are what make the difference legible. `high_quality` may
later gate on the override share once a corpus of graded trajectories exists to
calibrate a threshold. It must not gate on it now.

### 6.2 Conditioning

Two correspondence sets in complementary distribution are one phoneme with a
conditioned split. Three separate questions, three different answers.

**How the condition is expressed.** `CorrespondenceCommitment.conditioning`, a
`RuleEnvironment` — the DSL's existing left/right/word-edge vocabulary, reused
rather than reinvented, so the derived rule renders straight back into DSL text
and `score-synthetic` can keep matching structurally.

**How complementarity is checked.** Mechanically, and it is a **rejection**.
Given two commitments `A` and `B` with `A.merges_with_set_id == B.set_id`, the
harness computes over the node's own aligned columns:

- every column occurrence of `A`'s reflex tuple satisfies `A.conditioning`;
- every column occurrence of `B`'s reflex tuple satisfies `B.conditioning`;
- no column satisfies both conditions;
- `A.proto_segment == B.proto_segment`, and neither is `None`.

All four are arithmetic over the forms. A claim failing any of them is refused
at the tool boundary under `non-complementary-split`, with the offending
concept and column in the remediation. This is question one: the harness is not
deciding whether the collapse is *correct*, only whether the distributional
claim the model made is true of the data in front of it.

**Who asserts it.** The **model**, always. The harness *reports* candidates and
never proposes one: `summarize_correspondences` gains a
`complementary_candidates` block naming pairs of sets whose occurrences never
share an environment, because that is cheap, decidable, and exactly the kind of
fact a linguist wants surfaced. Proposing the collapse would be the harness
phonemicising, which is question three. The asymmetry is the same one that
governs `polarize`: retrieve the distribution, never name the value.

### 6.3 Residue

A column matching no committed set is the successor to today's unexplained form,
and the design's position is that **silence must be impossible while enumeration
must not be required**.

- `residue_policy` is **required with no default**. `retain_from_witness` says
  carry through whatever one named child shows and mark it unexplained; `drop`
  says the material is branch-specific innovation and contributes nothing.
  Rejecting on absence and never on content is the same shape as
  `directionality_rationale`, for the same reason: the harness cannot judge
  which policy is right and a reviewer needs the claim in the model's words.

  **Carry-through is the reading the assembler is built around and `drop` is the
  assertion**, not the other way round — §4.4 has the argument, and it is the
  difference between a partial inventory degrading gracefully and a partial
  inventory erasing the lexicon.

  **A `majority_reflex` policy was drafted here and removed, and the reason is
  the same principle that decided §11.1.** "Carry the segment most children
  show" is a majority vote over daughters, and this repository has already
  measured that a majority vote reconstructs innovations: eight of ten
  Polynesian daughters lost `*ʔ`, and `tools/outgroup_probe.py` found that
  averaging over daughters scores *exactly what alphabetical order scores*
  because it degenerates into a vote over shared innovations. Putting that in
  the residue path would have quietly made the harness reconstruct by counting
  in precisely the cases where the evidence is thinnest — the one place a
  linguist is most needed and least replaceable by arithmetic. `retain_from_witness`
  asks the model for the judgement instead, and records the answer.
- `residue_dispositions` handles named exceptions, per concept and column, for
  the loanword or the analogy the model has actually looked at.
- `AnomalyReport` is **unchanged and still required**. The four anomaly types
  (`loanword`, `morphological_leveling`, `taboo_deformation`,
  `unknown_irregularity`) describe exactly the material a residue policy
  disposes of mechanically, and the two are complementary: the policy says what
  the assembler *did*, the anomaly says what the model *thinks*.
- `unaccounted_column_count` and `unaccounted_column_rate` are reported to the
  model in the `test_proto_assembly` and commit results, recorded in the
  diagnostics, and printed by `inspect-run` beside the anomaly rate.

Nothing rejects on the *rate*. Under `min_support = 2` on Polynesian, 175 of 216
sets are singletons; a node whose residue rate is high may be a node looking
honestly at a messy lexicon. Rejecting on it would reward inventing a set per
exception, which is precisely what `docs/report_reject_or_score.md` says the
anomaly channel exists to avoid.

### 6.4 Migration

**Survives unchanged, and must:**

| Component | Why |
| --- | --- |
| `rules/parser.py` | The synthetic generator writes families in this DSL; derived rules render into it; `score-synthetic` matches on `parse_rule`. |
| `rules/engine.py` | The generator applies it forward, parent to child. Derived-rule verification applies it backward. |
| `alignment/` | Now load-bearing rather than advisory. No change, more weight. |
| `evaluation/`, `benchmarks/`, `synthesis/generator.py` | Untouched. |
| `tools/branch_recoverability.py` | Untouched and still meaningful. It measures a property of the gold and the daughters' forms under the DSL, **not** of the harness, so a different commit shape does not move it — it stays the independent statement of what no branch-local rule can reach. |
| `tools/tiebreak_probe.py`, `tools/outgroup_probe.py` | Both still exercise `traversal/beam.py`, which survives. `outgroup_probe` becomes *more* relevant, since it scores tie-break policies and §6.7 moves the remaining ties into columns; re-run both at stage 1 and record whether the per-clade, presence-only reading still holds. |
| `traversal/beam.py` | `normalize_and_prune`, `TIE_BREAK_POLICY`, `make_leaf_beam` all survive; only what produces the raw candidates changes. |
| `polarize`, `summarize_correspondences`, `get_alignments`, `search_forms`, `list_concepts`, `list_available_nodes`, `segment_morphemes` | Untouched. `polarize` becomes *more* central without changing at all: it retrieves the out-group distribution for one correspondence and still never names the original value — and the value it declines to name is now literally the field the model has to fill in. |

**Becomes a derived view:**

| Component | New status |
| --- | --- |
| `ReconstructionRule` / the branch cascade | Derived from the inventory, verified, reported, consumed by `score-synthetic` and `inspect-run`. Never committed. |
| `test_sound_law` | Demoted from validation gate to exploratory probe. Kept: it is the cheapest way to check a hypothesis about one branch before assigning a value, and its `contrast_reduction` and `held_out` blocks stay useful. |
| `get_node_reconstruction` | Returns the prior node's **inventory** plus its derived rules, through a `PriorNodeInventory` mirroring `PriorNodeReconstruction`. Both shapes readable during the migration. It carries `child_node_ids` beside the reflex tuples, without which another node cannot interpret them, and **strips `set_id`** — a set ID is derived from a reflex tuple over *that* node's children and its overlays, so it is meaningless anywhere else. Same read-only framing as today: a prior node's inventory is another session's hypothesis, carries no independent evidential weight, and must never appear as support for a commitment here. |
| `rules/contrast.py` | Retargeted, not rewritten: contrast reduction is now computed from the inventory (two sets sharing one `proto_segment` is a merger; a non-null reflex against a null `proto_segment` is a deletion) instead of by applying a cascade. Same arithmetic, same discipline, better evidence — it now sees the merger *as a merger* rather than inferring it from a mapping. |

**Removed** — see §9 for the full list with reasons. The headline is
`test_rule_cascade`, because under per-set assembly there is no order to
preview.

**Both shapes accepted, and for how long.** Stages 2 and 3.
`commit_reconstruction` accepts `rules` XOR `inventory` and rejects a call
carrying both. Stage 4 removes the rule path, and **stage 4 is conditional on
the falsification numbers in §7 being met over at least five seeds on both
benchmarks.** If they are not met, stages 1–3 stand as an additive capability
and the branch-cascade path is not removed. That is the whole point of staging
it this way: the expensive, irreversible half is last and is gated on evidence.

**The three prompt-05 consumers, named explicitly:**

- **`synthesis/generator.py`** keeps running `RuleEngine.apply_rules` forward and
  the family definitions stay written in the DSL. That coupling is deliberate —
  a change the DSL cannot state is a change the generator cannot make, which is
  what keeps the benchmark honest — and this design does not touch it. No file
  under `benchmarks/synthetic/` changes.
- **`synthesis/scoring.py`** gains an inventory comparison and keeps everything
  it has. §9.2.
- **`tools/oracle_ceiling.py`** gains modes and keeps its old ones. §9.3.

### 6.5 Trajectories

**The version must bump, and the README's own rule is why.** Bump when a
*reader* must behave differently, never merely because fields were added.
Prompt 05 is the worked example coming out the other way: it added defaulted
fields to result schemas, nothing reachable from `AgentTrajectory` moved, the
digest did not change, and records written on 2026-08-20 still read as
`current`. This change is not that. `CommittedReconstruction.request.rules` is
the object every downstream reader indexes — `inspect_run.py:783`,
`inspect_run.py:985`, `synthesis/scoring.py:226`,
`trajectory.py:280`, `orchestrator.py:1341` — and after this change some records
will not have it. A reader must branch. That is the definition.

**The mechanism.** `schema_version` widens to `Literal["2.0", "3.0"]`, and a
test asserts that every existing 2.0 file still loads. That test already exists:
`tests/workbench/test_schema_versioning.py::test_widening_the_version_literal_keeps_existing_files_loadable`
was written by prompt 05 to prove the widening it deliberately declined to
perform. It is exercised here for real, with `"3.0"` in place of its `"2.1"`.
`CommittedReconstruction` becomes a union discriminated by which request shape
is present:

```python
CommittedHypothesis = CommittedReconstruction | CommittedProtoInventory
```

`AgentTrajectory.committed_reconstruction` keeps its field name. Renaming it
would make every 2.0 record unloadable under `extra='forbid'` for a purely
cosmetic gain — the same argument that kept `tool_failures_by_type`.

**What happens to the existing records.** They are kept, and they are not
worthless. A 2.0 trajectory is a complete, valid example of everything up to the
commit turn: reading a correspondence survey, polarizing a set, pulling a
bounded alignment batch, refining an overapplying rule, recording an anomaly.
Only the commit turn teaches a protocol that no longer exists. Concretely, the
`tongic` session in `runs/google-gemma-4-26b-a4b-20260817-180220` is the single
best record this repository has of *why* this change is being made, and
discarding it would be discarding the evidence.

**Is a mixed corpus usable? The question is narrower than it looks.**
`runs/` is a **progress-tracking** archive, not a training corpus — a fine-tuning
corpus would be generated fresh, under whatever commit protocol is current at
the time. That settles it, and it deletes work from this design rather than
adding any:

- **No mixed-corpus machinery is needed.** `TrajectoryDatasetBuilder` gets no
  `--allow-mixed-commit-shapes` flag and `export-trajectories` gets no
  `--commit-shape` filter. Neither would have a caller.
- **`summarize-trajectories` reports `commit_shapes`** beside `schema_variants`.
  This one stays, because it is exactly the progress-tracking signal the archive
  exists for: "how many nodes has this build committed under the new protocol"
  is the question a migration wants answered every day, and it comes out of data
  every record already carries. Same argument prompt 05 made for the digest.
- **Every 2.0 record stays loadable and nothing is deleted.** The `tongic`
  session in `runs/google-gemma-4-26b-a4b-20260817-180220` is the only record of
  the failure this change exists to fix, and the archive is where a before/after
  is read.

What the union type buys, then, is not corpus curation but the ability to read
the archive across the migration at all — which is the whole requirement.

### 6.6 Validation

**The invariant today**: every non-empty committed rule needs an exact
same-session validation — a `test_sound_law` call or a `test_rule_cascade`
preview containing it, matched on the *parsed* rule, child scope, and overlay.
Its purpose is that no committed claim is untested.

**The equivalent invariant, in two parts:**

1. **Every commitment cites a set the harness itself produced.** `set_id` is
   deterministic in the reflex tuple, the child column order, and the
   segmentation and alignment overlays. On commit the harness re-derives the
   inventory from the node's forms under those overlays and checks that the
   cited set exists, that `reflexes` matches it, and that `support` matches it.
   A commitment citing a set the data does not contain is refused
   (`unknown-correspondence-set`); one whose support the model altered is
   refused (`correspondence-support-mismatch`). This is stronger than the rule
   invariant, not weaker: the evidence is not merely *tested*, it is
   *re-derived*.
2. **Every committed set was exercised by a `test_proto_assembly` in this
   session.** The preview returns, per concept: the alignment it used, the
   matched set per column, the assembled parent form, the unaccounted columns,
   and the derived per-branch rules with their verification.

   **Coverage is over sets, not over concepts**, and that distinction is what
   makes the invariant satisfiable on a large family. On Polynesian a preview
   can cover all 46 concepts for 27.8 KB (§6.8) and the question does not arise;
   on Romance, at 900 concepts, it must be batched, and requiring every *concept*
   to have been previewed would make a commit need dozens of calls. Requiring
   every committed *set* to have been exercised is the right invariant anyway:
   it is the sets that are the claims. `assembly_validation_call_id` may be
   omitted and resolved from the session's previews, exactly as
   `validation_call_id` may be today; where several previews are needed their
   coverage unions.

**Checked against prompt 03's test — can the model reach it by following
`system_prompt.md`?** Yes, and this is the part that has to be right, because prompt 03
exists because the prescribed workflow had no legal path through the commit
contract. The refinement loop here is:

```
1  summarize_correspondences               (unchanged, still first)
2  polarize the sets the children do not force   (unchanged, now central)
3  get_alignments for the sets under investigation  (unchanged)
4  assign a proto_segment to each set
5  test_proto_assembly on the whole proposed inventory
6  read the unaccounted columns and the per-concept assemblies
7  refine — add a conditioning environment, split a set, change a value
8  test_proto_assembly again
9  commit_reconstruction with the inventory
```

The refinement in step 7 produces a changed inventory, and a changed inventory
is validated by step 8 — **the same call that is the commit's evidence**. There
is no object that first exists inside a preview and then needs a separate
standalone test to be committable, which was precisely prompt 03's defect. The
loop closes.

**Directionality survives, with a better definition of "discards".** Today a
rule needs a `directionality_rationale` when applying it deletes or merges. For
a commitment the same two properties are read straight off the inventory rather
than inferred from a mapping:

- **deletion** — some child's reflex is non-null and `proto_segment` is `None`;
- **merger** — two committed sets carry the same `proto_segment` and their
  conditionings are not complementary, so a distinction some child makes is not
  made in the parent.

Both are arithmetic, both are more direct than the current detection, and the
rejection stays on **absence and never on content**. `contrast_reducing_rule_count`
becomes `contrast_reducing_set_count` and keeps its role as the counterweight to
coverage.

### 6.7 Scoring

**Where uncertainty lives.** Per set, in `confidence`, which is where it already
lives — a model judgement the beam consumes as a score weight. What changes is
that it is attached to a correspondence rather than to a rewrite, which is a
more honest object to be uncertain about.

**How it composes.** For each concept, the assembly walks the alignment columns.
A column matched by exactly one committed set contributes that set's
proto-phoneme with log-mass `log(confidence)`. A column matched by nothing
contributes what `residue_policy` says, with a fixed low mass named as a
constant in `traversal/assembler.py` rather than derived from anything — it is
not a probability and should not look like one. Where the model committed
alternatives, or where residue admits more than one reading, the column branches
and the candidates multiply, then merge and prune through the **existing**
`normalize_and_prune`. `TIE_BREAK_POLICY` is unchanged and still arbitrary and
still says so.

**It does not pretend to be a posterior**, and the existing wording covers it:
"normalized heuristic beam mass, not calibrated Bayesian posteriors". A product
over columns of numbers a model wrote down is not a likelihood. The design adds
no claim to the contrary and no new scored quantity.

#### Where the parent's alternatives come from

This was under-specified in the first draft and it is not optional, because
getting it wrong silently kills the beam. **Assembly operates on the children's
full beams, not on their top candidates.**

Measured under the oracle, the beam is genuinely occupied:

| node | concepts | mean candidates | concepts with > 1 |
| --- | --- | --- | --- |
| tongic | 46 | 1.72 | 28 |
| central_eastern | 46 | 2.76 | 37 |
| proto_polynesian | 46 | 3.80 | **43** |

43 of 46 concepts carry more than one candidate at the root, and that
distribution is load-bearing: it is what gives `synthetic_hard` 25/25 beam-exact
against 15/25 top-1, and it is the only reason a mistake at a low node is
survivable at a high one. Assembling from top candidates alone would emit
exactly one form per node, collapse the beam to width 1, and make every
intermediate error permanent.

So assembly slots in **at the same place `_PartialCombination` sits today**: the
reconstructor already walks a bounded Cartesian product over the children's
candidates, merging and pruning after each child. The only change is what
happens inside the loop — instead of transforming each child candidate through a
scoped cascade and collecting distinct outputs, the selected candidate tuple is
aligned and one form is assembled from it. Same combinatorics, same
`beam_width`, same `normalize_and_prune`, same `TIE_BREAK_POLICY`.

Two consequences worth stating:

- **`CorrespondenceCommitment.proto_segment` stays single-valued.** The
  alternatives come from the *children's beams*, which is where they come from
  today; the model does not need to commit several readings of one set, and a
  schema that let it would be inviting a hedge rather than a hypothesis.
- **Alignment cost multiplies by the candidate tuple count**, bounded by
  `beam_width ** len(children)` and in practice near 6 per concept at the root.
  Alignments must be cached by candidate tuple — many tuples repeat across
  concepts — and that caching is a stage-1 implementation requirement, not an
  optimisation.

**The successor to `decided_by_tie_break`.** This matters: today a reader can
tell an evidenced reconstruction from an arbitrary one because
`tie_broken_concept_count` says how many reported forms were chosen by segment
order. Under assembly, ties between whole strings mostly disappear — which is
the point — and the arbitrariness moves *into the columns*. Two counters replace
it and both are per node:

- `columns_decided_by_residue_policy` — columns whose value came from the
  policy rather than from a committed set;
- `columns_decided_by_tie_break` — columns where two committed sets matched at
  equal mass and `TIE_BREAK_POLICY` picked.

Without these the visibility prompt 05 bought is lost, and the beam would print
one candidate at p = 1.00 whether every column was evidenced or half of them
were defaults. `inspect-run` prints both beside `unaccounted_column_rate`.

**And the second kind is shown to the model before it commits.**
`test_proto_assembly` lists every column where two committed sets both match, so
the session can disambiguate it — by conditioning one of them, by splitting a
set, or by saying in the summary that the evidence does not decide. Resolving it
silently by segment order would be the harness making a call the model is better
placed to make, which is the thing §11.1 decided against. `TIE_BREAK_POLICY`
stays as the last resort and stays documented as arbitrary; what changes is that
the model gets a chance at it first.

**A note for later, deliberately not acted on now.** How per-column confidence
composes into form-level mass — a product of the committed confidences — is
inherited from what rule confidences already do and was kept unchanged on
purpose, so that this change is not also a scoring reform. Two things would
justify revisiting it: evidence that long forms are being systematically
outranked by short ones within a concept (the length bias the product carries,
which should mostly cancel under per-concept normalization but has not been
measured), or a decision to let a model express uncertainty per column in some
way other than a single scalar. Neither is urgent; both are cheap to test
against `tools/oracle_ceiling.py` when someone wants to. Alternatives to
consider then: a geometric mean, which removes the length term outright, or a
weakest-link minimum, which reads more like how a linguist talks about a
reconstruction resting on its shakiest correspondence.

**On the prompt's generation-versus-selection test.** §1.3 sets this out: the
prompt asks that beam-best NED fall, on the grounds that per-set assembly is a
claim about generation. The measurements say it is mostly a claim about
selection — beam-exact moves 41 → 42 while top-1 moves 32 → 39 — and that under
assembly top-1 and beam-best converge by construction. The test as stated would
reject a working change. §7 replaces it with one that measures the same concern
without the false premise.

### 6.8 Cost

Prompt 01 made affordability the precondition for anything the model is told to
call routinely, and the new required call is `test_proto_assembly`, which
returns alignments. That sounds expensive and is not, because the thing that
made `get_alignments` expensive is the *pairwise* correspondence views, which
grow with the square of the node count — and an assembly preview does not need
them. It needs the n-way rows.

Measured on the ten-daughter Polynesian benchmark, over all 56 cognate-set
alignments:

| payload | size |
| --- | --- |
| the full `get_alignments`-shaped map, ten nodes, every concept | 1025.5 KB |
| **the n-way alignment rows alone, ten nodes, every concept** | **27.8 KB** |
| per concept | 0.50 KB |
| a 24-concept preview batch | 11.9 KB |

27.8 KB is the same order as `summarize_correspondences` over the whole evidence
set (28 KB), which the model is already instructed to call first and
unprompted. So the preview that validates a commit can cover **every concept at
the node** and still cost less than one six-concept `get_alignments` call did
before prompt 01's work.

That is a design constraint as much as a measurement: `test_proto_assembly` must
return n-way rows and assembled forms, and must **not** return pairwise
correspondence views. It has no use for them, and returning them would put the
quadratic term back into the one call the workflow requires.

#### What this change removes from the live prompt

Measured on `runs/google-gemma-4-26b-a4b-20260820-212424`, per tool result, at
the node that came closest to dying of context:

| `marquesic` tool result | size |
| --- | --- |
| `summarize_correspondences` | 3.1 KB |
| `get_alignments` ×2 | 11.6 KB |
| `polarize` ×2 | 7.4 KB |
| **`test_rule_cascade` ×3** | **398.9 KB** |

The prompt went 18k → 69k → 119k → 177k tokens across those three calls. Every
piece of evidence the session actually looked at came to 22 KB; the cascade
previews came to 399 KB, and they are **never compactable** by design, because
they carry the validation IDs a commit is checked against.

`test_rule_cascade` is the tool this design deletes (§9.1). The largest observed
context consumer in a real run is removed by the change rather than optimised,
and it is replaced by a call that costs 27.8 KB for the whole benchmark. That
was not an argument for the change when it was written; it is one now.

#### And what it must not put back

`test_rule_cascade` is the cautionary tale for `test_proto_assembly`, and the
resemblance is uncomfortable: both are the call that validates a commit, both
therefore carry an ID that cannot be re-derived, and both are consequently
**ineligible for compaction for the whole session**. A preview that returned
per-concept alignments, matched sets, assembled forms, unaccounted columns *and*
derived rules for 46 concepts would be the same object under a new name.

Three constraints on its result, all design-time and none optional:

- **No pairwise correspondence views**, per the section above. It has no use for
  them and they are the quadratic term.
- **A `detail` argument defaulting to `"summary"`**, on the pattern
  `get_alignments` already uses: assembled forms, per-column matched set IDs,
  and the unaccounted-column count, with the full per-concept alignment rows
  only under `detail="full"`. The measured 27.8 KB is the *rows*; the summary is
  smaller.
- **The result must be split so the bulky half is compactable.** The part that
  cannot be dropped is the validation ID, the set-coverage list, and the
  verdict — a few hundred bytes. The per-concept evidence is re-derivable by
  calling the tool again, which is exactly the test `COMPACTABLE_TOOL_NAMES`
  applies. Today compaction is all-or-nothing per tool message, so this needs
  the result to be *shaped* for it rather than the compactor to be cleverer.

The third is the one to get right at stage 2, because retrofitting it after a
tool is in use means changing a result schema the trajectories already record.

### 6.9 Restoring a segment every child lost

§1.4 records the limit honestly: at a node where **every** active child has lost
a segment, the correspondence set is `⟨Ø : Ø⟩`, it reconstructs nothing, and
per-set assembly is exactly as stuck as a cascade. On `synthetic_hard` that is
`east`, whose two children both lost `*ʔ`, and it costs three concepts —
`leaf`, `tooth`, `tree` — taking that node from 25/25 to 22/25.

That limit is worth removing, because the comparative method removes it
routinely. A linguist reconstructing Proto-East knows `*ʔ` was there, because a
branch outside East still shows it. The model can already *see* that evidence —
`polarize` returns it, and `d1` attests the segment — and has no way to *commit*
it.

**The blocker is mechanical, not conceptual: there is no column.** An alignment
of two forms that both lack a segment has nothing at that position to attach a
commitment to.

#### A correction: this is not a correspondence set

An earlier version of this section routed the restoration through `realign`, on
the observation that an **all-gap column adds no material to any row** and so
satisfies the override invariant for free. That was elegant and it does not
work, for two reasons found while auditing the section against the code:

- `build_correspondence_sets` **skips all-gap columns outright** —
  `if all(segment is None for segment in key): continue` — so an inserted empty
  column yields no set, no `set_id`, and nothing to cite.
- Retaining them would be worse. The `support` of an all-gap set would count
  columns *the model itself inserted*, so the model would be manufacturing the
  evidence for its own support count — and support is the one number §4.1
  insists must never be a model claim.

The second point is the decisive one, and it says what the right shape is: a
restoration is **not a correspondence**. Nothing corresponds; that is the entire
situation. It is a per-position claim, and it belongs beside
`ResidueDisposition`, which is also per position, rather than among the
commitments.

```python
class SegmentRestoration(WorkbenchModel):
    concept_id: NonEmptyStr
    before_column_index: int = Field(ge=0)
    """Insert before this column of the alignment under the committed overlays.

    Indices are into that alignment and are unaffected by other restorations, so
    they stay stable however many are committed. At most one restoration per
    (concept_id, before_column_index); a second is refused.
    """
    proto_segment: NonEmptyStr
    restored_from_node_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    """Out-group nodes whose evidence licenses this. Verified, below."""
    directionality_rationale: NonEmptyStr
    """Required, never optional here: restoring a segment *is* the claim that
    every active branch lost it."""
```

`CommitProtoInventoryArgs` and `TestProtoAssemblyArgs` each carry
`restorations: tuple[SegmentRestoration, ...] = ()`, and `realign` is not
involved at all — which is also a simplification, since routing through it would
have needed `new_set` mode, the one mode that bypasses the join-a-set check.

Being per concept is verbose — restoring `*ʔ` across eight words takes eight
entries — and that is correct rather than unfortunate. Each is a separate claim
about a separate word, and each is separately verified.

**And the citation is verified, mechanically.** Using the machinery `polarize`
already has, the harness aligns the active children with each cited node and
checks that the cited node genuinely shows `proto_segment` at the corresponding
position. Three refusals, all arithmetic:

| Refusal | Code |
| --- | --- |
| A cited node does not attest the restored segment in that position | `restoration-unattested` |
| A cited node is a **descendant**, not an out-group | `restoration-cites-descendant` |
| A restoration at a node that has no out-group at all | `restoration-without-outgroup` |

The second matters and is the same cladistic error `polarize` was built to
prevent: a descendant lies *inside* the subtree and shows what these children
became, which is the proposition under test rather than evidence about it.
`polarize` already tags every node it reports with a `relation`, so this is a
property of the tool result and not a reading of the model's prose.

The third is a limit rather than a check, and it is worth stating because it
bites exactly where restoration is most tempting: **the root has no out-group**,
so nothing licenses a restoration there. That is the same limit `polarize`
carries and states, for the same reason, and it means this mechanism improves
the root only by improving the nodes that feed it.

**What is checked and what is not.** The harness verifies that the evidence
cited exists. It does not and cannot judge whether the restoration is *right* —
whether the segment was lost in both branches independently, or the alignment
position is correct, or the out-group is the relevant one. That is question
three, and `restored_segment_count` is reported per node, printed by
`inspect-run`, and gated on nothing.

**Why this is not a licence to invent material.** A restoration needs a real
out-group node showing the real segment in the aligned position. It cannot
produce a segment attested nowhere — which, note, is a *narrower* power than
`proto_segment` already has for an ordinary set, where PPn `*w` is reconstructed
from a column showing only `v` and gaps (§1.4). The stricter rule applies here
precisely because there is no column evidence at all to reason from.

---

## 7. Falsification

Stated before any code, as the prompt requires. Every number is the **oracle**
figure unless it says "live"; oracle numbers bound the architecture and live
numbers measure a model, and they are never interchangeable.

> **The verdict is §7.10.** Conditions 1, 3, 4 and 7 hold; 2, 5 and 6 trip.
> §7.10 separates the two trips that are instrument defects from the one that is
> an absent measurement, and concludes that **§7 does not close** and stage 4
> should not yet be put — on condition 6 alone, which is the only condition in
> the set that runs a live model on a real family and is the only one with no
> reading. §7.10 also proposes three conditions to the research owner beside the
> originals, one of which the change does not currently pass.

> **Every figure below was re-derived 2026-08-23** against
> `tools/oracle_ceiling.py` and `tools/assembly_ceiling.py` as prompt 07
> repaired them and as §12.5's boundary fix left them. The *questions* are the
> ones this section was written with and are unchanged; only the numbers were
> wrong, and §12.5 records what they were and why. Every command that produces
> one is in §7.5.

### 7.1 What must be true

The "expect" column is derived from the ceiling measurements §1.2 argued from,
re-measured against the repaired instruments, and is a prediction, not a
measurement of the unbuilt thing. The "stop" column is the part that binds.

| # | Instrument | Expect | **Stop if** |
| --- | --- | --- | --- |
| 1 | oracle assembly ceiling, Polynesian, width 5 | top-1 **≥ 44/46**, the measured node-local assembly ceiling | **top-1 < 33/46** — no better than the context-sensitive branch-cascade oracle, so the change bought nothing an `--oracle contextual` flag would not have shown |
| 2 | oracle, reachability | `assembly_beam_exact` **≥ 40/46**, matching *both* branch-cascade oracles, with 44/46 the node-local ceiling it could reach | **< 40/46** — below what both branch-cascade oracles reach, meaning the architecture can produce *fewer* correct answers than before. This is the prompt's beam-exact stop condition in the new architecture's terms |
| 3 | `cross_branch_assembly_rate`, oracle | **> 0 at some node**, and `1212`, `1217`, `1408`, `1439`, `1443` convert to top-1 hits | **= 0 at every node** — the mixing mechanism never fired, so whatever moved was not this |
| 4 | oracle graded | mean top NED **≤ 0.080** | **> 0.097** — worse than the context-sensitive branch-cascade top-1 it replaces |
| 5 | `score-synthetic` on `synthetic_hard`, 5 seeds | rule precision not lower and `misdirected_rule_count` not higher than the same seeds under the rule commit shape | either worsens — **right forms via worse-attributed changes is a worse result, not a better one** |
| 6 | `run-benchmark --seeds 5`, live, both benchmarks | top-1 up with non-overlapping spread | spreads overlap — one seed is not evidence and neither is five that disagree |
| 7 | suite | green at every stage | any stage leaves it red |

Condition 3 is the mechanism check and is the one that cannot be satisfied by
accident. Conditions 1 and 2 together are the shape check: **top-1 up and
reachability not down**, which is the same shape the branch-support change had
and the same shape `test_oracle_ceiling_regression.py` asserts the gap for.

**Condition 2 changed shape, not question.** It read "≥ 41/46", set one above a
then-measured 41; both oracles now report beam-exact **40/46**, so as phrased it
was unsatisfiable. The question it asks — *can the new architecture produce
fewer correct answers than the old one?* — is unchanged, and the honest form of
it is "not below 40", with expect and stop adjacent because "reachability not
down" is exactly a floor. It is not a demanding condition and was never meant to
be; condition 1 is where the demand lives.

**Condition 4's 0.080 is kept deliberately.** It was never derived from the
stale instrument: it was set as a target *below* the context-sensitive oracle's
mean top NED, which was then 0.110 and is now **0.097**. The stop threshold moves
with the measure, the target does not, and 0.080 stays a real improvement over
what assembly replaces. For scale, the same oracle's mean *beam-best* NED is
0.024, which is roughly where a mechanism that removes the whole-string selection
step should be heading.

### 7.2 What would show this was the wrong change

Three specific outcomes, each of which should stop the work rather than prompt a
patch:

- **`cross_branch_assembly_rate` is ~0 everywhere while top-1 rises.** The gain
  came from removing the whole-string selection step, which could have been had
  by fixing `traversal/beam.py` at a fraction of the cost and without touching
  the trajectory schema. If this happens, the right change is a selection fix
  and this design should be abandoned in favour of one.

  One caution before that verdict is reached: a rate of 0 is also the signature
  of the survey and the assembler seeing different columns, which has now
  happened twice — §12.3's beam-candidate mismatch and §12.5's stripped
  boundaries. **Suspect the instrument before the mechanism**, and check that a
  complete inventory still leaves `unaccounted_column_rate` near its floor.

- **`unaccounted_column_rate` above ~0.3 at most nodes under the oracle**, *read
  against the family's floor*. The correspondence sets would then not cover the
  evidence, the alignment would be doing more work than the inventory, and the
  committed object would be a fiction over a residue policy.

  **The floor is not zero and has to be subtracted first.** On Polynesian, with a
  proto-phoneme committed for **every one of the 246 sets the survey returns**,
  the rate is **0.125** — 42 unaccounted columns of 336, in 11 of 46 concepts,
  and all 11 carry more than one cognate set. That is the alignment/cognacy limit
  §12.4 quantifies: `summarize_correspondences` aligns per `(concept, cognate
  set)` while the assembler aligns whatever candidates the children's beams offer,
  because a beam candidate carries no cognate-set identity. So on this family the
  threshold has about **0.18 of headroom, not 0.3**, and on another family the
  floor must be re-measured the same way before the threshold means anything —
  commit every set the survey returns, read `unaccounted_column_rate`, and compare
  the live rate against *that*.

- **`alignment_overrides` correlates with accuracy across live seeds, or
  `override_singleton_sets_created` dominates.** The model is fitting the
  alignment to the answer and §6.1's constraints are not holding — the first
  says the lever is buying accuracy rather than repairing alignments, the second
  says it is routing around the join-a-set check through `new_set` mode. The
  remedy is, in order: tighten the `system_prompt.md` wording; reinstate the hard cap
  §6.1 declines to ship; and failing both, drop `realign` and accept SCA's
  alignments at the cost of `1217`-shaped concepts.

### 7.3 What is *not* evidence

- Top-1 rising on one seed. `run-benchmark --seeds N` exists for this.
- Any number from `tools/` whose `measuring:` line was not read.
- Any correspondence-set count or assembly ceiling quoted without the flags that
  produced it. The same benchmark gives 216 or 246 sets depending on `--reading`
  and `--boundaries`, and 38/46 or 44/46 node-local depending on `--boundaries`
  alone. A figure whose reading is not stated cannot be compared to anything.
- The `synthetic_hard` oracle figure as currently published (§0.5).
- Beam-exact under the new architecture compared against beam-exact under the
  old one without saying that the two beams contain different kinds of thing.

### 7.4 Which concepts condition 3 names, and why those five

Condition 3's list is the concepts that are simultaneously **(a)** unreachable
from any single branch under a context-sensitive oracle and **(b)** reachable by
assembly. Both halves moved when the instruments were repaired, so both are
re-derived here rather than quoted.

**(a), from `tools/branch_recoverability.py`.** The script gained `--method`,
because the figure §0.4 quotes for this was produced by an ad-hoc script that is
not in the repository, and a threshold nothing can reproduce is not a threshold.
`map` applies a best segment map by lookup and is the original measure; `cascade`
builds the branch's real ordered rule set and runs it through `RuleEngine`.

| | reachable from one branch | needs mixing | reachable from none |
| --- | --- | --- | --- |
| `--method map` | 37/46 | 8 — `1028`, `1212`, `1217`, `1221`, `1408`, `1439`, `1443`, `646` | 1 — `778` |
| `--method cascade --oracle context_free` | 39/46 | 6 — `1212`, `1217`, `1221`, `1408`, `1439`, `646` | 1 — `778` |
| **`--method cascade --oracle contextual`** | **40/46** | **5 — `1212`, `1217`, `1408`, `1439`, `1443`** | 1 — `778` |

The contextual row reproduces §0.4 exactly, including its five concepts. The
context-free cascade row comes out one concept above the 38 §0.4 records, which
is prompt 07's repairs showing through; §0.4's figures were taken before them.

**One thing the table must not be read as.** The contextual oracle is `>=` the
context-free one *per branch*, not per concept: `branch_rules` keeps whichever
cascade scores more exact forms on that branch as a whole, so a branch can lose a
concept while gaining others. That is why `1443` is on the contextual mixing list
and not on the context-free one, and why the lists are not nested.

**(b), from `tools/assembly_ceiling.py polynesian`.** Node-local assembly reaches
44/46 and cannot reach `1028` and `778`. So the intersection is all five of (a):

```
1212  1217  1408  1439  1443
```

**Two names dropped off the "cannot convert" side, and for different reasons.**

- **`1217` FATHER** is now reachable node-locally. The daughters carry two
  lexemes — `m a t u a` against `t a m a` — and the flat ten-way SCA alignment
  puts them in non-overlapping columns, which is why flat assembly still misses
  it. The bottom-up pass aligns the same material in smaller groups and gets it
  right, and node-local is the honest number because that is how assembly
  actually runs. It is the one case where node-local scores *above* flat.
- **`1443` WALK** became reachable when `tools/assembly_ceiling.py` was repaired;
  §1.2's four-concept flat-unreachable list is a pre-repair figure. It is on
  condition 3's list rather than off it.

**What is still not expected to convert**, and must not be built into a stop
condition: `1028` YAWN and `778` SMOKE. Neither is assemblable — gold `m a w a +
w a` wants a `w` no daughter shows anywhere, and `ʔ a h u + a f i` wants an `f`
that appears in no daughter — so a column restricted to attested reflexes cannot
produce them however good the analysis is. `778` is additionally unreachable from
every branch. A proto-phoneme genuinely need not be one of its reflexes, so a
model could still get them right; the *ceiling* cannot promise it.

### 7.5 Every command in this section

```bash
# conditions 1, 2 and 4: the assembly oracle itself
python tools/oracle_ceiling.py runs/benchmarks/polynesian.json --oracle assembly --json

# the stop thresholds those conditions quote, which are branch-cascade figures
python tools/oracle_ceiling.py runs/benchmarks/polynesian.json --oracle contextual --json
python tools/oracle_ceiling.py runs/benchmarks/polynesian.json --json

# conditions 1 and 3(b): the assembly ceiling, and what stripping boundaries cost
python tools/assembly_ceiling.py runs/benchmarks/polynesian.json --json
python tools/assembly_ceiling.py runs/benchmarks/polynesian.json --boundaries strip

# condition 3(a): which concepts no single branch reaches
python tools/branch_recoverability.py polynesian --method cascade --oracle contextual --json

# §7.2's floor: commit a value for every set the survey returns and read the rate
#   (no script; the recipe is in §12.5 and the figure is 0.125 on Polynesian)

# condition 5 and §7.10's d1 branch record: re-score a banked run
python -m cognate_reconstruction.cli score-synthetic \
  --answer-key runs/benchmarks/synthetic_hard.answer-key.json \
  --run-dir runs/sweeps/synthetic_hard-after-r2/seed-00
#   note the answer key is the *generated* artifact under runs/benchmarks/,
#   not benchmarks/synthetic/synthetic_hard.json, which is the definition and
#   fails validation with 42 errors if passed here.

# §7.10's commit rate and failure-mode split, and §7.11's replay corpus: no
# script — both are counts over runs/sweeps/*/seed-*/trajectories.jsonl. A node
# counts as committed when `committed_reconstruction` is non-null AND
# `completed` is true; a seed that did not attempt every internal node is
# excluded rather than averaged, which drops two of the five Polynesian after
# seeds. The replay itself is checked in as
# tests/workbench/test_directionality.py::
#   test_every_gap_bearing_polarize_the_model_wrote_is_accepted_now
```

Both ceiling tools accept `--gold-node`; on a multi-gold family the root's
binding is the default and anything else must be named. Read `measuring:` on
every line of output before quoting a number from it.

### 7.6 Whether condition 6 is evaluable on Polynesian

**This section decides nothing.** Condition 6 is not re-litigated here and no
threshold moves. What follows is the measurement-design finding that the live
half of §7 ran into, the arithmetic under it, and a recommendation for the
research owner. Everything is measured from the four sweep directories of
2026-08-24 under `runs/sweeps/`, which are gitignored; every figure below can be
re-derived from the `result.json` of the named seed.

#### The mechanism

`benchmarks/polynesian.json` binds gold at **one** of the tree's seven internal
nodes, `proto_polynesian`. `benchmarks/synthetic/synthetic_hard.json` binds gold
at **three** of four — `proto`, `west`, `east`.

A seed contributes a scoreable evaluation at a gold node only if that node
committed a real reconstruction. `benchmarks/sweep.py:270` excludes any
evaluation with `failure_fallback` set, and correctly: a fallback node's beam is
the harness's identity commit, so scoring it measures the fallback. On Polynesian
that means **one node of seven decides whether a seed produces any number at
all.**

Observed, per seed and per node:

| condition | seed | node | | top exact |
| --- | --- | --- | --- | --- |
| `polynesian-before` | 00 | `proto_polynesian` | committed | 0.500 |
| `polynesian-before` | 01 | `proto_polynesian` | committed | 0.413 |
| `polynesian-before` | 02 | `proto_polynesian` | **fallback** | 0.478 |
| `polynesian-after` | 00 | `proto_polynesian` | **fallback** | 0.543 |
| `polynesian-after` | 01 | — | stopped mid-flight, no `result.json` | — |

So `polynesian-before` yielded **two** scored seeds of three and
`polynesian-after` **none** of the two that ran. Six other nodes were
reconstructed in each of those seeds and none of them is scoreable, because
nothing is bound to them.

#### 1. The arithmetic

Four Polynesian seeds completed across the two conditions and **two lost the
root**, so the estimate of the rate at which a seed is scoreable is
`p = 1 − 2/4 = 0.50`; counting `polynesian-after` seed-01, which ran but was
stopped rather than failing, gives at best `p = 3/5 = 0.60`. Take the more
favourable one. Under a binomial with `p = 0.6`, for `N` seeds launched in one
condition:

| N | E[scored] | P(≥2) | P(≥3) | P(≥5) | P(≥3 in **both** conditions) | P(≥5 in **both**) |
| --- | --- | --- | --- | --- | --- | --- |
| 3 | 1.8 | 0.648 | 0.216 | 0.000 | **0.047** | 0.000 |
| 5 | 3.0 | 0.913 | 0.683 | 0.078 | 0.466 | 0.006 |
| 8 | 4.8 | 0.991 | 0.950 | 0.594 | 0.903 | 0.353 |
| 11 | 6.6 | 0.999 | 0.994 | 0.901 | 0.988 | 0.811 |
| 13 | 7.8 | 1.000 | 0.999 | 0.968 | 0.997 | **0.937** |

Condition 6 says `--seeds 5`. Read the table at the row that matters:

- At the **3 seeds per condition** the sweep actually ran, the probability of
  getting even three scored seeds on *both* sides was **0.047**. The sweep was
  about 95% likely to fail to produce a comparison, before the model was
  consulted at all. It did fail, and that is the expected outcome of the design
  rather than a result about the architecture.
- At the **5 seeds per condition** condition 6 asks for, P(five scored on both
  sides) is **0.006**.
- To get five scored seeds in both conditions nine times in ten needs **13 seeds
  per condition, 26 Polynesian runs**. A Polynesian seed took 49, 88, 56 and 49
  minutes in this sweep (mean 61), so that is about **26 hours** of serial
  LM Studio time for one line of one falsification table.

**And `p` itself is not known to one significant figure.** The 95%
Clopper–Pearson interval on a root-failure rate of 2 in 5 is **[0.053, 0.853]**,
so `p` is plausibly anywhere in [0.147, 0.947], and the seed count that follows
ranges from **6 to 60 per condition** — 12 to 120 runs, 12 to 122 hours. Five
seeds cannot pin down the rate that decides how many seeds are needed. Adding
seeds to learn the rate is the only way out of that circle, and it costs the same
hours.

#### 2. What is actually being estimated, which is the larger problem

Two findings from the same artifacts say that more seeds would not repair
condition 6 on this benchmark, only narrow the spread of a quantity that does not
mean what the condition assumes.

**(a) The excluded seeds are not missing at random, and they are not the bad
ones.** The two Polynesian roots that fell back scored **0.478** and **0.543**
top-exact; the two that committed scored **0.500** and **0.413**, mean 0.457. In
every observation available, the identity fallback scored at or above the model's
own mean. The same holds on `synthetic_hard`: `east` fell back in **6 of 6 seeds
in both conditions** and its identity beam scores **0.880** every time, which is
exactly the assembly oracle's own top-1 on that benchmark (22/25); `west`'s one
fallback scored 0.880 against a committed before-condition mean of 0.700.

The exclusion rule is right — scoring a fallback measures the fallback, not a
reconstruction. But its consequence is that condition 6 compares the two
instruction sets *on the subset of seeds where the model committed*, and drops,
unreported, both the rate at which each condition commits at all and the fact
that not committing scored better here. Four observations is far too few to
call that a bias with a direction, and it is more than enough to say the
quantity is not "top-1 accuracy of the architecture".

**(b) The pooled ± that condition 6 would be read against is mostly node
difficulty, not seed variance.** §7's live table quotes `synthetic_hard` as
0.448 ± 0.246 before against 0.720 ± 0.201 after, spreads overlapping. Split by
gold node, which is what a multi-gold benchmark makes possible:

| gold node | before | after | overlap? |
| --- | --- | --- | --- |
| `proto` | 0.280 ± 0.120, range **0.160–0.400**, n=3 | 0.547 ± 0.023, range **0.520–0.560**, n=3 | **no** |
| `west` | 0.700 ± 0.028, range **0.680–0.720**, n=2 | 0.893 ± 0.101, range **0.800–1.000**, n=3 | **no** |
| `east` | never scored — identity fallback in 3/3 | never scored — identity fallback in 3/3 | — |
| *pooled* | 0.448 ± 0.246 | 0.720 ± 0.201 | yes, heavily |

The pooled standard deviation is dominated by the 0.28-against-0.70 gap between
two nodes of different difficulty. Separated, both scored nodes showed
non-overlapping ranges in the direction condition 6 predicts — at n=2 and n=3,
which is why this was written as too weak to quote as satisfying the condition.

> **Superseded on 2026-08-25, and in the direction the caution predicted.**
> At 8 before-seeds and 5 after-seeds the ranges **stop being disjoint**:
> `proto` becomes 0.160–0.400 against 0.400–0.680, touching at a point, and
> `west` becomes 0.680–0.720 against 0.680–1.000, overlapping outright. The
> three-seed reading above was an artifact of three seeds, exactly as the
> paragraph it sits in warned. §7.7 has the re-run and the verdict; what
> survives from this sub-finding is only its second half.

What survives is the part that does not depend on n: pooling across gold nodes
destroys the very property the condition asks about, so condition 6 must be read
**per gold node** whatever else is decided.

#### 3. The options

- **A — more Polynesian seeds.** 26 runs (~26 h) for the point estimate, 12 to
  120 runs at the interval's edges. Buys a spread. Fixes neither (a) nor (b),
  because Polynesian has one gold node and cannot be read per-node.
- **B — define `hillburmish`.** `docs/benchmarks.md` records it as nine
  varieties plus Old Burmese, giving **two gold nodes in one tree**, which is
  the property Polynesian lacks. But it is a candidate, not a definition; the
  same document says which datasets carry a claim is a research-owner question;
  and a new family needs its own oracle ceiling and its own
  `unaccounted_column_rate` floor before any threshold applies to it (§7.2). It
  is the right long-term answer to the gold-binding problem and it delays
  condition 6 rather than enabling it.
- **C — read condition 6 on `synthetic_hard`, per gold node, and report
  Polynesian beside it without a verdict.** Costs one sweep of 10 runs (~3 h),
  uses the benchmark that degrades gracefully — every one of its six seeds
  produced at least one scoreable evaluation, against Polynesian's two of five —
  and is the only option under which the per-node reading in (b) is available at
  all. Its weakness is real and must be stated wherever the verdict is: it is a
  synthetic family, and condition 6 as written says "both benchmarks".
- **D — bind gold at more Polynesian nodes.** Ruled out, not recommended
  against: `walworthpolynesian` contains one proto variety, so there is no second
  gold node to bind. The option does not exist on this dataset.

#### The recommendation

**C, with the per-node reading from (b) made mandatory, and B raised separately
as the fix for the gold-binding problem rather than for this sweep.**

Concretely, for the research owner to accept or reject:

1. Condition 6's verdict is taken from `synthetic_hard`, at 5 seeds per
   condition, **reported per gold node and never pooled**. The reason is stated
   in the report: pooling mixes node difficulty into the spread, and on a
   single-gold benchmark the per-node reading is unavailable.
2. Polynesian is run at 5 seeds per condition and **reported, not scored**: the
   scoreable-seed count is published beside every number, and no verdict is
   taken from a line whose n is not stated. This is the "record the trip, put
   the argument in prose" treatment §7.3 already applies to condition 2.
3. Every condition-6 report also publishes, per node, **the rate at which that
   node committed at all** and **what the identity fallback scored there**.
   Finding (a) says those two numbers are not incidental to the comparison; on
   this data they were larger than the difference the condition is measuring.
4. `hillburmish` is proposed as a definition on its own merits, with its own
   ceiling and floor measured before anything is claimed from it — not as a
   substitute for step 1.

What this does **not** claim: that the architecture is better or worse. Nothing
in this section is a verdict on §7, and the live half of §7 stays unevaluated
until a sweep is run under a design the research owner has accepted.

#### One thing the re-run has to settle first

The sweeps of 2026-08-24 built their *before* condition as a **separate checkout
at the pre-stage-3 commit**. Tasks 1–3 of this prompt changed schemas both
conditions share, and one of them — the `AnomalyReport` descriptions — targets a
rejection class that is **13 of 20 pre-stage-3**. So re-running *before* in the
old checkout would compare the flip *and* three schema fixes, and re-running it
on the current tree with only the instructions reverted would isolate the flip.
The flip is exactly two surfaces, `agent/system_prompt.md` and
`COMMIT_REQUIREMENT_NOTES` in `agent/schemas.py` (`991bc16`), so the second
construction is small and well defined. It is also a measurement-design choice
and belongs with the decision above rather than under it.

### 7.7 The re-run of 2026-08-25, and what condition 6 does

Run after tasks 1–3 of prompt 10 landed and with the tree frozen: `synthetic_hard`,
**5 seeds per condition**, `google/gemma-4-26b-a4b`, temperature 1.0,
`top_k` 64 / `top_p` 0.95 / `repeat_penalty` 1.0, `--provider-seed-base 1000`,
`--max-tool-calls 48`, `--timeout 600`, uncapped `max_tokens`. Directories
`runs/sweeps/synthetic_hard-{before,after}-r2`.

**Polynesian was not re-run.** At the measured 61 minutes a seed it needs about
ten hours for five seeds per condition, against a five-hour budget for the whole
re-run, and §7.6's arithmetic says two or three seeds would produce nothing
evaluable. So **condition 6 has no real-data reading**, and this section is not
one. That is a gap in the evidence, not a result about the architecture.

The *before* condition is the pre-stage-3 checkout **unchanged**, verified rather
than assumed: its first seed records instruction hash `c4d25af1…` and
`configuration_sha256` `d93f3596…`, both byte-identical to the 2026-08-24 before
run. **Tasks 1–3 are therefore on the after side only**, which is stated again
wherever it matters below.

#### First, why the two before runs are poolable

The 2026-08-24 before run committed 2.67 ± 0.58 nodes a seed; the re-run, at the
identical `configuration_sha256`, committed **1.40 ± 0.55**. That looks like a
failed reproduction and is not one.

A fixed provider seed cannot reproduce a multi-turn run here. The provider
generates the `call_id` on every tool call and the harness echoes it back into
the next prompt as the tool message's `tool_call_id`, so from turn 1 onward the
context carries a random nine-digit number that differs between runs. Measured on
all three shared seeds: **turn 0 is identical** — same tool, same arguments, the
seed doing its job — and **turn 1 already diverges**, on seed 0 from `polarize`
to `get_alignments`. Divergence is structural, not drift, and not LM Studio's
panel.

The consequence is worth stating plainly because it changes how any two sweeps
are compared: `--provider-seed-base` buys **independent** samples, never
**reproducible** ones, and an identical `configuration_sha256` never implies an
identical trajectory. So the two before runs are eight independent draws from one
configuration and are pooled below; the two after runs are **not** pooled,
because tasks 1 and 3 edited `system_prompt.md` and their instruction hashes
differ. The after column is the re-run alone.

#### Condition 6, per gold node

Top-1 exact at each gold node, with the rate at which that node produced a
scoreable reconstruction at all, and what the identity fallback scored there —
the three numbers §7.6's recommendation asks to be published together.

| gold node | before, 8 seeds | after, 5 seeds | condition 6 |
| --- | --- | --- | --- |
| `proto` | committed **4/8**, 0.290 ± 0.100, range 0.160–0.400 | committed **5/5**, 0.528 ± 0.100, range 0.400–0.680 | up; ranges **touch at 0.400** |
| `west` | committed **2/8**, 0.700 ± 0.028, range 0.680–0.720 | committed **5/5**, 0.816 ± 0.115, range 0.680–1.000 | up; ranges **overlap** |
| `east` | committed **1/8**, 0.880 (n=1) | committed **0/5**, never scored | no comparison exists |

Identity fallbacks at the same nodes: `proto` before 0.36, 0.44, 0.48; `west`
before 0.88; `east` 0.88 in every seed of both conditions.

**Condition 6 trips as written.** Its stop column is "spreads overlap", and at
`west` they overlap outright, at `proto` they meet at a point, and `east` cannot
be compared at all. Top-1 is up at both comparable nodes and that is not
sufficient for the condition as phrased. Recorded, not rewritten — the same
treatment §7.3 gives condition 2.

**The argument, in prose, and it is not a defence of the threshold.** The
quantity condition 6 compares is conditioned on the node having committed, and
the two conditions commit at very different rates: 4/8 and 2/8 against 5/5 and
5/5. The before column is therefore computed over the subset of runs that went
well, and the after column over all of them, so the two are not like for like and
the gap between them is the *smaller* of the two effects. §7.6's finding (a) is
visible directly here: at `proto`, the before condition's identity fallbacks
scored **0.36, 0.44 and 0.48 against its own committed mean of 0.290** — under
the pre-stage-3 instructions, committing at the root was worse than not
committing.

What is unambiguous is the quantity condition 6 does not measure:

| | before, 8 seeds | after, 5 seeds |
| --- | --- | --- |
| nodes committed / 4 | 1.875 ± 0.835, range 1–3 | **3.000 ± 0.000**, range 3–3 |
| protocol failures / seed | 16.0 (re-run), 9.3 (2026-08-24) | **8.4 ± 1.5** |
| tool calls / seed | 73.4 (re-run) | **48.0 ± 1.0** |

Every after seed committed three of four nodes with **zero variance**, and the
one node it never commits, `east`, is the node whose identity beam already scores
0.880 — the assembly oracle's own top-1 on this benchmark. Whether "reconstructs
the same three nodes every time" should be what condition 6 measures is a
research-owner question and is not settled here.

#### What the re-run says about tasks 1–3

Per seed, so the 3-seed and 5-seed runs can be read side by side. The after
columns differ from each other by tasks 1–3 and by nothing else.

| rejection class | before (8 seeds) | after, 2026-08-24 | after, re-run |
| --- | --- | --- | --- |
| `commitments[].confidence=missing` | 0.25 | **3.0** | **0.0** |
| every `anomalies[].*` class together | 3.1 | **3.3** | **0.0** |
| `rule-unsupported` | 2.9 | 0.0 | 0.0 |
| `validation-unresolved` | 1.6 | 0.0 | 0.0 |
| `validation-ambiguous` | 0.9 | 0.0 | 0.0 |
| `dsl-parse-error` | 0.25 | 0.0 | 0.0 |
| `missing-rule-rationale` | 1.25 | 3.3 | 3.0 |
| `missing-directionality-rationale` | 0.25 | 1.7 | **3.6** |

- **Task 1 is confirmed live.** `confidence=missing` went 3.0 a seed to **zero**
  across five seeds. Nothing else touches that field.
- **Task 3 is confirmed live, within the after condition.** Every anomaly class
  went 3.3 a seed to **zero** while the instruction flip was held constant, and
  the before condition — which does not carry task 3 — still shows 3.1 a seed.
- **Task 2 is verified, by replay rather than by re-run** — see §7.11, added
  2026-08-28. `correspondence[]=string_type` never appears on `synthetic_hard`;
  it was a Polynesian class and Polynesian was not re-run, so all 41 gap-bearing
  `polarize` calls across the eight banked Polynesian seeds were re-validated
  through the boundary the registry uses. All 8 that were refused at the time are
  accepted now. §7.11 argues why a replay is the better instrument here and what
  it does not cover.
- **§6.6's "the loop closes" replicates at five seeds.** The four rejection
  classes that the flip removes are 5.65 a seed before and **zero** after, in
  both after runs.

**And one thing got worse, which is the question §6.6 and §4.1 own.**
`missing-directionality-rationale` went 0.25 a seed before to **3.6** after,
while committed rules a seed went 2.2 to 32.6. The requirement is per claim and
the number of claims went up by an order of magnitude, so the counter rising is
the requirement working, not failing. Whether a per-commitment rationale is the
right shape when a node commits thirty sets rather than three rules is a research
question and **must not be answered by relaxing the requirement to make the
counter fall**.

> **Settled by the research owner, 2026-08-25: the per-set requirement stays.**
> Two reasons, and the second was not in the framing above. A commit carrying
> thirty claims cannot have its reasoning attributed by one summary, which is
> the audit property the requirement exists for. And the rationales are useful
> to a *user* doing post-hoc analysis, not only to the validator that checks
> their presence — a per-set justification is the only place a reader can find
> out why one correspondence was read the way it was, and the inventory shape
> is what makes that a per-phoneme record rather than a per-cascade one. The
> cost is real and now quantified — output tokens are essentially the whole of
> wall-clock time (§7.9) — and it is accepted rather than unmeasured.

Related and still unresolved: the after run made **7 directionality claims with
no `polarize` call at all**, which `inspect-run` reports and nothing gates.

#### What this section does not establish

- Nothing about real data. Polynesian was not run.
- Nothing about condition 6 on a benchmark whose gold binding supports it;
  §7.6's recommendation stands unexecuted.
- Nothing about the architecture's ceiling, which is oracle work and did not
  move. (Task 2 was still open when this section was written; §7.11 closes it.)

### 7.8 Condition 5, evaluated from the seeds already run

Condition 5 needed no new inference. `score-synthetic` reads a run directory's
`trajectories.jsonl`, so the 16 `synthetic_hard` seeds banked across 2026-08-24
and the 2026-08-25 re-run answer it directly. Both halves below are pooled over
**branch** records rather than over seeds, because a branch is the unit the
answer key scores and a seed contributes a different number of them under the
two commit shapes — which turns out to be most of the story.

| run | all scored branches | invertible branches only | non-invertible |
| --- | --- | --- | --- |
| before, 2026-08-24 (3 seeds) | 0.273 (n=10) | **0.390** (n=7) | 0.000 (n=3) |
| before, re-run (5 seeds) | 0.200 (n=7) | **0.233** (n=6) | 0.000 (n=1) |
| after, 2026-08-24 (3 seeds) | 0.204 (n=9) | **0.306** (n=6) | 0.000 (n=3) |
| after, re-run (5 seeds) | 0.167 (n=16) | **0.267** (n=10) | 0.000 (n=6) |

`misdirected_rule_count` is **0 in every one of the 16 seeds, under both commit
shapes.**

#### The verdict

**The `misdirected` half does not trip. The precision half trips as written**,
and is recorded rather than rewritten, as §7.3 does for condition 2 and §7.7 for
condition 6.

Condition 5's stop clause is "right forms via worse-attributed changes is a worse
result, not a better one". The evidence does not show worse attribution, and
three things explain the number.

**A merger cannot be scored, and a merger is the case this architecture exists
for.** `rule_precision` matches a committed child-to-parent rule against the
answer key's *inverse* rules. A non-invertible change — a merger or a deletion —
has no inverse, so `true_inverse_rules` is empty and a **correct** rule scores
zero. Measured on `west->d1`, whose true change is `b > p`, b merging into an
existing p: the model committed `p > b`, which is exactly right, and scored
**0.000**. Every non-invertible branch scores 0.000 in every run above, thirteen
of them in total.

The after condition commits at more nodes, so it lands on more of these
guaranteed zeros — six against one in the re-run pair. It is penalised for
attempting. §2.1's argument is that **a merger makes a branch cascade strictly
less expressive**; the metric is blind exactly where the change is supposed to
pay, which is a defect of the instrument and not a finding about the
architecture.

**Restricted to branches where precision is earnable at all**, the gap narrows to
roughly 0.32 before against 0.28 after, at n=13 and n=16 — small, and well inside
the noise of a statistic whose before-side per-seed spread is ±0.35 to ±0.43,
because the before condition commits so few rules that a branch scores 0.0 or
1.0 and little between.

**The scorer already says precision is a lower bound.** Its own note: precision
"match[es] rule spellings exactly and [is] a lower bound; `functional_recovery_rate`
per branch is the measurement that survives a different spelling of the same
change." That spelling-robust measure went **up** in both pairings —
0.728 → 0.800 and 0.743 → 0.776.

And the dominant residual miss is **shared by both shapes and is a conditioning
omission, not a misdirection**: both write `e > a` where the answer key has
`a > e / _ i`. The before condition got the environment right in one seed of
five, the after condition in none. Where both attempt the chain shift at
`proto->east`, the after condition matches `t > k` and `s > t` in **5 of 5
seeds** against the before condition's **1 of 5**.

#### One objection that does not hold, checked rather than assumed

The obvious defence — that scoring *derived* rules against an answer key of
*claimed* rules compares two different kinds of thing, per §7.3's last bullet —
is **wrong here**, and `synthesis/scoring.py` says why in `_branch_claims`:
deriving the cascade from the inventory is what *keeps* rule precision, rule
recall, functional recovery and `misdirected_rule_count` comparable across the
migration, which is why §4.3 requires the derivation. The comparison is
legitimate. What damages the number is the invertibility blindness and the
number of attempts, not the shape change.

#### What this leaves

The precision half of condition 5 is a **weak instrument across this migration**
and it trips. The two quantities shipped beside it that survive a change of
spelling — `misdirected_rule_count` and `functional_recovery_rate` — both point
the other way. Nothing here is a verdict on the architecture, and no threshold
moves; whether condition 5 should be read on invertible branches only is a
research-owner question and is deliberately not answered here.

### 7.9 What a sweep actually spends its time on

Measured from the event and trajectory artifacts of the 2026-08-24 and
2026-08-25 sweeps, `google/gemma-4-26b-a4b` under LM Studio. This exists because
"run five seeds on both benchmarks" is a scheduling decision as much as a
measurement one, and the intuitions about where the hours go were wrong.

**Wall-clock time is model inference, essentially entirely.** SCA alignment, the
rule engine and the assembler together are **0.1%** of a run; median tool
execution is 0.01 s. Nothing here is fixable by optimising the harness.

**And inference time is output tokens, not context.** Correlating per-turn
latency against per-turn usage:

| | corr(latency, input tokens) | corr(latency, output tokens) |
| --- | --- | --- |
| `polynesian-after` seed-00, 92 turns | +0.294 | **+0.971** |
| `synthetic_hard-after-r2` seed-00, 47 turns | +0.270 | **+0.992** |

Decode runs at a steady 33–39 tokens a second. A 31,000-token context costs
almost nothing per turn, which means **prefix caching is already working** and
the transcript growing is not the problem. This is the opposite of the natural
assumption and it inverts the tuning advice: shrinking context buys nothing,
shrinking generation buys everything.

**Three quarters of what is generated is never seen.** Median output is 813
tokens a turn on Polynesian; the visible content plus tool arguments is worth
roughly 55. About **77%** of generated tokens are reasoning that never enters the
transcript — consistent with the thinking-mode measurement the operator skill
records. Thinking is therefore about three quarters of the wall clock of every
run in this document.

**A fifth to two fifths of generation is spent on turns that produce nothing.**

| | tool calls | exact duplicates | rejected | generation on rejected turns |
| --- | --- | --- | --- | --- |
| `polynesian-after` (2 seeds) | 127 | 11 (9%) | **47 (37%)** | **40%** |
| `synthetic_hard-after-r2` (5) | 240 | 26 (11%) | 42 (18%) | 22% |
| `synthetic_hard-before-r2` (5) | 367 | 49 (13%) | 82 (22%) | 20% |

An "exact duplicate" is the same tool with byte-identical arguments, repeated
inside one node session — the answer is already in the transcript. A rejected
turn costs **more** generation than an accepted one, not less: 875 against 730
median tokens on Polynesian, and 749 against 268 on `synthetic_hard`. The model
reasons longer on the turns it gets wrong.

Because latency is output tokens, those shares are shares of the clock directly.
On `polynesian-after` roughly **20 of every 49 minutes a seed** goes to calls the
harness refuses or has already answered.

**Failure is the expensive outcome, not the cheap one.** A node that commits
takes 2–9 minutes; a node that fails burns to its turn limit and returns nothing.
In `polynesian-after` seed-00 the three failed nodes cost 22.3 of 49.2 minutes
(45%); in `synthetic_hard-after-r2` seed-00 the single failing `east` cost 9.0 of
16.0 (56%). That is why the *before* condition is the slow one on an identical
benchmark — 40.8 minutes a seed against the after condition's 14.3 — despite
committing a third as many nodes.

#### What follows, and what does not

- **A rejection class removed is a speed-up as well as a quality fix.** After
  tasks 1–3, `synthetic_hard` went 17.6 to **14.3** minutes a seed and 21% to 18%
  rejected calls. Suggestive only — n=3 against n=5 and the ranges overlap
  (14.0–20.0 against 11.2–16.0) — but it is the direction the anatomy predicts.
- **Concurrency helps throughput, never latency.** The harness is strictly
  sequential inside a seed, so parallel slots speed up nothing unless separate
  seeds are launched as separate processes. And the headroom is not uniform: the
  slowest single turns already observed are 845 s, 717 s and 603 s against a
  600 s `--timeout`, all in the before condition, which already times out and
  retries. The after condition has 2.7× headroom on Polynesian and the before
  condition has none, so a concurrency slowdown would convert commits into
  failures — the expensive outcome, and a corrupted measurement.
- **KV-cache quantization attacks the wrong term.** The bottleneck is streaming
  weights per decoded token, not the cache, and prefill is already nearly free.
  It also changes numerics and is invisible to `configuration_sha256`, so it
  would make new seeds non-comparable with the sixteen already banked.
- **What is not established:** whether thinking mode *causes* the duplicate and
  rejected calls or merely multiplies their cost. That needs a paired run with
  thinking disabled, which would not be comparable with anything measured here
  and has not been done.

### 7.10 What §7 amounts to, and whether it closes

*Written 2026-08-28. Every oracle figure in this subsection was re-measured in
this checkout with the §7.5 commands rather than quoted from §7.6–§7.9; where a
re-measurement disagrees with an earlier reading, the re-measurement is the one
recorded and the disagreement is named.*

Three of seven conditions trip — 2, 5 and 6 — and §7.6–§7.9 argue all three in
prose. **That pattern is exactly what a falsification section looks like when it
is being read by someone who has decided the answer**, and it should be treated
as suspicious until it survives being taken apart. This subsection takes it
apart, and the answer is not uniform: two of the three arguments hold and the
third is not an argument at all.

#### The conditions sort by what they measure, and the sort is perfect

Ignore which conditions passed and group §7.1's table by what kind of quantity
each one reads:

| | conditions | outcome |
| --- | --- | --- |
| **absolute** — a property of the new architecture, read without reference to the old commit shape | 1, 3, 4, 7 | all four hold |
| **comparative** — the new architecture scored on a measure whose definition comes from the thing it replaces | 2, 5, 6 | all three trip |

Not one absolute condition trips. Not one comparative condition holds. That is a
property of §7.1 as drafted and is visible before any number is quoted.

Two readings fit it. Either **(a)** the architecture is worse and only comparison
reveals it, or **(b)** the comparisons are made with instruments defined by the
thing being replaced. These are distinguishable: under (a) the absolute measures
would also be poor. Re-measured today they are not — condition 4 beats its
target by a factor of two and a half, condition 3 fires at seven nodes, and
condition 1 clears its stop by six concepts. So (b).

**(b) is not a blanket excuse, and using it as one is the failure this section
exists to catch.** The three trips are not the same kind of thing, and filing
them together is what makes the pattern look like motivated reasoning. Taken one
at a time:

#### Condition 2 is badly posed, and §7 said so before any code was written

Re-measured 2026-08-28, all three oracles, Polynesian, width 5:

| oracle | beam-exact | top-1 | selection gap | mean top NED |
| --- | --- | --- | --- | --- |
| context-free cascade | **40/46** | 27/46 | 0.283 | 0.147 |
| context-sensitive cascade | **40/46** | 33/46 | 0.152 | 0.097 |
| **assembly** | **39/46** | **39/46** | **0.000** | **0.031** |

Condition 2 stops if `assembly_beam_exact < 40/46`. It is 39. **It trips by one
concept.**

For the assembly oracle, beam-exact and top-1 are *the same number*, and not by
coincidence: there is no selection step between them to fail at. Removing that
step is what §1.3 says the change is for. Both branch cascades reach 40 in a beam
and then lose seven or thirteen concepts choosing from it; assembly reaches 39
and loses none. So condition 2 stops the work for **not carrying four wrong
answers beside the right one**, while the quantity a user actually receives goes
33 → 39 against the better cascade and 27 → 39 against the other.

This is not hindsight. §7.3's last bullet — written before stage 0, in the list
of things that are *not evidence* — says: beam-exact under the new architecture
compared against beam-exact under the old one, without saying that the two beams
contain different kinds of thing, is not evidence. §7.1 asks for precisely that
comparison. **§7 contradicts itself, and §7.3 is the half that was right.**

The honest residue: 39 < 40 means there is one concept a cascade beam reaches
and assembly does not, so condition 2's underlying question — *can the new
architecture produce fewer correct answers?* — is answered "yes, by one" if
"produce" means "have somewhere among five candidates", and "no, by six" if it
means "return". Only the second is a thing anyone receives.

#### Condition 5's precision half is a blind instrument, and the scorer's own code proves it

Verified rather than accepted. Re-scoring `synthetic_hard-after-r2/seed-00`
against its answer key returns this branch record:

```
d1  invertible=False  true_inverse_rules=[]  committed_rules=['p > b']
    rule_precision=0.0   rule_recall=None   functional_recovery_rate=0.8
```

The true change on `d1` is `b > p`, `b` merging into an existing `p`. `p > b` is
the correct child-to-parent rule, and it recovers 80% of the branch
functionally. `rule_precision` scores it **0.0**.

§7.8 states this as "a merger cannot be scored". The sharper form, and the one
that settles it, is four lines of `synthesis/scoring.py`: `recall` returns
`None` when `true_inverse_rules` is empty; `precision` returns `0.0`. **The
scorer already knows how to abstain on a non-invertible branch. `precision` is
the one metric that does not.** That is a defect in the instrument, visible in
the code, not an interpretation of a number.

A selection effect sits on top of it. `precision` is `None` when a branch commits
nothing, so branches with no commitment drop out of the mean entirely, while a
condition that commits more lands on more of the guaranteed zeros. The after
condition is penalised for attempting.

And condition 5's stop clause is about **worse attribution** — "right forms via
worse-attributed changes". Nothing in the evidence shows worse attribution: the
two quantities shipped beside precision that survive a change of spelling both
point the other way, `misdirected_rule_count` at 0 in all sixteen seeds and
`functional_recovery_rate` up in both pairings. The half that trips is blind
exactly where §2.1 says the architecture pays.

#### Condition 6 is not disposed of, and it is not the same kind of thing

Conditions 2 and 5 are **demonstrations that an instrument is invalid**. Both are
checkable in this checkout, and one of them was pre-registered in §7.3. Condition
6 is different in kind and filing it alongside them is what makes §7 look like
special pleading.

- It has **no real-data reading at all.** Polynesian was never re-run. §7.7 says
  this itself, in its own words: a gap in the evidence, not a result about the
  architecture.
- Its `synthetic_hard` reading is confounded, because the before column is a mean
  over the runs that committed — 4/8 and 2/8 — and the after column a mean over
  5/5 and 5/5.
- That confound was **not predicted**. It was found after the numbers came in.

So condition 6 is not a trip that has been explained. It is a measurement that
was not made, plus a reason the substitute for it does not read. §7.7 already
labelled it honestly; what this subsection adds is that it must not be counted as
the third member of a set of three disposals. There are two disposals and one
IOU.

#### Does §7 close? No — and on exactly one thing

- Conditions **1, 3, 4 and 7 hold** on re-measurement. Condition 3, the mechanism
  check and the one §7.1 says cannot be satisfied by accident, fires at **all
  seven internal nodes** with a mean `cross_branch_assembly_rate` of **0.957**;
  §7.2's first abandon-the-design trigger — the rate ~0 everywhere while top-1
  rises, which would say the gain was really a selection fix — is not close to
  firing. Condition 1 is **39/46**,
  five below its 44/46 expect and six clear of its 33/46 stop; §7.13 accounts
  for those five and finds them morphological, and finds the expect itself
  unreachable by any inventory. Condition 4 is
  **0.031** against a target of 0.080 and a stop of 0.097. `mean_unaccounted_
  column_rate` is **0.0** under the oracle, against §7.2's 0.125 floor.
- Condition **2** is disposed of, by §7's own pre-registered rule.
- Condition **5**'s precision half is disposed of, by a defect provable in the
  scorer.
- Condition **6 is open.**

And condition 6 being the open one is worse than it sounds, because of what the
rest of the set is made of. Conditions 1, 2, 3 and 4 are **oracle** measures and
bound the architecture without a model in the loop; condition 7 is the suite.
Only 5 and 6 run a live model, and **only condition 6 runs one on real data.**

> **§7 therefore has no evidence from a live model on a real family.** The
> architecture is not falsified — nothing that trips survives inspection as a
> falsification — but the one condition that asks the live question where it
> matters has never been evaluated.

**Recommendation: stage 4 should not be put to the research owner on this
evidence.** Not because a condition trips; the trips are handled. Because
condition 6 has no real-data reading and stage 4 deletes the path that reading
would be compared against — deleting the branch-cascade commit path is the act
that makes the comparison unrepeatable, so it is the wrong thing to do while the
comparison is outstanding.

**And a Polynesian sweep will not close condition 6.** This has to be said
plainly, because "run Polynesian and close it" is the natural next move and
§7.6 already ruled it out. §7.6's option A — more Polynesian seeds — buys a
spread and "fixes neither (a) nor (b), because Polynesian has one gold node and
cannot be read per-node". §7.6's recommendation is that condition 6's **verdict**
is taken from `synthetic_hard`, per gold node, at 5 seeds per condition — which
**§7.7 did**, and condition 6 tripped there — while **Polynesian is run at 5
seeds per condition and *reported, not scored***, with the scoreable-seed count
published beside every number. So a Polynesian sweep discharges step 2 of that
recommendation and produces a report; it cannot produce a verdict on a
single-gold family, and no number of seeds changes that.

What would make condition 6 answerable on real data is §7.6's **option B**, a
family with two gold nodes in one tree — and §7.6 says option B "delays
condition 6 rather than enabling it", because a new family needs its own oracle
ceiling and its own `unaccounted_column_rate` floor (§7.2) before any threshold
applies to it. **Condition 6 is therefore not merely unmeasured; on the datasets
this repository has, it is unmeasurable in verdict-bearing form.** That is a
finding about §7's design, not about the architecture, and it is the strongest
reason to treat "§7 does not close" as a statement about the falsification set
rather than a hesitation about the change.

#### The condition §7 never asked, and what it actually says

§7 measures accuracy **conditioned on committing**, and never the commit rate
itself. Whether a node gets reconstructed at all is the quantity every other
condition is conditioned on — and it is what broke condition 6.

Measured in this checkout, 2026-08-28, over the banked seeds:

| | before | after |
| --- | --- | --- |
| `synthetic_hard`, nodes committed of 4 | 1.875 ± 0.835 (8 seeds), range 1–3 | **3.000 ± 0.000** (8 seeds), range 3–3 |
| `polynesian`, nodes committed of 7, complete seeds only | 4.33 ± 0.58 (n=3), range 4–5 | **4.00 ± 1.00** (n=3), range 3–5 |

On `synthetic_hard` the effect is large and has **zero variance in both after
runs independently**. That matters for attribution in a way §7.7 could not manage
for its other figures: the two after runs differ by tasks 1–3 and by nothing
else, and both give exactly 3.000 ± 0.000, so **tasks 1–3 did not move this
number.** What moved it is what else changed, which is the instruction flip.

**On real data it does not replicate.** Polynesian is flat, and the variance
roughly doubles. Two of the five after seeds did not attempt all seven nodes and
are excluded as incomparable — `polynesian-after/seed-01` attempted three and
`polynesian-after-gapbug/seed-02` attempted six. At n=3 a side this is not a
measurement, and the correction is worth stating plainly: **the commit-rate gain
is a `synthetic_hard` result and there is currently no evidence for it on a real
family.**

What *does* change on real data is the **failure mode**, and it inverts:

| polynesian | `AgentLoopLimitError` | `ProtocolStallError` |
| --- | --- | --- |
| before (3 seeds) | 6 | 2 |
| after (5 seeds) | **0** | **13** |

Under the inventory commit shape on real data, nodes stop running out of turns
and start being killed by the stall detector. Six of the thirteen are the
repeated-signature rule and seven the rejected-window rule. **A check that
`verify_commitments` now batches appears in nine of the thirteen** (§7.11), and
§7.12 measures how far that accounts for them. Whether batching converts any of
these into commits cannot be established without a sweep.

#### Three conditions proposed to the research owner, beside the originals

**Proposals, not amendments.** None of these replaces anything in §7.1, no
threshold in §7.1 moves, and nothing below was chosen by looking at whether the
change passes it — the third one it does not.

- **2′, beside 2.** *Assembly top-1 ≥ the better branch-cascade oracle's top-1.*
  Stop if assembly top-1 **< 33/46**. It asks condition 2's own question — can
  the new architecture produce fewer correct answers? — of the quantity that
  ships, rather than of a beam the new architecture deliberately does not build.
  Currently **39 against 33**. Condition 2 stays as written and stays tripped.
- **5′, beside 5.** *Read rule precision over invertible branches only, and
  publish the non-invertible branch count beside it* — or, better, repair
  `precision` to abstain on an empty `true_inverse_rules` the way `recall`
  already does. This is a change to an instrument, not to a threshold, and §7.8
  had already flagged it as a research-owner question rather than answering it.
- **8, new.** *Commit rate on both benchmarks, with the failure-mode split
  published beside it.* Stop if the after condition commits at a lower rate than
  the before condition on a real family. Report, never a gate — nothing may
  filter a trajectory on it.

  **As measured today this proposed condition sits at or just under its own stop
  on Polynesian: 4.00 ± 1.00 after against 4.33 ± 0.58 before.** That is the
  reason to add it. A falsification section whose newly proposed conditions all
  pass is the failure this section was written to prevent, and condition 8 is the
  only one of the three that the change does not currently clear.

#### What this subsection does not establish

- **Nothing live.** No inference was run. Every figure here is either an oracle
  measurement, a re-scoring of banked trajectories, or a count over banked
  artifacts.
- **Nothing about whether §7.11's batching converts a stalled node into a
  committed one.** It addresses three of thirteen observed stalls by
  construction; the effect on a run is unmeasured.
- **Nothing about condition 6.** It remains the open item and the reason §7 does
  not close. §7.6's recommendation is *half* executed: step 1, the
  `synthetic_hard` per-gold-node verdict at 5 seeds, is §7.7 and it tripped;
  step 2, Polynesian run at 5 seeds and reported rather than scored, has not
  been run. Discharging step 2 is worth doing and will not close the condition.

### 7.11 The two protocol items, closed 2026-08-28

Both are rejection-class work, both were measured against the banked seeds, and
neither needed inference. Read them with §7.9's cost anatomy: a rejection class
removed is a speed-up as well as a quality fix, and a *failed node* is the
expensive outcome.

#### Task 2, verified — and what a replay is and is not evidence for

Task 2 widened `PolarizeArgs.correspondence` to the writing vocabulary
`CorrespondenceCommitment.reflexes` already accepted. It shipped with unit tests
and was never confirmed against real model output, because the class it removes
(`schema:correspondence[]=string_type`) occurs on Polynesian and effectively
never on `synthetic_hard`.

**Replayed rather than re-run.** Every gap-bearing `polarize` call the model made
across the eight banked Polynesian seeds was re-validated through the boundary
`registry.execute` uses — `model_validate_json`, since `WorkbenchModel` is
`strict=True` and a JSON list does not coerce to a `tuple[...]` field in strict
python mode. Measured 2026-08-28:

| | polarize calls | gap-bearing | refused then | accepted now |
| --- | --- | --- | --- | --- |
| `polynesian-after` (2 seeds) | 23 | 12 | 5 `=string_type` | 12/12 |
| `polynesian-after-gapbug` (3) | 38 | 11 | 2 `=string_type` | 11/11 |
| `polynesian-before` (3) | 51 | 18 | 1 `=string_too_short` | 18/18 |
| **total** | **112** | **41** | **8** | **41/41** |
| `synthetic_hard` (16 seeds) | 83 | 7 (8.4%) | 0 | 7/7 |

The gap-bearing share is **37% on Polynesian against 8.4% on `synthetic_hard`**,
which is why the class is invisible on the synthetic benchmark. The five
`=string_type` refusals in `polynesian-after` are the same five the
`PolarizeArgs` docstring cites.

**A replay is adequate evidence for this class, and a live run is not better.**
Three distinct questions have to be kept apart:

1. *Does the harness accept and correctly answer each gap spelling?* Answered by
   `test_a_survey_row_carrying_a_gap_can_be_pasted_straight_into_polarize`,
   deterministically, over all six spellings, asserting `columns_matched` and not
   merely acceptance. Already covered before this session.
2. *Do the spellings a model actually emits fall inside that accepted set?*
   Answered only by the replay. This is the residual risk task 2 carried, and no
   unit test can ask it because the input has to come from a model.
3. *Does the class disappear from a live run's counts?* Answered only by a sweep.

For (2) the replay is **strictly better evidence than a live run**, because §7.7
established that a fixed `--provider-seed-base` cannot reproduce a multi-turn
run: the provider mints a fresh `call_id` on every tool call and the harness
echoes it into the next prompt, so turn 1 already diverges. A live re-run would
never re-present these 41 calls. It would draw different ones and answer (3),
weakly, at roughly ten hours for five seeds.

**What the replay does not establish**, stated because a closed corpus always
flatters itself: it says nothing about a spelling the model has not yet written.
Of the six accepted spellings the model exercised **four** — JSON `null`,
`"null"`, `"Ø"` and `""` — and `"∅"` and `"None"` are accepted on the strength of
the unit test alone, never observed. That is the point of widening rather than a
hole in it, but it means the corpus is evidence of coverage so far and not of
coverage in general.

Recorded as
`test_every_gap_bearing_polarize_the_model_wrote_is_accepted_now`, which skips
cleanly when `runs/sweeps` is absent and asserts the corpus still contains a
historically gap-refused call so that it cannot pass vacuously.

> **Narrowed 2026-08-29, by new live data.** The test first asserted that every
> gap-bearing call is *accepted*. §7.14's run added a call the model wrote as
> two `child_ids` against three `correspondence` entries — an arity mistake,
> correctly refused then and now, and nothing to do with gap spelling — and the
> over-broad assertion failed on it. It now asserts the narrower true thing:
> **no call is refused because of how its gap was spelled.** A replay corpus
> that grows is a test that gets re-examined, which is the point of checking it
> in rather than leaving it in a transcript.

#### `correspondence-reflex-mismatch`: the check was right and the reporting lost a node

Seven occurrences, and the shape of them was not what the class name suggests.
**All seven are one seed** (`polynesian-after/seed-00`) and **all seven are
`test_proto_assembly`**, never `commit_reconstruction` — the model was testing,
which is the workflow §6.6 asks for, and the gate caught it at the cheap point.

Six of the seven are a single systematic error: the model drops a leading or
trailing gap from the reflex row and repeats a neighbouring segment to keep the
length.

| written | the set |
| --- | --- |
| `['a', 'a', 'a']` | `[None, 'a', 'a']` |
| `['t', 'k', 'k']` | `[None, 't', 'k']` |
| `['f', 'h', 'h']` | `[None, 'f', 'h']` |
| `['ʔ', None, None]` | `[None, 'ʔ', None]` |
| `['+', '+']` (×2) | `['+', None]` |
| `['t', 't']` | `['o', 'o']` |

The last row is the only genuine mis-citation — a row written for a set the model
had not read. The other six are positional, and the fourth of them shows the
model writing gaps perfectly well while still losing which *position* they belong
in, so "the model will not write a gap" is the wrong diagnosis.

**Neither sharpening the instruction nor softening the gate is the fix, and the
transcript rules both out.** `reflexes`' own field description already says to
include the children that show nothing and that a one-child set is
`['ʔ', null]` and never `['ʔ']`. The rejection message already prints the correct
tuple verbatim — *that set is `[None, 'a', 'a']`*. There was no missing
information at either end.

What was missing was the **rest of the list**. On `nuclear_polynesian` the model
sent 19 commitments and `verify_commitments` raised on the first offender only:

| turn | rows wrong, of 19 | harness said |
| --- | --- | --- |
| 1 | 15 | `cs-08968e2078cb` is wrong |
| 2 | 9 | `cs-824774173e28` is wrong |
| 3 | 8 | `cs-88cb018807c3` is wrong |
| 4 | 8 | `cs-27d0ffaa5822` is wrong, and `ProtocolStallError` — *the model is not adapting to the tool contract* |

> **Correction, 2026-08-28.** An earlier version of this subsection said the
> model "fixed six of eight rows, then seven, then eight, and was killed on the
> turn it finally had every row right". That was read off the first 8 of 19
> commitments and is wrong. The model never converged: at the fatal turn 10
> rows were right, 8 were still wrong, and 1 cited a set no survey in the
> transcript returned. What is true, and is the actual argument, is in §7.12:
> **every set the harness named and gave the model a turn to fix, the model
> fixed — 21 of 21 across the whole after condition.** The 7 rows still wrong
> at the end were rows the harness had never named.

The stall signature is `(tool name, error code)`, which cannot tell *the same
mistake on a new set* from *the same mistake again*. The model was adapting,
visibly and monotonically, and the run was killed on the turn it finally had
every row right. Per §7.9 that is the expensive outcome: a failed node burns to
its limit and returns nothing.

The control is inside the same session. Pydantic reports **all** of its errors at
once on the same call, and on this node the model cleared all nineteen
`commitments[].confidence=missing` errors **in a single turn**. Serial reporting
took four turns and lost the node; batch reporting took one.

So `verify_commitments` now scans every commitment and reports every failure of a
class together. **No threshold moves and no check loosens** — each of the eight
rows is still refused, and the blind-citation case the gate exists for is still
caught. The single-failure message is unchanged, which matters because three of
the four live nodes that hit this check had exactly one bad row and recovered on
the next call.

**Not verified live.** Whether this converts `nuclear_polynesian` into a commit
needs a Polynesian sweep, which was not run. What can be said from the artifacts
is the bound §7.12 measures: a check this now batches appears in **9 of the 13**
`ProtocolStallError`s in the after condition's Polynesian seeds. In the three
killed by a repeated reflex-or-support signature it is the whole cause. In the
six window-saturation stalls it is one code among several, so batching reduces
the window's count without necessarily emptying it.

### 7.12 Is the stall detector killing models that are adapting?

*Measured 2026-08-28 over the 13 `ProtocolStallError`s in the five Polynesian
after-condition seeds. Banked artifacts only; no inference was run.*

§7.10 records that the failure mode inverts on real data: the before condition
runs out of turns, the after condition is killed by the stall detector, 13 times
against 2. Because a failed node returns nothing and is the most expensive
outcome (§7.9), this is the largest single lever on the real-data commit rate —
which is the one quantity where the migration currently shows no gain.

This subsection asks whether those 13 deaths are the detector doing its job.

#### What the detector actually keys on

Two rules, both in `AgentOrchestrator`:

- **Repeated signature.** The signature is `(tool name, error code)`. When it
  occurs `max_repeated_tool_failures` times inside a trailing window of
  `stall_window_calls`, the harness injects a correction; on a second saturation
  of the same signature it raises. The signature carries **no item identity**, so
  eight different commitments failing one check are indistinguishable from one
  commitment failing eight times.
- **Window saturation.** Protocol-category rejections in the trailing window,
  counted without regard to which codes they were. Exploratory rejections are
  excluded deliberately.

Both messages assert the same thing: *the model is not adapting to the tool
contract.* That assertion is testable against the transcripts, and it is mostly
false.

#### Test 1 — did the model fix what it was told about?

`verify_commitments` named exactly one offending set per rejection. The
harness's *own next verdict* says whether the model repaired it: if the next
rejection of that code names a different set, the named one is fixed; if it
names the same set again, it is not.

| | |
| --- | --- |
| consecutive named-set pairs | 14 |
| next rejection named a **different** set — repaired | **12 (86%)** |
| next rejection named the **same** set — not repaired | 2 |
| final rejection, no next turn | 11 |

**Twelve of fourteen.** The model repaired the set it was named most of the time,
and the two misses are recorded rather than smoothed: on
`after-gapbug/seed-02/nuclear_polynesian` it was told about `cs-08968e2078cb`
twice, and on `after-gapbug/seed-02/tahitic` it fixed one set and reintroduced an
earlier one.

> **Correction, 2026-08-28.** A first version of this table read **21 of 21**.
> It compared the model's next payload against a correspondence inventory
> rebuilt from the surveys in the transcript, and that inventory is not the one
> the harness commits against: `summarize_correspondences` can be called with a
> concept narrowing or a different overlay, so its `support` column is not the
> commit-time support. Sets whose support the model had copied from a narrowed
> survey therefore looked correct to the rebuilt inventory and were refused by
> the harness. The table above uses the harness's own verdicts and needs no
> reconstruction. **Prefer the harness's verdict to a re-derived one wherever
> both are available** — this is the third time in this document that a
> re-derived instrument has been the thing that was wrong.

The model's failure was still not an inability to read the contract. The harness
named one defect per turn while the payload carried up to eight defects of the
same kind, and the detector counted the turns.

#### Test 2 — the detector's own theory, applied to itself

"Not adapting" has a mechanical reading: the model re-sends a call the harness
already rejected. Comparing byte-identical arguments per node:

| | stalled nodes |
| --- | --- |
| changed the call after every rejection | **9 of 13** |
| re-sent a call that had already been rejected | **4 of 13** |

In **9 of the 13**, the model never once repeated a rejected call. The message
that ended those nodes states the opposite of what the transcript shows.

#### Where the detector was right, which matters

The counter-evidence is real and is not filed away. `tahitic` in
`after-gapbug/seed-01` sent the **byte-identical** `test_proto_assembly` call
three times after rejection. That is the behaviour the detector exists to catch,
and it caught it. Three other nodes repeated a rejected call once each.

So the detector is not broken in general. It is **blind to progress**, and on
this workload progress is the normal case: 9 of 13 changed every call, and the
one measure that tracks repair directly says 21 of 21.

#### One thing this does not say

It does not say the model would have committed. On `nuclear_polynesian` in
`after/seed-00` the defect count fell 15 → 9 → 8 → 8 out of 19 rows and then
stopped falling. The model was adapting and had **not** converged. §7.11 carries
a correction where it previously claimed otherwise.

What can be said is narrower and still strong: the reason it stopped falling is
that the remaining rows had never been named. Seven of the eight rows still
wrong at the fatal turn were rows the harness had not mentioned once. A model
cannot repair a defect it has not been shown, and its record on defects it *was*
shown is perfect.

#### Recommendation, for the research owner — not implemented

**The narrow fix is implemented. It is worth much less than this subsection's
first draft implied, and the measurement is below.**

`ToolInputError` and `ToolError` gained an optional `subject`: a sorted, hashed
digest of the offending `set_id`s, set by `verify_commitments` and read only by
the detector, whose signature is now `(tool, code, subject)`. `subject` carries
`exclude=True`, so the model's tool result and the trajectory are byte-identical
to before — checked, not assumed.

**Replayed against the 13 real stalls, it prevents one.** Each node's signature
sequence was rebuilt from its recorded payloads and run through both rules:

| | stalls |
| --- | --- |
| old rule `(tool, code)` | 13 of 13 |
| new rule `(tool, code, subject)` | **12 of 13** |

The one it prevents is `after/seed-00/nuclear_polynesian`, the node §7.11 is
about. `tahitic`, which sent a byte-identical call three times, **still stalls**,
which is the property that had to hold — both directions are pinned by
`test_a_model_repeating_itself_still_stalls` and
`test_a_different_offender_each_turn_does_not_stall`.

Why so little, stated plainly rather than explained away:

- **Six of the thirteen are window saturation**, which counts protocol
  rejections without regard to which they were. The signature change does not
  touch that rule at all, by construction.
- Of the seven repeated-signature stalls, two are
  `missing-directionality-rationale` and one is a schema rejection. None of
  those names a set, so none gets a subject, and their behaviour is deliberately
  unchanged.

So the honest verdict on the narrow fix: it is correct, it costs nothing, it
removes a demonstrated false positive, and **it is not the lever on the failure
rate that this subsection's first draft suggested.**

**The lever is window saturation.** Six of thirteen deaths come from a rule that
counts rejections and cannot see repair. **§7.15 implements the progress-aware
form**: a rejection naming fewer offenders than the fewest yet seen no longer
counts toward saturation. Replayed against the live run's two stalls it saves
the node that was repairing and still stops the one that was not.
**§7.14 is the live confirmation**: on the two seeds run after the batching
landed, both failed nodes died of window saturation and neither of the
repeated-signature rule.

**A caution about sequencing, which is the practical point.** A Polynesian sweep
run before this is decided measures the detector as much as the architecture,
because the detector ends 13 of 13 of the after condition's failed nodes and
9 of those 13 involve a check whose reporting changed on 2026-08-28. §7.6 already
holds that Polynesian cannot yield a verdict on condition 6. This is a second,
independent reason not to spend the ten hours yet.

#### Every command in this subsection

```bash
# both tests read only banked trajectories; no script is committed, because
# neither quantity can regress from a change to this repository's code — they
# are properties of runs already recorded.
#
# Test 1: for each rejection carrying "commitment 'cs-…'", look up that set_id
#   in the next test_proto_assembly / commit_reconstruction payload and compare
#   its reflexes (or support) against the survey the same transcript returned.
# Test 2: hash each tool call's arguments; a repeat is a hash already seen on a
#   call the harness rejected.
# Both iterate runs/sweeps/polynesian-after*/seed-*/trajectories.jsonl.
```

### 7.13 The five concepts condition 1 leaves on the table

*Measured 2026-08-28 with the §7.5 commands. Oracle work: no model was run.*

Condition 1 expects assembly top-1 **≥ 44/46**, the node-local assembly ceiling,
and stops below 33/46. It measures **39/46**. §7.10 records that it holds, being
six clear of its stop, and does not account for the five concepts between 39 and
44. This subsection accounts for them, because a gap in a *ceiling* is a bound on
the architecture that no model can beat and is worth knowing before stage 4.

#### The seven misses, and which five are the gap

`tools/oracle_ceiling.py --oracle assembly` prints its misses as reported against
gold:

| concept | reported | gold | reachable node-locally? |
| --- | --- | --- | --- |
| `1028` | `m a a w a + w a` | `m a w a + w a` | **no** |
| `778` | `a u ʔ a f i` | `ʔ a h u + a f i` | **no** |
| `1217` | `t a m a a + n a` | `t a m a + n a` | yes |
| `1239` | `p e + f e a a` | `p e + f e a` | yes |
| `670` | `a k a a` | `a k a` | yes |
| `671` | `ʔ o n o e` | `ʔ o n e` | yes |
| `1212` | `k m a + t o u` | `k i + m a + t o u` | yes |

`1028` and `778` are the two `tools/assembly_ceiling.py` already reports as
node-locally unreachable, and §7.4 records them as concepts the ceiling cannot
promise. Removing them leaves exactly **five**, which is the gap: 39 + 5 = 44.

**Four of the five are one segment too many, and it is always a vowel.**

#### What they have in common: the daughters carry different morphology

Reading the daughter forms for each of the five:

| concept | gold | segment-length spread across daughters | what differs |
| --- | --- | --- | --- |
| `670` | `a k a` (3) | 3, 8 | Māori and Rarotongan carry the compound `p a k i + a k a`; everyone else the simplex |
| `671` | `ʔ o n e` (4) | 3, 4, 7, 9 | Tongan and Samoan carry the **reduplicated** `ʔ o n e + ʔ o n e` |
| `1217` | `t a m a + n a` (7) | 4, 5, 6, 10 | different compounds entirely — `m a k u a + k aː n e` against `t a m a + i` |
| `1239` | `p e + f e a` (6) | 5, 6, 9, 10, 11 | every daughter has a boundary and they carry two or three morphemes, not the same two |
| `1212` | `k i + m a + t o u` (9) | 2, 3, 5, 6, 8, 11 | 30 daughter forms, 26 with boundaries — the multi-etymon case |

Every one of them is a **morphological** length mismatch: reduplication,
compounding, or extra derivational material in a subset of daughters. The
aligner aligns whole strings, so that extra material becomes its own column, and
a column is a correspondence set the inventory has to commit a value for.

#### Why the architecture cannot drop those columns, which is the real finding

The obvious repair is for the offending column to reconstruct nothing.
`CorrespondenceCommitment.proto_segment` allows exactly that — an explicit null
meaning "every branch showing material here innovated it" — and the oracle's own
`column_targets` prices a column emitting nothing at **0**, the same as a column
emitting an attested segment. So per concept, the right answer is available and
the oracle finds it.

**It cannot keep it.** `column_targets` is solved per concept; the committed
object is an inventory, and an inventory is *one value per correspondence set for
the whole node*. Where the morphologically-extra column's set also occurs in
concepts that legitimately reconstruct a vowel, the two demands collide and the
single committed value has to serve both. The vote goes to the segment, and the
concepts that wanted nothing emit a spurious vowel.

So the gap is **not** an aligner defect that better alignment would remove, and
it is not a defect of the oracle's search. It is the **price of generality**, and
it is the same property §4.1 makes the case for: an inventory is a claim about
the node rather than about a word. The conditioning that would resolve it is
morphological — *this set reconstructs nothing inside a reduplicant* — and
`RuleEnvironment` is evaluated in proto **phonological** terms, neighbouring
proto-phonemes and word edges, by design.

`mean_unaccounted_column_rate` is **0.000** under this oracle, which rules out
the competing explanation: nothing here is falling to a residue policy. Every
one of these columns *is* explained by a correspondence set. The set is simply
made to say one thing in a word where it should say another.

#### What this does and does not change

- **Condition 1's expect was never reachable by this architecture.** 44/46 is
  what free per-column choice reaches; 39/46 is what one value per set reaches.
  The two instruments are answering different questions, and §7.10's separation
  of absolute from comparative conditions does not catch this one, because both
  numbers are absolute. This is a third kind of mis-posing and it is recorded,
  not repaired: **no threshold moves here.**
- **It is a bound on the model too.** A live model committing an inventory cannot
  beat 39/46 on this family either, for the same reason. Any live top-1 above
  39/46 on Polynesian would mean the run was not committing a pure inventory.
- **It does not touch the case for the change.** The comparison that matters is
  against what assembly replaces, and the branch cascades reach 33/46 and 27/46
  top-1 on the same benchmark. Assembly's 39 is six and twelve concepts better
  while leaving five to morphology.

#### What is not established

The vote-collision mechanism follows from how the instrument is built — per
concept targets, one value per set — and from the fact that the residue rate is
zero, which leaves no other route for the segment to appear. **It was not
confirmed by exhibiting the colliding set and the concepts on each side of the
vote.** Doing that needs a per-set trace the tool does not currently print, and
it is the obvious next measurement if anyone wants to act on this rather than
know it.

### 7.14 The batched rejection, observed live

*Run 2026-08-28/29. Two Polynesian seeds, `google/gemma-4-26b-a4b`, temperature
1.0, `top_k` 64 / `top_p` 0.95 / `repeat_penalty` 1.0 sent explicitly,
`--provider-seed-base 1000`, `--max-turns 24`, `--max-tool-calls 48`,
`--timeout 600`, `max_tokens` uncapped. Directory
`runs/sweeps/polynesian-after-batched`. 97.6 minutes for the pair.*

#### What this run can and cannot answer, decided before it was launched

**It answers one question: does the batched rejection fire, and does the model
use it?** That is an observation about the current harness and needs no
baseline.

**It cannot answer whether stalls fell.** Two reasons, and both were settled
before the two hours were spent:

- **The seeds are not comparable to the banked ones.** Checked against
  `polynesian-after/seed-00` rather than assumed:

  | component | banked | this run |
  | --- | --- | --- |
  | the agent instructions | `e01d547f31b9` | `8aaa9c3a7218` |
  | the tool schemas | `9e5d226f2ac4` | `b5ceb9cb7367` |
  | the provider and limit settings | `a5403ff98746` | `a5403ff98746` |
  | the give-up thresholds | `68d2f586d4b6` | `68d2f586d4b6` |

  The banked Polynesian after-runs are from 2026-08-24; `system_prompt.md` has
  since taken tasks 1 and 3, and `PolarizeArgs` has since taken task 2. An
  outcome comparison would be confounded three ways.
- **Two seeds could not settle it even if they were comparable.** The measured
  effect of the signature change is 1 stall in 13, about 0.23 stalls a seed
  against a per-seed spread of ±1.00. At 80% power that is roughly **300 seeds
  an arm**. No outcome comparison is made below, and none should be read into
  the numbers that are reported.

#### The batching fired, and the model cleared thirteen rows in one turn

`nuclear_polynesian` in seed 0 produced the shape the fix was built for:

```
13 of 30 commitments fail this check, and every one of them is listed:
  - commitment 'cs-08968e2078cb' carries reflexes ['a', 'a', 'a'] but that set is [None, 'a', 'a']
  - commitment 'cs-fe2360e1a6c1' carries reflexes ['i', 'i', 'i'] but that set is [None, 'i', 'i']
  …
```

Comparing each mismatch rejection against the next one at that node:

| named | next names | cleared | still failing | newly surfaced |
| --- | --- | --- | --- | --- |
| **13** | 8 | **13** | **0** | 8 |
| 8 | 8 | 3 | 5 | 3 |

**All thirteen were repaired in a single turn.** Under the serial reporting
§7.11 describes, the same repair needed one round trip per row. The model then
reached an **accepted** `test_proto_assembly` at that node.

The eight that surfaced next are the finding behind the finding. They are a
*different* defect — trailing gaps, `[None, None, 'a']` written for
`[None, 'a', None]`, where the first thirteen were leading gaps. Serial
reporting had never named them, because it never got past the first row. **The
batched message did not only speed up the repair; it made a whole class of
defect visible for the first time.**

Elsewhere the single-offender path behaved as designed and unchanged: five
rejections named exactly one set and read as one sentence, including one at
`tahitic` that the model repaired before committing.

#### And both failed nodes died on the rule the fix does not touch

| seed | committed | failed node | rule that ended it |
| --- | --- | --- | --- |
| 0 | 6 of 7 | `nuclear_polynesian` | **window saturation** |
| 1 | 6 of 7 | `marquesic` | **window saturation** |

Neither was the repeated-signature rule. `nuclear_polynesian` died as *6 of the
last 9 tool calls were rejected on protocol grounds*, with the window carrying
`correspondence-reflex-mismatch`, two schema codes and
`unknown-correspondence-set` together; `marquesic` died at 7 of 9 with the two
by-design rationale codes in the mix.

This is §7.12's own prediction landing on the first two seeds that could test
it: **the window rule is the binding constraint, it counts rejections of any
kind without seeing repair, and batching one check does not empty it.** The
model at `nuclear_polynesian` had just cleared thirteen rows in one turn and
reached an accepted preview, and the window ended it anyway.

#### One thing that is *not* evidence, said because it is tempting

`nuclear_polynesian` **committed** in seed 1, and it failed in four of the five
banked seeds. That commit is **not attributable to anything in this document**:
the node took exactly one rejection, `missing-rule-rationale`, and produced no
mismatch at all. The model simply wrote the reflex rows correctly that time.
Both seeds committed 6 of 7 nodes, against 4, 5 and 3 in the banked complete
seeds — and per the hash table above, that difference is not attributable
either.

#### What this establishes

- **Established.** The batched message is produced, it names every offender,
  and this model cleared a thirteen-item list in one turn. A defect class that
  serial reporting hid is now surfaced.
- **Established.** Window saturation, not the repeated signature, ended both
  failed nodes — n=2, and consistent with the 6 of 13 in the banked seeds.
- **Not established.** Any rate, any outcome comparison, and any claim that the
  fix converts failures into commits.

### 7.15 The window rule, made able to see repair

*Implemented 2026-08-29, after §7.14 measured that window saturation ended both
failed nodes of the live run and 6 of the 13 stalls in the banked seeds.*

#### The defect

The window rule counts protocol rejections in the trailing window and raises
when they saturate it. It counts them without regard to which they were and
without regard to whether the model is fixing them.

§7.14 measured the cost at `nuclear_polynesian`. The model was told about 13 bad
rows, repaired **all 13 in one turn**, reached an **accepted**
`test_proto_assembly`, and the window ended the node anyway. Its message says
the model is cycling through malformed calls rather than adapting. The
transcript says the opposite.

#### The rule

**A protocol rejection that shows measurable repair no longer counts toward
window saturation.** Repair is a strict decrease in the number of offenders
named, against the **fewest that `(tool, code)` has ever named** at this node.

`ToolInputError` and `ToolError` gained an `offender_count` beside `subject`,
set by `verify_commitments` and carried with `exclude=True`, so neither the
model's tool result nor a trajectory byte changes. A check that cannot count its
offenders reports `None`, and a schema rejection is therefore never a repair —
those paths behave exactly as before.

Nothing else moves. The repeated-signature rule is untouched, no threshold
changes, and a rejection that shows no repair is refused exactly as it is today.

#### Best-so-far rather than last, which a test found

The first version compared against the *previous* count. **A model alternating
9, 8, 9, 8 then marks every second rejection a repair**, half the window never
counts, and it buys turns forever by re-breaking a row it has just fixed —
which is precisely the "burn the budget and return nothing" outcome §7.9 calls
the expensive one. `test_oscillating_offender_counts_still_hit_the_window`
failed on exactly that sequence.

Against the best so far, the second 8 is not below 8 and only new ground counts.

**The rule cannot be exploited to run forever.** The best-so-far count is a
non-negative integer that only decreases, so a node has at most as many repairs
as its first rejection had offenders. Then it either commits or saturates.

#### Replayed against the two real stalls

Each failed node's call sequence was rebuilt from its recorded rejections, with
the offender counts the messages state, and run through both rules:

| node | offender counts | old rule | new rule |
| --- | --- | --- | --- |
| `after-batched/seed-00/nuclear_polynesian` | 13, 8, 8 | stall | **no stall** |
| `after-batched/seed-01/marquesic` | 1, 1, 1 | stall | **stall** |

**It saves the node that was provably repairing and stops the one that was
not.** `marquesic` named one offender every time and never reduced it; nothing
in that reads as repair and it is still refused. This is a discriminating
change rather than a loosened threshold, which is the only form in which
loosening a termination guard is defensible.

Four cases are pinned as tests: a falling count is forgiven, a flat count
stalls, a sawtooth stalls, and an uncounted rejection stalls.

#### The rationale requirement reports its offenders too

The per-set rationale requirement **stays** — the research owner settled that on
2026-08-25 and §7.7 records why. But it is **22% of the protocol rejections in
the stalled nodes** of the Polynesian after seeds, and it appears in **8 of the
15**. It is the single largest contributor to window saturation.

Without a count the window rule cannot tell a model working steadily through
thirty rationales from one that is stuck, so all four rationale rejections now
report `subject` and `offender_count` the same way `verify_commitments` does.
`offender_digest` moved to `agent/tools/errors.py` and is shared rather than
restated.

**Nothing about the requirement is relaxed.** A commit still needs a rationale
on every claim, the rejection still refuses the commit, and only the detector's
reading of it changes.

#### What is not established

- **Nothing live.** This is a replay of recorded sequences through the new rule.
  Whether `nuclear_polynesian` then *commits* is a different question, and the
  model would take a different path from the turn the reprieve is granted.
- **Nothing about rates.** Two nodes. The banked 13 stalls cannot be replayed
  the same way, because under serial reporting every rejection named exactly one
  offender, so no decrease was observable even where the model was repairing.
  That is the defect, not a property of those runs.
- **The remaining stall modes are untouched**, and the by-design rationale
  requirement is one of the codes that filled `marquesic`'s window.


### 7.16 A third-party division by zero ended a whole seed

*Found live on 2026-08-29. Made survivable the same day. The trigger was then
reproduced from the banked run, so nothing in this section is a hypothesis.*

#### What happened

A sweep seed had committed 5 of 7 nodes. LingPy raised `ZeroDivisionError`, the
exception left a C module, crossed the identity fallback the harness was
building for a node that had already failed, and ended the process. The
trajectories were on disk and survived. `result.json` was never written, so the
aggregate was lost with five good commits in it.

The arithmetic is LingPy's own, at `lingpy/algorithm/cython/_calign.py:1879`
inside `align_pairwise`:

```python
dist = 1 - ( 2 * sim / ( simA + simB ) )
```

`simA` and `simB` are the self-similarity of the two rows. Material with no
phonological content scores zero on both, and the sum is not guarded. The path
is `prog_align` → `_get_pairwise_alignments` → `align_pairwise`, reached from
`alignment/lingpy_adapter.py::align_multiple`.

#### The exact input, reproduced

The trigger is **within one node's own beam, not across two nodes**. That is
why an earlier probe that aligned each shared concept first-candidate against
first-candidate reproduced nothing.

`traversal/beam.py::beam_to_lexicon` exposes *every* retained candidate as its
own `LexicalForm`. A reconstructed child carries no cognate set, so all of one
concept's candidates land in a single alignment group. In
`runs/sweeps/polynesian-after-window/seed-00`, `nuclear_polynesian` retained
five candidates for concept `1920`, and three of them were nothing but a
morphological boundary, at lengths 1, 2 and 3:

| candidate segments | probability |
| --- | --- |
| `['+']` | 0.0 |
| `['+', '+']` | 0.0 |
| `['+', '+', '+']` | 0.0 |

Replaying that banked beam through the aligner refuses concept `1920` against
**every** sibling — `central_eastern`, `futunic`, `marquesic` and `tongic`
alike — because the failing pair is inside `nuclear_polynesian` and the sibling
is only along for the ride.

The minimal reproduction is two boundary-only rows of unequal length. Two rows
of *equal* length align without complaint, and an empty sequence raises
`ValueError` rather than `ZeroDivisionError`, so neither is the case being
guarded. `tests/workbench/test_degenerate_alignment.py` pins all of it.

#### The fix, in two layers

- **`AlignmentFailure`** (`alignment/protocol.py`) is raised where the harness
  calls LingPy, naming the concept and the cognate set that was refused. It
  subclasses `ValueError` on purpose: `registry.execute` and
  `agent/tools/polarize.py` already code a refused alignment as a tool error on
  `ValueError`, so every model-facing caller keeps the handling it has and
  `polarize` is repaired without touching it.
- **`_correspondence_maps` degrades instead of dying.**
  `ReconstructionStep.correspondence_maps` is a report, nothing scores it, and
  the method already returns `()` when it has fewer than two lexicons.
  Returning `()` on a refusal matches the branch beside it.

The node then behaves the way every other node failure already behaves: it is
recorded in `result.json:node_failures`, the parent becomes an identity
fallback, and the run continues.

**It is not a silent swallow.** The step records
`diagnostics.correspondence_map_failure` with the reason, and the agent layer
turns that into a `correspondence_map_degraded` event naming the node. An empty
`correspondence_maps` on its own has always been ambiguous — a node with one
child lexicon produces one too — so the field says *why* the report is empty.

#### Why a beam candidate is a bare `+`, measured

The crash is a symptom. Over every banked sweep in `runs/sweeps` — 28 seed
files, 4940 beam candidates:

| measurement | value |
| --- | --- |
| boundary-only candidates | **20** (0.40%) |
| seeds carrying one | 3 of 28 |
| node sessions carrying one | 3 |
| commit shape | **inventory on all 20**; none from a branch cascade |
| `residue_policy` at those three nodes | **`drop` on all three** |
| candidates that were their concept's **only** candidate | **12 of 20** |

Those 12 are the serious number. A sole candidate at probability 1.0 means the
assembled parent form for that concept *is* a bare `+`.

The node that crashed the run says why. Its diagnostics, beside its siblings in
the same seed:

| node | committed sets | assembled columns | unaccounted | rate | concepts out |
| --- | --- | --- | --- | --- | --- |
| `tongic` | 30 | 231 | 27 | 0.117 | 46 |
| `futunic` | 15 | 213 | 51 | 0.239 | 46 |
| `marquesic` | 15 | 203 | 36 | 0.177 | 45 |
| `central_eastern` | 26 | 191 | 5 | 0.026 | 45 |
| **`nuclear_polynesian`** | 15 | 165 | **135** | **0.818** | **23** |

`nuclear_polynesian` committed sets that explained 30 of its 165 columns and
chose `residue_policy: drop`, which asserts that the other 135 are branch-
specific innovation. `drop` then deleted them. For 12 concepts the only column
the inventory explained was the boundary column, so the boundary is the whole
parent form. Half the concepts did not survive at all: 23 out of 46.

So a boundary-only candidate is **not a boundary bug**. It is `drop` applied to
an inventory that explained 18% of its columns — the failure mode
`ResiduePolicy.DROP`'s own docstring predicts, at the scale §7.2's
`unaccounted_column_rate` floor exists to catch.

**Nothing was changed on the strength of this.** The measurement is reported
first, as the prompt asked, and the decision sits beside the morpheme reading:
if a morpheme reading changes what a boundary is, it changes this too, and the
two should be decided together.

---

## 8. Staged implementation plan

Every stage leaves the suite green and the harness runnable. Stage numbering is
the merge order.

### Stage 0 — instrumentation only, no behaviour change

Run as its own session; the prompt is `prompts/07-proto-inventory-instruments.md`.

This stage is worth landing **whatever happens to the rest of this design**: it
repairs the falsification instrument, and three of the four repairs are
independent of the architecture question.

- Fix `order_rules()` to match its own docstring (§0.5). Per-branch figures are
  re-recorded — Hawaiian 15/46 → 22/46, total over ten daughters 214 → 221 — and
  the tree-level assertions do not move, which is itself worth a line in
  `docs/analysis_tools.md`.
- Fix the multi-gold binding selection: default to the root's binding, require
  `--gold-node` where the root carries none, and put `gold_node_id` in `--json`.
- Honour every gold alternative through `compare_to_nearest`, as
  `HistoricalTargetEvaluation` already does. Beam-exact goes 39 → 40 under the
  context-free oracle; the pinned value is updated with the reason recorded in
  the test.
- `tools/oracle_ceiling.py` gains `--oracle {context_free,contextual}`,
  defaulting to `context_free`. The context-free path keeps its identity as the
  measure every recorded baseline used.
- New `tools/assembly_ceiling.py`, both variants.
- `tests/workbench/test_oracle_ceiling_regression.py` gains the contextual
  numbers **beside** the pinned context-free ones. Both are asserted; neither
  replaces the other. A test is added for `order_rules` against its docstring
  example, since that is the assertion whose absence let the defect run from
  `febf03b` (2026-08-17), the commit that introduced the script, to now.
- `docs/analysis_tools.md` and `docs/benchmarks.md` record the corrected
  `synthetic_hard` figures, the corrected beam-exact, and the contextual ceiling.

Suite: current 320 plus roughly 8. Nothing in `cognate_reconstruction/` changes.

### Stage 0.5 — bound the road not taken (optional, measurement only)

§11.1 is decided, so this is no longer a decision aid. It is worth running once
anyway, to record what the alternative would have been worth, and it must **not**
be merged: wiring an out-group heuristic into the scorer substitutes the
harness's judgement for the model's, which is the direction §11.1 rejects.

`tools/outgroup_probe.py` has measured four tie-break policies against the
withheld gold and nobody has wired the winner in:

```
                    ties  winnable  alphabetical  outgroup-clades  morphs+clades
total (7 nodes)       66        29            18               23             25
```

The scorer uses alphabetical. Wiring the per-clade, presence-only policy into
`traversal/beam.py` and re-running the oracle says how much of the 9-concept
selection gap closes without touching the commit shape.

Read the result against §5.3, the case a selection fix provably cannot reach
whatever it scores. Whatever the number is, it belongs in
`docs/analysis_tools.md` as the recorded value of the alternative, not in
`traversal/beam.py`.

### Stage 1 — the deterministic assembler, called by nothing

Stages 1 and 2 run as one session, 3 and 4 as their own; the prompt is
`prompts/08-proto-inventory-implementation.md` and it carries the boundaries.

- `schemas/inventory.py` — the models in §4.1–4.2 and §4.6.
- `ReconstructionDiagnostics` gains the §4.5 fields, all `None`-defaulted;
  `ReconstructionStep` gains `assembly_reports`, also defaulted.
- `traversal/assembler.py` — inventory + child beams + alignments → parent beam,
  derived rules, verification, diagnostics, implementing §4.4 exactly: the
  empty-inventory short-circuit, residue carry-through, the two-pass
  conditioning, and the per-child environment rendering.
- Alignment caching by candidate tuple (§6.7), which is a requirement rather than
  an optimisation.
- Unit tests including the `*ʔ` and `*t` cases from §5 as fixtures, the
  contradiction case as an unrepresentability assertion, and the
  `non_invertible_child_ids` path.

Suite green. No tool, no CLI, no schema anyone writes today changes.

### Stage 2 — the tools, additive

- `summarize_correspondences` returns a deterministic `set_id` per set and a
  `complementary_candidates` report. Additive: `CorrespondenceSet.set_id` is
  defaulted, so `tools/correspondence_inventory.py` and every existing caller
  are unaffected and records written before it still load.
- New `test_proto_assembly`, split result and all (§4.6) — the split has to be
  right in the first version, because the result schema enters trajectories the
  moment it ships.
- `get_node_reconstruction` gains its `PriorNodeInventory` variant (§6.4).
- New `realign`, with the §6.1 invariant, including the all-gap column insertion
  that §6.9 depends on.
- Restoration commitments and their three refusals (§6.9), reusing `polarize`'s
  existing out-group machinery rather than a second implementation of it.
- `commit_reconstruction` accepts `rules` **xor** `inventory`; a call carrying
  both is refused. New error codes added to `agent/error_codes.py` and
  classified — the AST scan test already enforces that nothing widens the
  vocabulary silently.
- `schema_version` widens to `["2.0", "3.0"]`; `CommittedHypothesis` union;
  `summarize-trajectories` reports `commit_shapes`.
- `inspect-run` learns to print an inventory node.

Suite green, both commit paths covered, every checked-in pre-change trajectory
still loading — `tests/workbench/fixtures/trajectory_real_pre_change.jsonl` is
the guard and it is a real artifact.

### Stage 3 — flip the instructions and measure

- **Done 2026-08-24.** `system_prompt.md` teaches the inventory workflow (§6.6
  step list), the edge-case framing for `realign` (§6.1), and when a restoration
  is warranted (§6.9). The rule cascade keeps a section of its own, because it
  stays an accepted commit shape through this stage; what changed is which one
  the manual leads with and why. The file was renamed from `SKILL.md` at design
  time, because two unrelated files carried that name — the model's system
  prompt and the harness's own operator skill under `skills/` — and the
  collision was a standing source of confusion.
  `COMMIT_REQUIREMENT_NOTES` covers both shapes for the same reason, because a
  requirement living only in code is one the model discovers by being rejected.
  **This changes `instruction_sha256`**, so every checkpoint written before it
  refuses to resume, naming the instructions as the part that moved. That is the
  mechanism working: a resumed run must not mix nodes reconstructed under two
  different manuals.
- `run-benchmark --seeds 5` on Polynesian and `synthetic_hard`, before and
  after, both commit shapes, recorded in `docs/benchmarks.md`.
- `score-synthetic` gains the inventory comparison (§9.2).
- **Decision point.** §7's conditions are evaluated here. Stage 4 proceeds only
  if they hold. Its thresholds were re-derived against the repaired instruments
  on 2026-08-23 and every one is reproducible from a command in §7.5; a session
  evaluating them re-runs those commands rather than quoting the table.

Both commit shapes still accepted. A regression is a revert of one document.

### Stage 4 — remove the branch-cascade commit path

- Delete what §9 lists.
- `oracle_ceiling.py` default mode becomes `assembly`; the two branch-cascade
  modes stay runnable as the historical baseline.
- The regression test's pinned numbers become the assembly ones, with the
  branch-cascade numbers kept in the module docstring as the recorded before.
- Trajectory readers keep accepting 2.0; nothing writes it.

---

## 9. What gets deleted

The prompt is right that the value is as much in the removal as in the addition.
Everything here goes at stage 4, and only if §7 holds.

### 9.1 From the harness

| Removed | Why it can go |
| --- | --- |
| `test_rule_cascade` (tool, args, result, ~90 lines) | It exists to preview an **order**. Sets are independent, so there is no order to preview. It is also, measured, the largest single context consumer in a live run: 399 KB across three calls at one node against 22 KB for all the evidence that node inspected, and never compactable. See §6.8. |
| `CommittedSoundRule` (schema) and `CommitReconstructionArgs.rules` | Replaced by `CorrespondenceCommitment`. |
| `cascade_validation_call_id` | Nothing to point at. |
| Per-rule validation resolution in `agent/tools/commit_reconstruction.py` — the matching, the ambiguity handling, the near-match remediation | Replaced by set re-derivation, which is a lookup rather than a search. This is the largest single deletion; the file is 700+ lines and most of it is this. |
| `ValidationKind` | One kind of validation remains. |
| `ReconstructionDiagnostics.rule_complexity_cost` | Counts DSL tokens in an object that is no longer committed. Already "diagnostic only" and consumed by nothing. |
| `child_convergence_rate`, `divergent_concept_count`, `divergent_concept_ids` — **retired, not removed** | The fields stay (already `None`-defaulted, and 2.0 records carry real values); nothing populates them on a 3.0 step. The failure they detect is unrepresentable under assembly. §4.5, and a paragraph owed to `docs/report_reject_or_score.md`, whose second worked example they are. Roughly a dozen read sites across `cli.py` and `inspect_run.py` already handle `None`. |
| `high_quality`'s `sound_law_tests < committed_rule_count` and `cascade_tests == 0` conditions | Replaced by "the committed inventory has a covering `test_proto_assembly`". Note this is **nearly vacuous at the gate**, because the commit already refuses without one — exactly as the condition it replaces is nearly vacuous today. It is kept for the same reason: it is an *artifact-level* check over records that may have been written before enforcement existed, which is what lets `export-trajectories` filter a corpus it did not produce. |
| `derive_rule_id`'s use at commit time | Set IDs are derived from the set. The function stays for `test_sound_law`. |
| `ReconstructionDiagnostics.rule_coverage` | Replaced by `unaccounted_column_rate`, which is coverage over columns rather than over (rule × in-scope child) pairs. §4.5 says why that is the better shape. |

### 9.2 The synthetic families and their answer keys

**The families do not change.** `benchmarks/synthetic/*.json` are untouched and
`synthesis/generator.py` keeps applying `RuleEngine.apply_rules` forward. The
coupling between the generator and the DSL is deliberate and is what keeps the
benchmark honest; this change gives no reason to loosen it.

**The answer keys gain a field and lose nothing.** `SyntheticAnswerKey` gains
`node_inventories`: per internal node, the true correspondence-set →
proto-phoneme mapping, computed deterministically from the generator's own
lexicons by aligning each node's children and reading the parent's segment in
each column. `SyntheticBranchAnswer` keeps `rules`, `inverse_rules`,
`invertible` and `innovated` exactly as they are.

Answer keys are written to `runs/benchmarks/`, which is gitignored, so nothing
checked in changes and `build-synthetic` rebuilds them.

**`synthesis/scoring.py` gains a comparison and keeps every one it has.** The
existing rule precision, rule recall and functional recovery are computed
against the **derived** per-branch rules, which is why §4.3 requires them to be
derived and verified: it keeps the measurement comparable across the migration
rather than replacing it. New beside them:

- `set_precision` / `set_recall` — committed sets against the true ones;
- `proto_phoneme_accuracy` — per node, the share of true sets given the right
  value.

**`misdirected_rule_count` survives unchanged and is the reason the derived
rules must exist.** It is the one measurement that speaks directly to prompt
04's failure, it is checkable nowhere but here, and a commit shape that could
not produce a branch-scoped rule would have destroyed it. A rule derived for a
branch the answer key gave no rule to is still a rule pointed at a branch that
did not change.

### 9.3 The oracle-ceiling regression test

**It goes red when this lands, and it must not be deleted.** It is the
falsification instrument, and deleting an instrument because it reported
something is the failure mode the whole file exists to prevent.

The plan is that **the question survives and the implementation gains a mode.**
"What would a flawless hypothesis manager score?" is architecture-independent:
give the oracle the perfect proto-inventory at every node and run the real
assembler. So:

- Stage 0 — the test pins context-free **and** contextual branch-cascade
  numbers. Two measures, both live.
- Stage 2–3 — it gains the assembly numbers as a third block, computed by
  `oracle_ceiling.py --oracle assembly`. Three measures, all live, all pinned,
  because during the migration both architectures exist and a reader needs the
  before and the after in one file. **Landed 2026-08-24**: top-1 **39/46**,
  beam-exact **39/46**, mean top NED **0.031**, `cross_branch_assembly_rate`
  0.957 and non-zero at all 7 nodes, flat at every beam width from 1 to 10.
- Stage 4 — the branch-cascade numbers move from `assert` to the module
  docstring, marked with the date they were recorded and the commit at which the
  path they measured was removed. They stay *computable* — the modes remain in
  the script — and they stop being *asserted*, because asserting a property of
  deleted code is noise.

The gap assertion survives in the new architecture's terms: `assembly_beam_exact
- assembly_top_exact`, which under assembly should be **small**, and the test
should say why — a large gap would mean the assembler is generating candidates
it then fails to select among, which is the old defect returning at a new level.
It is **0** as measured, and `MAX_ASSEMBLY_SELECTION_GAP = 2` is what the test
asserts.

**What the oracle is given, and the two things it is not.** It commits one value
per correspondence set, optionally with a `conditioning` found in the same
bounded environment space `--oracle contextual` searches, and it picks a residue
policy per node by running each. Those are all claims about a *language*. It is
given no `restorations` and no `residue_dispositions`, because those are claims
about one concept: a restoration would hand it the `*w` in `1028` YAWN that no
daughter attests, and §7.4 records `1028` and `778` as concepts the ceiling
cannot promise. They stay unpromised — both are still misses under this oracle.

**One consequence to carry into §7.** Under a branch cascade the beam holds one
whole string per branch, so beam-exact measures the selection slack. Under
assembly one candidate tuple assembles into exactly one parent form, so top-1
and beam-exact converge by construction and the slack is gone. The two
beam-exact numbers are therefore not comparable by subtraction, which is what
§7.3's last bullet already says and which condition 2 has to be read against.

`tests/workbench/fixtures/polynesian_benchmark_segments.json` is unchanged: the
oracle reads segments, the tree and the gold binding, and assembly reads the
same three things.

---

## 10. Report, reject, or score

Applying `docs/report_reject_or_score.md`'s decision rule to every new number.

**Rejections — question one, deterministic code is certain:**

| Signal | Code |
| --- | --- |
| A commitment cites a set the node's data does not contain | `unknown-correspondence-set` |
| A commitment's `support` differs from the re-derived support | `correspondence-support-mismatch` |
| A claimed conditioned split is not complementary over the actual columns | `non-complementary-split` |
| The inventory has no covering `test_proto_assembly` in this session | `missing-assembly-validation` |
| `residue_policy` absent | `missing-residue-policy` |
| `directionality_rationale` absent on a commitment that deletes or merges | `missing-directionality-rationale` (existing) |
| An `AlignmentOverride` whose gapless rows do not reproduce the child's form | `overlay-invalid-edit` (existing) |
| A realignment whose named set does not actually gain the claimed support | `realignment-does-not-join-set` |
| A restoration citing a node that does not attest the segment there | `restoration-unattested` |
| A restoration citing a descendant rather than an out-group | `restoration-cites-descendant` |
| A restoration at a node with no out-group, the root included | `restoration-without-outgroup` |

Each is arithmetic over the forms or a missing required field. None is a
judgement about the linguistics, and in particular the last two are rejections
**on absence and never on content**, unchanged in kind from what already ships.

**Every new code needs an `exploratory` / `protocol` classification**, because
`agent/error_codes.py` requires one and an AST scan test fails if a raise site
widens the vocabulary silently. The principle: *exploratory* means the model made
a claim about the evidence and the evidence refused it — the hypothesis loop
working, and charging for it would score a model that explores below one that
never explores. *Protocol* means the call was malformed or referenced something
that is not there.

| exploratory | protocol |
| --- | --- |
| `non-complementary-split` — the split was proposed and the columns refute it | `unknown-correspondence-set` — a stale or fabricated ID |
| `restoration-unattested` — a reconstruction the cited evidence does not support | `correspondence-support-mismatch` — a transcription error |
| `restoration-cites-descendant` — a claim about evidence the harness refutes | `missing-assembly-validation` — no covering preview |
| `realignment-does-not-join-set` — an alignment proposed, the data did not bear it out | `missing-residue-policy` — a required field is absent |
| | `restoration-without-outgroup` — structurally impossible here; retrying teaches nothing |

**Reports — question two, a fact a human wants where "bad" needs judgement:**

`unaccounted_column_rate`, `cross_branch_assembly_rate`, `committed_set_count`,
`proto_phoneme_count`, `mean_set_support`, `alignment_overrides`,
`override_singleton_sets_created`, `restored_segment_count`,
`columns_decided_by_residue_policy`, `columns_decided_by_tie_break`,
`contrast_reducing_set_count`, and the derived per-branch rules themselves.

Run each through the question in the pocket — **what happens when this fires on
a correct run?** `cross_branch_assembly_rate` is 0 on a node whose children
happen to agree, which is a perfectly good node. `alignment_overrides` is 3 on a
node with three genuinely mis-aligned compounds. `unaccounted_column_rate` is
high on an honest reading of a messy lexicon. All three fire on correct runs, so
all three are printed and none is consumed.

**Scores — unchanged in kind.** `confidence` already weights the beam and
continues to; it is now attached to a correspondence instead of a rewrite. No
new quantity reaches the beam, no new quantity reaches `high_quality`, and
nothing new filters a trajectory. Whether per-column confidence *should* compose
differently is a research-owner decision and belongs beside the branch penalty
and the anchor boost.

**One hazard the section as approved does not name** — that the gate can
*loosen* under the new commit shape, because existing quantities stop reaching
it — is §12.2. It is the one place this change can do irreversible damage.

**Neither, and deliberately: "is this inventory typologically credible?"** An
inventory invites the question — that is the point of making it a first-class
object — and the answer is that the harness will not answer it. This repository
holds no table of sound changes, no naturalness score, and no typology data, and
prompt 04 rejected `assess_change` outright with reasoning that is binding here.
A credibility score over a proto-phoneme inventory is question three wearing a
number: it would need typology data to compute, it would fire on correct runs
(Proto-Polynesian's inventory is unusual and correct), and the moment it reached
`high_quality` it would define "typologically ordinary" as "valid". The
inventory is **printed** — by `inspect-run`, in `result.json`, in
`summarize-trajectories` — and a human reads it. That is the whole of it.

---

## 11. Decisions that need the research owner

**1. Whether stage 4 happens at all — DECIDED: yes, proceed.** The decision was
taken on the division of labour rather than on the accuracy: **reading a
correspondence set and naming the proto-phoneme that gave rise to it is the
linguist's job, and it is the job this harness exists to have a model do.** The
current architecture does not let the model state that answer — §5.3 is the
proof, where two daughters attest the gold form of concept 1408 verbatim and it
is destroyed at the first node above them under oracle rules. A model can be
entirely right about Polynesian and have no way to say so.

Stage 4 remains gated on §7's conditions, and that is not a re-litigation of
this decision: those conditions check that the *implementation* does what the
design says, not that the design was worth doing.

**The principle has three consequences recorded elsewhere in this document**,
because it decides more than the scope question:

- **Stage 0.5 is a measurement, not a candidate fix** (§8). Wiring the
  out-group tie-break into the scorer would substitute a harness heuristic for
  the model's judgement, which is the direction this decision rejects. It is
  worth running to bound the road not taken; it is not worth merging.
- **The `majority_reflex` residue policy is removed** (§6.3). It was a majority
  vote over daughters, which this repository has measured as reconstructing
  innovations. `retain_from_witness` asks the model to name a conservative
  branch instead.
- **Equal-mass column ties are surfaced to the model** (§6.7), not resolved
  silently by `TIE_BREAK_POLICY`. A column two committed sets both match is a
  distinction the model should have drawn.

**2. Whether `realign` ships — DECIDED: yes, uncapped.** §6.1 carries the
mechanism: purpose-bound (a realignment must name the set it joins), verified
(the set must actually gain that support), per-concept, session-local, counted,
and **not budgeted**. The draft's hard cap was dropped because how many repairs
a node legitimately needs is a property of how well SCA handles that family's
phonology, which no quantity the harness can see predicts — a fixed cap would be
tight exactly where repairs are most needed. What stands in for it is the
join-a-set check (which scales with the evidence rather than with a constant), a
soft advisory in every `realign` result modelled on `contrast_reduction`, and an
instruction in `system_prompt.md` that this is for edge cases.

This is the one place the design knowingly depends on the model complying with
an instruction, and the README records the opposite call being made in a
neighbouring case (`rule_coverage` was fixed rather than the instruction). The
dependency is accepted because the part that *can* be checked mechanically is
checked, and the residual is a matter of degree. Watch `alignment_overrides`
across seeds at stage 3; §7.2 carries the condition that would bring the cap
back.

**3. What happens to the existing trajectory archive — DECIDED: keep it, as
progress tracking.** `runs/` is not a fine-tuning corpus; a training corpus would
be generated fresh under whatever protocol is current. §6.5 is simplified
accordingly and the mixed-corpus machinery is dropped. `commit_shapes` in
`summarize-trajectories` stays, because it is the migration's daily progress
signal.

**4. How per-column confidence composes — DECIDED: unchanged.** Multiplicative,
as today, attached to a correspondence rather than to a rewrite. The sub-question
this exposed is resolved in §6.7 and is *not* a matter of taste: assembly runs
over the children's full beams, because 43 of 46 concepts carry more than one
candidate at the root and collapsing that would make every intermediate error
permanent.

And one that is not really a decision, recorded so it is not lost if the rest is
rejected: **stage 0 should land either way.** Four defects in the falsification
instrument are four defects whether or not this architecture changes, and the
one in `order_rules()` has been silently costing the Hawaiian branch seven
concepts since the script was written. Repairing an instrument is not a
commitment to the change it was built to evaluate.

---

## 12. Post-approval additions and corrections

> Everything in this section post-dates the approval of §§0–11 and was written
> while stage 1 and stage 2 were implemented, against commit `76cdd0b`. It is
> here rather than edited into the sections above so that a reader of §4.6 and
> §10 can see what the code outgrew and when.

### 12.1 `ComplementaryCandidate` reports the tokens that distinguish the pair

*Added 2026-08-23, post-approval. Extends the §4.6 sketch; changes nothing in
§6.2's asymmetry.*

§6.2 has the harness report pairs of sets whose occurrences never share an
environment, and never propose the collapse. That asymmetry is kept exactly.
What the §4.6 sketch omitted is the one fact the model needs in order to *write*
the `conditioning`: **which tokens actually separate the two sets.** Without it
the tool reports a conclusion while withholding the evidence for it, and the
model has to go pull alignments to recover what the tool already computed.

The pair therefore carries `left_context_tokens` and `right_context_tokens`,
each a two-tuple positional against `set_ids`, holding the sorted distinct
tokens observed adjacent to that set's occurrences. A word edge is reported as
`#`, which cannot collide with a segment because `rules/parser.py::_tokens`
refuses `#` inside a segment expression.

**This is retrieval, not phonology.** It reports tokens present in the node's
own data. It imports no feature table, names no natural class, and ranks
nothing, which is what keeps it on the admissible side of §10's last row. A
reader may see `("e", "i")` as "front vowels"; the harness must not, and does
not say so.

**It ships in the first version of the schema**, for the reason §6.8 gives about
`test_proto_assembly`: a tool result is written verbatim into
`trajectories.jsonl` the moment the tool ships, and the archive is append-only.
Retrofitting it would leave records a later reader could not tell apart from
records where no context distinguished the pair.

Nothing here reaches the beam, `high_quality`, or a rejection. It fires on
correct runs — two sets in complementary distribution are frequently just two
phonemes — so it is printed and never counted.

#### The one definition of adjacency, and where it lives

The constraint that did the real work is that **the report and the §6.2
rejection must compute "environment" the same way.** If the report derived its
contexts under one notion of adjacency and `non-complementary-split` rejected
under another, a model would be handed tokens and then refused for using them
with no way to see why.

They do share one, and it lives in `cognate_reconstruction/alignment/environments.py`:

> **Adjacency** is the columns of one alignment, in order, skipping every column
> that contributes no segment. **A column reads as what it contributes to the
> proto-form, and as what the nodes show where nothing has decided that yet.**
> **Satisfaction is membership, not agreement**: `left = ("e",)` holds when `e`
> is among the tokens the preceding column reads as, not when every node shows
> `e` there — because the report unions across nodes, so the check has to accept
> the union it reported. A word edge contributes `#`.

The second sentence is what unifies the three callers rather than papering over
them. `summarize_correspondences` has no inventory, so *nothing* has decided any
column and every column reads as its observed segments — which is exactly what
the report hands back. `test_proto_assembly` and `commit_reconstruction` resolve
the node's own columns under the committed inventory first, so a column a set
covers reads as its `proto_segment`, a column the residue policy carries through
reads as the witness's segment, and a column that contributes nothing is skipped.
The assembler's pass 2 uses the same readings with `None` for a column pass 1 did
not decide, which is precisely §4.4's "deciding neighbour is itself still
ambiguous" case.

The one asymmetry left is worth stating because it is the residual of the
constraint: **a token the model was handed is always accepted where it was
observed, unless the model's own inventory reconstructs that column as something
else.** The goalposts can only be moved by the commit being checked, which is
legible in the commit.

**And one thing the report can hand back that a `conditioning` cannot express.**
`RuleEnvironment` holds a literal token *sequence*, not a disjunction, so a
palatalization pair reporting `right_context_tokens = (("e", "i"), ("a", "o",
"u"))` cannot be collapsed by a single conditioning: `/ _e` covers the `e`
occurrences and not the `i` ones, and §6.2's first condition — *every* column
occurrence of `A`'s reflex tuple satisfies `A.conditioning` — then fails. That
is a pre-existing limit of the DSL rather than something this addition creates,
and the design's response is unchanged: the model *sees* both tokens and can
tell that one environment will not cover them, and `non-complementary-split` is
classified `exploratory` precisely so proposing the split and being refused
costs nothing. Showing the whole token set is what makes the limit visible;
hiding it would have made the rejection unexplainable.

**Bounding the report.** Complementarity is decided over the **union** of each
set's contexts on one side — two sets are complementary when nothing they are
ever observed to the left of is shared, or nothing to the right of is. That is
both cheap and exactly the case a single `RuleEnvironment` can express; an
occurrence-level test would report pairs no conditioning could separate. Pairs
are drawn from the sets that already passed `min_support`, ordered by combined
support, and capped at `MAX_COMPLEMENTARY_CANDIDATES = 20` with the total count
reported beside the sample, because on Polynesian 41 sets clear
`min_support = 2` and most of the 820 pairs among them are trivially
complementary.

### 12.2 The `high_quality` gate silently loosens under the new commit shape

*Added 2026-08-23, post-approval. A hazard §10 does not name.*

§10 states that no *new* quantity reaches `high_quality`. That is true and it is
not the hazard. The hazard is that **existing quantities stop reaching it.**

`high_quality` is this repository's only gate — `export-trajectories
--high-quality-only` selects a corpus with it — and three of its failure
conditions are keyed to rule-shaped counters: `committed_no_op_rule_count` reads
`committed_reconstruction.parsed_rules`, which `CommittedProtoInventory` does not
have; `sound_law_tests < committed_rule_count` and `committed_rule_count > 1 and
cascade_tests == 0` read counters that are both 0 on a session that called
`test_proto_assembly` instead. Widen `committed_reconstruction` to the union and
each condition either raises `AttributeError` or, worse, quietly evaluates to
"no problem" — every 3.0 session passes all three unconditionally, the gate
becomes strictly more permissive, the suite stays green because nothing crashed,
and corpora selected under the loosened gate cannot be un-selected. That is
precisely the asymmetry `docs/report_reject_or_score.md` names in "Why 'gate' is
a special word".

What stage 2 decided, in prose rather than as a silent fallback:

- **`committed_rule_count` means `len(commitments)` for an inventory.** That is
  the unit the model actually committed and the unit a reviewer counts. It is a
  persisted field, so the meaning is fixed once records exist. The field name is
  kept — `tool_failures_by_type` is the precedent for a name whose meaning has
  moved, and documenting the move is not optional.
- **`test_proto_assembly` is the successor to both workflow counters.** A new
  defaulted `assembly_tests` counts it. Since one preview covers a whole
  inventory, the analogue of "N rules against M sound-law tests" is "N sets
  committed with no covering preview at all", and the cascade-order condition
  has no analogue because sets have no order (§2.2).
- **`committed_no_op_rule_count` returns 0 for an inventory, with a comment
  saying why.** A commitment whose `proto_segment` equals every child's reflex
  derives no rule at all (§4.3); that is an ordinary identity correspondence,
  not a defect. 0 because the check is meaningless here is a decision; 0 because
  the attribute was missing is a bug that looks identical in the output.
- **`inspect_run.py::committed_rule_views` reads an inventory's
  `derived_rules`.** Without that, all three cross-node observations go blank on
  every 3.0 run and `inspect-run` prints "No cross-node observations." on a run
  full of them.
- **A test pins the gate across both commit shapes.** Two sessions with
  equivalent workflow behaviour — one 2.0, one 3.0 — get the same verdict and
  the same reasons, and a 3.0 session that committed without a preview is
  genuinely caught. Absent that test nothing in the suite can tell "the gate
  passed this session" from "the gate could not see this session".

### 12.3 Corrections found while implementing

*Three wrong turns, kept with their reasons rather than deleted, on the same
principle as §6.9's all-gap column and §6.1's hard budget.*

**A per-`set_id` uniqueness rule makes §4.4's multi-match branch unreachable.**
§4.1 says "A validator rejects duplicate `set_id`s"; §4.4 resolves columns that
"more than one" commitment matches, and §6.7 counts
`columns_decided_by_tie_break` for "columns where two committed sets matched at
equal mass". Those cannot both hold. `set_id` is a pure function of the reflex
tuple, the child order and the overlays, so identical reflexes always give
identical IDs — two commitments can only match one column if they share a
`set_id`, which the validator forbade.

Worse, the rule forbids a real analysis. `⟨A t : B s⟩` reconstructing `*t`
generally and `*ts` before `*i` is one correspondence with a conditioned split,
and there is no second reflex tuple to hang the second value on. **The
uniqueness unit is the `(set_id, conditioning)` pair**, which keeps what the rule
was for — the same claim cannot be committed twice — and makes the
elsewhere-condition expressible. Column resolution then reads: a conditioned
commitment whose environment holds wins; failing that, the unconditioned
commitment on the same set is the elsewhere case; failing both, the column is
residue. Several satisfied conditionings is the genuine tie, and it is what
`columns_decided_by_tie_break` counts and what `test_proto_assembly` lists as
`ambiguous_columns`.

**§5.1's "No branch produced it" is inaccurate for the flat ten-daughter
illustration.** The table two paragraphs above it shows EastFutuna and EastUvea
as `ʔ a l e l o`, which is the gold form verbatim, so the assembled form *is* two
daughters' strings there. What is true, and is what the paragraph was reaching
for, is that the two sets it combines have different witnesses: `ʔ` is attested
by EastFutuna, EastUvea and Tongan, and `a` by the nine daughters that are not
Tongan. The claim as written is exactly true one paragraph later at the `tongic`
node — Tongan `ʔ e l e l o`, Niuean `a l e l o`, Proto-Tongic `*ʔ a l e l o` —
which is the case §5.1 actually argues from and the case the live `tongic`
failure is about. `tests/workbench/test_proto_assembly.py` asserts both, and the
flat one asserts the true statement rather than the quoted one.

**A concept fewer than two children attest has no correspondence to read.** §4.4
does not say what happens to it, and the naive reading is a crash: a width-1
reflex tuple matches no set, every column falls to the residue policy, and under
`retain_from_witness` with a witness that is not the attesting child the form
comes out empty and `normalize_and_prune` refuses it. Such a concept is passed
through unchanged, which is what today's identity path does and what keeps the
beam emitting only forms some child actually produced.

**The survey and the assembler saw different columns, and the whole mechanism
rested on it.** This is the largest thing found while implementing, and it is
not visible anywhere in §§4–6.

`summarize_correspondences` aligns the child *lexicons*. At an internal node a
child's lexicon is `beam_to_lexicon(step.output_beam)` — **every retained
candidate** — so a concept where two children carry three candidates each goes
into one six-row MSA, and `build_correspondence_sets` then keeps one row per
node out of it ("the last one wins, as in the prototype"). The assembler, per
§6.7, aligns **one candidate per child**. Two different alignments, therefore
two different column boundaries, therefore two different reflex tuples — so at
every internal node a model would commit values for sets the assembler never
sees, every column would fall to residue, and `cross_branch_assembly_rate` would
read 0 everywhere. That is §7.2's first stop condition, fired by a defect rather
than by the mechanism being useless, which is the worst possible way for it to
fire.

The fix is one function, `alignment/correspondence_sets.py::one_reading_per_node`,
applied by both `summarize_correspondences` and the commit-time re-derivation:
**keep one form per node per (concept, cognate set), the first listed.** The
first rather than the last because `beam_to_lexicon` emits candidates in beam
order, so the first is the form that node reports.

It is a correction rather than a compromise. A correspondence is a
correspondence between the languages' *reported* forms; aligning ten alternative
readings of one concept from one node and then reporting one of their rows is a
correspondence between one language and an aggregate of another's guesses. The
alternative readings are not discarded — assembly still runs over the children's
full beams, and a tuple containing a non-top candidate simply aligns to whatever
it aligns to and is scored on how much of it the inventory explains.

Two limits of the fix, stated rather than hidden. A concept whose children fall
in *different* cognate sets yields two single-member alignments, which the
aligner skips, so no set covers it and assembly falls to residue — concept
`1217` FATHER is exactly that case and §1.2 already names it as unreachable. And
a benchmark using `segment_slice` cognate memberships would align slices in the
survey while the beam carries whole forms; every membership on the Polynesian
benchmark is `whole_form` (520 of 520, measured), so this does not bite today
and would need handling before it did.

### 12.4 What the new call actually costs

*Measured 2026-08-23 on `runs/benchmarks/polynesian.json`, ten daughters, all 46
concepts, through the registry rather than by estimate.*

| payload | size |
| --- | --- |
| `summarize_correspondences`, default page (30 of 39 sets at `min_support` 2), with the complementary-pair report | **17.5 KB** |
| `test_proto_assembly`, `detail="summary"`, 41 committed sets, all 46 concepts | **23.5 KB** |
| the same at `detail="full"` | 75.2 KB |
| **the non-compactable half of either** — validation ID, covered set IDs, rates, ambiguous columns | **1.4 KB** |

Against the design's predictions this comes in slightly under: §6.8 budgeted
27.8 KB for the n-way rows and the preview costs 23.5 KB for the whole node.
Against the tool it replaces it is not close — `test_rule_cascade` measured
**399 KB across three calls at one live node**, never compactable, against 22 KB
for all the evidence that node inspected.

The number that matters most is the last row. §6.8's third constraint is that the
result be *shaped* so its bulky half can be dropped while the validation ID and
the verdict stay, and 1.4 KB is what a session has to carry to its commit. The
other 22 KB is re-derivable by calling the tool again, which is exactly the test
`COMPACTABLE_TOOL_NAMES` applies — even though the tool itself is, and must
remain, ineligible for compaction.

#### The floor under `unaccounted_column_rate`, and where it comes from

*Measured 2026-08-23. These are **structural** figures — what the mechanism can
do on this benchmark's alignments — and are neither oracle nor live numbers.
They bound nothing about accuracy; they say what the residue rate means.*

> **Re-measured later the same day, after §12.5's boundary fix landed.** The
> figures below are the pre-fix ones and are kept because §12.5 quotes them as
> its before half. Post-fix, over the 246 sets the aligner now yields:
> `unaccounted_column_rate` **0.125**, `cross_branch_assembly_rate` **0.761**,
> 46 of 46 concepts assembled; recurrent-only (50 sets at `min_support` 2)
> **0.551** and 0.522. The account below of *where* the residue is survives
> intact: 42 unaccounted columns of 336, in 11 of 46 concepts, and all 11 carry
> more than one cognate set — still 100%. **0.125 is the floor §7 has to state.**

Committing a proto-phoneme for **every** one of Polynesian's 218 correspondence
sets, with `retain_from_witness`:

| | |
| --- | --- |
| `unaccounted_column_rate` | **0.141** |
| `cross_branch_assembly_rate` | **0.783** |
| concepts assembled | 46 of 46 |

And with only the 39 recurrent sets (`min_support = 2`): unaccounted **0.609**,
cross-branch 0.500. That second figure is not a defect — 175 of 218 sets are
singletons, and §5.1 already says refusing them would make most concepts
unassemblable. It is what `mean_set_support` exists to make visible.

The first figure is the interesting one, because a complete inventory ought to
explain every column and does not. **All 40 unaccounted columns, in 11 of 46
concepts, are in concepts whose daughters carry more than one cognate set —
100% of them.** The cause is a difference in grouping the design does not name:
`summarize_correspondences` aligns per `(concept, cognate set)`, so two etyma
under one gloss are two alignments and neither yields a correspondence over the
node's children; the assembler aligns whatever candidates the children's beams
offer for the concept, because **a beam candidate carries no cognate-set
identity** — `beam_to_lexicon` does not give it one, and at an internal node
there is nothing to give.

That is not fixable in this session and probably not fixable at all in the
obvious direction. Making the assembler cognate-set-aware works only where the
children are observed leaves; at every higher node the candidates are
reconstructions with no cognate-set identity, so it would repair the preview and
not the step, and re-open the preview/step divergence §12.3 exists to close.
Carrying cognate sets through the beam is a much larger change and arguably a
wrong one — which cognate set a reconstructed parent form belongs to is itself a
claim, not a datum.

**What matters for §7 is that this is a floor, not a score** — 0.141 as measured
here, 0.125 after the boundary fix. §7.2 stops the work if
`unaccounted_column_rate` runs "above ~0.3 at most nodes under the oracle", on
the reasoning that the sets would then not cover the evidence. On Polynesian the
multi-etymon floor is 0.13 with a *complete* inventory, so that threshold has
about 0.18 of headroom rather than 0.3, and a reader comparing against it must
subtract the floor for the family in question first. The
concepts concerned are the ones §1.2 already names — `1443` WALK carries four
etyma and loses 5 of its 12 columns, `1212` carries three — so this is the
alignment/cognacy limit that section describes, quantified rather than newly
discovered.

**One reporting choice made from the measurement.** Complementary pairs are
ordered by the *weaker* half's support, not by the combined total. Ordered by the
total, every page was headed by a set occurring in twenty words paired with one
occurring in two, where complementarity is an artefact of the rare set being
rare. By the weaker half the sample is pairs at support 11 against 8 and 11
against 5, whose contexts genuinely separate — one after consonants, the other
after vowels and the word edge. It is still only a count; the harness names no
class and ranks no segment.

**A gap can be written the way the DSL writes one.** Measured on a live node
rather than reasoned about: handed the `⟨Ø : ʔ⟩` set, the model wrote
`"reflexes": ["∅", "ʔ"]`, was refused for a support mismatch it had not made,
and spent two further turns discovering that `null` was meant. `Ø` and `∅` are
`GAP_SEGMENT_TOKENS`, which `summarize_correspondences` already accepts in its
`segment` filter for exactly this reason, so `CorrespondenceCommitment.reflexes`
and `AlignmentOverride.rows` accept them and normalize to `None`. No check is
loosened — the reflex tuple is still compared against the harness's own.

### 12.5 Two findings that blocked stage 3, neither of them stage 2's work

*Found 2026-08-23 while checking §7 against the instrument prompt 07 repaired.
Recorded here rather than fixed on the spot, because each is a separate
reviewable change with consequences outside stages 1–2, and neither was safe to
fold into them silently. The first is now fixed and this section records what it
cost; the second is the re-derivation the fix had to land before.*

#### The assembler dropped morphological boundaries, and the rule path did not

*Found 2026-08-23, **fixed 2026-08-23** in the commit that added
`include_boundaries` to `LingPyAligner`. The finding is kept in full because the
measurement it rests on is the before half of the before/after below.*

`LingPyAligner._alignment_inputs` aligned `phonetic_segments`, which strips `+`
and `-`. Every evidence tool had always done this, and under branch cascades it
cost nothing: `make_leaf_beam` carries `form.segments` *with* the boundaries, and
`RuleEngine` passes them through untouched, so a parent form inherits the
boundary its children showed.

Assembly builds the parent out of **alignment columns**, and there is no column
for a token the aligner never saw. So:

```
children  m a n u + l e l e   /   m a n u + r e r e
rule path      →  m a n u + l e l e
assembly       →  m a n u   l e l e
```

That was a **regression against the shipped path**, not a limitation of the new
one, and it was silent — nothing rejected, nothing counted it, the form simply
came out one token short.

Measured on Polynesian: 128 of 520 daughter forms carry a boundary, and **8 of
the 46 gold concepts carry one in every gold alternative** — `1028`, `1212`,
`1217`, `1239`, `1439`, `1741`, `2105`, `778`. Those eight were unreachable by
assembly *by construction*, which capped top-1 at **38/46** before the model did
anything, against a node-local ceiling of 44/46. And two of the three concepts §7
condition 3 names as the proof the mechanism fired — `1212` and `1439` — were in
that list, so the check the design relies on to distinguish "the mechanism
worked" from "something else moved" would have failed on two thirds of its
evidence for a reason having nothing to do with the mechanism.

`tools/assembly_ceiling.py` saw this coming and says so in `align_rows`: it
deliberately aligns `form.segments` rather than `phonetic_segments` because "a
column that could never contribute a `+` would make those concepts unreachable by
construction rather than by measurement". The ceiling was measured one way and
the implementation ran the other way, and the two share no alignment code that
could have disagreed out loud — which is why the gap survived every test in the
suite.

##### The fix: at the shared input, not in the assembler

`LingPyAligner.align_multiple` and `align` take `include_boundaries`, defaulting
to `True`, and `_alignment_inputs` passes it to
`LexicalForm.segments_for_membership` on the cognate-membership branch and
selects `form.segments` over `form.phonetic_segments` on the other. Nothing else
in the harness names the choice. That placement is the whole point: the survey,
the preview, the commit-time re-derivation and the assembler all read one
alignment, so a set ID a model is handed is a set the assembler can reproduce.
Repairing this in `traversal/assembler.py` alone would have re-opened the exact
defect §12.3 records — the survey naming columns the assembler cannot see, every
boundary-bearing concept falling to residue, and `cross_branch_assembly_rate`
reading 0, which is §7.2's stop condition fired by a bug.

The default is shared rather than chosen per caller for the same reason. A caller
that genuinely wants the phonetic string alone passes `include_boundaries=False`
and gets exactly the old behaviour; `tools/correspondence_inventory.py` and
`tools/assembly_ceiling.py` both grew a matching `--boundaries` flag so that the
baselines recorded before this change stay reproducible rather than merely
remembered.

**One collision had to be handled first.** LingPy writes an alignment gap as `-`,
and `-` is one of this repository's two morphological boundaries. Handing one to
the aligner unencoded would read every `-` boundary back as a gap — the same
silent one-token loss, one level down. So a `-` is re-spelled `+` on the way in
(LingPy's SCA maps both to its own morpheme-boundary sound class `_`) and
restored positionally on the way out, and the row's non-gap tokens are checked
against the caller's own segments rather than assumed. It does not arise on any
benchmark checked in here — all 148 Polynesian boundaries are `+` — which is
precisely why it has a test.

##### Whether a boundary is a correspondence: yes, and argued rather than assumed

This is the substantive question and it is not settled by the bug. Making the
aligner see `+` does not by itself make `⟨+ : +⟩` a *correspondence set*; that
follows because `build_correspondence_sets` aggregates every column that is not
all-gap, and nothing was carved out for boundaries. The case for leaving it that
way, in three parts:

- **It is what the evidence is.** A `⟨+ : Ø⟩` set says one child has a boundary
  where another has none, which is exactly the signal `polarize`'s own
  documentation calls decisive: *material added at a morph boundary is innovation
  however well its segments are attested elsewhere.* Until now the harness had no
  way to **show** a session that asymmetry — `polarize` could not be asked about
  a boundary at all, because no correspondence contained one. It can now, and it
  answers: on Polynesian, `⟨+ : Ø⟩` between EastFutuna and EastUvea matches three
  columns in `1233`, `658` and `778`, and reports what all eight out-group nodes
  show in each.
- **It puts the decision where §11.1 put every other one.** The alternative was a
  post-assembly heuristic — put a `+` back where most children had one — and that
  is the harness deciding where morphology goes, on a majority vote, which this
  repository has measured to reconstruct innovations. Reading the evidence and
  naming the value is the model's job. The harness retrieves a column; it does
  not place a morph.
- **The DSL is unaffected, deliberately.** `rules/parser.py` still refuses `+`
  and `-` as rule targets and as insertions, so a derived branch cascade can
  never start rewriting boundaries. `derive_branch_rules` therefore has a fifth
  case: either side a boundary → no rule, and the child recorded in
  `boundary_change_child_ids`. That is the same shape as
  `non_invertible_child_ids` — a fact about what the derived *view* cannot spell,
  never a rejection of the commit, because the form assembles from its columns
  either way. The commonest boundary commitment, `⟨+ : +⟩ → *+`, is an identity
  correspondence and derives nothing at all.

The cost is real and is stated below rather than waved at: more sets, bigger
payloads on the alignment tools, and a `⟨+ : + … +⟩` row occupying space on a
bounded page. The argument is that a dull correspondence that lets a form be
reconstructed beats no correspondence and a form one token short.

##### What it cost and what it bought, measured

All on `runs/benchmarks/polynesian.json`, 2026-08-23, before and after in the
same checkout. `strip` is the old behaviour, `include` the new.

`tools/correspondence_inventory.py --min-support 1`, both readings:

| `--reading` | `--boundaries` | distinct sets | at support ≥ 2 | singletons |
| --- | --- | --- | --- | --- |
| `all` | `strip` | 216 | 41 | 175 |
| `all` | `include` | 237 | 60 | 177 |
| `reported` | `strip` | 218 | 39 | 179 |
| `reported` | `include` | **246** | **50** | 196 |

The 216 and 218 figures are what `docs/analysis_tools.md` recorded, and both
moved. Note where the growth is: `sets_at_min_support` rises by more than a
quarter, from 39 to 50, because boundary correspondences *recur*. They are not
tail noise.

Payload sizes, through the registry over the flat ten-daughter node:

| payload | `strip` | `include` |
| --- | --- | --- |
| `summarize_correspondences`, default page | 17.5 KB | 17.9 KB |
| `test_proto_assembly`, `detail="summary"`, recurrent inventory, all 46 concepts | 23.5 KB | **21.7 KB** |
| the same at `detail="full"` | 75.0 KB | 82.9 KB |
| **the non-compactable half of either** | 1.4 KB | 1.6 KB |
| `get_alignments`, 3 concepts × 10 nodes, `detail="full"` | 151.6 KB | 176.9 KB |

The affordability precondition prompt 01 set holds. The survey grew 3%; the
preview a session actually reads *shrank*, because the recurrent inventory now
covers columns that previously fell to residue and the per-concept reports carry
less; the half a session must carry to its commit went from 1.4 KB to 1.6 KB.
`get_alignments` grew 17%, which is the one figure that got worse — it is also
the call the tool's own docstring already tells a session to prefer
`summarize_correspondences` over. (§12.4's "41 committed sets" beside the 23.5 KB
was a miscount: the run was the 39 sets at `min_support` 2 under `--reading
reported`, and the byte figure reproduces exactly.)

Assembly with a value committed for **every** set, `retain_from_witness`:

| | `strip` | `include` |
| --- | --- | --- |
| sets committed | 218 | 246 |
| `unaccounted_column_rate` | 0.141 | **0.125** |
| `cross_branch_assembly_rate` | 0.783 | 0.761 |
| concepts assembled | 46 of 46 | 46 of 46 |
| assembled forms carrying a boundary | **0 of 46** | **29 of 46** |

The residue rate falls because the denominator grows faster than the numerator:
40 unaccounted columns of 284 becomes 42 of 336. §12.4's account of *where* that
residue is survives the change intact — all 42 columns are in 11 concepts, and
all 11 carry more than one cognate set, 100% as before. The floor is 0.125, and
§7 is where that has to be said.

The last row is the point. Under `strip` no assembled form could carry a
boundary; under `include`, 29 do, including every one of the eight gold concepts
that carry one in every alternative.

And the ceiling the implementation can now actually reach,
`tools/assembly_ceiling.py polynesian --boundaries …`:

| variant | `include` | `strip` |
| --- | --- | --- |
| flat | 43/46 | 38/46 |
| **node-local** | **44/46** | **38/46** |
| node-local cannot reach | `1028`, `778` | `1028`, `1212`, `1217`, `1239`, `1439`, `1741`, `2105`, `778` |

**Six of the eight capped concepts become reachable**: `1212`, `1217`, `1239`,
`1439`, `1741`, `2105`. `1028` and `778` stay out of reach either way, for the
reason §1.2 already gives — a segment no daughter shows — which is what makes the
six attributable to the boundary and to nothing else. Both of §7 condition 3's
boundary-bearing witnesses, `1212` and `1439`, are among them.

##### What a session saw under the instructions that shipped before stage 3

Recorded because it was true and measured, and because the branch-cascade
workflow is still an accepted commit shape: a session that takes it sees
boundary correspondence sets while being taught a DSL that refuses `+` and `-`
as rule targets. That combination was reachable before the instructions flipped
and is reachable now, so it was checked rather than left to be discovered.

A rule about a boundary is refused at the parser: `+ > Ø` and `+ > Ø / #_` give
*"morphological boundaries may constrain context but not be targets"*, `a > a +
a` gives *"rules may not insert morphological boundaries"*. All are
`dsl-parse-error`, which `agent/error_codes.py` classifies **exploratory** — the
model proposed a rule and the parser refused — so none of them counts toward
`high_quality` or toward the stall detector's protocol window. The message names
the problem without a remediation because it is already the whole answer.

That is the right outcome and was not a gap to close before stage 3: the
evidence is visible, acting on it through the wrong mechanism is refused
legibly, and the refusal is free. A boundary is committable through the
inventory shape, and since 2026-08-24 `agent/system_prompt.md` says so — the
Sound Rule DSL section states that a set may take `+` as its `proto_segment`
and that only the *derived* per-branch rule for such a set cannot be written,
which is what `boundary_change_child_ids` reports.

##### Does the ceiling still bound the implementation? Measured, not argued

`tools/assembly_ceiling.py` keeps its own `align_rows` and the harness runs
`LingPyAligner.align_multiple`, and that separation is the point — an instrument
that imported the thing it measures would agree with it by construction. Its
cost is that the two can drift with nothing saying so, which is what this section
is about. So the agreement is now a measurement rather than an inference: walk
the tree bottom-up as the node-local pass does and, at every (node, concept),
align the same rows both ways and compare the column structure.

| | identical column structure | node-local ceiling, instrument | node-local ceiling, harness |
| --- | --- | --- | --- |
| boundaries stripped | 225 of 322 — **69.9%** | 44/46 | **38/46** |
| boundaries included | **322 of 322 — 100%** | 44/46 | **44/46**, same two concepts missed |

The top row is the defect stated exactly: the instrument was reporting a ceiling
of 44/46 for an implementation that could only reach 38/46, and 97 of 322
alignments differed. The bottom row is what makes the 44/46 quotable at all — a
ceiling measured on one alignment does not bound an implementation running
another, whatever the two happen to score.

`tests/workbench/test_oracle_ceiling_regression.py` pins the *property* — every
column the instrument sees is a column the harness sees — rather than those
counts, and fails on the pre-fix aligner naming the first concept that diverges.
It is the test whose absence let this live: no test in the suite compared the two.

##### What did not move, and one thing that quietly became true

`tools/oracle_ceiling.py` is unchanged — 27/46 top-1, 40/46 beam-exact, and the
pinned regression test green — exactly as predicted, because it runs
`RuleBasedReconstructor` over `make_leaf_beam` and never calls
`LingPyAligner.align_multiple`. A movement there would have meant something
unintended had changed.

Two adjacent things had to move with the aligner and did:

- `realign`'s constraint 1 compares the gapless rows of an override against
  `form.segments` rather than `phonetic_segments`. Against the phonetic string an
  override on a boundary-bearing concept could pass the check and then match no
  candidate tuple in `ProtoInventoryAssembler._matching_override`, which compares
  against the children's own beam segments — a second silent divergence of the
  same kind.
- A restoration may cite a boundary an out-group node still shows, for the same
  reason: a boundary is restorable material now, and reading the phonetic string
  there would have exempted the one segment class every child is most likely to
  have lost.

And `segment_morphemes` became load-bearing in a way it was not. The
segmentation overlay ID has always entered every `set_id` digest, but while
boundaries were stripped an overlay changed *only the digest*: the same columns
came back under new names. It now genuinely adds a column, so
`build_correspondence_sets`'s claim that "a segmentation overlay changes what a
segment is" is true of the alignment and not just of the ID. Both halves are
pinned by a test, because the interaction was worth checking rather than
assuming.

#### §7's thresholds quoted the instrument prompt 07 repaired

*Found 2026-08-23, **re-derived 2026-08-23** in the commit after §12.5's boundary
fix, and in that order deliberately: §7's thresholds are stated against
`tools/assembly_ceiling.py`, which aligns with boundaries, while the
implementation ran without them. Re-deriving first would have pinned numbers the
fix immediately invalidated — the mistake §7 had already made once.*

§7 was written before stage 0, against the measurements in §0 and §1.2. Prompt 07
then repaired four defects in `tools/oracle_ceiling.py`, landed
`tools/assembly_ceiling.py`, and re-recorded everything — and nobody re-stated §7
in the repaired instrument's terms. Every threshold in §7.1 was therefore a
pre-repair number:

| §7 condition | as written | re-derived |
| --- | --- | --- |
| 1, expect | top-1 ≥ **39/46** (node-local assembly) | **≥ 44/46** |
| 1, stop if | top-1 < **32/46** (context-sensitive oracle) | **< 33/46** |
| 2, expect | beam-exact ≥ **41/46** | **≥ 40/46**, both oracles' figure |
| 2, stop if | < **40/46** | unchanged at **< 40/46** |
| 4, expect | mean top NED ≤ **0.080** | unchanged — a target below the measure, not a reading of it |
| 4, stop if | mean top NED > **0.110** | **> 0.097** |
| 3, watch | `1212`, `1408`, `1439` convert; `1217` and `1443` cannot | **`1212`, `1217`, `1408`, `1439`, `1443`** convert; `1028` and `778` cannot |

Condition 2 was the one that had gone from demanding to unsatisfiable-as-phrased:
"≥ 41/46" was set one above a then-measured 41, and beam-exact is 40 for both
oracles. Condition 1's "expect" was five concepts too low, so a change could have
cleared it while leaving five reachable concepts on the table.

This is exactly the failure prompt 07 exists to prevent, one level up: *do not
quote an oracle number produced before the repair*. §7 was not wrong about what
to measure — the shape check (top-1 up, reachability not down) and the mechanism
check (`cross_branch_assembly_rate` > 0 somewhere) both stood, and both are
unchanged. Only its numbers were wrong.

Three things the re-derivation needed that were not there:

- **`tools/branch_recoverability.py` gained `--method`.** Condition 3's half (a)
  — "unreachable from any single branch under a context-sensitive oracle" — was
  measured in §0.4 by a script that is not in the repository. A threshold nothing
  can reproduce is not a threshold, so the cascade method now lives in the script
  that owns the question. `--method cascade --oracle contextual` reproduces §0.4's
  40/5/1 and its five concepts exactly; `--method cascade --oracle context_free`
  comes out at 39 against §0.4's 38, which is prompt 07's repairs showing through.
- **§7.2's residue threshold needed a floor.** "Above ~0.3 at most nodes" means
  nothing without knowing what a *complete* inventory leaves behind. On Polynesian
  that is **0.125**, entirely in multi-etymon concepts, so the real headroom is
  0.18. §7.2 now says so, and says how to re-measure it for another family.
- **§7.5 lists every command.** Every figure in §7 is now reproducible from a line
  in the document, which is what the appendix table has always asked of the rest
  of this file.

## Appendix: every figure in this document, and where it came from

All measured 2026-08-21 in this checkout unless the row says otherwise,
`measuring: /Users/acraev/Work/cognate-reconstruction/cognate_reconstruction`.
The §12.5 and §7 rows were measured 2026-08-23, before and after the boundary
fix; where a figure has a before and an after, both are in §12.5 with the flags
that produced them.

| Figure | Source |
| --- | --- |
| 27/46, 39/46, 0.158, 0.043, 0.960 | `tools/oracle_ceiling.py runs/benchmarks/polynesian.json --json`; **pre-repair** — now 27/46, 40/46, 0.147, 0.030, 0.963 |
| 32/46, 41/46, 0.110, 0.020, 0.965 | context-sensitive oracle, this session's script; **pre-repair** — now `--oracle contextual`, 33/46, 40/46, 0.097, 0.024, 0.963 |
| width curve, both oracles | same script, `--widths 1,3,5,10` |
| 38/46 and 40/46 single-daughter reach | same script, cascade-applied per daughter |
| 37 / 8 / 1 | `tools/branch_recoverability.py`, map-applied per daughter |
| 39/46 top-1 and beam-exact, 0.031 NED, 0.957 cross-branch, assembly | `tools/oracle_ceiling.py runs/benchmarks/polynesian.json --oracle assembly --json`, 2026-08-24 |
| 42/46 flat, 39/46 node-local, 46/46 free-choice assembly | this session's `assembly_ceiling.py`; **pre-repair** — now 43/46, 44/46, 46/46 |
| 15/25 and 16/25 on `synthetic_hard` against `proto` | contextual-oracle script with `--gold-node proto` |
| 22/25 as published | `tools/oracle_ceiling.py runs/benchmarks/synthetic_hard.json`, scored against `east` |
| Hawaiian 15/46 → 22/46, total 214 → 221, tree-level unchanged | this session's `order_fix.py`, patching `oracle_ceiling.order_rules` |
| beam-exact 39 → 40 honouring gold alternatives | this session, `compare_to_nearest` over `target_segment_alternatives` |
| North Marquesan 18/46, Tongan 29/46 under the contextual oracle | this session's `contextual_oracle.py`, per branch |
| 0 of 100 node-concepts needing mixing on `synthetic_hard` | this session's `node_mixing.py` over the answer key |
| the 1408 node-by-node trace, and Maori/Rarotongan/Tahitian all getting `r > l` | this session, `oracle_ceiling.build_rules` plus a bottom-up beam trace |
| `*r` in 2 of 46 gold forms, `*l` in 10 | segment counts over the gold binding |
| beam occupancy 1.72 / 2.76 / 3.80 candidates, 43 of 46 concepts > 1 at the root | this session, oracle run with per-node distribution sizes |
| 30 of 46 concepts carrying an alignment-difficulty signal | this session, morph-boundary mismatch or ≥3-token length spread |
| tie-break probe: 66 ties, 29 winnable, 18 / 18 / 23 / 25 | `tools/outgroup_probe.py runs/benchmarks/polynesian.json` |
| per-tool-result sizes and per-turn prompt growth | `runs/google-gemma-4-26b-a4b-20260820-212424`, `trajectories.jsonl` and `events.jsonl` |
| fixed prompt floor: 22.6 KB system + 23.8 KB tool schemas + 2.1 KB payload ≈ 8.8k tokens | same run, message and tool-definition sizes |
| `east` at 22/25 node-local, the three concepts being `leaf`, `tooth`, `tree` | this session's `node_mixing.py` over the answer key |
| correspondence sets and their supports | `tools/correspondence_inventory.py`; figures before 2026-08-23 are `--reading all --boundaries strip` |
| 216 / 237 / 218 / 246 sets across the two readings and the two boundary settings | `tools/correspondence_inventory.py polynesian --reading {all,reported} --boundaries {strip,include} --min-support 1` |
| 44/46 and 38/46 node-local assembly, and the six concepts between them | `tools/assembly_ceiling.py polynesian --boundaries {include,strip}` |
| 0.125 / 0.761 / 46 of 46, and 42 unaccounted columns of 336 in 11 multi-etymon concepts | every set the survey returns committed through `test_proto_assembly`, post-boundary-fix; §12.5 |
| payload sizes before and after the boundary fix | the same registry calls, in one checkout, both settings; §12.5 |
| 322 of 322 column agreement, against 225 of 322 stripped | the node-local walk run through both aligners; pinned as a property by `test_oracle_ceiling_regression.py` |
| §7's re-derived thresholds: 44/46, 33/46, 40/46, 0.097 | `tools/oracle_ceiling.py … --oracle contextual --json` and `tools/assembly_ceiling.py … --json`, 2026-08-23; §7.5 lists every command |
| §7.4's 37/8/1, 39/6/1 and 40/5/1 | `tools/branch_recoverability.py polynesian --method {map,cascade} --oracle {context_free,contextual}` |
| forms for 1205, 1355, 1215, 1028, 1217, 1443, 778 | `runs/benchmarks/polynesian.json` |
| 21/46, 31/46, 0.214, 0.081, 0.950 live | `docs/benchmarks.md`, run `runs/google-gemma-4-26b-a4b-20260820-212424`, quoted not re-measured |
| suite at 320 | `pytest -q -k "not local_run_artifacts"` |
| §7.10's three-oracle table: 40/27/0.283/0.147, 40/33/0.152/0.097, 39/39/0.000/0.031 | `tools/oracle_ceiling.py runs/benchmarks/polynesian.json [--oracle {contextual,assembly}] --json`, re-measured 2026-08-28; the assembly row reproduces the 2026-08-24 row above exactly |
| §7.10's `d1` record: `p > b` committed, precision 0.0, recall `None`, functional 0.8 | `score-synthetic --answer-key runs/benchmarks/synthetic_hard.answer-key.json --run-dir runs/sweeps/synthetic_hard-after-r2/seed-00`, 2026-08-28 |
| §7.10's commit rate: 1.875 ± 0.835 → 3.000 ± 0.000 (`synthetic_hard`), 4.33 ± 0.58 → 4.00 ± 1.00 (`polynesian`, complete seeds) | counts over `runs/sweeps/*/seed-*/trajectories.jsonl`; committed = `committed_reconstruction` non-null and `completed` true; §7.5 states the exclusion rule |
| §7.10's failure-mode inversion: Polynesian 6/2 before against 0/13 after | `failure` field of the same trajectories, 2026-08-28 |
| §7.11's replay: 112 polarize calls, 41 gap-bearing, 8 refused then, 41/41 accepted now | `test_every_gap_bearing_polarize_the_model_wrote_is_accepted_now`, 2026-08-28 |
| §7.12's repair rate: 12 of 14 named sets fixed | consecutive `commitment 'cs-…'` names in the rejections of one node, `runs/sweeps/polynesian-after*`, 2026-08-28 |
| §7.12's stall replay: 13 of 13 old rule, 12 of 13 new rule | each stalled node's signature sequence rebuilt from its recorded payloads and run through both rules, 2026-08-28 |
| §7.13's seven misses and the five-concept gap | `tools/oracle_ceiling.py runs/benchmarks/polynesian.json --oracle assembly` (its own "first 12 misses" block) against `tools/assembly_ceiling.py … --json`, 2026-08-28 |
| §7.13's daughter length spreads | segment counts per concept over `runs/benchmarks/polynesian.json`, 2026-08-28 |
| suite at 439 | `pytest -q -k "not local_run_artifacts"`, 2026-08-28 |
