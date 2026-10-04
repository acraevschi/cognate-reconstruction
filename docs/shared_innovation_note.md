# Shared innovations, and what the supplied tree does not encode

> **Deferred historical proposal; not implemented as of 2026-09-15.**
> The inventory infrastructure now exists, and both commit shapes remain supported.
> Stage 4 was cancelled; the original sequencing/deletion argument below is obsolete.
> This proposal is outside the immediate [research plan](research_plan.md).
> Existing cross-node reports are not the three reports proposed here.
> Before implementing, revisit the linguistic claim: a shared child-to-parent
> rewrite is a model claim about a correspondence, not by itself evidence of a
> shared historical innovation. Parallel changes, direction and conditioning need
> consideration. Keep any such observation report-only.
>
> Written 2026-08-23 against `76cdd0b`; retained for its design discussion.

## 1. The question nothing in the harness answers

Only **shared innovations** define subgroups. Shared retentions do not: two
languages both keeping `*t` tell you nothing about whether they form a clade,
because every language that has not changed looks alike. This is the single
oldest discipline in the comparative method and the harness currently has no
view of it.

It has the neighbouring views. `polarize` retrieves what the rest of the tree
shows where the children disagree, and refuses to say which value is original.
`directionality_rationale` records which branch the model claims innovated, and
is rejected on absence. `contrast.py` proves mechanically which commitments
discard material. What is missing is the aggregate: **given everything committed
across the run, which innovations are shared by which children, and by which
proper subsets of them.**

## 2. Why it becomes nearly free

`docs/proto_inventory_design.md` §4.2 persists `derived_rules` on
`CommittedProtoInventory`, and §4.3 derives them per child: for each commitment
and each child `c`, the rule `r_c > p` under the set's conditioning. A derived
rule *is* an innovation on the edge from this node to that child — that is what
"derived" means here, and it is why nothing in this note needs a new
computation, a new tool, or a new model-facing surface.

`ReconstructionRule.source_child_ids` already names the scope. So every
observation below is set arithmetic over one committed object, per node:

```
P.derived_rules → for each rule: (rule.source, set(rule.source_child_ids))
P's children    → named by the rules themselves, or by the reconstruction step
```

No tree walk, no second pass, no inference.

## 3. The observations

Three kinds, each a line of set arithmetic, each landing in the existing
`cross_node_observations` extension point in `inspect_run.py` — which already
has per-kind capping, the text renderer, and the HTML renderer.

### 3.1 `shared_innovation` — the payload

> A derived rule at node `P` scoped to a **proper subset** of `P`'s children:
> at least two of them, but not all.

This is the one worth building the note for. If the supplied classification
already grouped those children, they would sit under a single node and `P` would
never see them separately. So an innovation shared by two of `P`'s five children
is **evidence for a subgroup the supplied tree does not encode.**

It is most informative exactly where the harness is already most careful. A
development invariant says *retain native polytomies unless a research decision
explicitly resolves them*; this observation says which children of an unresolved
polytomy share innovations — which is to say, where that polytomy might resolve,
and on what evidence. That it stays an observation and never resolves anything
is the point (§5).

### 3.2 `undifferentiated_child` — the edge that carries nothing

> A child of `P` with **zero** derived rules.

That edge carries no innovation in this reconstruction: the child is supported
by retention alone. For an internal child it is the sharper reading — an
internal node whose edge carries no innovation is a node this run gives no
positive evidence for.

**This is not a claim that the tree is wrong, and the wording must not imply it
is.** A genuinely conservative branch produces exactly this output and is
correct. So does a node whose innovations are all in material this run's
inventory did not cover. Both are ordinary. See §5.

### 3.3 `universal_innovation` — the change that may belong one edge up

> A derived rule at `P` scoped to **every** one of `P`'s children.

Every child changed the same way from the reconstructed parent. Two readings,
and the harness cannot choose between them: the change happened once before `P`
split and belongs on `P`'s own edge, or it happened independently in each
branch.

It has a mechanical companion worth reporting on the same line, because it falls
out of the same read and is the same claim seen from the other side: commitments
where `proto_segment` is **not among** `reflexes`. §4.1 deliberately permits
these and the benchmark needs them — Proto-Polynesian `*w` in concept `1028` is
attested as `v` or as nothing in every daughter, `*f` in `778` as `s` or `h`.
They are legitimate and they are also the claims that most need out-group
support, so they should be visible rather than inferred by a reader diffing two
tuples by eye.

