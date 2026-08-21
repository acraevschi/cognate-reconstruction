"""Does a rule remove a distinction the forms it applies to actually make?

Arithmetic over the forms, never a claim about sound change. Applying a rule to
a child's forms induces a mapping from input token sequences to output token
sequences, and exactly two properties of that mapping are computed here:

- **deletion** — the rule's replacement is empty, so every application removes
  material from the form;
- **merger** — two distinct input sequences produce one output sequence, so a
  contrast the child made no longer exists in the parent.

Both are exact and cheap. Neither says whether losing the contrast is *right*:
mergers are ordinary sound change and a harness that forbade them would be
wrong. What makes them worth naming is that they are the one class of change
the harness can never undo for the model — a merger is not reversible, which is
why nothing here ever inverts a rule — so a reviewer has to be told which
branch was claimed to have innovated while the claim is still being made. See
`docs/report_reject_or_score.md` for why this is reported and required in
prose, and never scored.

The mapping is built token-wise outside the matched spans and span-wise inside
them, which is what makes "two inputs, one output" decidable at all. One
consequence is worth stating: a rule whose replacement is longer than one token
can only collide with the identity image of a single token, so `k > k w` is not
reported as a merger even in a child that already has `k w` sequences. That is
deliberate — the detection reports what it can prove, and an under-report costs
a rationale that was not demanded, while an over-report would demand one for a
rule that reduces nothing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from cognate_reconstruction.rules.engine import RuleEngine
from cognate_reconstruction.schemas.lexicon import LexicalForm
from cognate_reconstruction.schemas.rules import ParsedSoundRule, ReconstructionRule


@dataclass(frozen=True)
class ContrastReduction:
    """One rule, and the distinction its application removes.

    `discarded_segments` is the rule's target: after the rule runs, that
    material is gone from the parent forms it matched. `merged_into` is the
    replacement it became, empty for a deletion.
    """

    rule_id: str
    source: str
    deletes: bool
    merges: bool
    discarded_segments: tuple[str, ...]
    merged_into: tuple[str, ...]
    source_child_ids: tuple[str, ...] = ()

    def merged(self, other: ContrastReduction) -> ContrastReduction:
        """Fold one rule's reduction across two children it is scoped to.

        A rule may delete for one child and merge for another — the children
        hold different segments — and the rule is one object in the commit, so
        the report has to be one object too.
        """
        if other.rule_id != self.rule_id:
            raise ValueError("contrast reductions for different rules cannot merge")
        return ContrastReduction(
            rule_id=self.rule_id,
            source=self.source,
            deletes=self.deletes or other.deletes,
            merges=self.merges or other.merges,
            discarded_segments=self.discarded_segments,
            merged_into=self.merged_into,
            source_child_ids=tuple(
                dict.fromkeys((*self.source_child_ids, *other.source_child_ids))
            ),
        )


def rule_contrast_reduction(
    rule: ParsedSoundRule,
    forms: Sequence[LexicalForm],
    *,
    child_id: str | None = None,
    engine: RuleEngine | None = None,
) -> ContrastReduction | None:
    """Report the distinction `rule` removes from `forms`, or `None`.

    A rule that never fires on these forms removes nothing from them, and is
    reported as `None` rather than as a reduction nobody observed.
    """
    engine = engine or RuleEngine()
    report = engine.apply_rule(rule, tuple(forms))
    target = rule.target.tokens
    replacement = rule.replacement.tokens
    applied = False
    # Every input sequence this rule maps, and what it maps to. Tokens outside a
    # matched span map to themselves; a matched span maps to the replacement.
    images: dict[tuple[str, ...], set[tuple[str, ...]]] = {}
    for result in report.results:
        covered = {
            index
            for location in result.locations
            for index in range(location.start_token, location.end_token)
        }
        if result.locations:
            applied = True
            images.setdefault(target, set()).add(replacement)
        for index, token in enumerate(result.input_segments):
            if index not in covered:
                images.setdefault((token,), set()).add((token,))
    if not applied:
        return None
    sources_by_image: dict[tuple[str, ...], set[tuple[str, ...]]] = {}
    for source, outputs in images.items():
        for output in outputs:
            sources_by_image.setdefault(output, set()).add(source)
    # An empty image is a deletion, reported as such; it is not a merger of the
    # deleted material with anything.
    merges = any(
        len(sources) > 1 for image, sources in sources_by_image.items() if image
    )
    deletes = not replacement
    if not (merges or deletes):
        return None
    return ContrastReduction(
        rule_id=rule.rule_id,
        source=rule.source,
        deletes=deletes,
        merges=merges,
        discarded_segments=target,
        merged_into=replacement,
        source_child_ids=(child_id,) if child_id is not None else (),
    )


def cascade_contrast_reductions(
    rules: Sequence[ReconstructionRule],
    forms_by_child: Mapping[str, Sequence[LexicalForm]],
    *,
    engine: RuleEngine | None = None,
) -> tuple[ContrastReduction, ...]:
    """Every rule of a committed order that removes a distinction, in order.

    Each child is walked through its own scoped subsequence of the cascade, so a
    rule is judged against the forms it will actually receive rather than
    against the child's untransformed lexicon. That matters for exactly the case
    the cascade exists for: an earlier rule can create the segment a later one
    merges into.
    """
    engine = engine or RuleEngine()
    reductions: dict[str, ContrastReduction] = {}
    for child_id, forms in forms_by_child.items():
        current = tuple(forms)
        if not current:
            continue
        for scoped in rules:
            if child_id not in scoped.source_child_ids:
                continue
            reduction = rule_contrast_reduction(
                scoped.rule, current, child_id=child_id, engine=engine
            )
            if reduction is not None:
                existing = reductions.get(reduction.rule_id)
                reductions[reduction.rule_id] = (
                    reduction if existing is None else existing.merged(reduction)
                )
            current, _reports = engine.apply_rules((scoped.rule,), current)
    order = {rule.rule.rule_id: index for index, rule in enumerate(rules)}
    return tuple(
        sorted(reductions.values(), key=lambda item: order.get(item.rule_id, 0))
    )


__all__ = [
    "ContrastReduction",
    "cascade_contrast_reductions",
    "rule_contrast_reduction",
]
