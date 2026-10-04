"""Oracle ceiling for the deterministic reconstruction layer.

Gives every branch the best child-to-parent rule set that a chosen oracle can
write, computed against the withheld gold proto-forms, then runs the real
`RuleBasedReconstructor` bottom-up. This measures the harness, not the model:
it is the accuracy a flawless hypothesis manager would obtain.

Two numbers matter, and it is the gap between them that this exists to watch:

    top   -- the parent form the beam actually reports
    beam  -- whether the correct form is anywhere in the beam at all

A large gap means the combination/selection step is discarding answers the
system already computed.

**Three oracles, and they are not interchangeable.** `--oracle context_free` is
the original: one target per source segment, globally, which is strictly weaker
than the DSL. Every baseline recorded in `docs/analysis_tools.md` and every
figure pinned by the regression test was measured with it, so it keeps its
identity and stays the default. `--oracle contextual` searches the DSL's own
environment vocabulary as well, and is >= the context-free measure per branch by
construction. It lands *beside* the first, never in place of it: silently
redefining the default would make every recorded before/after uncomparable,
which is the failure `tools/_bootstrap.py` exists to prevent at one remove.

`--oracle assembly` asks the same question of the other architecture. There is
no per-branch cascade to write: the committed object is one proto-phoneme per
correspondence set at a node, and the parent form is assembled column by column
from the children's beams by the real `ProtoInventoryAssembler`. So the number
is not comparable to the two above by subtraction -- the two beams contain
different kinds of thing, which `docs/proto_inventory_design.md` §7.3 says in as
many words -- and it is reported beside them because during the migration both
architectures exist and a reader needs the before and the after in one place.

None of the three is a target. An oracle bounds the architecture and a miss
under one is not a structural limit -- see the note on the contextual builder
below, and the two claims `oracle_commitments` deliberately withholds.

`measure()` is importable by the regression test in `tests/workbench`, so the
number the suite pins and the number this script prints come from one
implementation. The script stays the runnable form for the full benchmark.

Usage:
    python tools/oracle_ceiling.py <benchmark-input.json> [--beam-width 5]
    python tools/oracle_ceiling.py polynesian --json
    python tools/oracle_ceiling.py polynesian --oracle contextual
    python tools/oracle_ceiling.py polynesian --oracle assembly
    python tools/oracle_ceiling.py synthetic_hard --gold-node east
"""

from __future__ import annotations

import argparse
import collections
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import _bootstrap  # noqa: F401  (bind to this checkout; see module)

from cognate_reconstruction.alignment.environments import (
    WORD_EDGE_TOKEN,
    context_tokens,
    environment_matches,
    readings_from,
)
from cognate_reconstruction.evaluation.metrics import compare_to_nearest
from cognate_reconstruction.rules.engine import RuleEngine
from cognate_reconstruction.rules.parser import parse_rule, NoOpRuleError
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.schemas.lexicon import LexicalForm
from cognate_reconstruction.schemas.inventory import (
    CommitProtoInventoryArgs,
    CommittedProtoInventory,
    CorrespondenceCommitment,
    ResiduePolicy,
    derive_set_id,
)
from cognate_reconstruction.schemas.rules import (
    ReconstructionRule,
    RuleEnvironment,
    SegmentExpression,
)
from cognate_reconstruction.traversal.assembler import (
    ProtoInventoryAssembler,
    build_plan,
)
from cognate_reconstruction.traversal.beam import make_leaf_beam
from cognate_reconstruction.traversal.reconstructor import RuleBasedReconstructor
from cognate_reconstruction.tree import assign_node_ids, parse_newick, postorder_groups

CONTEXT_FREE = "context_free"
CONTEXTUAL = "contextual"
ASSEMBLY = "assembly"

BRANCH_ORACLES = (CONTEXT_FREE, CONTEXTUAL)
"""The two that write a per-branch rewrite cascade.

`assembly` is not among them and cannot be: it commits one value per
correspondence set at a node, which is not a property of any single branch.
`tools/branch_recoverability.py` asks a per-branch question and offers these.
"""

ORACLES = (*BRANCH_ORACLES, ASSEMBLY)


def align_pair(left: tuple[str, ...], right: tuple[str, ...]):
    """SCA-align two token sequences, returning both rows with None for gaps."""
    from lingpy import Multiple

    multiple = Multiple([list(left), list(right)])
    multiple.prog_align(model="sca", mode="global")
    rows = [
        [None if token == "-" else str(token) for token in row]
        for row in multiple.alm_matrix
    ]
    return rows[0], rows[1]


def oracle_map(forms: dict[str, tuple[str, ...]], gold: dict[str, tuple[str, ...]]):
    """Best single-valued segment map from these forms onto the gold forms."""
    counts: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter
    )
    for concept_id, segments in forms.items():
        if concept_id not in gold:
            continue
        source_row, gold_row = align_pair(segments, gold[concept_id])
        for source, target in zip(source_row, gold_row, strict=True):
            if source is not None:
                counts[source][target] += 1
    return {
        source: counter.most_common(1)[0][0] for source, counter in counts.items()
    }


def _order_sources(produced: dict[str, set[str | None]]) -> list[str]:
    """Order rule sources so no source's output is consumed by a later rule.

    The general form of `order_rules`, taking every replacement a source's rules
    emit rather than a single one, because the contextual oracle writes several
    rules per source. A source is free to be emitted once nothing it produces is
    still a pending source.
    """
    remaining = dict(produced)
    ordered: list[str] = []
    while remaining:
        free = [
            source
            for source, targets in remaining.items()
            if not ((targets - {source}) & remaining.keys())
        ]
        if not free:
            # Cycle: emit the rest in a stable order and let the caller see the
            # damage rather than silently pretending the oracle was clean.
            print(
                f"  [cycle] unorderable rules dropped: {sorted(remaining)}",
                file=sys.stderr,
            )
            break
        for source in sorted(free):
            ordered.append(source)
            remaining.pop(source)
    return ordered


def order_rules(mapping: dict[str, str | None]) -> list[tuple[str, str | None]]:
    """Order x>y rules so no rule consumes another rule's output.

    Rules are an ordered cascade, so a rule mapping k>t placed before one
    mapping t>s would turn every original k into s. A rule whose target is
    another rule's replacement must therefore run first. Cycles (a true swap)
    cannot be expressed without a scratch symbol and are dropped.

    So the documented example orders the chain shift from its far end:

        order_rules({"k": "t", "t": "s"})  ->  [("t", "s"), ("k", "t")]

    This ran backwards from `febf03b` to 2026-08-22 -- it emitted a source once
    nothing mapped *into* it, which is the other direction -- and cost Hawaiian
    seven of 46 forms, because `*t > k` and `*k > ʔ` make its oracle map a chain
    shift and the reversed order turned `ʔ a k a` into `t a t a` rather than
    gold `k a t a`. `tests/workbench/test_oracle_ceiling_regression.py` now pins
    this docstring's own example.
    """
    changing = {
        source: target for source, target in mapping.items() if source != target
    }
    order = _order_sources({source: {target} for source, target in changing.items()})
    return [(source, changing[source]) for source in order]


