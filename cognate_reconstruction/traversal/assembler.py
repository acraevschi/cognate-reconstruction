"""Assemble a parent form column by column out of a committed proto-inventory.

The deterministic half of the per-set protocol. A session commits a mapping from
correspondence sets to proto-phonemes; this walks the children's aligned columns,
emits the matched set's value in each, and builds the parent beam out of what
comes back. The per-branch rewrite cascade is *derived* from the same inventory
as a view (`derive_branch_rules`), reported and verified, never the mechanism —
which is why insertion never needs to exist here: a set `⟨Tongan ʔ : Niuean Ø⟩`
reconstructs `*ʔ` because the parent segment comes from the set, not from any
child's string.

Four things in `docs/proto_inventory_design.md` §4.4 are load-bearing and each is
implemented deliberately rather than incidentally.

**An unaccounted column carries through. It does not vanish.** The naive reading
— emit the matched set's value, drop the rest — turns a one-set inventory into
the proto-form `ʔ`, and an empty one into an empty form that
`normalize_and_prune` refuses outright. Carry-through makes assembly
*monotonic*: committing more sets refines a reconstruction, committing none
leaves it where the children are, and there is no cliff between the two. `drop`
stays available for a column the model positively believes is innovation, and is
now what it should always have been — an assertion, not a default.

**An inventory that asserts nothing short-circuits.** When there is no
commitment, no residue disposition and no restoration, the assembler is not
invoked at all and the parent beam is the children's candidates combined,
exactly as an identity rule commit produces today. That is not an ugly special
case: *asserting nothing* is a categorically different act from *asserting
something*, and the alternative was worse — letting each uncommitted column
branch into one candidate per distinct reflex manufactures recombinations no
child ever attested, where today's identity only ever emits forms some child
actually produced. `agent/reconstructor.py::_fallback_step` therefore keeps its
behaviour bit-for-bit.

**Conditioning is evaluated in proto terms, in two passes.** A conditioned split
is conditioned by the neighbouring proto-phonemes, not by any one child's
segments. Pass 1 assigns every unambiguously matched column; pass 2 resolves
conditioned columns against pass-1 neighbours; a conditioned column whose
deciding neighbour is itself still undecided falls to residue and is reported.
Two passes terminate — there is no fixpoint to chase and no cycle to detect.
Adjacency and satisfaction come from `alignment/environments.py`, which is the
same definition the `complementary_candidates` report and the
`non-complementary-split` rejection use.

**Assembly runs over the children's full beams.** 43 of 46 concepts carry more
than one candidate at the Polynesian root; assembling from top candidates alone
would collapse the beam to width 1 and make every intermediate error permanent.
So the Cartesian product over the children's candidates is walked, each tuple is
aligned and assembled into one form, and the results merge and prune through the
existing `normalize_and_prune` with the existing `TIE_BREAK_POLICY`.

Nothing here is a gate. Every count it produces is a report; the only quantity
that reaches the beam is `confidence`, which already weighted it, now attached to
a correspondence instead of a rewrite.
"""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from cognate_reconstruction.alignment.environments import (
    ColumnReading,
    environment_matches,
    readings_from,
)
from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.alignment.protocol import AlignmentProvider
from cognate_reconstruction.rules.engine import RuleEngine
from cognate_reconstruction.rules.parser import parse_rule
from cognate_reconstruction.schemas.beam import CandidateDerivation, NodeBeamState
from cognate_reconstruction.schemas.common import MORPHOLOGICAL_BOUNDARY_TOKENS
from cognate_reconstruction.schemas.inventory import (
    AlignmentOverride,
    ColumnResolution,
    CommittedProtoInventory,
    ConceptAssemblyReport,
    CorrespondenceCommitment,
    ResidueDisposition,
    ResiduePolicy,
    SegmentRestoration,
)
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm
from cognate_reconstruction.schemas.rules import (
    AnchorPolicy,
    AnomalyReport,
    ReconstructionRule,
    RuleEnvironment,
    SegmentExpression,
)
from cognate_reconstruction.schemas.traversal import (
    NodeReconstructionContext,
    ReconstructionDiagnostics,
    ReconstructionStep,
)
from cognate_reconstruction.traversal.beam import (
    RawCandidate,
    decided_by_tie_break,
    normalize_and_prune,
)
from cognate_reconstruction.traversal.reconstructor import RuleBasedReconstructor

RESIDUE_COLUMN_CONFIDENCE = 0.25
"""Mass a column carries when the residue policy resolved it, not a set.

Fixed, named here, and derived from nothing. It is not a probability and should
not look like one: it exists so that within one concept a reading whose columns
are evidenced outranks one whose columns are defaults, and it says nothing
whatsoever about how likely an unexplained column is to be right. The whole
composition it feeds is "normalized heuristic beam mass, not calibrated Bayesian
posteriors", exactly as the rule confidences it replaces were.
"""

RESIDUE_COLUMN_LOG_MASS = math.log(RESIDUE_COLUMN_CONFIDENCE)

RESTORATION_LOG_MASS = 0.0
"""Mass a restored segment carries: none, and deliberately.

A restoration is applied identically to every candidate tuple of its concept, so
whatever number went here would cancel in the ranking. Zero says that plainly
instead of inventing a confidence the model never supplied.
"""


def _tuple_budget(beam_width: int) -> int:
    """How many candidate tuples one concept's frontier may hold.

    The Cartesian product over the children's candidates is bounded by
    `beam_width ** len(children)`, which is fine at the arities real
    classifications have — the Polynesian tree's widest internal node has three
    children — and unbounded in principle. The frontier is pruned to this after
    each child by accumulated child mass, so a tuple is only ever dropped in
    favour of tuples the children themselves scored higher.

    `beam_width ** 2` reproduces the full product exactly at every binary node,
    and at any node whose children's beams are not full — which, measured under
    the oracle, is most of them: the mean candidate count is 1.72 at `tongic` and
    2.76 at `central_eastern`.
    """
    return max(1, beam_width**2)


