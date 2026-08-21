"""Score a run's committed changes against a synthetic family's answer key.

This is what a synthetic benchmark buys that no published dataset can. A run
that reconstructs the right forms via the wrong changes is a different result
from one that got both, and until there is an answer key nothing can tell them
apart — the forms are all anyone can check.

Three measurements, in increasing order of how much they mean:

- **rule precision and recall**, matching committed rules against the true
  child-to-parent cascade structurally. Strict and deliberately literal: two
  spellings of one change (`e > a / ʔ_` and `ʔ e > ʔ a`) do not match. Read it
  as a lower bound.
- **functional recovery**, applying the committed cascade for a branch to that
  branch's gold forms and asking whether the parent's gold forms come back.
  This is the measurement that survives a different spelling of the same change.
- **directionality**, which is free here and checkable nowhere else. The branch
  that innovated is the branch the definition gave a rule to, so a rule scoped
  to a branch the answer key left empty is a rule pointed at a branch that did
  not change — whatever its `directionality_rationale` asserts.

Everything here is a report. Nothing gates a trajectory, weights a candidate,
or decides whether a run was valid; see `docs/report_reject_or_score.md`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from cognate_reconstruction.agent.trajectory import AgentTrajectory
from cognate_reconstruction.rules.engine import RuleEngine
from cognate_reconstruction.rules.parser import parse_rule
from cognate_reconstruction.schemas.lexicon import LexicalForm
from cognate_reconstruction.schemas.synthetic import SyntheticAnswerKey

RuleShape = tuple[
    tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...], bool, bool
]


def rule_shape(dsl: str) -> RuleShape | None:
    """The parsed content of a rule, for comparing two spellings of one change.

    `None` when the text does not parse — which happens: a committed rule is
    always parseable, but an answer key edited by hand may not be, and reporting
    that as an unmatched rule is more useful than raising.
    """
    try:
        parsed = parse_rule(dsl)
    except ValueError:
        return None
    environment = parsed.environment
    return (
        parsed.target.tokens,
        parsed.replacement.tokens,
        environment.left.tokens if environment.left else (),
        environment.right.tokens if environment.right else (),
        environment.word_initial,
        environment.word_final,
    )


@dataclass(frozen=True)
class CommittedBranchRule:
    """One committed rule, resolved to the single branch it is scoped to."""

    parent_node_id: str
    child_node_id: str
    dsl: str
    confidence: float
    directionality_rationale: str | None


@dataclass(frozen=True)
class BranchScore:
    node_id: str
    parent_node_id: str
    innovated: bool
    invertible: bool
    true_forward_rules: tuple[str, ...]
    true_inverse_rules: tuple[str, ...]
    committed_rules: tuple[str, ...]
    matched_rules: tuple[str, ...]
    """Committed rules matching some true rule — the *precision* numerator."""
    matched_true_rules: tuple[str, ...]
    """True rules matched by some committed rule — the *recall* numerator.

    Kept separate from `matched_rules` because the two counts differ whenever a
    commit spells one change twice: `x > k` and `x > k / _` are the same rule to
    the engine, and counting both against a single true rule would report a
    recall above 1.0.
    """
    unmatched_true_rules: tuple[str, ...]
    functional_recovery_rate: float | None
    misdirected: bool
    misdirected_rationales: tuple[str, ...] = field(default=())

    @property
    def precision(self) -> float | None:
        if not self.committed_rules:
            return None
        return len(self.matched_rules) / len(self.committed_rules)

    @property
    def recall(self) -> float | None:
        if not self.true_inverse_rules:
            return None
        return len(self.matched_true_rules) / len(self.true_inverse_rules)

    def as_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "parent_node_id": self.parent_node_id,
            "innovated": self.innovated,
            "invertible": self.invertible,
            "true_forward_rules": list(self.true_forward_rules),
            "true_inverse_rules": list(self.true_inverse_rules),
            "committed_rules": list(self.committed_rules),
            "matched_rules": list(self.matched_rules),
            "matched_true_rules": list(self.matched_true_rules),
            "unmatched_true_rules": list(self.unmatched_true_rules),
            "rule_precision": self.precision,
            "rule_recall": self.recall,
            "functional_recovery_rate": self.functional_recovery_rate,
            "misdirected": self.misdirected,
            "misdirected_rationales": list(self.misdirected_rationales),
        }


@dataclass(frozen=True)
class SyntheticRunScore:
    family: str
    branches: tuple[BranchScore, ...]
    committed_nodes: tuple[str, ...]
    failed_nodes: tuple[str, ...]
    unknown_branches: tuple[str, ...]

    @property
    def rule_precision(self) -> float | None:
        committed = sum(len(branch.committed_rules) for branch in self.branches)
        matched = sum(len(branch.matched_rules) for branch in self.branches)
        return matched / committed if committed else None

    @property
    def rule_recall(self) -> float | None:
        true_rules = sum(
            len(branch.true_inverse_rules) for branch in self.branches
        )
        matched = sum(
            len(branch.matched_true_rules) for branch in self.branches
        )
        return matched / true_rules if true_rules else None

    @property
    def misdirected_rule_count(self) -> int:
        return sum(
            len(branch.committed_rules)
            for branch in self.branches
            if branch.misdirected
        )

    @property
    def reachable_true_rules(self) -> int:
        """True rules a branch-scoped commit could express at all.

        A branch containing a deletion has no child-to-parent cascade, because
        the DSL has no empty-target insertion, so recall over *all* true changes
        would charge the model for a rule it cannot write. This is the honest
        denominator; the raw one is reported beside it.
        """
        return sum(len(branch.true_inverse_rules) for branch in self.branches)

    def as_dict(self) -> dict:
        return {
            "family": self.family,
            "rule_precision": self.rule_precision,
            "rule_recall": self.rule_recall,
            "reachable_true_rules": self.reachable_true_rules,
            "misdirected_rule_count": self.misdirected_rule_count,
            "misdirected_branches": [
                branch.node_id for branch in self.branches if branch.misdirected
            ],
            "committed_nodes": list(self.committed_nodes),
            "failed_nodes": list(self.failed_nodes),
            "unknown_branches": list(self.unknown_branches),
            "branches": [branch.as_dict() for branch in self.branches],
            "note": (
                "rule_precision and rule_recall match rule spellings exactly "
                "and are a lower bound; functional_recovery_rate per branch is "
                "the measurement that survives a different spelling of the same "
                "change. A misdirected rule is one scoped to a branch the "
                "answer key gave no rule at all, which is directionality "
                "checked mechanically rather than read out of the prose."
            ),
            "misdirection_caveat": (
                "Read misdirected_rule_count against failed_nodes. When a node "
                "below the committing one was walked over as an identity "
                "fallback, its children's forms reach the parent unchanged, and "
                "a rule the model then scopes to that fallback node may be "
                "attributing a real change to the wrong *level* rather than to "
                "a branch that did not change. Both are worth knowing and they "
                "are not the same mistake; the harness reports the count and "
                "the failures side by side rather than deciding which it was."
            ),
        }


def committed_branch_rules(
    trajectories: Sequence[AgentTrajectory],
) -> tuple[tuple[CommittedBranchRule, ...], tuple[str, ...], tuple[str, ...]]:
    """Flatten every completed session's commit to one record per (rule, child).

    A rule scoped to three children is three claims about three branches, and
    the answer key has three separate answers, so it is counted three times.
    """
    rules: list[CommittedBranchRule] = []
    committed: list[str] = []
    failed: list[str] = []
    for trajectory in trajectories:
        commit = trajectory.committed_reconstruction
        if commit is None or not trajectory.completed:
            failed.append(trajectory.node_id)
            continue
        committed.append(trajectory.node_id)
        for rule in commit.request.rules:
            for child_id in rule.source_child_ids:
                rules.append(
                    CommittedBranchRule(
                        parent_node_id=trajectory.node_id,
                        child_node_id=child_id,
                        dsl=rule.dsl,
                        confidence=rule.confidence,
                        directionality_rationale=rule.directionality_rationale,
                    )
                )
    return tuple(rules), tuple(committed), tuple(failed)


def _functional_recovery(
    answer_key: SyntheticAnswerKey,
    child_id: str,
    parent_id: str,
    committed: Sequence[str],
) -> float | None:
    """Share of concepts on which the committed cascade recovers the parent.

    Computed over the answer key's own lexicons, which are the regular output
    of the generator before any controlled noise: a rule cannot be expected to
    undo a perturbation the definition introduced on purpose.
    """
    lexicons = {
        lexicon.variety_id: lexicon for lexicon in answer_key.node_lexicons
    }
    if child_id not in lexicons or parent_id not in lexicons:
        return None
    child_forms = lexicons[child_id].forms
    expected = {
        form.concept_id: form.segments for form in lexicons[parent_id].forms
    }
    if not child_forms:
        return None
    parsed = []
    for dsl in committed:
        try:
            parsed.append(parse_rule(dsl))
        except ValueError:
            continue
    if parsed:
        transformed, _ = RuleEngine().apply_rules(parsed, child_forms)
    else:
        transformed: tuple[LexicalForm, ...] = child_forms
    hits = sum(
        expected.get(form.concept_id) == form.segments for form in transformed
    )
    return hits / len(transformed)


def score_run(
    answer_key: SyntheticAnswerKey,
    trajectories: Sequence[AgentTrajectory],
    *,
    branch_rules: (
        tuple[Sequence[CommittedBranchRule], Sequence[str], Sequence[str]] | None
    ) = None,
) -> SyntheticRunScore:
    """Score a run, or a hand-built commit set supplied as `branch_rules`.

    The override exists so the scoring itself can be exercised without a live
    model: what a run contributes is a set of (rule, branch) claims, and those
    can be written down directly.
    """
    rules, committed_nodes, failed_nodes = (
        branch_rules
        if branch_rules is not None
        else committed_branch_rules(trajectories)
    )
    by_child: dict[str, list[CommittedBranchRule]] = {}
    for rule in rules:
        by_child.setdefault(rule.child_node_id, []).append(rule)
    known = {answer.node_id for answer in answer_key.branches}
    scores: list[BranchScore] = []
    for answer in answer_key.branches:
        committed = tuple(
            rule.dsl for rule in by_child.get(answer.node_id, ())
        )
        true_shapes = {
            shape: dsl
            for dsl in answer.inverse_rules
            if (shape := rule_shape(dsl)) is not None
        }
        matched: list[str] = []
        for dsl in committed:
            shape = rule_shape(dsl)
            if shape in true_shapes:
                matched.append(dsl)
        matched_shapes = {rule_shape(dsl) for dsl in matched}
        scores.append(
            BranchScore(
                node_id=answer.node_id,
                parent_node_id=answer.parent_node_id,
                innovated=answer.innovated,
                invertible=answer.invertible,
                true_forward_rules=answer.rules,
                true_inverse_rules=answer.inverse_rules,
                committed_rules=committed,
                matched_rules=tuple(matched),
                matched_true_rules=tuple(
                    dsl
                    for shape, dsl in true_shapes.items()
                    if shape in matched_shapes
                ),
                unmatched_true_rules=tuple(
                    dsl
                    for shape, dsl in true_shapes.items()
                    if shape not in matched_shapes
                ),
                functional_recovery_rate=_functional_recovery(
                    answer_key,
                    answer.node_id,
                    answer.parent_node_id,
                    committed,
                ),
                # The one directionality fact a machine can settle: the answer
                # key gave this branch no rule, so nothing about it changed, and
                # a committed rule here is pointed the wrong way.
                misdirected=bool(committed) and not answer.innovated,
                misdirected_rationales=tuple(
                    rule.directionality_rationale
                    for rule in by_child.get(answer.node_id, ())
                    if not answer.innovated
                    and rule.directionality_rationale is not None
                ),
            )
        )
    return SyntheticRunScore(
        family=answer_key.name,
        branches=tuple(scores),
        committed_nodes=tuple(committed_nodes),
        failed_nodes=tuple(failed_nodes),
        unknown_branches=tuple(sorted(set(by_child) - known)),
    )