BOUNDARIES = {"+", "-"}


def _render(source: str, target: str | None, environment: "Environment | None") -> str:
    change = f"{source} > {target if target else 'Ø'}"
    if environment is None:
        return change
    left = " ".join(part for part in (
        "#" if environment.word_initial else "", environment.left or "",
    ) if part)
    right = " ".join(part for part in (
        environment.right or "", "#" if environment.word_final else "",
    ) if part)
    return f"{change} / {left}_{right}"


def _rule(child_id: str, text: str) -> ReconstructionRule | None:
    try:
        parsed = parse_rule(text)
    except (NoOpRuleError, ValueError):
        return None
    return ReconstructionRule(
        rule=parsed, source_child_ids=(child_id,), confidence=1.0
    )


def _writable(mapping: dict[str, str | None]) -> dict[str, str | None]:
    # Morphological boundaries may constrain a context but cannot be targets or
    # replacements, so the oracle simply cannot touch them. That is a real limit
    # of the DSL and is left visible rather than worked around.
    return {
        source: target
        for source, target in mapping.items()
        if source not in BOUNDARIES and target not in BOUNDARIES
    }


def build_rules(child_id: str, mapping: dict[str, str]) -> list[ReconstructionRule]:
    """The context-free cascade: one rule per changed source segment."""
    rules = []
    for source, target in order_rules(_writable(mapping)):
        rule = _rule(child_id, _render(source, target, None))
        if rule is not None:
            rules.append(rule)
    return rules


# --------------------------------------------------------------------------
# The context-sensitive oracle.
#
# A rule writer as strong as the rule language, which the context-free one is
# not. It exists to keep "the architecture cannot reach this form" from being
# asserted on the strength of a measure that was never able to say it.
#
# It is also emphatically not a plausible analysis: on Polynesian it writes
# several times as many rules as the context-free oracle, many conditioned on a
# single word. That is what an oracle is for -- it bounds the architecture and
# is not a target. Quoting its top-1 as "what a good model should get" is the
# same category error as quoting a context-free miss as a structural limit.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Environment:
    """One environment the DSL can spell, over single tokens and word edges."""

    left: str | None = None
    right: str | None = None
    word_initial: bool = False
    word_final: bool = False

    @property
    def parts(self) -> int:
        return sum(
            (self.left is not None, self.right is not None,
             self.word_initial, self.word_final)
        )


@dataclass(frozen=True)
class Occurrence:
    """One aligned column, with the child-side neighbours a rule could name."""

    target: str | None
    left: str | None
    right: str | None
    word_initial: bool
    word_final: bool

    def matches(self, environment: Environment) -> bool:
        if environment.word_initial and not self.word_initial:
            return False
        if environment.word_final and not self.word_final:
            return False
        if environment.left is not None and self.left != environment.left:
            return False
        if environment.right is not None and self.right != environment.right:
            return False
        return True


def observe(
    forms: dict[str, tuple[str, ...]], gold: dict[str, tuple[str, ...]]
) -> dict[str, list[Occurrence]]:
    """Every source segment's aligned gold target, with its child-side context.

    Neighbours are read from the child form itself, not from the aligned row:
    the rule engine matches contexts against the form it is applying to, and a
    gap in the alignment is not a token there.
    """
    occurrences: dict[str, list[Occurrence]] = collections.defaultdict(list)
    for concept_id, segments in forms.items():
        if concept_id not in gold:
            continue
        source_row, gold_row = align_pair(segments, gold[concept_id])
        index = -1
        for source, target in zip(source_row, gold_row, strict=True):
            if source is None:
                continue
            index += 1
            occurrences[source].append(
                Occurrence(
                    target=target,
                    left=segments[index - 1] if index > 0 else None,
                    right=(
                        segments[index + 1]
                        if index + 1 < len(segments)
                        else None
                    ),
                    word_initial=index == 0,
                    word_final=index + 1 == len(segments),
                )
            )
    return dict(occurrences)


def candidate_environments(occurrences: list[Occurrence]) -> list[Environment]:
    """The bounded space this oracle searches: what the DSL can actually spell.

    Word-initial, word-final, a single left token, a single right token, and the
    four two-part combinations of those. Multi-token contexts are expressible
    and deliberately not searched -- the space is bounded so the oracle stays a
    measurement rather than a search problem.
    """
    lefts = sorted({item.left for item in occurrences if item.left is not None})
    rights = sorted({item.right for item in occurrences if item.right is not None})
    environments = [
        Environment(word_initial=True),
        Environment(word_final=True),
        *(Environment(left=left) for left in lefts),
        *(Environment(right=right) for right in rights),
        Environment(word_initial=True, word_final=True),
        *(Environment(word_initial=True, right=right) for right in rights),
        *(Environment(left=left, word_final=True) for left in lefts),
        *(
            Environment(left=left, right=right)
            for left in lefts
            for right in rights
        ),
    ]
    return environments


def conditioned_rules(
    source: str, occurrences: list[Occurrence]
) -> tuple[list[tuple[str | None, Environment]], str | None]:
    """Conditioned splits of one source segment, plus its unconditioned default.

    An environment is usable only if it is *pure*: every occurrence it matches
    shares one gold target. A mixed environment would be a rule that is wrong
    somewhere it fires, and the point of an oracle is to be right wherever it
    can be, not to guess.
    """
    default = collections.Counter(
        item.target for item in occurrences
    ).most_common(1)[0][0]
    exceptions = [item for item in occurrences if item.target != default]
    if not exceptions:
        return [], default

    usable: list[tuple[int, int, str, str | None, Environment]] = []
    for environment in candidate_environments(occurrences):
        matched = [item for item in occurrences if item.matches(environment)]
        if not matched:
            continue
        targets = {item.target for item in matched}
        if len(targets) != 1:
            continue
        target = targets.pop()
        if target == default:
            continue
        usable.append(
            (-len(matched), -environment.parts, _render(source, target, environment),
             target, environment)
        )

    selected: list[tuple[str | None, Environment]] = []
    covered: set[int] = set()
    outstanding = {id(item) for item in exceptions}
    for _, _, _, target, environment in sorted(usable, key=lambda item: item[:3]):
        matched = {
            id(item) for item in exceptions if item.matches(environment)
        }
        if not matched - covered:
            continue
        selected.append((target, environment))
        covered |= matched
        if covered >= outstanding:
            break
    # Most specific first: every selected environment is pure over the observed
    # data, but two of them can still overlap on a token the cascade produces
    # later, and the narrower statement is the one that should win there.
    selected.sort(key=lambda item: -item[1].parts)
    return selected, default