@dataclass(frozen=True)
class DerivedBranchRules:
    """The per-branch cascade an inventory implies, and what it could not say."""

    rules: tuple[ReconstructionRule, ...] = ()
    rule_set_ids: tuple[str, ...] = ()
    """The `set_id` each rule was derived from, positional against `rules`.

    Provenance rather than decoration: `synthesis/scoring.py` measures rule
    precision and `misdirected_rule_count` against the derived cascade, and a
    derived rule's `directionality_rationale` is the one on the commitment it
    came from. Without this the rationale would be unrecoverable and the
    measurement that speaks most directly to prompt 04's failure would silently
    read every derived rule as unjustified.
    """
    non_invertible_child_ids: tuple[str, ...] = ()
    """Children some committed set assigns a gap against a non-null proto.

    The insertion the DSL cannot write, recorded as a fact rather than raised as
    a rejection. Same convention as `schemas/synthetic.py`'s `invertible: false`,
    so `score-synthetic` compares like with like across the migration.
    """
    boundary_change_child_ids: tuple[str, ...] = ()
    """Children a committed set makes rewrite a morphological boundary.

    `+` and `-` are structural, and `rules/parser.py` refuses them as rule
    targets and as insertions on purpose — a cascade that rewrote them would be
    the harness placing morphs. Since boundaries became alignment material, a
    commitment *can* say something the DSL cannot write: `⟨+ : +⟩ → nothing`
    deletes a boundary, `⟨a : a⟩ → *+` inserts one. The assembly is unaffected
    — a parent form is built from columns, not from these rules — so the rule is
    dropped and the child recorded, exactly as `non_invertible_child_ids`
    records the insertion the DSL cannot write.

    Recorded rather than rejected: a model that reconstructs a boundary where a
    branch lost it has made a claim the evidence may well support, and refusing
    the commit because the *cascade* cannot spell it would be the derived view
    vetoing the committed one.
    """
    unspellable_reflex_child_ids: tuple[str, ...] = ()
    """Children a committed set gives a segment the DSL cannot name.

    A Lexibank segment is an arbitrary token, and the rule DSL reserves `>`,
    `/`, `_`, `#` and whitespace. Where they collide the rule cannot be written
    down at all — `pylexibank`'s grapheme/phoneme spelling puts a literal `/`
    inside a segment, as in `ṅ/ŋ`, and `parse_rule` then reads the segment as an
    environment separator.

    This is not a rare corner. Measured over the 174 local CLDF datasets, 104
    carry at least one such segment, `meloniromance` among them at 2146
    occurrences — so `benchmarks/romance.json` hit this before `hillburmish`
    existed. It went unnoticed because the only families ever run under the
    assembler, `walworthpolynesian` and the synthetic ones, carry none.

    Recorded rather than raised, exactly as the three fields around it are: the
    parent form is assembled from columns, so it assembles either way, and only
    the derived per-branch view loses a rule. A bare `ValueError` out of
    `parse_rule` ended the node instead, and through `_fallback_step` it ended
    the run.
    """
    unconditioned_context_child_ids: tuple[str, ...] = ()
    """Children whose derived rule lost its conditioning environment.

    A commitment's `conditioning` is in proto terms; a derived rule's is in the
    child's own segments, because the rule has to stay applicable to that child's
    forms for the verification to mean anything. Where the child shows a gap in
    the deciding column, or where no single committed set gives that proto token
    a reflex in the child, the rule falls back to its unconditioned form rather
    than reaching past the gap for the next segment — which would be a non-local
    environment the DSL cannot express.
    """


def _render_environment(environment: RuleEnvironment) -> str:
    left = " ".join(environment.left.tokens) if environment.left else ""
    right = " ".join(environment.right.tokens) if environment.right else ""
    if environment.word_initial:
        left = f"# {left}".strip()
    if environment.word_final:
        right = f"{right} #".strip()
    return f"{left}_{right}".strip()


DSL_RESERVED_CHARACTERS: frozenset[str] = frozenset(">/_#")
"""What `rules/parser.py` reads as syntax rather than as a segment.

`>` separates target from replacement, `/` introduces the environment, `_` is
the focus marker, `#` is a word boundary. Whitespace splits one segment
expression into several and is checked beside them.
"""


def _is_spellable(token: str | None) -> bool:
    """Can this segment appear verbatim in a DSL rule?

    Checked before rendering rather than by catching the parser's complaint,
    so a genuine defect in `_render_rule` still surfaces as an error instead of
    being filed away as an unspellable segment.
    """
    if token is None:
        return True
    return not (
        DSL_RESERVED_CHARACTERS & set(token)
        or any(character.isspace() for character in token)
    )


def _render_rule(target: str, replacement: str | None, environment: RuleEnvironment | None) -> str:
    """Render one derived rule as DSL text the parser accepts back.

    Round-tripping through `parse_rule` rather than building a `ParsedSoundRule`
    directly is what keeps a derived rule structurally comparable to a rule the
    model wrote and to a synthetic answer key's `inverse_rules`, which
    `synthesis/scoring.py` matches with `parse_rule`.
    """
    body = f"{target} > {replacement if replacement else 'Ø'}"
    if environment is None:
        return body
    rendered = _render_environment(environment)
    return body if rendered in {"", "_"} else f"{body} / {rendered}"


def _reflex_of_proto(
    commitments: Sequence[CorrespondenceCommitment],
    token: str,
    child_index: int,
) -> str | None:
    """The one segment `child_index` shows for a proto token, or `None`.

    `None` when no committed set reconstructs the token, when the child shows a
    gap for it, or when several sets reconstruct it with different reflexes — a
    merger, where the proto token has no single spelling in that child. All three
    make the environment unrenderable for that child rather than wrong.
    """
    values = {
        item.reflexes[child_index]
        for item in commitments
        if item.proto_segment == token
    }
    if len(values) != 1:
        return None
    return next(iter(values))


