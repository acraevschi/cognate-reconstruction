"""Validated terminal tool for committing a node reconstruction."""

from __future__ import annotations

from dataclasses import dataclass

from cognate_reconstruction.agent.context import AgentContext
from cognate_reconstruction.agent.schemas import (
    CommitReconstructionArgs,
    CommitReconstructionResult,
    CommittedReconstruction,
    CommittedSoundRule,
    ContrastReductionReport,
    ValidationKind,
)
from cognate_reconstruction.agent.tools.contrast import (
    contrast_reduction_reports,
)
from cognate_reconstruction.agent.tools.convergence import commit_convergence
from cognate_reconstruction.agent.tools.errors import (
    ToolInputError,
    parse_rule_or_reject,
)
from cognate_reconstruction.agent.tools.heldout import held_out_evaluation
from cognate_reconstruction.schemas.common import WorkbenchModel
from cognate_reconstruction.schemas.rules import ParsedSoundRule, ReconstructionRule

_RuleIdentity = tuple[
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    bool,
    bool,
]
"""What makes two rules the same rule to the engine that applies them."""


def _rule_identity(rule: ParsedSoundRule) -> _RuleIdentity:
    """Identify a rule by what it does, not by how it was spelled.

    `t > k` and `t > k / _` parse to the same target, the same replacement, and
    the same all-empty environment: the engine cannot tell them apart, and a
    live session produced both spellings for one rule and was rejected for it.
    `rule_id` stays lexical — it is persisted in trajectories and normalizing it
    would rewrite existing records — so the identity used for matching is
    derived from the parse instead. This changes no rule semantics; the parse
    was already identical.
    """
    environment = rule.environment
    return (
        rule.target.tokens,
        rule.replacement.tokens,
        environment.left.tokens if environment.left is not None else (),
        environment.right.tokens if environment.right is not None else (),
        environment.word_initial,
        environment.word_final,
    )