def build_contextual_rules(
    child_id: str, forms: dict[str, tuple[str, ...]], gold: dict[str, tuple[str, ...]]
) -> list[ReconstructionRule]:
    """A cascade using the DSL's environments, ordered by the same feeding rule."""
    observations = observe(forms, gold)
    conditioned: dict[str, list[tuple[str | None, Environment]]] = {}
    defaults: dict[str, str | None] = {}
    for source, occurrences in observations.items():
        if source in BOUNDARIES:
            continue
        splits, default = conditioned_rules(source, occurrences)
        # A boundary cannot be a replacement, though it may still condition one.
        splits = [item for item in splits if item[0] not in BOUNDARIES]
        if default in BOUNDARIES:
            default = source
        conditioned[source] = splits
        defaults[source] = default

    produced = {
        source: {defaults[source], *(target for target, _ in conditioned[source])}
        for source in defaults
        if defaults[source] != source or conditioned[source]
    }
    rules: list[ReconstructionRule] = []
    for source in _order_sources(produced):
        for target, environment in conditioned[source]:
            rule = _rule(child_id, _render(source, target, environment))
            if rule is not None:
                rules.append(rule)
        rule = _rule(child_id, _render(source, defaults[source], None))
        if rule is not None:
            rules.append(rule)
    return rules


def _apply(rules: list[ReconstructionRule], forms: dict[str, tuple[str, ...]]):
    lexical = [
        LexicalForm(
            form_id=f"probe:{concept_id}",
            variety_id="probe",
            concept_id=concept_id,
            segments=segments,
        )
        for concept_id, segments in sorted(forms.items())
    ]
    produced, _ = RuleEngine().apply_rules(
        [rule.rule for rule in rules], lexical
    )
    return {form.concept_id: form.segments for form in produced}


def _exact(
    produced: dict[str, tuple[str, ...]],
    gold_alternatives: dict[str, tuple[tuple[str, ...], ...]],
) -> int:
    return sum(
        1
        for concept_id, segments in produced.items()
        if segments in gold_alternatives.get(concept_id, ())
    )


def branch_rules(
    child_id: str,
    forms: dict[str, tuple[str, ...]],
    gold: dict[str, tuple[str, ...]],
    gold_alternatives: dict[str, tuple[tuple[str, ...], ...]],
    oracle: str,
) -> tuple[list[ReconstructionRule], bool]:
    """This branch's cascade, and whether the contextual builder fell back.

    The contextual oracle is >= the context-free one per branch *by
    construction* and not by argument: where its extra rules would score fewer
    exact forms on this branch, the context-free cascade is used instead. A
    measure that claimed to be a superset and was not would be worse than no
    measure.
    """
    if oracle == ASSEMBLY:
        raise SystemExit(
            "the assembly oracle commits one value per correspondence set at a "
            "node and writes no per-branch cascade; ask it of a node, not of a "
            f"branch. Per-branch oracles: {BRANCH_ORACLES}"
        )
    context_free = build_rules(child_id, oracle_map(forms, gold))
    if oracle == CONTEXT_FREE:
        return context_free, False
    contextual = build_contextual_rules(child_id, forms, gold)
    if _exact(_apply(contextual, forms), gold_alternatives) < _exact(
        _apply(context_free, forms), gold_alternatives
    ):
        return context_free, True
    return contextual, False


# --- the assembly oracle -------------------------------------------------
#
# The same question the two above ask -- "what would a flawless hypothesis
# manager score?" -- put to the architecture `docs/proto_inventory_design.md`
# proposes. There the committed object is not a per-branch cascade but one
# proto-phoneme per correspondence set at a node, and the parent form is
# assembled from the children's aligned columns rather than selected from a
# beam of whole strings. So the oracle changes shape and the question does not,
# which is exactly what §9.3 asks for.
#
# **Two things the oracle is deliberately not given**, because both are
# per-concept claims and an inventory is a general one:
#
#   restorations       -- a gold segment no column produced. Polynesian `1028`
#                         YAWN wants a `w` no daughter shows anywhere, and a
#                         `restorations` entry could hand it over. Granting them
#                         would measure the gold strings, not the inventory, and
#                         §7.4 records `1028` and `778` as concepts the ceiling
#                         cannot promise. They stay unpromised.
#   residue dispositions -- the same objection, one column at a time.
#
# What it *is* given is the two general claims the schema carries: one value per
# set, and a residue policy. The policy is chosen per node the way
# `branch_rules` chooses per branch -- by running both and keeping whichever
# scores more exact forms -- because "what happens to material my inventory does
# not explain" is a claim about the node, not about a concept.

def column_targets(
    options: Sequence[frozenset[str]], gold: tuple[str, ...]
) -> tuple[int, tuple[str | None, ...]]:
    """Which gold segment each column should emit, and what the choice cost.

    A column emits one proto-phoneme or nothing, left to right, and the
    concatenation is the parent form -- so reaching a gold form is an assignment
    problem over the columns rather than a search over strings. This returns the
    cheapest assignment, under the same cost model
    `tools/assembly_ceiling.py::assemble` uses, because the two instruments
    should disagree about the architecture and not about arithmetic:

        0  a column emitting a segment its own reflexes attest, and a column
           emitting nothing. Both are what a correspondence ordinarily does.
        1  a column emitting a segment none of its reflexes attests. Legal --
           `*w` in Polynesian `1028` YAWN is why `proto_segment` is not
           restricted to `reflexes` -- and priced so the oracle reaches for it
           only where nothing attested will do.
        1  a gold segment no column covers. Only a `restorations` entry produces
           one and the oracle commits none, so this records a miss rather than
           taking a transition.

    **Pricing the unattested emission at 1 rather than at "cheaper than a miss"
    is the whole of it.** Charged less, the DP will scatter a short gold form
    across whichever columns come first -- on Polynesian `1237` WHERE it put
    `f e a` into the three columns of Tongan's `ʔ i +` prefix, at three
    unattested emissions, rather than leave one gold segment uncovered. Every
    column then votes for a phoneme it has no relation to, and the inventory
    built from those votes is noise wearing the shape of a measurement.

    Ties go first to the assignment that emits more -- a node that cannot reach
    gold still hands its material to the node above, and discarded material
    cannot be recovered there -- and then to the one whose emitting columns are
    furthest left, which is arbitrary and is the last resort for that reason.
    """
    width, length = len(options), len(gold)
    ceiling = (length + 1, 0, 0)
    best = [[ceiling] * (length + 1) for _ in range(width + 1)]
    back: list[list[tuple[int, int, str | None] | None]] = [
        [None] * (length + 1) for _ in range(width + 1)
    ]
    best[0][0] = (0, 0, 0)

    def offer(row, column, score, origin):
        if score < best[row][column]:
            best[row][column] = score
            back[row][column] = origin

    for index in range(width + 1):
        for consumed in range(length + 1):
            cost, emitted, tie = best[index][consumed]
            if (cost, emitted, tie) >= ceiling:
                continue
            if index < width:
                # Emit nothing from this column.
                offer(
                    index + 1, consumed, (cost, emitted, tie), (index, consumed, None)
                )
                if consumed < length:
                    wanted = gold[consumed]
                    penalty = 0 if wanted in options[index] else 1
                    offer(
                        index + 1,
                        consumed + 1,
                        (cost + penalty, emitted - 1, tie + index),
                        (index, consumed, wanted),
                    )
            if consumed < length:
                # A gold segment no column produced.
                offer(
                    index,
                    consumed + 1,
                    (cost + 1, emitted, tie),
                    (index, consumed, ""),
                )

    assignment: list[str | None] = [None] * width
    position = (width, length)
    while position != (0, 0):
        origin = back[position[0]][position[1]]
        if origin is None:
            break
        previous_index, previous_consumed, token = origin
        if token and previous_index < position[0]:
            assignment[previous_index] = token
        position = (previous_index, previous_consumed)
    return best[width][length][0], tuple(assignment)