def derive_branch_rules(
    commitments: Sequence[CorrespondenceCommitment],
    child_node_ids: Sequence[str],
) -> DerivedBranchRules:
    """Derive the per-branch reflex cascade implied by an inventory.

    Child-to-parent, so each rule is written *reflex > proto*. Six cases, and
    they are exhaustive:

    - the child shows a gap against a non-null proto — no rule, and the child is
      recorded as non-invertible;
    - either side is a morphological boundary — no rule, and the child is
      recorded in `boundary_change_child_ids`; the DSL refuses `+` and `-` as
      targets and as insertions, deliberately;
    - either side carries a character the DSL reserves — no rule, and the child
      is recorded in `unspellable_reflex_child_ids`; a Lexibank segment is an
      arbitrary token and `ṅ/ŋ` is a real one;
    - the child shows material against a null proto — `reflex > Ø`;
    - both present and different — `reflex > proto`;
    - both present and equal — no rule; that is an ordinary identity
      correspondence, not a defect. `⟨+ : +⟩ → *+` lands here, which is why the
      commonest boundary commitment derives nothing and costs nothing.

    Two rules for one child with the same target and environment cannot arise,
    because a (set, conditioning) pair carries exactly one value. That is the
    contradiction case — `f > p / _eː` on Tongan beside `p > f / _e` on Niuean —
    becoming unrepresentable, stated as an invariant a test asserts directly.
    """
    rules: list[ReconstructionRule] = []
    rule_set_ids: list[str] = []
    non_invertible: list[str] = []
    unconditioned: list[str] = []
    boundary_changes: list[str] = []
    unspellable: list[str] = []
    for child_index, child_id in enumerate(child_node_ids):
        for item in commitments:
            reflex = item.reflexes[child_index]
            proto = item.proto_segment
            if reflex is None:
                if proto is not None and child_id not in non_invertible:
                    non_invertible.append(child_id)
                continue
            if reflex == proto:
                continue
            if (
                reflex in MORPHOLOGICAL_BOUNDARY_TOKENS
                or proto in MORPHOLOGICAL_BOUNDARY_TOKENS
            ):
                if child_id not in boundary_changes:
                    boundary_changes.append(child_id)
                continue
            if not (_is_spellable(reflex) and _is_spellable(proto)):
                if child_id not in unspellable:
                    unspellable.append(child_id)
                continue
            environment = item.conditioning
            if environment is not None:
                environment = _child_environment(
                    environment, commitments, child_index
                )
                if environment is not None and not all(
                    _is_spellable(token)
                    for expression in (environment.left, environment.right)
                    if expression is not None
                    for token in expression.tokens
                ):
                    # Same outcome as an environment that could not be derived:
                    # the rule falls back to its unconditioned form rather than
                    # being dropped, because the target is still spellable.
                    environment = None
                if environment is None and child_id not in unconditioned:
                    unconditioned.append(child_id)
            dsl = _render_rule(reflex, proto, environment)
            rules.append(
                ReconstructionRule(
                    rule=parse_rule(dsl),
                    source_child_ids=(child_id,),
                    confidence=item.confidence,
                )
            )
            rule_set_ids.append(item.set_id)
    return DerivedBranchRules(
        rules=tuple(rules),
        rule_set_ids=tuple(rule_set_ids),
        non_invertible_child_ids=tuple(non_invertible),
        boundary_change_child_ids=tuple(boundary_changes),
        unspellable_reflex_child_ids=tuple(unspellable),
        unconditioned_context_child_ids=tuple(unconditioned),
    )


def _child_environment(
    environment: RuleEnvironment,
    commitments: Sequence[CorrespondenceCommitment],
    child_index: int,
) -> RuleEnvironment | None:
    """Re-spell a proto environment in one child's own segments, or give up.

    One commitment can therefore derive differently spelled environments for
    different children, which is correct rather than a wart: the derived rule
    stays applicable to that child's forms, which is what makes verifying it
    against the assembler meaningful. In `synthetic_hard`'s `d4` (`a > e / _ i`)
    the proto and child spellings coincide, which is why the distinction does not
    surface there and would have been easy to miss.
    """
    left = environment.left
    right = environment.right
    if left is not None:
        tokens = [
            _reflex_of_proto(commitments, token, child_index)
            for token in left.tokens
        ]
        if any(token is None for token in tokens):
            return None
        left = SegmentExpression(tokens=tuple(tokens))
    if right is not None:
        tokens = [
            _reflex_of_proto(commitments, token, child_index)
            for token in right.tokens
        ]
        if any(token is None for token in tokens):
            return None
        right = SegmentExpression(tokens=tuple(tokens))
    return RuleEnvironment(
        left=left,
        right=right,
        word_initial=environment.word_initial,
        word_final=environment.word_final,
    )


@dataclass(frozen=True)
class ContrastReducingSet:
    """One commitment that gives up a distinction, and which kind."""

    set_id: str
    deletes: bool
    merges: bool
    note: str


def inventory_contrast_reductions(
    commitments: Sequence[CorrespondenceCommitment],
) -> tuple[ContrastReducingSet, ...]:
    """Which committed sets delete a segment or merge two into one.

    Read straight off the inventory rather than inferred from a mapping, which
    is both more direct than applying a cascade and better evidence: it sees the
    merger *as* a merger. Two sets carrying one `proto_segment` whose
    conditionings are not both present are a merger — a distinction some child
    makes that the parent does not; a non-null reflex against a null
    `proto_segment` is a deletion.

    A count, never a verdict. Contrast loss is ordinary sound change; what the
    commit contract requires is that each such set carries a
    `directionality_rationale` saying which branch innovated.
    """
    by_proto: dict[str, list[CorrespondenceCommitment]] = defaultdict(list)
    for item in commitments:
        if item.proto_segment is not None:
            by_proto[item.proto_segment].append(item)
    merged_ids: dict[str, str] = {}
    for proto, items in by_proto.items():
        if len(items) < 2:
            continue
        # Sets in a claimed conditioned split are one phoneme, not a merger; the
        # claim itself is checked separately and refused if the columns refute
        # it, so an unconditioned member is what makes this a lost distinction.
        unconditioned = [item for item in items if item.conditioning is None]
        if len(unconditioned) < 2:
            continue
        for item in unconditioned:
            merged_ids[item.set_id] = (
                f"{len(unconditioned)} committed sets reconstruct {proto!r} with "
                "no conditioning between them, so a distinction some child makes "
                "is not made in the parent"
            )
    reductions: list[ContrastReducingSet] = []
    for item in commitments:
        deletes = item.proto_segment is None and any(
            reflex is not None for reflex in item.reflexes
        )
        note = merged_ids.get(item.set_id)
        if not deletes and note is None:
            continue
        if deletes and note is None:
            note = (
                "every child showing material in this set loses it: the set "
                "reconstructs nothing"
            )
        reductions.append(
            ContrastReducingSet(
                set_id=item.set_id,
                deletes=deletes,
                merges=note is not None and not deletes,
                note=note or "",
            )
        )
    return tuple(reductions)