## 4. The one change outside `inspect_run.py`

`CommittedRuleView` (`inspect_run.py:172`) flattens a committed rule to
`node_id, rule_id, source, target, replacement, environment, confidence`. It
drops `source_child_ids`, which is the field every observation here needs.

Add it. Note that `committed_rule_views` must already learn to read an
inventory's `derived_rules` under the proto-inventory change — prompt 08 carries
that as a required fix, because otherwise all three *existing* cross-node
observations go blank on every 3.0 run. This note's prerequisite is therefore
already someone else's work, and adding one field to the view is the whole of
the remaining plumbing.

## 5. Report, reject, or score

Applying `docs/report_reject_or_score.md`'s decision rule.

**All three are reports.** None rejects, none scores, none reaches
`high_quality`, none weights a candidate, none filters a trajectory, and none
changes traversal or the supplied tree.

Run each through the question in the pocket — *what happens when this fires on a
correct run?*

| observation | on a correct run |
| --- | --- |
| `shared_innovation` | fires whenever two branches genuinely underwent the same change, including by parallel innovation, which is common and correct |
| `undifferentiated_child` | fires on every conservative branch, and on any node whose innovations lie outside the committed inventory |
| `universal_innovation` | fires on every change that predates a split, which is the ordinary case for a well-supported node |

All three fire on correct runs. That is decisive: all three are printed and none
is consumed.

**The specific thing this must never do is adjudicate parallel innovation.** A
rule shared by children `X` and `Y` is indistinguishable, by arithmetic alone,
from two independent changes that happened to coincide. Telling them apart means
knowing which sound changes are common enough to recur — which is typology data,
which is refused outright by prompt 04, design §10, and the invariant in prompt
08. The harness reports the coincidence and names the children; a comparative
linguist decides whether it is a synapomorphy or a drift.

The external review's framing — *"alerts the linguist if an internal node is
supported only by retentions, indicating the tree topology itself may be
cladistically unjustified"* — is therefore accepted in its first half and
rejected in its second. Print which edges carry no innovation. Do not conclude
anything about the topology, and do not word the line as though the harness has.

## 6. Original sequencing rationale (superseded)

Under the branch-cascade path the committed rules are whole-string rewrites
scoped to branches, and "which children share an innovation" is a question about
rule *ordering* as much as rule content — §2.2 of the design is the argument
that ordering stops being load-bearing only after the change. Building this
first would mean building it twice and deleting the first one at stage 4.

After stages 1–2 the input is a persisted `derived_rules` tuple with explicit
per-child scope, and the whole note is a read.

Sequence: land session B, land session C's measurement, then build this. It has
no deadline of its own — nothing here enters a tool result or a persisted
schema, so unlike the two additions recorded in prompt 08 it cannot be made
harder by waiting.

## 7. How anyone would know whether it worked

Weak conditions, because a reporting change earns weak conditions.

- **It fires at all.** On Polynesian, at least one node reports a
  `shared_innovation` over a proper subset of its children. If every node
  reports none, either the tree is fully resolved with respect to everything the
  inventories committed — possible, and worth knowing — or the scope field is
  not being populated the way §4.3 implies. Check which before concluding
  anything.
- **It agrees with `polarize` where both have an opinion.** A `shared_innovation`
  among children that `polarize` shows the out-group contradicting is a case
  worth reading by hand; a systematic disagreement is a defect in one of the two.
- **It does not fire on the root.** At the root every other node is a descendant
  and nothing lies outside, which is already the rule `polarize` states. A root
  observation claiming subgroup evidence is a bug.

What would make it not worth keeping: if the observations are dominated by
`universal_innovation` lines that every reader learns to skip, it is noise with a
per-kind cap and should be cut back to `shared_innovation` alone.

## 8. Cost

One field on `CommittedRuleView`, three functions shaped like
`_confidence_spread_observations`, their entries in the tuple at
`cross_node_observations:391`, and tests. The renderers, the capping, and the
`inspect-run` sections already exist and do not change.

Small enough that the reason it is a separate change is not its size. It is that
prompt 08's boundaries are hard stops, and session B is already the largest
session in that plan.