def _live_columns(
    rows: Sequence[Sequence[str | None]],
) -> list[tuple[int, tuple[str | None, ...]]]:
    """The columns assembly will resolve, each with its index in the alignment.

    An all-gap column is skipped, because `assembler.resolve_columns` skips it
    and no correspondence set can name it -- but its *index* still matters,
    because `alignment/environments.py` walks the alignment by absolute index.
    Building the inventory over a different set of columns from the one assembly
    resolves is the defect §12.3 and §12.5 each found once; it is not worth
    finding a third time.
    """
    width = max((len(row) for row in rows), default=0)
    live = []
    for index in range(width):
        reflexes = tuple(
            row[index] if index < len(row) else None for row in rows
        )
        if any(segment is not None for segment in reflexes):
            live.append((index, reflexes))
    return live


@dataclass(frozen=True)
class ColumnEvidence:
    """One concept's alignment at a node, and what gold wants in each column."""

    rows: tuple[tuple[str | None, ...], ...]
    live: tuple[tuple[int, tuple[str | None, ...]], ...]
    wanted: tuple[str | None, ...]
    scored: bool
    """Whether this concept carries gold. An unscored concept still shows its
    columns -- they count toward support -- and votes for nothing."""


def column_evidence(
    child_node_ids: Sequence[str],
    forms_by_child: dict[str, dict[str, tuple[str, ...]]],
    gold_alternatives: dict[str, tuple[tuple[str, ...], ...]],
    assembler: ProtoInventoryAssembler,
) -> tuple[ColumnEvidence, ...]:
    """Align this node's children once, and price every column against gold.

    The alignment comes from `assembler.align_candidate_tuple`, not from a
    second aligner written here, so the columns voted on are the columns
    assembly resolves.
    """
    plan = build_plan(child_node_ids, (), residue_policy=ResiduePolicy.DROP)
    cache: dict[tuple, tuple[tuple[str | None, ...], ...]] = {}
    concept_ids = sorted(
        {
            concept_id
            for child_id in child_node_ids
            for concept_id in forms_by_child.get(child_id, {})
        }
    )
    evidence: list[ColumnEvidence] = []
    for concept_id in concept_ids:
        segments_by_child = {
            child_id: forms_by_child[child_id][concept_id]
            for child_id in child_node_ids
            if concept_id in forms_by_child.get(child_id, {})
        }
        if not segments_by_child:
            continue
        rows = assembler.align_candidate_tuple(
            concept_id, segments_by_child, plan, cache
        )
        live = tuple(_live_columns(rows))
        targets = gold_alternatives.get(concept_id)
        if targets is None:
            evidence.append(
                ColumnEvidence(
                    rows=tuple(rows),
                    live=live,
                    wanted=(None,) * len(live),
                    scored=False,
                )
            )
            continue
        options = [
            frozenset(segment for segment in reflexes if segment is not None)
            for _, reflexes in live
        ]
        _, assignment = min(
            (column_targets(options, target) for target in targets),
            key=lambda item: item[0],
        )
        evidence.append(
            ColumnEvidence(
                rows=tuple(rows), live=live, wanted=assignment, scored=True
            )
        )
    return tuple(evidence)


def _pick(tally: collections.Counter) -> str | None:
    """The set's value: most columns first, then a segment over a deletion.

    A deletion is the stronger claim and a tie is no evidence for it. Ties after
    that go lexicographic, which is arbitrary and is the last resort for that
    reason.
    """
    return sorted(
        tally.items(), key=lambda item: (-item[1], item[0] is None, item[0] or "")
    )[0][0]


def unconditioned_values(
    evidence: Sequence[ColumnEvidence],
) -> tuple[dict[tuple[str | None, ...], str | None], collections.Counter]:
    """One proto-phoneme per correspondence set, and how many columns show it.

    The per-set analogue of `oracle_map`, and single-valued for the same reason:
    a commitment carries one value per (set, conditioning) pair, so the best an
    unconditioned inventory can do is the value that reaches gold in the most
    columns showing that set.
    """
    votes: dict[tuple[str | None, ...], collections.Counter] = (
        collections.defaultdict(collections.Counter)
    )
    support: collections.Counter = collections.Counter()
    for item in evidence:
        for _, reflexes in item.live:
            support[reflexes] += 1
        if not item.scored:
            continue
        for (_, reflexes), value in zip(item.live, item.wanted, strict=True):
            votes[reflexes][value] += 1
    return {
        reflexes: _pick(tally) for reflexes, tally in votes.items()
    }, support


def _readings_under(
    item: ColumnEvidence, values: dict[tuple[str | None, ...], str | None]
) -> tuple:
    """This concept's alignment read in proto terms, under an unconditioned map.

    The assembler's pass 1, computed by the assembler's own code: a column reads
    as the single segment its set contributes, or as nothing where the set
    contributes nothing. It is deliberately *optimistic* about columns that end
    up conditioned -- the assembler reads those as undecided in pass 2, so an
    environment this oracle selects on the strength of a conditioned neighbour
    may not fire. That costs the oracle accuracy and cannot cost it correctness,
    which is the right way round for a bound.
    """
    decided: dict[int, object] = {
        index: frozenset() for index in range(len(item.rows[0]) if item.rows else 0)
    }
    width = max((len(row) for row in item.rows), default=0)
    decided = {index: frozenset() for index in range(width)}
    for index, reflexes in item.live:
        value = values.get(reflexes)
        decided[index] = frozenset() if value is None else frozenset({value})
    return readings_from(item.rows, decided)


def _environment_parts(environment: RuleEnvironment) -> int:
    return sum(
        (
            environment.left is not None,
            environment.right is not None,
            environment.word_initial,
            environment.word_final,
        )
    )


def _candidate_environments(
    observations: Sequence[tuple[tuple, int, str | None]],
) -> list[RuleEnvironment]:
    """The bounded space this oracle searches: what a `conditioning` can spell.

    The same shape `candidate_environments` searches for rules -- word edges, a
    single left token, a single right token, and the four two-part combinations
    -- read in *proto* terms through `alignment/environments.py`, because that
    is what the assembler evaluates a conditioning against.
    """
    lefts: set[str] = set()
    rights: set[str] = set()
    for readings, index, _ in observations:
        left, right = context_tokens(readings, index)
        lefts |= {token for token in left if token != WORD_EDGE_TOKEN}
        rights |= {token for token in right if token != WORD_EDGE_TOKEN}
    def expression(token: str) -> SegmentExpression:
        return SegmentExpression(tokens=(token,))
    return [
        RuleEnvironment(word_initial=True),
        RuleEnvironment(word_final=True),
        *(RuleEnvironment(left=expression(token)) for token in sorted(lefts)),
        *(RuleEnvironment(right=expression(token)) for token in sorted(rights)),
        RuleEnvironment(word_initial=True, word_final=True),
        *(
            RuleEnvironment(word_initial=True, right=expression(token))
            for token in sorted(rights)
        ),
        *(
            RuleEnvironment(left=expression(token), word_final=True)
            for token in sorted(lefts)
        ),
        *(
            RuleEnvironment(left=expression(left), right=expression(right))
            for left in sorted(lefts)
            for right in sorted(rights)
        ),
    ]