@dataclass(frozen=True)
class AssemblyPlan:
    """A committed inventory, indexed for column matching."""

    child_node_ids: tuple[str, ...]
    commitments: tuple[CorrespondenceCommitment, ...]
    residue_policy: ResiduePolicy
    residue_witness_index: int | None
    dispositions: Mapping[tuple[str, int], ResidueDisposition]
    restorations: Mapping[str, Mapping[int, SegmentRestoration]]
    overrides: Mapping[str, tuple[AlignmentOverride, ...]]
    by_reflexes: Mapping[tuple[str | None, ...], tuple[CorrespondenceCommitment, ...]]

    @property
    def asserts_nothing(self) -> bool:
        return not (self.commitments or self.dispositions or self.restorations)


def build_plan(
    child_node_ids: Sequence[str],
    commitments: Sequence[CorrespondenceCommitment],
    *,
    residue_policy: ResiduePolicy,
    residue_witness_child_id: str | None = None,
    residue_dispositions: Sequence[ResidueDisposition] = (),
    restorations: Sequence[SegmentRestoration] = (),
    overrides: Sequence[AlignmentOverride] = (),
) -> AssemblyPlan:
    """Index one inventory for assembly. Pure bookkeeping, no judgement."""
    columns = tuple(child_node_ids)
    by_reflexes: dict[
        tuple[str | None, ...], list[CorrespondenceCommitment]
    ] = defaultdict(list)
    for item in commitments:
        by_reflexes[tuple(item.reflexes)].append(item)
    restored: dict[str, dict[int, SegmentRestoration]] = defaultdict(dict)
    for item in restorations:
        restored[item.concept_id][item.before_column_index] = item
    by_concept: dict[str, list[AlignmentOverride]] = defaultdict(list)
    for item in overrides:
        by_concept[item.concept_id].append(item)
    return AssemblyPlan(
        child_node_ids=columns,
        commitments=tuple(commitments),
        residue_policy=residue_policy,
        residue_witness_index=(
            columns.index(residue_witness_child_id)
            if residue_witness_child_id is not None
            and residue_witness_child_id in columns
            else None
        ),
        dispositions={
            (item.concept_id, item.column_index): item
            for item in residue_dispositions
        },
        restorations={key: dict(value) for key, value in restored.items()},
        overrides={
            key: tuple(value) for key, value in by_concept.items()
        },
        by_reflexes={
            key: tuple(value) for key, value in by_reflexes.items()
        },
    )


@dataclass(frozen=True)
class ColumnOutcome:
    """One resolved column, with the mass it contributes."""

    resolution: ColumnResolution
    log_mass: float
    reading: ColumnReading


def _residue_outcome(
    plan: AssemblyPlan,
    concept_id: str,
    column_index: int,
    reflexes: tuple[str | None, ...],
) -> ColumnOutcome:
    disposition = plan.dispositions.get((concept_id, column_index))
    if disposition is not None:
        proto = disposition.proto_segment
        return ColumnOutcome(
            resolution=ColumnResolution(
                column_index=column_index,
                reflexes=reflexes,
                proto_segment=proto,
                resolved_by="residue_disposition",
            ),
            log_mass=RESIDUE_COLUMN_LOG_MASS,
            reading=frozenset() if proto is None else frozenset({proto}),
        )
    proto: str | None = None
    if (
        plan.residue_policy is ResiduePolicy.RETAIN_FROM_WITNESS
        and plan.residue_witness_index is not None
    ):
        proto = reflexes[plan.residue_witness_index]
    return ColumnOutcome(
        resolution=ColumnResolution(
            column_index=column_index,
            reflexes=reflexes,
            proto_segment=proto,
            resolved_by="residue_policy",
        ),
        log_mass=RESIDUE_COLUMN_LOG_MASS,
        reading=frozenset() if proto is None else frozenset({proto}),
    )


def _matched_outcome(
    item: CorrespondenceCommitment,
    column_index: int,
    reflexes: tuple[str | None, ...],
    *,
    conditioned: bool,
    competing: Sequence[str] = (),
) -> ColumnOutcome:
    proto = item.proto_segment
    return ColumnOutcome(
        resolution=ColumnResolution(
            column_index=column_index,
            reflexes=reflexes,
            set_id=item.set_id,
            proto_segment=proto,
            resolved_by="conditioned_set" if conditioned else "set",
            competing_set_ids=tuple(competing),
        ),
        log_mass=math.log(item.confidence),
        reading=frozenset() if proto is None else frozenset({proto}),
    )


@dataclass
class _ColumnStats:
    unaccounted: int = 0
    residue_policy_decided: int = 0
    tie_broken: int = 0
    ambiguous: list[ColumnResolution] = field(default_factory=list)


def resolve_columns(
    rows: Sequence[Sequence[str | None]],
    concept_id: str,
    plan: AssemblyPlan,
) -> tuple[tuple[ColumnOutcome, ...], _ColumnStats]:
    """Resolve every column of one alignment against a committed inventory.

    Two passes, per §4.4. An all-gap column is skipped outright — it is what
    `build_correspondence_sets` skips, so no set can name it and it carries no
    material for any policy to retain.
    """
    width = max((len(row) for row in rows), default=0)
    stats = _ColumnStats()
    reflexes_by_column: dict[int, tuple[str | None, ...]] = {}
    outcomes: dict[int, ColumnOutcome] = {}
    deferred: list[int] = []

    for column in range(width):
        reflexes = tuple(
            row[column] if column < len(row) else None for row in rows
        )
        if all(segment is None for segment in reflexes):
            continue
        reflexes_by_column[column] = reflexes
        matches = plan.by_reflexes.get(reflexes, ())
        if any(item.conditioning is not None for item in matches):
            deferred.append(column)
            continue
        if len(matches) == 1:
            outcomes[column] = _matched_outcome(
                matches[0], column, reflexes, conditioned=False
            )
        else:
            outcomes[column] = _residue_outcome(plan, concept_id, column, reflexes)
            stats.unaccounted += 1
            stats.residue_policy_decided += 1

    decided: dict[int, ColumnReading] = {
        column: outcome.reading for column, outcome in outcomes.items()
    }
    for column in reflexes_by_column:
        decided.setdefault(column, None)
    # Columns skipped as all-gap contribute nothing and are decided as such, so
    # the walk in `environments` steps over them rather than stalling on them.
    for column in range(width):
        if column not in reflexes_by_column:
            decided[column] = frozenset()
    readings = readings_from(rows, decided)

    for column in deferred:
        reflexes = reflexes_by_column[column]
        matches = plan.by_reflexes.get(reflexes, ())
        satisfied: list[CorrespondenceCommitment] = []
        for item in matches:
            if item.conditioning is None:
                continue
            verdict = environment_matches(item.conditioning, readings, column)
            if verdict is True:
                satisfied.append(item)
        if satisfied:
            best = _choose_column_commitment(satisfied)
            competing = tuple(
                item.set_id for item in satisfied if item.set_id != best.set_id
            )
            outcome = _matched_outcome(
                best, column, reflexes, conditioned=True, competing=competing
            )
            if competing:
                stats.tie_broken += 1
                stats.ambiguous.append(outcome.resolution)
            outcomes[column] = outcome
            continue
        fallback = [item for item in matches if item.conditioning is None]
        if fallback:
            outcomes[column] = _matched_outcome(
                fallback[0], column, reflexes, conditioned=False
            )
            continue
        outcomes[column] = _residue_outcome(plan, concept_id, column, reflexes)
        stats.unaccounted += 1
        stats.residue_policy_decided += 1

    ordered = tuple(outcomes[column] for column in sorted(outcomes))
    return ordered, stats


