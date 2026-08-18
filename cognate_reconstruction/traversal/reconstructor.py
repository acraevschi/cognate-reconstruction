"""Deterministic rule-driven combination of an n-ary child beam set."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from cognate_reconstruction.alignment.lingpy_adapter import LingPyAligner
from cognate_reconstruction.alignment.protocol import AlignmentProvider
from cognate_reconstruction.rules.engine import RuleEngine
from cognate_reconstruction.schemas.alignment import (
    CorrespondenceDetail,
    CorrespondenceMap,
)
from cognate_reconstruction.schemas.beam import CandidateDerivation, NodeBeamState
from cognate_reconstruction.schemas.lexicon import LexicalForm
from cognate_reconstruction.schemas.rules import (
    ApplicationStatus,
    AnchorPolicy,
    AnomalyReport,
    ParsedSoundRule,
    ReconstructionRule,
    RuleApplicationReport,
)
from cognate_reconstruction.schemas.traversal import ReconstructionDiagnostics
from cognate_reconstruction.schemas.traversal import (
    NodeReconstructionContext,
    ReconstructionStep,
)
from cognate_reconstruction.traversal.beam import (
    RawCandidate,
    decided_by_tie_break,
    normalize_and_prune,
)
from cognate_reconstruction.traversal.convergence import report_convergence


@dataclass(frozen=True)
class _TransformedCandidate:
    segments: tuple[str, ...]
    confidence_log_score: float
    applied_rule_ids: tuple[str, ...]
    matched_anchor_ids: tuple[str, ...]


BranchSupports = tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]
"""Per distinct parent output, the active children that produced it."""


@dataclass(frozen=True)
class _PartialCombination:
    """A bounded Cartesian-product state over children processed so far.

    `branch_supports` replaced a set of distinct outputs. A set records *which*
    forms the children proposed and throws away *how many* proposed each, so a
    form backed by four branches and a form backed by one were indistinguishable
    by the time they were scored.
    """

    branch_supports: BranchSupports
    anchor_matches: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]
    log_score: float
    derivations: tuple[CandidateDerivation, ...]

    @property
    def total_support(self) -> int:
        """Active children folded into this state; one output each."""
        return sum(len(child_ids) for _, child_ids in self.branch_supports)


def _logsumexp(values: Sequence[float]) -> float:
    maximum = max(values)
    return maximum + math.log(sum(math.exp(value - maximum) for value in values))


def _ordered_unique(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _extend_supports(
    existing: BranchSupports,
    output: tuple[str, ...],
    child_id: str,
) -> BranchSupports:
    supports = {segments: list(child_ids) for segments, child_ids in existing}
    supports.setdefault(output, []).append(child_id)
    return tuple(
        (segments, tuple(child_ids))
        for segments, child_ids in sorted(supports.items())
    )


def _support_signature(
    branch_supports: BranchSupports,
) -> tuple[tuple[tuple[str, ...], int], ...]:
    """The score-relevant content of a support map: outputs and their counts.

    Two partial states scoring identically from here on should merge, and the
    score depends on the counts rather than on which child contributed which
    form. Keying on the counts keeps `{X: c1, Y: c2}` and `{X: c2, Y: c1}` a
    single state, exactly as the old output-set key did, while separating the
    states the old key wrongly conflated — a four-branch form and a one-branch
    form of the same shape.
    """
    return tuple(
        (segments, len(child_ids)) for segments, child_ids in branch_supports
    )


def _branch_log_weight(support: int, total_support: int) -> float:
    """Log share of a partial's mass going to a form `support` children produced.

    Operational heuristic, not a probabilistic model of sound change: a parent
    candidate takes the share of its state's mass that matches the share of
    active children proposing it. It is a strict generalization of the flat
    `-log(len(outputs))` branch penalty it replaces — the two agree exactly
    whenever every distinct output has equal support, which is every binary node
    whose children disagree — and it differs only where the old rule handed the
    same score to a form four branches attest and a form one branch attests.
    """
    return math.log(support) - math.log(total_support)


def _extend_anchor_matches(
    existing: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...],
    output: tuple[str, ...],
    anchor_ids: tuple[str, ...],
) -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
    matches = {segments: set(ids) for segments, ids in existing}
    matches.setdefault(output, set()).update(anchor_ids)
    return tuple(
        (segments, tuple(sorted(ids)))
        for segments, ids in sorted(matches.items())
    )


def _merge_and_prune_partials(
    partials: Sequence[_PartialCombination],
    *,
    beam_width: int,
    anchor_match_log_boost: float,
) -> list[_PartialCombination]:
    """Merge equivalent partial states and prune after each child expansion.

    States are equivalent when they carry the same per-output support counts and
    the same anchor matches, since those are what the remaining scoring reads.
    The merged state keeps the *highest-scoring* member's child-ID attribution:
    equal counts can come from different children, and provenance is bounded here
    the same way `derivations` is rather than accumulating every attribution.
    """
    grouped: dict[
        tuple[
            tuple[tuple[tuple[str, ...], int], ...],
            tuple[tuple[tuple[str, ...], tuple[str, ...]], ...],
        ],
        list[_PartialCombination],
    ] = defaultdict(list)
    for partial in partials:
        grouped[
            (_support_signature(partial.branch_supports), partial.anchor_matches)
        ].append(partial)
    merged = [
        _PartialCombination(
            branch_supports=max(
                items, key=lambda item: item.log_score
            ).branch_supports,
            anchor_matches=anchor_matches,
            log_score=_logsumexp([item.log_score for item in items]),
            # Bound provenance growth along with hypothesis growth.
            derivations=tuple(
                derivation
                for item in items
                for derivation in item.derivations
            )[:beam_width],
        )
        for (_signature, anchor_matches), items in grouped.items()
    ]
    return sorted(
        merged,
        key=lambda item: (
            -(
                item.log_score
                + max((len(ids) for _, ids in item.anchor_matches), default=0)
                * anchor_match_log_boost
            ),
            _support_signature(item.branch_supports),
            item.anchor_matches,
        ),
    )[:beam_width]


class RuleBasedReconstructor:
    """Apply branch-scoped rule cascades and combine n-ary child evidence.

    Rules are interpreted in their written direction. If historical inference
    requires inverse rules, callers must supply those inverse hypotheses
    explicitly; the engine never guesses an inverse for a non-bijective law.

    Anchors are advisory by default: matches remain visible in reports without
    changing scores. With ``anchor_policy=SCORED``, ``anchor_match_factor`` is a
    likelihood multiplier applied once per unique match before pruning.
    """

    def __init__(
        self,
        *,
        beam_width: int = 5,
        anchor_policy: AnchorPolicy | str = AnchorPolicy.ADVISORY,
        anchor_match_factor: float = 100.0,
        engine: RuleEngine | None = None,
        aligner: AlignmentProvider | None = None,
    ) -> None:
        if beam_width < 1:
            raise ValueError("beam_width must be positive")
        if not math.isfinite(anchor_match_factor) or anchor_match_factor < 1.0:
            raise ValueError("anchor_match_factor must be finite and at least 1")
        self.beam_width = beam_width
        # Used only to record what the children's evidence showed. Nothing it
        # returns reaches a score; see `_correspondence_maps`.
        self.aligner = aligner or LingPyAligner()
        self.anchor_policy = AnchorPolicy(anchor_policy)
        self.anchor_match_factor = anchor_match_factor
        self.anchor_match_log_boost = (
            math.log(anchor_match_factor)
            if self.anchor_policy is AnchorPolicy.SCORED
            else 0.0
        )
        self.engine = engine or RuleEngine()

    @staticmethod
    def _scope_rules(
        rules: Sequence[ReconstructionRule | ParsedSoundRule],
        child_ids: tuple[str, ...],
    ) -> tuple[ReconstructionRule, ...]:
        active = set(child_ids)
        scoped: list[ReconstructionRule] = []
        for rule in rules:
            normalized = (
                rule
                if isinstance(rule, ReconstructionRule)
                else ReconstructionRule(
                    rule=rule,
                    source_child_ids=child_ids,
                    confidence=1.0,
                )
            )
            unknown = sorted(set(normalized.source_child_ids) - active)
            if unknown:
                raise ValueError(
                    f"rule {normalized.rule.rule_id!r} targets inactive children: {unknown}"
                )
            scoped.append(normalized)
        return tuple(scoped)

    def _transform(
        self,
        parent_node_id: str,
        concept_id: str,
        child_id: str,
        candidate_id: str,
        segments: tuple[str, ...],
        rules: Sequence[ReconstructionRule],
        anchors: Sequence[LexicalForm],
    ) -> tuple[_TransformedCandidate, tuple[RuleApplicationReport, ...]]:
        form = LexicalForm(
            form_id=f"beam-form:{candidate_id}",
            variety_id=parent_node_id,
            concept_id=concept_id,
            segments=segments,
        )
        child_rules = tuple(rule for rule in rules if child_id in rule.source_child_ids)
        active_anchors = () if self.anchor_policy is AnchorPolicy.IGNORE else anchors
        anchor_expected = {
            form.form_id: {anchor.form_id: anchor.segments for anchor in active_anchors}
        }
        transformed, reports = self.engine.apply_rules(
            tuple(rule.rule for rule in child_rules),
            (form,),
            anchor_expected=anchor_expected,
            source_candidate_ids={form.form_id: candidate_id},
        )
        applied_rule_ids: list[str] = []
        confidence_score = 0.0
        matched_anchor_ids: set[str] = set()
        for scoped_rule, report in zip(child_rules, reports, strict=True):
            result = report.results[0]
            if result.locations:
                applied_rule_ids.append(scoped_rule.rule.rule_id)
                confidence_score += math.log(scoped_rule.confidence)
            matched_anchor_ids.update(result.matched_anchor_ids)
        final_segments = transformed[0].segments
        final_anchor_ids = {
            anchor.form_id
            for anchor in active_anchors
            if anchor.segments == final_segments
        }
        matched_anchor_ids.intersection_update(final_anchor_ids)
        return (
            _TransformedCandidate(
                segments=final_segments,
                confidence_log_score=confidence_score,
                applied_rule_ids=tuple(applied_rule_ids),
                matched_anchor_ids=tuple(sorted(matched_anchor_ids)),
            ),
            reports,
        )

    def _correspondence_maps(
        self,
        child_ids: tuple[str, ...],
        evidence_context: NodeReconstructionContext | None,
    ) -> tuple[CorrespondenceMap, ...]:
        """Record what this node's children corresponded in, pair by pair.

        Diagnostics, not scoring: no count here reaches a rule, a candidate, or
        the beam. `ReconstructionStep.correspondence_maps` was declared and
        serialized as `[]` into every artifact by every run, which made a
        reconstruction impossible to audit against its own evidence without
        re-running the aligner by hand.

        The compact rendering is deliberate. The full trace is one record per
        aligned column per node pair, so recording it would put a payload in
        every step that no reader asked for; the counts are the auditable claim,
        and `alignment_ids` reproduce exactly — they are derived from the child
        IDs, the concept, and the cognate set — for a reader who wants the
        columns back.

        The source is the evidence context's own child lexicons, so this is the
        same view the evidence tools give the model for these children,
        reconstructed child beams included. A caller that supplies no evidence
        context gets nothing rather than a guess: the input beams alone carry
        every retained candidate with no cognate-set grouping, which is not the
        evidence the node was reasoning about.
        """
        if evidence_context is None:
            return ()
        lexicons_by_id = {
            item.node_id: item.lexicon for item in evidence_context.available_nodes
        }
        lexicons = [
            lexicons_by_id[child_id]
            for child_id in child_ids
            if child_id in lexicons_by_id
        ]
        if len(lexicons) < 2:
            return ()
        return self.aligner.align_multiple(
            lexicons,
            correspondence_detail=CorrespondenceDetail.SUMMARY,
        ).pairwise_correspondences

    def reconstruct(
        self,
        parent_node_id: str,
        children: Sequence[NodeBeamState],
        *,
        rules: Sequence[ReconstructionRule | ParsedSoundRule] = (),
        anomalies: Sequence[AnomalyReport] = (),
        anchors: Sequence[LexicalForm] = (),
        evidence_context: NodeReconstructionContext | None = None,
        inspected_concept_ids: Sequence[str] | None = None,
    ) -> ReconstructionStep:
        """Combine child beams under a committed cascade.

        `inspected_concept_ids` are the concepts a session actually looked at.
        Only the agent layer knows them, and only that layer passes them; `None`
        means "nobody recorded this", which is what a purely deterministic run
        should say rather than claiming it inspected nothing.
        """
        child_beams = tuple(children)
        if len(child_beams) < 2:
            raise ValueError("reconstruction requires at least two child beams")
        child_ids = tuple(child.node_id for child in child_beams)
        if len(set(child_ids)) != len(child_ids):
            raise ValueError("child beam node IDs must be unique")
        scoped_rules = self._scope_rules(rules, child_ids)

        distributions_by_child = tuple(
            {distribution.concept_id: distribution for distribution in child.distributions}
            for child in child_beams
        )
        concept_ids = sorted(
            set().union(*(set(distributions) for distributions in distributions_by_child))
        )
        anchors_by_concept: dict[str, list[LexicalForm]] = defaultdict(list)
        for anchor in anchors:
            anchors_by_concept[anchor.concept_id].append(anchor)

        output_distributions = []
        all_reports: list[RuleApplicationReport] = []
        # What each child's best candidate became after its own scoped cascade,
        # which is what "the children agreed" is a claim about.
        convergence_outputs: dict[str, dict[str, tuple[tuple[str, ...], ...]]] = {}
        winning_support: list[float] = []
        tie_broken_concepts = 0
        for concept_id in concept_ids:
            available = [
                (child, distributions[concept_id])
                for child, distributions in zip(
                    child_beams, distributions_by_child, strict=True
                )
                if concept_id in distributions
            ]
            partials: list[_PartialCombination] = []
            child_top_outputs: dict[str, tuple[str, ...]] = {}
            for child_index, (child, distribution) in enumerate(available):
                transformed_candidates = []
                for candidate in distribution.candidates:
                    transformed, reports = self._transform(
                        parent_node_id,
                        concept_id,
                        child.node_id,
                        candidate.candidate_id,
                        candidate.segments,
                        scoped_rules,
                        anchors_by_concept[concept_id],
                    )
                    all_reports.extend(reports)
                    transformed_candidates.append((candidate, transformed))
                # Candidates are sorted by descending mass, so the first is the
                # form this child would report on its own.
                child_top_outputs[child.node_id] = transformed_candidates[0][
                    1
                ].segments

                expanded: list[_PartialCombination] = []
                if child_index == 0:
                    for candidate, transformed in transformed_candidates:
                        note = "single child evidence"
                        if transformed.matched_anchor_ids:
                            note += "; matched anchors: " + ", ".join(
                                transformed.matched_anchor_ids
                            )
                        expanded.append(
                            _PartialCombination(
                                branch_supports=(
                                    (transformed.segments, (child.node_id,)),
                                ),
                                anchor_matches=(
                                    (
                                        transformed.segments,
                                        transformed.matched_anchor_ids,
                                    ),
                                ),
                                log_score=candidate.log_score
                                + transformed.confidence_log_score,
                                derivations=(
                                    CandidateDerivation(
                                        derivation_id=(
                                            f"{parent_node_id}:{concept_id}:"
                                            f"{candidate.candidate_id}"
                                        ),
                                        child_candidate_ids=(candidate.candidate_id,),
                                        rule_ids=transformed.applied_rule_ids,
                                        note=note,
                                    ),
                                ),
                            )
                        )
                else:
                    for partial in partials:
                        for candidate, transformed in transformed_candidates:
                            branch_supports = _extend_supports(
                                partial.branch_supports,
                                transformed.segments,
                                child.node_id,
                            )
                            anchor_matches = _extend_anchor_matches(
                                partial.anchor_matches,
                                transformed.segments,
                                transformed.matched_anchor_ids,
                            )
                            derivations = tuple(
                                CandidateDerivation(
                                    derivation_id=(
                                        f"{derivation.derivation_id}:"
                                        f"{candidate.candidate_id}"
                                    ),
                                    child_candidate_ids=(
                                        *derivation.child_candidate_ids,
                                        candidate.candidate_id,
                                    ),
                                    rule_ids=_ordered_unique(
                                        (
                                            *derivation.rule_ids,
                                            *transformed.applied_rule_ids,
                                        )
                                    ),
                                    note="incremental n-ary child-beam derivation",
                                )
                                for derivation in partial.derivations
                            )
                            expanded.append(
                                _PartialCombination(
                                    branch_supports=branch_supports,
                                    anchor_matches=anchor_matches,
                                    log_score=(
                                        partial.log_score
                                        + candidate.log_score
                                        + transformed.confidence_log_score
                                    ),
                                    derivations=derivations,
                                )
                            )
                partials = _merge_and_prune_partials(
                    expanded,
                    beam_width=self.beam_width,
                    anchor_match_log_boost=self.anchor_match_log_boost,
                )

            raw: list[RawCandidate] = []
            for partial in partials:
                total_support = partial.total_support
                anchor_matches = dict(partial.anchor_matches)
                for output, supporting_child_ids in partial.branch_supports:
                    raw.append(
                        (
                            output,
                            partial.log_score
                            + _branch_log_weight(
                                len(supporting_child_ids), total_support
                            )
                            + len(anchor_matches.get(output, ()))
                            * self.anchor_match_log_boost,
                            # One derivation per output, naming the branches that
                            # produced exactly this form.
                            partial.derivations[0].model_copy(
                                update={
                                    "supporting_child_ids": supporting_child_ids
                                }
                            ),
                        )
                    )
            distribution = normalize_and_prune(
                parent_node_id,
                concept_id,
                raw,
                beam_width=self.beam_width,
            )
            output_distributions.append(distribution)
            tie_broken_concepts += decided_by_tie_break(distribution)
            convergence_outputs[concept_id] = {
                child_id: (segments,)
                for child_id, segments in child_top_outputs.items()
            }
            winning_segments = distribution.candidates[0].segments
            winning_support.append(
                sum(
                    segments == winning_segments
                    for segments in child_top_outputs.values()
                )
                / len(child_beams)
            )

        output_beam = NodeBeamState(
            node_id=parent_node_id,
            distributions=tuple(output_distributions),
            beam_width=self.beam_width,
            source_child_ids=child_ids,
        )
        unique_results = {}
        for report in all_reports:
            for result in report.results:
                key = (
                    report.rule.rule_id,
                    result.form_id,
                    result.source_candidate_id,
                    result.input_segments,
                    result.output_segments,
                )
                unique_results[key] = result
        evaluated_results = tuple(unique_results.values())
        successful = sum(bool(result.locations) for result in evaluated_results)
        # A form that never contained the target could not have been changed by
        # the rule; it is vacuous for that rule rather than a failure of it.
        applicable = sum(
            result.status is not ApplicationStatus.TARGET_ABSENT
            for result in evaluated_results
        )
        complexity = sum(
            1
            + len(rule.rule.target.tokens)
            + len(rule.rule.replacement.tokens)
            + (
                len(rule.rule.environment.left.tokens)
                if rule.rule.environment.left is not None
                else 0
            )
            + (
                len(rule.rule.environment.right.tokens)
                if rule.rule.environment.right is not None
                else 0
            )
            + int(rule.rule.environment.word_initial)
            + int(rule.rule.environment.word_final)
            for rule in scoped_rules
        )
        concept_count = len(output_distributions)
        convergence = report_convergence(convergence_outputs)
        diagnostics = ReconstructionDiagnostics(
            rule_count=len(scoped_rules),
            rule_complexity_cost=complexity,
            rule_results_evaluated=len(evaluated_results),
            successful_applications=successful,
            target_absent=sum(
                result.status is ApplicationStatus.TARGET_ABSENT
                for result in evaluated_results
            ),
            context_mismatches=sum(
                result.status is ApplicationStatus.CONTEXT_MISMATCH
                for result in evaluated_results
            ),
            anchor_mismatches=sum(
                result.status is ApplicationStatus.ANCHOR_MISMATCH
                for result in evaluated_results
            ),
            applicable_rule_results=applicable,
            rule_coverage=(successful / applicable if applicable else 0.0),
            anomaly_count=len(anomalies),
            anomaly_rate=len(anomalies) / concept_count if concept_count else 0.0,
            identity_reconstruction=not scoped_rules,
            # A node with no concepts has nothing to agree or disagree about;
            # 0.0 would read as total divergence rather than as no evidence.
            child_convergence_rate=convergence.rate if concept_count else None,
            divergent_concept_count=(
                convergence.divergent_concept_count if concept_count else None
            ),
            divergent_concept_ids=convergence.reported_divergent_concept_ids,
            mean_branch_support=(
                sum(winning_support) / len(winning_support)
                if winning_support
                else None
            ),
            concepts_inspected=(
                len(set(inspected_concept_ids) & set(concept_ids))
                if inspected_concept_ids is not None
                else None
            ),
            concepts_available=len(concept_ids),
            tie_broken_concept_count=tie_broken_concepts,
        )
        return ReconstructionStep(
            parent_node_id=parent_node_id,
            child_node_ids=child_ids,
            input_beams=child_beams,
            correspondence_maps=self._correspondence_maps(
                child_ids, evidence_context
            ),
            output_beam=output_beam,
            rule_reports=tuple(all_reports),
            anomaly_reports=tuple(anomalies),
            diagnostics=diagnostics,
        )