def conditioned_values(
    evidence: Sequence[ColumnEvidence],
    values: dict[tuple[str | None, ...], str | None],
) -> dict[tuple[str | None, ...], list[tuple[str | None, RuleEnvironment]]]:
    """Conditioned splits of the sets whose columns do not all want one value.

    The per-set analogue of `conditioned_rules`, and pure in the same sense: an
    environment is usable only when every column it matches wants the same
    value. A mixed environment would be a commitment that is wrong somewhere it
    fires, and the point of an oracle is to be right wherever it can be.
    """
    observations: dict[
        tuple[str | None, ...], list[tuple[tuple, int, str | None]]
    ] = collections.defaultdict(list)
    for item in evidence:
        if not item.scored:
            continue
        readings = _readings_under(item, values)
        for (index, reflexes), value in zip(item.live, item.wanted, strict=True):
            observations[reflexes].append((readings, index, value))

    splits: dict[
        tuple[str | None, ...], list[tuple[str | None, RuleEnvironment]]
    ] = {}
    for reflexes, seen in observations.items():
        default = values.get(reflexes)
        exceptions = [item for item in seen if item[2] != default]
        if not exceptions:
            continue
        usable: list[tuple[int, int, str, str | None, RuleEnvironment]] = []
        for environment in _candidate_environments(seen):
            matched = [
                item
                for item in seen
                if environment_matches(environment, item[0], item[1]) is True
            ]
            if not matched:
                continue
            wanted = {item[2] for item in matched}
            if len(wanted) != 1:
                continue
            target = wanted.pop()
            if target == default:
                continue
            usable.append(
                (
                    -len(matched),
                    -_environment_parts(environment),
                    environment.model_dump_json(),
                    target,
                    environment,
                )
            )
        selected: list[tuple[str | None, RuleEnvironment]] = []
        covered: set[int] = set()
        outstanding = {id(item) for item in exceptions}
        for _, _, _, target, environment in sorted(usable, key=lambda x: x[:3]):
            matched = {
                id(item)
                for item in exceptions
                if environment_matches(environment, item[0], item[1]) is True
            }
            if not matched - covered:
                continue
            selected.append((target, environment))
            covered |= matched
            if covered >= outstanding:
                break
        if selected:
            splits[reflexes] = selected
    return splits


def build_commitments(
    child_node_ids: Sequence[str],
    values: dict[tuple[str | None, ...], str | None],
    support: collections.Counter,
    splits: dict[tuple[str | None, ...], list[tuple[str | None, RuleEnvironment]]],
) -> tuple[CorrespondenceCommitment, ...]:
    """Turn a voted map, and optionally its splits, into a committed inventory.

    A set with splits commits them *and* its unconditioned value: the assembler
    defers such a column to pass 2, resolves it against the conditioned
    commitments, and falls back to the unconditioned one where none is
    satisfied. That is the elsewhere-condition, and it is why the two are
    committed together rather than the default being dropped.
    """
    commitments = []
    for reflexes in sorted(
        support, key=lambda item: tuple("" if x is None else x for x in item)
    ):
        if reflexes not in values:
            # A set seen only in concepts this node carries no gold for. Nothing
            # checked it, so nothing commits it, and residue policy decides it.
            continue
        set_id = derive_set_id(
            reflexes,
            child_node_ids,
            segmentation_overlay_id=None,
            alignment_overlay_id=None,
        )
        for target, environment in splits.get(reflexes, ()):
            commitments.append(
                CorrespondenceCommitment(
                    set_id=set_id,
                    reflexes=reflexes,
                    proto_segment=target,
                    conditioning=environment,
                    support=support[reflexes],
                    confidence=1.0,
                    rationale="oracle: a pure environment over this node's gold",
                    directionality_rationale=(
                        "oracle: computed from withheld gold, not a linguistic "
                        "claim"
                    ),
                )
            )
        commitments.append(
            CorrespondenceCommitment(
                set_id=set_id,
                reflexes=reflexes,
                proto_segment=values[reflexes],
                support=support[reflexes],
                confidence=1.0,
                rationale=(
                    "oracle: the value reaching gold in the most columns "
                    "showing this set"
                ),
                directionality_rationale=(
                    "oracle: computed from withheld gold, not a linguistic claim"
                ),
            )
        )
    return tuple(commitments)


def _oracle_inventory(
    node_id: str,
    child_node_ids: Sequence[str],
    commitments: tuple[CorrespondenceCommitment, ...],
    residue_policy: ResiduePolicy,
    residue_witness_child_id: str | None,
) -> CommittedProtoInventory:
    return CommittedProtoInventory(
        request=CommitProtoInventoryArgs(
            node_id=node_id,
            child_node_ids=tuple(child_node_ids),
            commitments=commitments,
            residue_policy=residue_policy,
            residue_witness_child_id=residue_witness_child_id,
            summary=(
                "oracle inventory: one value per correspondence set, voted "
                "against the withheld gold"
            ),
        )
    )


def _score_against_gold(
    step, gold_alternatives: dict[str, tuple[tuple[str, ...], ...]]
) -> tuple[int, float]:
    """How close this node's reported forms are to the gold it is aimed at.

    Exact hits first, then negative total edit distance. The graded half is not
    decoration: at an internal node the oracle is aimed at the *root's* gold,
    which almost nothing there matches exactly, so an exact-only criterion is
    nearly flat and picks among the general claims by accident. The distance
    still separates them, and separating them is the whole point of choosing.
    """
    exact = 0
    distance = 0.0
    for distribution in step.output_beam.distributions:
        targets = gold_alternatives.get(distribution.concept_id)
        if not targets:
            continue
        segments = distribution.candidates[0].segments
        if segments in targets:
            exact += 1
        distance += compare_to_nearest(segments, targets).normalized_edit_distance
    return exact, -distance