def _choose_column_commitment(
    satisfied: Sequence[CorrespondenceCommitment],
) -> CorrespondenceCommitment:
    """Pick among committed sets that all match one column.

    By mass first, and where the mass is equal by `TIE_BREAK_POLICY` — ascending
    lexicographic order of the proto segment, which is arbitrary and says so.
    The model gets a chance at it before this does: `test_proto_assembly` lists
    every such column so a session can condition one of the sets, split a set, or
    say in its summary that the evidence does not decide.
    """
    return min(
        satisfied,
        key=lambda item: (-item.confidence, item.proto_segment or "", item.set_id),
    )


def _assemble_segments(
    outcomes: Sequence[ColumnOutcome],
    restorations: Mapping[int, SegmentRestoration],
) -> tuple[str, ...]:
    """Concatenate the resolved columns, inserting restorations by index.

    Restoration indices are into the alignment under the committed overlays and
    are unaffected by other restorations, so however many are committed the
    insertion order is deterministic and independent of them. An index past the
    last resolved column appends, which is how a lost word-final segment is
    restored.
    """
    by_column = {outcome.resolution.column_index: outcome for outcome in outcomes}
    segments: list[str] = []
    for position in sorted(set(by_column) | set(restorations)):
        restoration = restorations.get(position)
        if restoration is not None:
            segments.append(restoration.proto_segment)
        outcome = by_column.get(position)
        if outcome is not None and outcome.resolution.proto_segment is not None:
            segments.append(outcome.resolution.proto_segment)
    return tuple(segments)


@dataclass(frozen=True)
class ConceptAssembly:
    """One concept's winning assembly, and everything a report needs from it."""

    report: ConceptAssemblyReport
    ambiguous_columns: tuple[ColumnResolution, ...]
    residue_policy_columns: int
    tie_broken_columns: int
    anchors_available: bool