def _change_identity(rule: ParsedSoundRule) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The target and replacement alone, ignoring the environment.

    Two rules that share this and differ in identity are the same change under
    different conditioning — which is exactly what refining an overapplying rule
    produces, and what the rejection has to be able to name.
    """
    return (rule.target.tokens, rule.replacement.tokens)


@dataclass(frozen=True)
class _ValidationRecord:
    """One same-session application of one rule to real forms.

    A `test_sound_law` result is one of these. So is each rule of a successful
    `test_rule_cascade`: the cascade applied that rule to the same forms, in the
    order it is being committed in, and returned its diff. That is the evidence
    the per-rule requirement exists to guarantee, so both kinds satisfy it.
    """

    call_id: str
    kind: ValidationKind
    parsed_rule: ParsedSoundRule
    source_child_ids: tuple[str, ...]
    segmentation_overlay_id: str | None
    supporting_form_ids: tuple[str, ...]

    @property
    def identity(self) -> _RuleIdentity:
        return _rule_identity(self.parsed_rule)

    def describe(self) -> str:
        scope = ", ".join(self.source_child_ids)
        overlay = (
            f" on overlay {self.segmentation_overlay_id}"
            if self.segmentation_overlay_id is not None
            else ""
        )
        return (
            f'"{self.call_id}" ({self.kind.value}) tested '
            f'"{self.parsed_rule.source}" on [{scope}]{overlay}'
        )


def _session_validations(context: AgentContext) -> tuple[_ValidationRecord, ...]:
    """Every rule this session has actually applied to forms, with its diff.

    Standalone validations come first in call order, then each cascade's rules
    in call order. Ordering is load-bearing only for the tie-break in
    `_choose_validation`, which prefers the most recent record of a kind.
    """
    records = [
        _ValidationRecord(
            call_id=call_id,
            kind=ValidationKind.SOUND_LAW,
            parsed_rule=validation.parsed_rule,
            source_child_ids=validation.source_child_ids,
            segmentation_overlay_id=validation.segmentation_overlay_id,
            supporting_form_ids=validation.supporting_form_ids,
        )
        for call_id, validation in context.validations.items()
    ]
    for call_id, cascade in context.cascade_validations.items():
        # A cascade reports one diff per (child, rule) pair, so a rule's
        # supporting forms are collected across every report that names it.
        supporting: dict[str, list[str]] = {}
        for report in cascade.reports:
            for result in report.results:
                if result.locations:
                    supporting.setdefault(report.rule.rule_id, []).append(
                        result.form_id
                    )
        records.extend(
            _ValidationRecord(
                call_id=call_id,
                kind=ValidationKind.RULE_CASCADE,
                parsed_rule=rule.rule,
                source_child_ids=rule.source_child_ids,
                segmentation_overlay_id=cascade.segmentation_overlay_id,
                supporting_form_ids=tuple(
                    dict.fromkeys(supporting.get(rule.rule.rule_id, ()))
                ),
            )
            for rule in cascade.rules
        )
    return tuple(records)


def describe_session_validations(context: AgentContext) -> str:
    """Render the join key between a validation and a committed rule.

    A commit has to reference validations recorded earlier in the same session.
    Listing them as ``(validation_call_id, dsl, source_child_ids)`` triples turns
    that join into a lookup. The text is derived only from recorded session
    state, so it is stable for a given session and safe to store in a
    trajectory.
    """
    lines: list[str] = []
    if context.validations:
        lines.append(
            "Successful test_sound_law validations in this session "
            "(validation_call_id, dsl, source_child_ids):"
        )
        lines.extend(
            f'  - ("{call_id}", "{validation.parsed_rule.source}", '
            f"[{', '.join(validation.source_child_ids)}])"
            + (
                f" tested on overlay {validation.segmentation_overlay_id}"
                if validation.segmentation_overlay_id is not None
                else ""
            )
            for call_id, validation in context.validations.items()
        )
    elif not context.cascade_validations:
        lines.append(
            "No test_sound_law validation and no test_rule_cascade preview has "
            "succeeded in this session. Every committed rule needs one; call "
            'test_sound_law or test_rule_cascade first, or commit "rules": [] '
            "for an identity reconstruction."
        )
    if context.cascade_validations:
        lines.append(
            "Successful test_rule_cascade validations. Each rule below also "
            "counts as that rule's own validation, so a rule you refined "
            "inside a cascade preview can be committed directly:"
        )
        for call_id, cascade in context.cascade_validations.items():
            lines.append(
                f'  - "{call_id}" for the order '
                + " then ".join(f'"{rule.rule.source}"' for rule in cascade.rules)
                + (
                    f" on overlay {cascade.segmentation_overlay_id}"
                    if cascade.segmentation_overlay_id is not None
                    else ""
                )
            )
            lines.extend(
                f'      ("{call_id}", "{rule.rule.source}", '
                f"[{', '.join(rule.source_child_ids)}])"
                for rule in cascade.rules
            )
        lines.append(
            "Only these IDs are valid in cascade_validation_call_id, which "
            "still means the whole committed order was previewed."
        )
    else:
        lines.append(
            "No test_rule_cascade call has succeeded in this session, so "
            "cascade_validation_call_id must be omitted."
        )
    if context.validations or context.cascade_validations:
        lines.append(
            "Per-rule validation_call_id is optional: omit it and the harness "
            "resolves the same-session validation — of either kind — whose "
            "rule, child scope, and overlay are identical to the committed "
            "rule. supporting_form_ids may be omitted too; it then defaults to "
            "that validation's forms."
        )
    return "\n".join(lines)


def _describe_validation_gap(
    committed: CommittedSoundRule,
    parsed: ParsedSoundRule,
    context: AgentContext,
    overlay_id: str | None,
    records: tuple[_ValidationRecord, ...],
) -> str:
    """Answer the question the rejection actually raised, about *this* rule.

    Listing every recorded validation answers "what did I validate", which is
    not what a rule rejected for having no validation needs to know. A model
    that refined an overapplying rule inside a cascade preview has moved past
    the validations that list contains, and reading them again told it nothing.

    The near-match case is the one worth naming: a recorded validation with the
    same target and replacement but a different environment *is* the
    unrefined ancestor of this rule, and saying so points at the one call that
    unblocks the commit. The full catalogue still follows, because the rejection
    may also be a mistyped reference to a validation that does exist.
    """
    scope = set(committed.source_child_ids)
    identity = _rule_identity(parsed)
    change = _change_identity(parsed)
    lines = [
        f"Rule {committed.rule_id!r} is \"{parsed.source}\" on "
        f"[{', '.join(committed.source_child_ids)}]"
        + (f" with overlay {overlay_id}" if overlay_id is not None else "")
        + ". No same-session validation applied that exact rule to that exact "
        "child scope and overlay."
    ]
    refinements = [
        record
        for record in records
        if _change_identity(record.parsed_rule) == change
        and record.identity != identity
    ]
    rescoped = [
        record
        for record in records
        if record.identity == identity
        and (
            set(record.source_child_ids) != scope
            or record.segmentation_overlay_id != overlay_id
        )
    ]
    if refinements:
        lines.append(
            "These validations tested the same change in a different "
            "environment, so this rule looks like a refinement of one of them:"
        )
        lines.extend(f"  - {record.describe()}" for record in refinements)
        lines.append(
            f'Validate the refined form: call test_sound_law with dsl '
            f'"{parsed.source}" and source_child_ids '
            f"[{', '.join(committed.source_child_ids)}], or include it in a "
            "test_rule_cascade preview of the committed order. Either one "
            "counts as this rule's validation; the earlier, unconditioned "
            "validation does not."
        )
    if rescoped:
        lines.append(
            "This exact rule was validated, but not for the committed child "
            "scope or overlay:"
        )
        lines.extend(f"  - {record.describe()}" for record in rescoped)
        lines.append(
            "Commit the scope and overlay that was validated, or re-test the "
            "rule on the scope and overlay you intend to commit."
        )
    if not refinements and not rescoped:
        lines.append(
            "Nothing recorded in this session is close to it. Call "
            "test_sound_law on this exact rule and child scope before "
            "committing it."
        )
    lines.append(describe_session_validations(context))
    return "\n".join(lines)


def _choose_validation(
    matches: list[_ValidationRecord],
) -> _ValidationRecord | None:
    """Pick between validations that a reviewer could not tell apart.

    Two records matching one rule agree by construction on the rule, the child
    scope, and the overlay; a node's forms do not change inside a session, so
    the only thing left that a commit could differ by is which forms the rule
    applied to. When even that agrees, the records are the same experiment run
    twice — a model re-testing a rule while iterating, or refining it across two
    cascade previews — and asking the model to choose between them asks for a
    decision with no content. It is also the case letting cascades count makes
    common, so rejecting it would punish exactly the careful work this contract
    is meant to encourage.

    Returns `None` only when the matches genuinely disagree, which is the one
    situation an explicit `validation_call_id` can resolve. Otherwise a cascade
    record wins over a standalone one, so the bound record is the one that
    exercised the rule in its committed order, and the most recent of a kind
    wins over an earlier one.
    """
    if len(matches) == 1:
        return matches[0]
    if len({record.supporting_form_ids for record in matches}) > 1:
        return None
    cascades = [
        record for record in matches if record.kind is ValidationKind.RULE_CASCADE
    ]
    return (cascades or matches)[-1]


def _reject_ambiguous(
    committed: CommittedSoundRule,
    matches: list[_ValidationRecord],
) -> ToolInputError:
    return ToolInputError(
        f"rule {committed.rule_id!r} matches {len(matches)} same-session "
        "validations that disagree about which forms it applied to; name the "
        "intended one in validation_call_id",
        code="validation-ambiguous",
        remediation=(
            "These validations all match this rule's DSL, child scope, and "
            "overlay, but each supports a different set of forms:\n"
            + "\n".join(
                f"  - {record.describe()}, supporting "
                f"{list(record.supporting_form_ids)}"
                for record in matches
            )
            + "\nSet validation_call_id on this rule to the one you mean."
        ),
    )


def _resolve_validation(
    committed: CommittedSoundRule,
    parsed: ParsedSoundRule,
    context: AgentContext,
    overlay_id: str | None,
) -> _ValidationRecord:
    """Bind one committed rule to its exact same-session validation.

    Explicit IDs are looked up directly, and a named call still has to have
    tested this rule, this child scope, and this overlay — the three checks keep
    their own rejection codes. An omitted ID is resolved by exact equality of
    the parsed rule, child scope, and segmentation overlay: this removes a
    transcription step, never a check.
    """
    records = _session_validations(context)
    scope = set(committed.source_child_ids)
    identity = _rule_identity(parsed)
    if committed.validation_call_id is not None:
        named = [
            record
            for record in records
            if record.call_id == committed.validation_call_id
        ]
        if not named:
            raise ToolInputError(
                f"rule {committed.rule_id!r} references an unknown validation "
                f"call {committed.validation_call_id!r}",
                code="validation-unknown",
                remediation=describe_session_validations(context),
            )
        matches = [record for record in named if record.identity == identity]
        if not matches:
            raise ToolInputError(
                f"rule {committed.rule_id!r} was not validated with this exact DSL",
                code="validation-mismatch",
                remediation=_describe_validation_gap(
                    committed, parsed, context, overlay_id, records
                ),
            )
        scoped = [
            record for record in matches if set(record.source_child_ids) == scope
        ]
        if not scoped:
            raise ToolInputError(
                f"rule {committed.rule_id!r} was not validated for this child scope",
                code="scope-mismatch",
                remediation=_describe_validation_gap(
                    committed, parsed, context, overlay_id, records
                ),
            )
        matches = [
            record
            for record in scoped
            if record.segmentation_overlay_id == overlay_id
        ]
        if not matches:
            raise ToolInputError(
                f"rule {committed.rule_id!r} was not validated on the committed "
                "segmentation overlay",
                code="overlay-mismatch",
                remediation=_describe_validation_gap(
                    committed, parsed, context, overlay_id, records
                ),
            )
    else:
        matches = [
            record
            for record in records
            if record.identity == identity
            and set(record.source_child_ids) == scope
            and record.segmentation_overlay_id == overlay_id
        ]
        if not matches:
            raise ToolInputError(
                f"rule {committed.rule_id!r} omitted validation_call_id and no "
                "same-session test_sound_law validation or test_rule_cascade "
                "preview applied this exact rule to this exact child scope and "
                "segmentation overlay",
                code="validation-unresolved",
                remediation=_describe_validation_gap(
                    committed, parsed, context, overlay_id, records
                ),
            )
    chosen = _choose_validation(matches)
    if chosen is None:
        raise _reject_ambiguous(committed, matches)
    return chosen


def _require_rationales_on_multi_rule_commits(
    rules: tuple[CommittedSoundRule, ...],
) -> None:
    """Require per-rule reasoning exactly where the summary cannot carry it.

    `rationale` is optional in the schema because transcription burden on
    `commit_reconstruction` was the harness's dominant failure mode, and the
    measured friction was entirely on single-rule commits, where the required
    top-level `summary` says everything a per-rule note would.

    A multi-rule commit is the case that argument does not cover: one summary
    cannot attribute reasoning to one of several rules, so a corpus filter would
    have to discard *every* multi-rule commit for missing reasoning. That is a
    worse outcome than one extra required string on the minority call.
    """
    if len(rules) <= 1:
        return
    missing = [rule.rule_id for rule in rules if rule.rationale is None]
    if not missing:
        return
    raise ToolInputError(
        f"{len(missing)} of {len(rules)} committed rules omit 'rationale'. It "
        "is required on every rule of a commit that carries more than one, "
        "because the single top-level 'summary' cannot attribute reasoning to "
        "an individual rule",
        code="missing-rule-rationale",
        remediation=(
            "Add a 'rationale' to each of these rules: "
            + ", ".join(f"{rule_id!r}" for rule_id in missing)
            + ". A one-rule commit still needs none; the 'summary' carries it."
        ),
    )


def _require_directionality_rationales(
    rules: tuple[CommittedSoundRule, ...],
    reductions: tuple[ContrastReductionReport, ...],
) -> None:
    """Make a commit that gives up a contrast say which branch innovated.

    The case is detected mechanically — the committed cascade either deletes
    material or sends two of a child's distinct sequences to one, both of them
    arithmetic over the forms — and the rejection is on *absence* only. The
    harness never evaluates whether the stated reason is good; that is a
    linguistic judgement it is not equipped to make, and the whole point of
    demanding the sentence is that a human reviewer can read it later.

    The requirement exists because this is the one class of rule the harness
    cannot undo. A merger is not reversible, so if the direction was chosen
    wrongly nothing downstream can recover it, and live runs chose it wrongly:
    `ʔ > Ø / #_` scoped to the Tongic branch that *preserves* the glottal stop,
    `f > h` and `t > k` scoped to North Marquesan when Hawaiian innovated both.
    Nothing in the tool surface had ever asked which branch changed.
    """
    if not reductions:
        return
    flagged = {report.rule_id for report in reductions}
    missing = [
        rule.rule_id
        for rule in rules
        if rule.rule_id in flagged and rule.directionality_rationale is None
    ]
    if not missing:
        return
    notes = {report.rule_id: report.note for report in reductions}
    raise ToolInputError(
        f"{len(missing)} committed rule(s) remove a distinction and omit "
        "'directionality_rationale'. A rule that deletes a segment or merges "
        "two segments into one has to say which branch innovated, because the "
        "harness cannot invert it later and nothing else records the claim",
        code="missing-directionality-rationale",
        remediation=(
            "What the harness found:\n"
            + "\n".join(f"  - {rule_id!r}: {notes[rule_id]}" for rule_id in missing)
            + "\nWhat it needs from you, on each of those rules: a "
            "'directionality_rationale' naming *which of the active children "
            "innovated*, what the change is called if it has a name, and what "
            "evidence outside those children polarizes it. Restating the "
            "counts above is not an answer to that — they are the finding, not "
            "the claim. polarize reports what nodes outside the active children "
            "show in the same columns. The harness does not judge what you "
            "write; it records that you wrote it, so a reviewer can check it."
        ),
    )


def commit_reconstruction(
    raw_arguments: WorkbenchModel,
    context: AgentContext,
    call_id: str,  # noqa: ARG001 - uniform tool signature
) -> CommitReconstructionResult:
    arguments = CommitReconstructionArgs.model_validate(raw_arguments)
    if context.commit is not None:
        raise ToolInputError(
            "this node already has a committed reconstruction",
            code="already-committed",
        )
    if arguments.node_id != context.node_id:
        raise ToolInputError(
            f"commit node {arguments.node_id!r} does not match active node {context.node_id!r}",
            code="node-mismatch",
        )
    if (
        arguments.segmentation_overlay_id is not None
        and arguments.segmentation_overlay_id not in context.overlays
    ):
        raise ToolInputError(
            f"unknown segmentation overlay {arguments.segmentation_overlay_id!r}",
            code="unknown-overlay",
        )
    _require_rationales_on_multi_rule_commits(arguments.rules)
    active_children = set(context.child_ids)
    parsed_rules: list[ReconstructionRule] = []
    resolved_rules: list[CommittedSoundRule] = []
    for committed in arguments.rules:
        unknown = sorted(set(committed.source_child_ids) - active_children)
        if unknown:
            raise ToolInputError(
                f"rule {committed.rule_id!r} targets inactive children: {unknown}",
                code="inactive-children",
            )
        parsed = parse_rule_or_reject(committed.dsl, rule_id=committed.rule_id)
        validation = _resolve_validation(
            committed,
            parsed,
            context,
            arguments.segmentation_overlay_id,
        )
        # Deterministic engine output, not a model claim: an omitted list is
        # filled in from the validation rather than retyped by the model.
        supporting = (
            committed.supporting_form_ids or validation.supporting_form_ids
        )
        unsupported = sorted(
            set(supporting) - set(validation.supporting_form_ids)
        )
        if unsupported:
            raise ToolInputError(
                f"rule {committed.rule_id!r} cites unsupported forms: {unsupported}",
                code="unsupported-forms",
                remediation=(
                    f"validation {validation.call_id!r} supports only "
                    f"{list(validation.supporting_form_ids)}. Omit "
                    "supporting_form_ids to use exactly that list."
                ),
            )
        if not supporting:
            raise ToolInputError(
                f"rule {committed.rule_id!r} applied to no form in validation "
                f"{validation.call_id!r} and cannot be committed",
                code="rule-unsupported",
                remediation=(
                    "Retest the rule against forms it actually changes, widen "
                    "its child scope, or drop it from the commit."
                ),
            )
        resolved_rules.append(
            committed.model_copy(
                update={
                    "validation_call_id": validation.call_id,
                    "validation_kind": validation.kind,
                    "supporting_form_ids": tuple(supporting),
                }
            )
        )
        parsed_rules.append(
            ReconstructionRule(
                rule=parsed,
                source_child_ids=committed.source_child_ids,
                confidence=committed.confidence,
            )
        )
    # The stored request records the resolved IDs, so the trajectory stays
    # explicit about which validation backs each committed rule and which kind
    # of call it was.
    arguments = arguments.model_copy(update={"rules": tuple(resolved_rules)})

    # Detected on the parsed cascade, so the check reads the rules as the engine
    # will run them. Reported either way; only its absence is a rejection.
    reductions = contrast_reduction_reports(
        context,
        parsed_rules,
        segmentation_overlay_id=arguments.segmentation_overlay_id,
    )
    _require_directionality_rationales(arguments.rules, reductions)

    if arguments.cascade_validation_call_id is not None:
        try:
            cascade = context.cascade_validations[
                arguments.cascade_validation_call_id
            ]
        except KeyError as error:
            raise ToolInputError(
                "commit references an unknown cascade validation call; "
                "cascade_validation_call_id must come from a successful "
                "test_rule_cascade result, or be omitted when no cascade "
                "preview was run",
                code="cascade-unknown",
                remediation=describe_session_validations(context),
            ) from error
        if cascade.segmentation_overlay_id != arguments.segmentation_overlay_id:
            raise ToolInputError(
                "ordered cascade was not tested on the committed segmentation overlay",
                code="overlay-mismatch",
            )
        committed_signature = tuple(
            (
                _rule_identity(rule.rule),
                rule.source_child_ids,
            )
            for rule in parsed_rules
        )
        validated_signature = tuple(
            (
                _rule_identity(rule.rule),
                rule.source_child_ids,
            )
            for rule in cascade.rules
        )
        if committed_signature != validated_signature:
            raise ToolInputError(
                "committed rule order, DSL, or child scope differs from the "
                "tested cascade",
                code="cascade-signature-mismatch",
                remediation=describe_session_validations(context),
            )

    active_form_ids = {form.form_id for form in context.all_forms} | {
        anchor.form_id for anchor in context.active_anchors
    }
    active_concept_ids = {form.concept_id for form in context.all_forms} | {
        anchor.concept_id for anchor in context.active_anchors
    }
    for anomaly in arguments.anomalies:
        if anomaly.form_id is not None and anomaly.form_id not in active_form_ids:
            raise ToolInputError(
                f"anomaly references unknown form {anomaly.form_id!r}",
                code="anomaly-unknown-reference",
            )
        if anomaly.concept_id is not None and anomaly.concept_id not in active_concept_ids:
            raise ToolInputError(
                f"anomaly references unknown concept {anomaly.concept_id!r}",
                code="anomaly-unknown-reference",
            )

    reconstruction = CommittedReconstruction(
        request=arguments,
        parsed_rules=tuple(parsed_rules),
    )
    context.commit = reconstruction
    # The last thing the session sees should be what its hypothesis produced,
    # not only that the commit passed its checks. This never rejects: a commit
    # whose children still disagree is a legitimate hypothesis with a residue.
    return CommitReconstructionResult(
        reconstruction=reconstruction,
        convergence=commit_convergence(
            context,
            parsed_rules,
            segmentation_overlay_id=arguments.segmentation_overlay_id,
        ),
        contrast_reductions=reductions,
        held_out=held_out_evaluation(
            context,
            parsed_rules,
            segmentation_overlay_id=arguments.segmentation_overlay_id,
        ),
    )