def assembly_step(
    parent_node_id: str,
    child_node_ids: Sequence[str],
    child_beams: tuple,
    forms_by_child: dict[str, dict[str, tuple[str, ...]]],
    gold_alternatives: dict[str, tuple[tuple[str, ...], ...]],
    assembler: ProtoInventoryAssembler,
):
    """Assemble one node under its best oracle inventory.

    Returns the step, the inventory that produced it, and a label naming the two
    choices that were searched rather than derived.

    **Both choices are settled by running them, not by arguing them**, which is
    what `branch_rules` does per branch and for the same reason: a measure that
    claimed to bound the architecture while leaving one of its general claims
    unset would bound something else.

      conditioning   an inventory whose sets carry pure `conditioning`
                     environments is the analogue of `--oracle contextual`, and
                     like it is >= the unconditioned one by *measurement*. It
                     can lose: the assembler reads a conditioned column as
                     undecided in pass 2, so a split selected against an
                     optimistic neighbour may simply not fire, and where the
                     splits cost more than they buy the unconditioned inventory
                     is used.
      residue policy what happens to a column no committed set explains. A
                     policy is a claim about the node, so the oracle is entitled
                     to it; a `residue_disposition` is a claim about one column
                     of one concept, so it is not. See `column_evidence`.
    """
    evidence = column_evidence(
        child_node_ids, forms_by_child, gold_alternatives, assembler
    )
    values, support = unconditioned_values(evidence)
    splits = conditioned_values(evidence, values)
    shapes = [
        ("unconditioned", build_commitments(child_node_ids, values, support, {})),
    ]
    if splits:
        shapes.append(
            ("conditioned", build_commitments(child_node_ids, values, support, splits))
        )
    residues: list[tuple[ResiduePolicy, str | None]] = [
        (ResiduePolicy.RETAIN_FROM_WITNESS, child_id) for child_id in child_node_ids
    ] + [(ResiduePolicy.DROP, None)]

    best = None
    for shape, commitments in shapes:
        for policy, witness in residues:
            inventory = _oracle_inventory(
                parent_node_id, child_node_ids, commitments, policy, witness
            )
            step = assembler.reconstruct(
                parent_node_id, child_beams, inventory=inventory
            )
            scored = _score_against_gold(step, gold_alternatives)
            if best is None or scored > best[0]:
                label = policy.value + (
                    f"[{witness}]" if witness is not None else ""
                )
                best = (scored, step, inventory, f"{shape}/{label}")
    _, step, inventory, label = best
    return step, inventory, label



@dataclass(frozen=True)
class OracleMeasurement:
    """What a flawless hypothesis manager would score under this architecture.

    Exact counts and graded distances side by side. The graded numbers matter
    for the same reason they matter for a live run: a top-1 miss that is one
    segment away and a top-1 miss that is unrelated are different failures, and
    the exact counters cannot tell them apart.
    """

    root_node_id: str
    gold_node_id: str
    oracle: str
    beam_width: int
    evaluated: int
    top_exact: int
    beam_exact: int
    mean_top_normalized_edit_distance: float
    mean_beam_best_normalized_edit_distance: float
    mean_top_bcubed_f1: float
    rules_written: int = 0
    branches: int = 0
    fallback_branches: int = 0
    # Assembly-only, and None under the two branch-cascade oracles rather than
    # zero: an inventory counter of 0 and an inventory counter that does not
    # apply are different readings, and a JSON consumer must be able to tell
    # them apart.
    commitments_written: int | None = None
    residue_policy_choices: tuple[str, ...] = ()
    mean_unaccounted_column_rate: float | None = None
    mean_cross_branch_assembly_rate: float | None = None
    nodes_with_cross_branch_assembly: int | None = None
    misses: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = field(
        default=()
    )
    # The concepts the top-1 form got exactly right. `top_exact` is their count;
    # the identities are what `selection_reachable` has to be intersected with,
    # because an oracle can match the selection bar's count while getting a
    # different set of concepts right.
    top_exact_concept_ids: tuple[str, ...] = ()

    @property
    def top_exact_rate(self) -> float:
        return self.top_exact / self.evaluated if self.evaluated else 0.0

    @property
    def beam_exact_rate(self) -> float:
        return self.beam_exact / self.evaluated if self.evaluated else 0.0

    @property
    def selection_gap(self) -> float:
        """Beam-exact minus top-1: answers computed and then not reported."""
        return self.beam_exact_rate - self.top_exact_rate

    @property
    def normalized_edit_distance_selection_gap(self) -> float:
        return (
            self.mean_top_normalized_edit_distance
            - self.mean_beam_best_normalized_edit_distance
        )

    def as_dict(self) -> dict:
        return {
            "root_node_id": self.root_node_id,
            # Which node's gold produced this number. `measuring:` already stops
            # a figure being quoted from the wrong checkout; nothing used to stop
            # one being quoted from the wrong node, and on a multi-gold family
            # that is exactly what happened.
            "gold_node_id": self.gold_node_id,
            "oracle": self.oracle,
            "beam_width": self.beam_width,
            "evaluated_concepts": self.evaluated,
            "top_exact": self.top_exact,
            "beam_exact": self.beam_exact,
            "top_exact_rate": self.top_exact_rate,
            "beam_exact_rate": self.beam_exact_rate,
            "selection_gap": self.selection_gap,
            "mean_top_normalized_edit_distance": (
                self.mean_top_normalized_edit_distance
            ),
            "mean_beam_best_normalized_edit_distance": (
                self.mean_beam_best_normalized_edit_distance
            ),
            "normalized_edit_distance_selection_gap": (
                self.normalized_edit_distance_selection_gap
            ),
            "mean_top_bcubed_f1": self.mean_top_bcubed_f1,
            "rules_written": self.rules_written,
            "branches": self.branches,
            "fallback_branches": self.fallback_branches,
            "commitments_written": self.commitments_written,
            "residue_policy_choices": list(self.residue_policy_choices),
            "mean_unaccounted_column_rate": self.mean_unaccounted_column_rate,
            "mean_cross_branch_assembly_rate": (
                self.mean_cross_branch_assembly_rate
            ),
            "nodes_with_cross_branch_assembly": (
                self.nodes_with_cross_branch_assembly
            ),
        }


def selection_reachable(payload: WorkbenchPayload, binding) -> set[str]:
    """Concepts some daughter already attests exactly, in the gold's own reading.

    This is the **selection bar** of `docs/proto_inventory_design.md` §7.20,
    recomputed here rather than imported: the `tools/` scripts are independent
    implementations, so the bar an oracle is checked against must not come from
    the script that publishes the bar.

    A concept is reachable when any attested daughter form equals any gold
    alternative -- the same any/any reading `HistoricalTargetEvaluation` uses,
    so a hit here and a hit in a live score mean the same thing.

    The point of the set, rather than its size: an oracle can match the bar's
    *count* while getting a different set of concepts right, and only the
    intersection says whether the architecture reached anything selection
    could not.
    """
    gold: dict[str, set[tuple[str, ...]]] = {}
    for form in binding.forms:
        gold.setdefault(form.concept_id, set()).add(tuple(form.segments))
    reachable = set()
    for lexicon in payload.lexicons:
        for form in lexicon.forms:
            targets = gold.get(form.concept_id)
            if targets and tuple(form.segments) in targets:
                reachable.add(form.concept_id)
    return reachable