class ProtoInventoryAssembler:
    """Build a parent beam from a committed inventory and the children's beams.

    Mirrors `RuleBasedReconstructor`'s constructor and `reconstruct` shape so the
    agent layer can pick a path by commit shape and nothing else changes. The
    anchor policy behaves as it does there, one step later: a candidate tuple is
    assembled into a form first, and the form is then compared to the concept's
    anchors, with a unique exact match taking the boost before
    `normalize_and_prune`.
    """

    def __init__(
        self,
        *,
        beam_width: int = 5,
        anchor_policy: AnchorPolicy | str = AnchorPolicy.ADVISORY,
        anchor_match_factor: float = 100.0,
        aligner: AlignmentProvider | None = None,
        engine: RuleEngine | None = None,
        max_candidate_tuples: int | None = None,
    ) -> None:
        if beam_width < 1:
            raise ValueError("beam_width must be positive")
        if not math.isfinite(anchor_match_factor) or anchor_match_factor < 1.0:
            raise ValueError("anchor_match_factor must be finite and at least 1")
        if max_candidate_tuples is not None and max_candidate_tuples < 1:
            raise ValueError("max_candidate_tuples must be positive")
        self.beam_width = beam_width
        self.aligner = aligner or LingPyAligner()
        self.engine = engine or RuleEngine()
        self.anchor_policy = AnchorPolicy(anchor_policy)
        self.anchor_match_factor = anchor_match_factor
        self.anchor_match_log_boost = (
            math.log(anchor_match_factor)
            if self.anchor_policy is AnchorPolicy.SCORED
            else 0.0
        )
        self.max_candidate_tuples = max_candidate_tuples or _tuple_budget(beam_width)
        # Identity is not assembly. An inventory that asserts nothing is walked
        # through the existing rule path with no rules, which is what keeps the
        # empty commit and the node-failure fallback bit-for-bit identical to
        # what they produce today.
        self._identity = RuleBasedReconstructor(
            beam_width=beam_width,
            anchor_policy=self.anchor_policy,
            anchor_match_factor=anchor_match_factor,
            engine=self.engine,
            aligner=self.aligner,
        )

    def align_candidate_tuple(
        self,
        concept_id: str,
        segments_by_child: Mapping[str, tuple[str, ...]],
        plan: AssemblyPlan,
        cache: dict[tuple, tuple[tuple[str | None, ...], ...]],
    ) -> tuple[tuple[str | None, ...], ...]:
        """Align one candidate tuple, positional against `child_node_ids`.

        Caching by candidate tuple is a requirement rather than an optimisation:
        assembly runs over the children's full beams, so a node aligns up to
        `beam_width ** children` tuples per concept and many of them repeat —
        every tuple that differs only in a child which contributes the same
        string, and every concept whose children happen to share a form.

        A child that does not attest the concept contributes an all-gap row, so
        the width of the returned rows always matches `child_node_ids`. That is
        what `build_correspondence_sets` does with an absent node, and it is
        right on the evidence: neither a gap nor an absence attests anything.
        """
        key = tuple(
            (child_id, segments_by_child.get(child_id))
            for child_id in plan.child_node_ids
        )
        cached = cache.get(key)
        if cached is not None:
            return cached
        override = self._matching_override(concept_id, segments_by_child, plan)
        if override is not None:
            rows = override.rows
            cache[key] = rows
            return rows
        present = [
            (child_id, segments_by_child[child_id])
            for child_id in plan.child_node_ids
            if child_id in segments_by_child
        ]
        lexicons = [
            LanguageLexicon(
                variety_id=child_id,
                name=child_id,
                forms=(
                    LexicalForm(
                        form_id=f"assembly:{child_id}:{concept_id}",
                        variety_id=child_id,
                        concept_id=concept_id,
                        segments=segments,
                    ),
                ),
            )
            for child_id, segments in present
        ]
        alignment_map = self.aligner.align_multiple(lexicons)
        aligned = {
            member.variety_id: member.aligned_segments
            for alignment in alignment_map.alignments
            for member in alignment.members
            if not member.is_anchor
        }
        width = max((len(row) for row in aligned.values()), default=0)
        rows = tuple(
            aligned.get(child_id, (None,) * width)
            for child_id in plan.child_node_ids
        )
        cache[key] = rows
        return rows

    @staticmethod
    def _matching_override(
        concept_id: str,
        segments_by_child: Mapping[str, tuple[str, ...]],
        plan: AssemblyPlan,
    ) -> AlignmentOverride | None:
        """The override laid over exactly these strings, if the model made one.

        An override is one concept's alignment of specific forms. It applies to
        a candidate tuple whose gapless rows are those forms and to no other, so
        a realignment can never silently re-lay a reading the model never looked
        at.
        """
        for override in plan.overrides.get(concept_id, ()):
            gapless = {
                child_id: tuple(
                    segment for segment in row if segment is not None
                )
                for child_id, row in zip(
                    plan.child_node_ids, override.rows, strict=False
                )
            }
            expected = {
                child_id: segments
                for child_id, segments in gapless.items()
                if segments
            }
            if expected == dict(segments_by_child):
                return override
        return None

    def _candidate_tuples(
        self,
        distributions: Sequence[tuple[str, object]],
    ) -> list[tuple[tuple[str, str, tuple[str, ...], float], ...]]:
        """The bounded Cartesian product over the attesting children's beams.

        Expanded child by child and pruned to `max_candidate_tuples` after each,
        by accumulated child mass — the same shape `_PartialCombination` already
        walks, with the transform replaced by an assembly that needs the whole
        tuple at once.
        """
        frontier: list[tuple[tuple[tuple[str, str, tuple[str, ...], float], ...], float]] = [
            ((), 0.0)
        ]
        for child_id, distribution in distributions:
            expanded = [
                (
                    (
                        *partial,
                        (
                            child_id,
                            candidate.candidate_id,
                            candidate.segments,
                            candidate.log_score,
                        ),
                    ),
                    score + candidate.log_score,
                )
                for partial, score in frontier
                for candidate in distribution.candidates
            ]
            expanded.sort(
                key=lambda item: (
                    -item[1],
                    tuple(entry[2] for entry in item[0]),
                )
            )
            frontier = expanded[: self.max_candidate_tuples]
        return [partial for partial, _score in frontier]

    def assemble_concept(
        self,
        parent_node_id: str,
        concept_id: str,
        distributions: Sequence[tuple[str, object]],
        plan: AssemblyPlan,
        *,
        anchors: Sequence[LexicalForm],
        derived: DerivedBranchRules,
        cache: dict[tuple, tuple[tuple[str | None, ...], ...]],
    ) -> tuple[list[RawCandidate], dict[tuple[str, ...], ConceptAssembly]]:
        """Assemble every candidate tuple of one concept into a parent form.

        Returns the raw candidates for `normalize_and_prune` and, per distinct
        assembled form, the report for the highest-scoring tuple that produced
        it. Keyed by form rather than by tuple because two tuples can assemble
        to one string, `normalize_and_prune` merges their mass, and the merged
        form can then outrank the single best tuple — so the caller has to look
        the report up by the form the beam actually reports, or the report and
        the beam would describe different reconstructions.

        A concept fewer than two children attest is passed
        through unchanged: there is no correspondence to read, the reflex tuple
        could match no set, and every column would fall to a residue policy whose
        witness may not even be the attesting child. Today's identity does the
        same thing, and it only ever emits forms some child actually produced.
        """
        anchor_segments = {anchor.form_id: anchor.segments for anchor in anchors}
        raw: list[RawCandidate] = []
        best: dict[tuple[str, ...], tuple[float, ConceptAssembly]] = {}
        pass_through = len(distributions) < 2
        for candidate_tuple in self._candidate_tuples(distributions):
            segments_by_child = {
                child_id: segments
                for child_id, _candidate_id, segments, _score in candidate_tuple
            }
            child_score = sum(score for *_rest, score in candidate_tuple)
            if pass_through:
                assembled = next(iter(segments_by_child.values()))
                outcomes: tuple[ColumnOutcome, ...] = ()
                stats = _ColumnStats()
                rows: tuple[tuple[str | None, ...], ...] = ()
                column_mass = 0.0
            else:
                rows = self.align_candidate_tuple(
                    concept_id, segments_by_child, plan, cache
                )
                outcomes, stats = resolve_columns(rows, concept_id, plan)
                assembled = _assemble_segments(
                    outcomes, plan.restorations.get(concept_id, {})
                )
                column_mass = sum(outcome.log_mass for outcome in outcomes) + (
                    RESTORATION_LOG_MASS
                    * len(plan.restorations.get(concept_id, {}))
                )
            if not assembled:
                # Every column reconstructed nothing. The concept has no parent
                # form under this reading; it is dropped rather than emitted as
                # an empty candidate, which `normalize_and_prune` refuses.
                continue
            matched_anchors = tuple(
                sorted(
                    anchor_id
                    for anchor_id, expected in anchor_segments.items()
                    if expected == assembled
                )
            )
            log_score = (
                child_score
                + column_mass
                + len(matched_anchors) * self.anchor_match_log_boost
            )
            raw.append(
                (
                    assembled,
                    log_score,
                    CandidateDerivation(
                        derivation_id=(
                            f"{parent_node_id}:{concept_id}:"
                            + ":".join(
                                candidate_id
                                for _child, candidate_id, *_rest in candidate_tuple
                            )
                        ),
                        child_candidate_ids=tuple(
                            candidate_id
                            for _child, candidate_id, *_rest in candidate_tuple
                        ),
                        rule_ids=(),
                        supporting_child_ids=tuple(
                            child_id for child_id, *_rest in candidate_tuple
                        ),
                        note=(
                            "children passed through: fewer than two attest this "
                            "concept"
                            if pass_through
                            else "assembled per correspondence set"
                        ),
                    ),
                )
            )
            previous = best.get(assembled)
            if previous is not None and log_score <= previous[0]:
                continue
            report = ConceptAssemblyReport(
                concept_id=concept_id,
                alignment_id=_assembly_alignment_id(
                    parent_node_id, concept_id, segments_by_child, plan
                ),
                assembled_segments=assembled,
                columns=tuple(outcome.resolution for outcome in outcomes),
                unaccounted_column_count=stats.unaccounted,
                column_count=len(outcomes),
                matched_anchor_ids=matched_anchors,
                cross_branch_assembled=(
                    not pass_through
                    and _no_child_reproduces(
                        assembled, segments_by_child, derived, self.engine
                    )
                ),
            )
            best[assembled] = (
                log_score,
                ConceptAssembly(
                    report=report,
                    ambiguous_columns=tuple(stats.ambiguous),
                    residue_policy_columns=stats.residue_policy_decided,
                    tie_broken_columns=stats.tie_broken,
                    anchors_available=bool(anchor_segments),
                ),
            )
        return raw, {form: entry[1] for form, entry in best.items()}

    def reconstruct(
        self,
        parent_node_id: str,
        children: Sequence[NodeBeamState],
        *,
        inventory: CommittedProtoInventory,
        anomalies: Sequence[AnomalyReport] = (),
        anchors: Sequence[LexicalForm] = (),
        evidence_context: NodeReconstructionContext | None = None,
        inspected_concept_ids: Sequence[str] | None = None,
        overrides: Sequence[AlignmentOverride] = (),
        override_singleton_sets_created: int = 0,
        held_out_unaccounted_column_rate: float | None = None,
    ) -> ReconstructionStep:
        """Combine child beams under a committed proto-inventory."""
        child_beams = tuple(children)
        if len(child_beams) < 2:
            raise ValueError("reconstruction requires at least two child beams")
        child_ids = tuple(child.node_id for child in child_beams)
        if len(set(child_ids)) != len(child_ids):
            raise ValueError("child beam node IDs must be unique")
        request = inventory.request
        if tuple(request.child_node_ids) != child_ids:
            raise ValueError(
                "the committed inventory's child_node_ids do not match the "
                f"child beams: {list(request.child_node_ids)} against "
                f"{list(child_ids)}"
            )
        plan = build_plan(
            child_ids,
            request.commitments,
            residue_policy=request.residue_policy,
            residue_witness_child_id=request.residue_witness_child_id,
            residue_dispositions=request.residue_dispositions,
            restorations=request.restorations,
            overrides=overrides,
        )
        if plan.asserts_nothing:
            return self._identity_step(
                parent_node_id,
                child_beams,
                inventory,
                anomalies=anomalies,
                anchors=anchors,
                evidence_context=evidence_context,
                inspected_concept_ids=inspected_concept_ids,
                overrides=overrides,
                override_singleton_sets_created=override_singleton_sets_created,
            )

        derived = derive_branch_rules(request.commitments, child_ids)
        distributions_by_child = tuple(
            {
                distribution.concept_id: distribution
                for distribution in child.distributions
            }
            for child in child_beams
        )
        concept_ids = sorted(
            set().union(
                *(set(distributions) for distributions in distributions_by_child)
            )
        )
        anchors_by_concept: dict[str, list[LexicalForm]] = defaultdict(list)
        active_anchors = () if self.anchor_policy is AnchorPolicy.IGNORE else anchors
        for anchor in active_anchors:
            anchors_by_concept[anchor.concept_id].append(anchor)

        cache: dict[tuple, tuple[tuple[str | None, ...], ...]] = {}
        output_distributions = []
        reports: list[ConceptAssemblyReport] = []
        tie_broken_concepts = 0
        assembled_columns = 0
        unaccounted_columns = 0
        residue_policy_columns = 0
        tie_broken_columns = 0
        cross_branch_concepts = 0
        assembled_concepts = 0
        anchor_mismatches = 0
        for concept_id in concept_ids:
            available = [
                (child.node_id, distributions[concept_id])
                for child, distributions in zip(
                    child_beams, distributions_by_child, strict=True
                )
                if concept_id in distributions
            ]
            raw, assemblies = self.assemble_concept(
                parent_node_id,
                concept_id,
                available,
                plan,
                anchors=anchors_by_concept[concept_id],
                derived=derived,
                cache=cache,
            )
            if not raw:
                continue
            distribution = normalize_and_prune(
                parent_node_id, concept_id, raw, beam_width=self.beam_width
            )
            output_distributions.append(distribution)
            tie_broken_concepts += decided_by_tie_break(distribution)
            # The report for the form the beam reports, not for the tuple that
            # scored highest before merging.
            assembly = assemblies.get(distribution.candidates[0].segments)
            if assembly is None:
                continue
            reports.append(assembly.report)
            assembled_columns += assembly.report.column_count
            unaccounted_columns += assembly.report.unaccounted_column_count
            residue_policy_columns += assembly.residue_policy_columns
            tie_broken_columns += assembly.tie_broken_columns
            if assembly.report.column_count:
                assembled_concepts += 1
                cross_branch_concepts += assembly.report.cross_branch_assembled
            if assembly.anchors_available and not assembly.report.matched_anchor_ids:
                anchor_mismatches += 1

        output_beam = NodeBeamState(
            node_id=parent_node_id,
            distributions=tuple(output_distributions),
            beam_width=self.beam_width,
            source_child_ids=child_ids,
        )
        concept_count = len(output_distributions)
        supports = [item.support for item in request.commitments]
        proto_phonemes = inventory.proto_phonemes or tuple(
            sorted(
                {
                    item.proto_segment
                    for item in request.commitments
                    if item.proto_segment is not None
                }
            )
        )
        diagnostics = ReconstructionDiagnostics(
            # Every rule counter below is zero because an inventory commits no
            # rules. The cascade it *derives* lives on the commit, where
            # `inspect-run` reads it; putting derived-rule counts here would
            # report a view as if the session had written it.
            rule_count=0,
            rule_complexity_cost=0,
            rule_results_evaluated=0,
            successful_applications=0,
            target_absent=0,
            context_mismatches=0,
            anchor_mismatches=anchor_mismatches,
            applicable_rule_results=0,
            rule_coverage=0.0,
            anomaly_count=len(anomalies),
            anomaly_rate=len(anomalies) / concept_count if concept_count else 0.0,
            contrast_reducing_rule_count=None,
            contrast_reducing_set_count=len(
                inventory_contrast_reductions(request.commitments)
            ),
            identity_reconstruction=inventory.identity_reconstruction,
            # Retired rather than reimplemented: one candidate tuple assembles
            # into exactly one parent form, so branch divergence about the parent
            # is structurally impossible and the metric's subject is gone.
            child_convergence_rate=None,
            divergent_concept_count=None,
            mean_branch_support=None,
            concepts_inspected=(
                len(set(inspected_concept_ids) & set(concept_ids))
                if inspected_concept_ids is not None
                else None
            ),
            concepts_available=len(concept_ids),
            tie_broken_concept_count=tie_broken_concepts,
            committed_set_count=len(request.commitments),
            proto_phoneme_count=len(proto_phonemes),
            assembled_column_count=assembled_columns,
            unaccounted_column_count=unaccounted_columns,
            unaccounted_column_rate=(
                unaccounted_columns / assembled_columns if assembled_columns else 0.0
            ),
            cross_branch_assembly_rate=(
                cross_branch_concepts / assembled_concepts
                if assembled_concepts
                else 0.0
            ),
            columns_decided_by_residue_policy=residue_policy_columns,
            columns_decided_by_tie_break=tie_broken_columns,
            mean_set_support=(sum(supports) / len(supports) if supports else 0.0),
            restored_segment_count=len(request.restorations),
            alignment_overrides=len({item.concept_id for item in overrides}),
            override_singleton_sets_created=override_singleton_sets_created,
            held_out_unaccounted_column_rate=held_out_unaccounted_column_rate,
        )
        maps, map_failure = self._identity._correspondence_maps(
            child_ids, evidence_context
        )
        if map_failure is not None:
            diagnostics = diagnostics.model_copy(
                update={"correspondence_map_failure": map_failure}
            )
        return ReconstructionStep(
            parent_node_id=parent_node_id,
            child_node_ids=child_ids,
            input_beams=child_beams,
            correspondence_maps=maps,
            output_beam=output_beam,
            assembly_reports=tuple(reports),
            anomaly_reports=tuple(anomalies),
            diagnostics=diagnostics,
        )

    def _identity_step(
        self,
        parent_node_id: str,
        child_beams: tuple[NodeBeamState, ...],
        inventory: CommittedProtoInventory,
        *,
        anomalies: Sequence[AnomalyReport],
        anchors: Sequence[LexicalForm],
        evidence_context: NodeReconstructionContext | None,
        inspected_concept_ids: Sequence[str] | None,
        overrides: Sequence[AlignmentOverride],
        override_singleton_sets_created: int,
    ) -> ReconstructionStep:
        """An inventory that asserts nothing, walked through the identity path.

        Bit-for-bit what a `rules: []` commit produces, with the inventory
        counters filled in so a reader can still tell that this node committed an
        empty inventory rather than that it predates the protocol.
        """
        step = self._identity.reconstruct(
            parent_node_id,
            child_beams,
            anomalies=anomalies,
            anchors=anchors,
            evidence_context=evidence_context,
            inspected_concept_ids=inspected_concept_ids,
        )
        return step.model_copy(
            update={
                "diagnostics": step.diagnostics.model_copy(
                    update={
                        "committed_set_count": 0,
                        "proto_phoneme_count": 0,
                        "assembled_column_count": 0,
                        "unaccounted_column_count": 0,
                        "unaccounted_column_rate": 0.0,
                        "cross_branch_assembly_rate": 0.0,
                        "columns_decided_by_residue_policy": 0,
                        "columns_decided_by_tie_break": 0,
                        "mean_set_support": 0.0,
                        "restored_segment_count": 0,
                        "contrast_reducing_set_count": 0,
                        "contrast_reducing_rule_count": None,
                        "alignment_overrides": len(
                            {item.concept_id for item in overrides}
                        ),
                        "override_singleton_sets_created": (
                            override_singleton_sets_created
                        ),
                        "identity_reconstruction": (
                            inventory.identity_reconstruction
                        ),
                    }
                )
            }
        )