def select_binding(payload: WorkbenchPayload, root_id: str, requested: str | None):
    """The gold binding to score against, defaulting to the tree root's own.

    `bindings[0]` used to be taken unconditionally. On a family carrying gold at
    several nodes that is whichever binding was written first -- `east` on
    `synthetic_hard`, not `proto` -- so the root beam was scored against a
    non-root gold and published under the root's name. Defaulting to the root's
    binding, and refusing to guess where the root has none, is the whole fix.
    """
    bindings = [
        binding
        for binding in payload.historical_form_bindings
        if binding.role.value == "target"
    ]
    if not bindings:
        raise SystemExit("input has no historical target binding to score against")
    by_node = {binding.node_id: binding for binding in bindings}
    if requested is not None:
        if requested not in by_node:
            raise SystemExit(
                f"no target binding at {requested!r}; this input has gold at "
                f"{', '.join(sorted(by_node))}"
            )
        return by_node[requested]
    if root_id in by_node:
        return by_node[root_id]
    raise SystemExit(
        f"the root {root_id!r} carries no gold binding, and scoring a beam "
        f"against another node's gold is a measurement with the wrong label. "
        f"Pass --gold-node from: {', '.join(sorted(by_node))}"
    )


def measure(
    payload: WorkbenchPayload,
    beam_width: int = 5,
    *,
    oracle: str = CONTEXT_FREE,
    gold_node_id: str | None = None,
) -> OracleMeasurement:
    """Run the real reconstructor with a perfect rule set on every branch."""
    if oracle not in ORACLES:
        raise SystemExit(f"unknown oracle {oracle!r}; choose from {ORACLES}")
    root = parse_newick(payload.newick)
    node_ids = assign_node_ids(root)
    root_id = node_ids[id(root)]
    binding = select_binding(payload, root_id, gold_node_id)

    # Two views of the same gold, and the split is deliberate. Rule construction
    # needs one aligned target per concept and a segment map is single-valued,
    # so it keeps the original last-one-wins reading. *Evaluation* honours every
    # alternative, exactly as `HistoricalTargetEvaluation` does through
    # `compare_to_nearest`: on Polynesian `1443` WALK carries four gold forms and
    # scoring against only the last of them is a defect of this script, not a
    # property of the harness.
    gold = {form.concept_id: form.segments for form in binding.forms}
    alternatives: dict[str, list[tuple[str, ...]]] = collections.defaultdict(list)
    for form in binding.forms:
        alternatives[form.concept_id].append(form.segments)
    gold_alternatives = {
        # Deduplicated in order, exactly as `agent/service.py` does, so the two
        # readings of the same binding cannot differ.
        concept_id: tuple(dict.fromkeys(forms))
        for concept_id, forms in alternatives.items()
    }

    lexicons = {lexicon.variety_id: lexicon for lexicon in payload.lexicons}
    beams = {}
    forms_by_node: dict[str, dict[str, tuple[str, ...]]] = {}
    for leaf in root.get_leaves():
        beams[id(leaf)] = make_leaf_beam(lexicons[leaf.label], beam_width=beam_width)
        forms_by_node[leaf.label] = {
            form.concept_id: form.segments for form in lexicons[leaf.label].forms
        }
    if oracle == ASSEMBLY:
        # The assembly oracle's inventory has to be voted over the columns the
        # assembler will actually resolve, and the assembler resolves the beam's
        # candidates. Where a leaf attests a concept twice, the beam's top
        # candidate is decided by `TIE_BREAK_POLICY` and the last form written
        # down is decided by the file; those disagree, and only the first is a
        # column assembly will see. The rule oracles keep the last-one-wins
        # reading they were measured with -- `oracle_map` builds a segment map,
        # not a column, so nothing there depends on which of the two it is.
        for leaf in root.get_leaves():
            forms_by_node[leaf.label] = {
                distribution.concept_id: distribution.candidates[0].segments
                for distribution in beams[id(leaf)].distributions
            }

    reconstructor = RuleBasedReconstructor(beam_width=beam_width)
    assembler = (
        ProtoInventoryAssembler(beam_width=beam_width)
        if oracle == ASSEMBLY
        else None
    )
    scored_node = None
    rules_written = branches = fallbacks = 0
    commitments_written = 0
    residue_choices: list[str] = []
    unaccounted_rates: list[float] = []
    cross_branch_rates: list[float] = []
    for children, parent in postorder_groups(root):
        parent_id = node_ids[id(parent)]
        child_ids = [node_ids[id(child)] for child in children]
        child_beams = tuple(beams[id(child)] for child in children)
        if oracle == ASSEMBLY:
            step, inventory, residue_label = assembly_step(
                parent_id,
                child_ids,
                child_beams,
                forms_by_node,
                gold_alternatives,
                assembler,
            )
            commitments_written += len(inventory.request.commitments)
            branches += len(child_ids)
            residue_choices.append(f"{parent_id}={residue_label}")
            unaccounted_rates.append(
                step.diagnostics.unaccounted_column_rate or 0.0
            )
            cross_branch_rates.append(
                step.diagnostics.cross_branch_assembly_rate or 0.0
            )
        else:
            rules: list[ReconstructionRule] = []
            for child_id in child_ids:
                built, fell_back = branch_rules(
                    child_id, forms_by_node[child_id], gold, gold_alternatives, oracle
                )
                rules.extend(built)
                rules_written += len(built)
                branches += 1
                fallbacks += fell_back
            step = reconstructor.reconstruct(parent_id, child_beams, rules=rules)
        beams[id(parent)] = step.output_beam
        forms_by_node[parent_id] = {
            distribution.concept_id: distribution.candidates[0].segments
            for distribution in step.output_beam.distributions
        }
        if parent_id == binding.node_id:
            scored_node = beams[id(parent)]
    if scored_node is None:
        raise SystemExit(
            f"gold node {binding.node_id!r} is not an internal node of this tree"
        )

    top_hits = beam_hits = evaluated = 0
    misses = []
    top_neds: list[float] = []
    beam_neds: list[float] = []
    bcubed_scores: list[float] = []
    hit_ids: list[str] = []
    for distribution in scored_node.distributions:
        targets = gold_alternatives.get(distribution.concept_id)
        if targets is None:
            continue
        evaluated += 1
        candidates = [candidate.segments for candidate in distribution.candidates]
        top = compare_to_nearest(candidates[0], targets)
        if candidates[0] in targets:
            top_hits += 1
            hit_ids.append(distribution.concept_id)
        else:
            # The alternative the score was computed against, not the last one
            # written down: printing a different gold from the one that graded
            # the form is how the multi-gold defect stayed invisible.
            misses.append(
                (distribution.concept_id, candidates[0], top.nearest_target)
            )
        if any(target in candidates for target in targets):
            beam_hits += 1
        top_neds.append(top.normalized_edit_distance)
        bcubed_scores.append(top.bcubed_f1)
        beam_neds.append(
            min(
                compare_to_nearest(segments, targets).normalized_edit_distance
                for segments in candidates
            )
        )
    return OracleMeasurement(
        root_node_id=root_id,
        gold_node_id=binding.node_id,
        oracle=oracle,
        beam_width=beam_width,
        evaluated=evaluated,
        top_exact=top_hits,
        beam_exact=beam_hits,
        mean_top_normalized_edit_distance=(
            sum(top_neds) / len(top_neds) if top_neds else 0.0
        ),
        mean_beam_best_normalized_edit_distance=(
            sum(beam_neds) / len(beam_neds) if beam_neds else 0.0
        ),
        mean_top_bcubed_f1=(
            sum(bcubed_scores) / len(bcubed_scores) if bcubed_scores else 0.0
        ),
        rules_written=rules_written,
        branches=branches,
        fallback_branches=fallbacks,
        commitments_written=(
            commitments_written if oracle == ASSEMBLY else None
        ),
        residue_policy_choices=tuple(residue_choices),
        mean_unaccounted_column_rate=(
            sum(unaccounted_rates) / len(unaccounted_rates)
            if unaccounted_rates
            else None
        ),
        mean_cross_branch_assembly_rate=(
            sum(cross_branch_rates) / len(cross_branch_rates)
            if cross_branch_rates
            else None
        ),
        nodes_with_cross_branch_assembly=(
            sum(1 for rate in cross_branch_rates if rate > 0.0)
            if oracle == ASSEMBLY
            else None
        ),
        misses=tuple(misses),
        top_exact_concept_ids=tuple(hit_ids),
    )


def run(
    payload_path: Path,
    beam_width: int,
    *,
    as_json: bool = False,
    oracle: str = CONTEXT_FREE,
    gold_node_id: str | None = None,
    selection_overlap: bool = False,
) -> int:
    payload = WorkbenchPayload.model_validate_json(
        payload_path.read_text(encoding="utf-8")
    )
    result = measure(
        payload, beam_width, oracle=oracle, gold_node_id=gold_node_id
    )
    overlap = None
    if selection_overlap:
        binding = select_binding(
            payload, result.root_node_id, gold_node_id or result.gold_node_id
        )
        reachable = selection_reachable(payload, binding)
        hits = set(result.top_exact_concept_ids)
        overlap = {
            "selection_bar": len(reachable),
            "selection_bar_rate": (
                len(reachable) / result.evaluated if result.evaluated else 0.0
            ),
            "top_exact_inside_bar": len(hits & reachable),
            "top_exact_outside_bar": sorted(hits - reachable),
        }
    if as_json:
        _bootstrap.emit_json(
            {
                **_bootstrap.measurement_envelope(payload_path),
                "measurement": "oracle_ceiling",
                **result.as_dict(),
                **({"selection_overlap": overlap} if overlap else {}),
            }
        )
        return 0
    print(f"benchmark: {payload_path}")
    # State which source produced the number. A figure quoted from this tool is
    # meaningless without it: the script and the package it measures can come
    # from different checkouts. See tools/_bootstrap.py.
    print(f"measuring: {_bootstrap.loaded_package_path()}")
    print(
        f"root node: {result.root_node_id}   gold node: {result.gold_node_id}   "
        f"oracle: {result.oracle}"
    )
    if result.oracle == ASSEMBLY:
        print(
            f"beam width: {beam_width}   concepts: {result.evaluated}   "
            f"sets: {result.commitments_written} over {result.branches} branches"
        )
    else:
        print(
            f"beam width: {beam_width}   concepts: {result.evaluated}   "
            f"rules: {result.rules_written} over {result.branches} branches"
            + (
                f"   ({result.fallback_branches} fell back to context-free)"
                if result.fallback_branches
                else ""
            )
        )
    print()
    print(
        f"  top  exact  {result.top_exact:>3}/{result.evaluated}  "
        f"{result.top_exact_rate:6.1%}   what the beam reports"
    )
    print(
        f"  beam exact  {result.beam_exact:>3}/{result.evaluated}  "
        f"{result.beam_exact_rate:6.1%}   correct form present anywhere in the beam"
    )
    print(
        f"  selection gap                {result.selection_gap:6.1%}   "
        "computed but not chosen"
    )
    print()
    print("  graded, against the same gold (lower is better for NED):")
    print(
        f"    top  NED   {result.mean_top_normalized_edit_distance:6.3f}   "
        "mean normalized edit distance of the reported form"
    )
    print(
        f"    beam NED   {result.mean_beam_best_normalized_edit_distance:6.3f}   "
        "best any retained candidate reached"
    )
    print(
        f"    NED gap    {result.normalized_edit_distance_selection_gap:6.3f}   "
        "distance recoverable by choosing better"
    )
    print(
        f"    B-Cubed F1 {result.mean_top_bcubed_f1:6.3f}   "
        "structural agreement, higher is better"
    )
    if result.oracle == ASSEMBLY:
        print()
        print("  assembly, per node (reports; nothing here is a gate):")
        print(
            f"    unaccounted columns  {result.mean_unaccounted_column_rate:6.3f}   "
            "mean rate; read it against the family's floor, not against 0"
        )
        print(
            f"    cross-branch         "
            f"{result.mean_cross_branch_assembly_rate:6.3f}   "
            f"mean rate, non-zero at {result.nodes_with_cross_branch_assembly} "
            f"of {len(result.residue_policy_choices)} nodes"
        )
        print(
            "    residue policy       "
            + ", ".join(result.residue_policy_choices)
        )
    if overlap is not None:
        outside = overlap["top_exact_outside_bar"]
        print()
        print("  against the selection bar (§7.20; nothing here is a gate):")
        print(
            f"    selection bar  {overlap['selection_bar']:>3}/{result.evaluated}  "
            f"{overlap['selection_bar_rate']:6.1%}   "
            "concepts some daughter already attests exactly"
        )
        print(
            f"    inside it      {overlap['top_exact_inside_bar']:>3}"
            f"/{result.top_exact}          "
            "of this oracle's hits, a daughter had the form already"
        )
        print(
            f"    outside it     {len(outside):>3}"
            f"/{result.top_exact}          "
            "reached with no daughter attesting it: "
            + (", ".join(outside) if outside else "none")
        )
    print()
    print("first 12 misses (reported | gold):")
    for concept_id, got, want in result.misses[:12]:
        print(f"  {concept_id:<10} {' '.join(got):<22} | {' '.join(want)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        help="A prepared benchmark payload, or the name of a defined benchmark.",
    )
    parser.add_argument("--beam-width", type=int, default=5)
    parser.add_argument(
        "--oracle",
        choices=ORACLES,
        default=CONTEXT_FREE,
        help=(
            "context_free is the measure every recorded baseline used and is "
            "the default for that reason; contextual searches the DSL's own "
            "environments and lands beside it, never in place of it; assembly "
            "commits one proto-phoneme per correspondence set at each node and "
            "runs the real assembler, which is the same question put to the "
            "other architecture."
        ),
    )
    parser.add_argument(
        "--gold-node",
        default=None,
        help=(
            "Which node's gold binding to score against. Defaults to the tree "
            "root's; required where the root carries none."
        ),
    )
    parser.add_argument(
        "--selection-overlap",
        action="store_true",
        help=(
            "Also report how many of this oracle's hits are concepts some "
            "daughter already attests exactly. An oracle can match the "
            "selection bar's count on a different set of concepts, so the "
            "intersection is the part that says whether the architecture "
            "reached anything selection could not."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit one machine-readable object, including the measured source.",
    )
    args = parser.parse_args()
    return run(
        _bootstrap.resolve_benchmark(args.input),
        args.beam_width,
        as_json=args.json,
        oracle=args.oracle,
        gold_node_id=args.gold_node,
        selection_overlap=args.selection_overlap,
    )


if __name__ == "__main__":
    raise SystemExit(main())