def _assembly_alignment_id(
    parent_node_id: str,
    concept_id: str,
    segments_by_child: Mapping[str, tuple[str, ...]],
    plan: AssemblyPlan,
) -> str:
    """Name the alignment one assembly used, reproducibly.

    Derived from the parent, the concept, and the exact strings aligned, so two
    readers of the same record resolve it to the same columns without the rows
    being carried in the report.
    """
    material = "\0".join(
        f"{child_id}\t{' '.join(segments_by_child.get(child_id, ()))}"
        for child_id in plan.child_node_ids
    )
    digest = hashlib.sha256(material.encode()).hexdigest()[:12]
    return f"asm:{parent_node_id}:{concept_id}:{digest}"


def _no_child_reproduces(
    assembled: tuple[str, ...],
    segments_by_child: Mapping[str, tuple[str, ...]],
    derived: DerivedBranchRules,
    engine: RuleEngine,
) -> bool:
    """Is this concept cross-branch assembled?

    True when *no* single child's derived cascade, applied to that child's own
    form, reproduces the assembled parent form. Stated this way it is decidable
    in one pass with no prior knowledge of which concepts mixed — and its
    converse is the verification of the derived rules: on every concept where
    some child does reproduce the assembled form, that child's rules are
    confirmed against the assembler rather than assumed to agree with it.
    """
    for child_id, segments in segments_by_child.items():
        rules = tuple(
            rule.rule
            for rule in derived.rules
            if child_id in rule.source_child_ids
        )
        form = LexicalForm(
            form_id=f"verify:{child_id}",
            variety_id=child_id,
            concept_id="verify",
            segments=segments,
        )
        transformed, _reports = engine.apply_rules(rules, (form,))
        if transformed[0].segments == assembled:
            return False
    return True


__all__ = [
    "RESIDUE_COLUMN_CONFIDENCE",
    "RESIDUE_COLUMN_LOG_MASS",
    "RESTORATION_LOG_MASS",
    "AssemblyPlan",
    "ColumnOutcome",
    "ContrastReducingSet",
    "DerivedBranchRules",
    "ProtoInventoryAssembler",
    "build_plan",
    "derive_branch_rules",
    "inventory_contrast_reductions",
    "resolve_columns",
]
