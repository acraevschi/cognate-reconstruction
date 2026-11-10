"""Offline forward-prediction feasibility and withheld-data evaluation (R06).

Evaluates explicit parent-to-child branch hypotheses on development and
etymon-held-out concept splits under three ancestor input regimes:

1. ``inferred_ancestor`` — parent forms reconstructed from non-target sisters
   alone (primary claim-bearing regime).
2. ``direct_sister_baseline`` — copy an observed sister's forms as the pseudo-parent
   and fit a lateral sister-to-target cascade (non-tree baseline).
3. ``given_ancestor_control`` — supply generator/oracle parent forms (privileged
   diagnostic control, never a deployable baseline).

Also provides etymon-cluster split construction with cognate-unit leakage
checks, payload target-daughter masking, post-run zero-leakage verification,
corpus-wide aligned B-Cubed contrast-equivalence scoring, forward cascade
invertibility checks, development residual autopsies, hypothesis diffing, and
auxiliary rule-order permutation diagnostics.
"""

from __future__ import annotations

import itertools
import json
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from cognate_reconstruction.evaluation.metrics import (
    GAP,
    align,
    bcubed,
    compare_to_nearest,
    edit_distance,
    normalized_edit_distance,
)
from cognate_reconstruction.rules.contrast import (
    ContrastReduction,
    rule_contrast_reduction,
)
from cognate_reconstruction.rules.engine import RuleEngine
from cognate_reconstruction.rules.parser import parse_rule
from cognate_reconstruction.schemas.common import (
    MORPHOLOGICAL_BOUNDARY_TOKENS,
    NonEmptyStr,
    WorkbenchModel,
)
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm
from cognate_reconstruction.schemas.rules import (
    ApplicationStatus,
    ParsedSoundRule,
)
from cognate_reconstruction.schemas.synthetic import SyntheticAnswerKey
from cognate_reconstruction.synthesis.generator import (
    _invert,
    _verified_inverse,
)

FORWARD_EVALUATOR_VERSION = "r06-forward-v1"
ETYMON_SPLIT_VERSION = "r06-etymon-split-v1"


class AncestorSourceKind(StrEnum):
    """Provenance classification of an ancestor input form for a concept."""

    INFERRED_UNATTESTED = "inferred_unattested"
    INFERRED_DAUGHTER_ATTESTED = "inferred_daughter_attested"
    DIRECT_SISTER_COPY = "direct_sister_copy"
    GIVEN_GENERATOR_ORACLE = "given_generator_oracle"
    HISTORICAL_ATTESTATION = "historical_attestation"


@dataclass(frozen=True)
class EtymonClusterSplit:
    """Partition of concepts by etymon / cognate-unit cluster."""

    split_version: str
    development_etymon_ids: tuple[str, ...]
    held_out_etymon_ids: tuple[str, ...]
    development_concept_ids: tuple[str, ...]
    held_out_concept_ids: tuple[str, ...]
    concept_to_etymon_id: dict[str, str]
    shared_cognate_units_across_split: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "split_version": self.split_version,
            "development_etymon_ids": list(self.development_etymon_ids),
            "held_out_etymon_ids": list(self.held_out_etymon_ids),
            "development_concept_ids": list(self.development_concept_ids),
            "held_out_concept_ids": list(self.held_out_concept_ids),
            "development_etymon_count": len(self.development_etymon_ids),
            "held_out_etymon_count": len(self.held_out_etymon_ids),
            "development_concept_count": len(self.development_concept_ids),
            "held_out_concept_count": len(self.held_out_concept_ids),
            "concept_to_etymon_id": dict(self.concept_to_etymon_id),
            "shared_cognate_units_across_split": list(
                self.shared_cognate_units_across_split
            ),
        }


def build_etymon_cluster_split(
    concept_etymon_map: Mapping[str, str],
    held_out_etymon_ids: Sequence[str],
    *,
    payload: WorkbenchPayload | None = None,
    allowed_shared_affix_units: Sequence[str] = (),
) -> EtymonClusterSplit:
    """Build a leakage-checked development / held-out split grouped by etymon ID.

    Every concept sharing an etymon ID is placed on the same side of the split.
    When ``payload`` is provided, all whole-form and partial-cognate membership
    IDs across ``payload.lexicons`` (excluding ``allowed_shared_affix_units``)
    are verified to be disjoint between development and held-out concepts.
    """
    if not concept_etymon_map:
        raise ValueError("concept_etymon_map must not be empty")
    all_etymons = set(concept_etymon_map.values())
    held_out_ordered = tuple(dict.fromkeys(held_out_etymon_ids))
    if not held_out_ordered:
        raise ValueError("held_out_etymon_ids must not be empty")
    held_out_set = set(held_out_ordered)
    unknown = sorted(held_out_set - all_etymons)
    if unknown:
        raise ValueError(
            f"held_out_etymon_ids contains unknown etymon IDs: {unknown}"
        )
    dev_ordered = tuple(
        dict.fromkeys(
            etymon_id
            for etymon_id in concept_etymon_map.values()
            if etymon_id not in held_out_set
        )
    )
    if not dev_ordered:
        raise ValueError(
            "held_out_etymon_ids must leave at least one development etymon"
        )

    dev_concepts = tuple(
        cid
        for cid, etymon_id in concept_etymon_map.items()
        if etymon_id not in held_out_set
    )
    held_out_concepts = tuple(
        cid
        for cid, etymon_id in concept_etymon_map.items()
        if etymon_id in held_out_set
    )

    shared_units: tuple[str, ...] = ()
    if payload is not None:
        allowed_affixes = set(allowed_shared_affix_units)
        dev_concept_set = set(dev_concepts)
        held_out_concept_set = set(held_out_concepts)
        dev_units: set[str] = set()
        test_units: set[str] = set()
        for lexicon in payload.lexicons:
            for form in lexicon.forms:
                units: set[str] = set()
                if form.cognate_set_id is not None:
                    units.add(form.cognate_set_id)
                for membership in form.cognate_memberships:
                    units.add(membership.cognate_set_id)
                units -= allowed_affixes
                if form.concept_id in dev_concept_set:
                    dev_units.update(units)
                elif form.concept_id in held_out_concept_set:
                    test_units.update(units)
        shared_units = tuple(sorted(dev_units & test_units))
        if shared_units:
            raise ValueError(
                "Etymon split leaks shared cognate units across dev and test: "
                f"{shared_units}"
            )

    return EtymonClusterSplit(
        split_version=ETYMON_SPLIT_VERSION,
        development_etymon_ids=dev_ordered,
        held_out_etymon_ids=held_out_ordered,
        development_concept_ids=dev_concepts,
        held_out_concept_ids=held_out_concepts,
        concept_to_etymon_id=dict(concept_etymon_map),
        shared_cognate_units_across_split=shared_units,
    )


def mask_target_daughter_in_payload(
    payload: WorkbenchPayload,
    *,
    target_daughter_id: str,
    masked_concept_ids: Sequence[str],
    drop_historical_bindings: bool = True,
) -> WorkbenchPayload:
    """Return a copy of ``payload`` with ``masked_concept_ids`` removed from ``target_daughter_id``."""
    masked_set = set(masked_concept_ids)
    found = False
    new_lexicons: list[LanguageLexicon] = []
    for lexicon in payload.lexicons:
        if lexicon.variety_id == target_daughter_id:
            found = True
            kept_forms = tuple(
                form
                for form in lexicon.forms
                if form.concept_id not in masked_set
            )
            new_lexicons.append(
                lexicon.model_copy(update={"forms": kept_forms})
            )
        else:
            new_lexicons.append(lexicon)
    if not found:
        raise ValueError(
            f"Target daughter {target_daughter_id!r} not found in payload lexicons"
        )
    updates: dict[str, Any] = {"lexicons": tuple(new_lexicons)}
    if drop_historical_bindings:
        updates["historical_form_bindings"] = ()
    return payload.model_copy(update=updates)


def verify_no_target_leakage(
    masked_payload: WorkbenchPayload,
    *,
    target_daughter_id: str,
    withheld_forms: Mapping[str, Sequence[str]],
    answer_key: SyntheticAnswerKey | None = None,
    tool_exchanges: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Verify that withheld target-daughter forms and answer-key rules never leaked."""
    bindings_empty = len(masked_payload.historical_form_bindings) == 0

    target_lexicon = next(
        (
            lex
            for lex in masked_payload.lexicons
            if lex.variety_id == target_daughter_id
        ),
        None,
    )
    present_target_concepts = (
        {form.concept_id for form in target_lexicon.forms}
        if target_lexicon is not None
        else set()
    )
    masked_daughter_test_forms_present = sorted(
        cid for cid in withheld_forms if cid in present_target_concepts
    )

    payload_json = json.dumps(masked_payload.model_dump(mode="json"), ensure_ascii=False)
    exchanges_json = json.dumps(list(tool_exchanges), ensure_ascii=False)
    combined_blob = payload_json + "\n" + exchanges_json

    leaked_form_ids: list[str] = []
    for cid in withheld_forms:
        form_id = f"{target_daughter_id}:{cid}"
        if form_id in combined_blob:
            leaked_form_ids.append(form_id)

    answer_key_rules_in_payload = False
    if answer_key is not None:
        for branch in answer_key.branches:
            for rule_text in (*branch.rules, *branch.inverse_rules):
                if rule_text and rule_text in payload_json:
                    answer_key_rules_in_payload = True
                    break

    ok = (
        bindings_empty
        and not masked_daughter_test_forms_present
        and not leaked_form_ids
        and not answer_key_rules_in_payload
    )
    return {
        "ok": ok,
        "target_daughter_id": target_daughter_id,
        "withheld_concept_count": len(withheld_forms),
        "bindings_empty": bindings_empty,
        "masked_daughter_test_forms_present": masked_daughter_test_forms_present,
        "leaked_form_ids": leaked_form_ids,
        "answer_key_rules_in_payload": answer_key_rules_in_payload,
    }


class ForwardLexicalException(WorkbenchModel):
    """Explicitly budgeted irregular/exceptional lexical override on a forward branch."""

    concept_id: NonEmptyStr
    override_segments: tuple[NonEmptyStr, ...] = Field(min_length=1)
    note: NonEmptyStr


class ForwardBranchHypothesis(WorkbenchModel):
    """Explicit parent-to-child sound-change cascade hypothesis for a target daughter."""

    hypothesis_id: NonEmptyStr
    parent_node_id: NonEmptyStr
    child_node_id: NonEmptyStr
    direction: Literal["parent_to_child"] = "parent_to_child"
    ancestor_regime: Literal[
        "inferred_ancestor",
        "direct_sister_baseline",
        "given_ancestor_control",
    ] = "inferred_ancestor"
    privileged_operator_control: bool = False
    deployable_baseline: bool = True
    rule_sources: tuple[NonEmptyStr, ...] = ()
    lexical_exceptions: tuple[ForwardLexicalException, ...] = ()
    max_lexical_exceptions: int = Field(default=1, ge=0)
    notes: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_hypothesis(self) -> ForwardBranchHypothesis:
        if self.parent_node_id == self.child_node_id:
            raise ValueError("parent_node_id and child_node_id must be distinct")
        for index, source in enumerate(self.rule_sources):
            try:
                parse_rule(source)
            except Exception as exc:
                raise ValueError(
                    f"Invalid forward rule at index {index} ({source!r}): {exc}"
                ) from exc
        exception_concepts = [exc.concept_id for exc in self.lexical_exceptions]
        if len(exception_concepts) != len(set(exception_concepts)):
            raise ValueError(
                "lexical_exceptions must have unique concept_id entries"
            )
        if (
            self.ancestor_regime == "given_ancestor_control"
            or self.privileged_operator_control
        ):
            if not self.privileged_operator_control or self.deployable_baseline:
                raise ValueError(
                    "given_ancestor_control requires privileged_operator_control=True "
                    "and deployable_baseline=False"
                )
        return self

    def parsed_rules(self) -> tuple[ParsedSoundRule, ...]:
        """Parse ``rule_sources`` into ``ParsedSoundRule`` objects in cascade order."""
        return tuple(parse_rule(source) for source in self.rule_sources)


@dataclass(frozen=True)
class ForwardRuleStageTrace:
    """Step-by-step application trace of one forward rule on one concept form."""

    step_index: int
    rule_id: str
    rule_source: str
    status: str
    input_segments: tuple[str, ...]
    output_segments: tuple[str, ...]
    locations: tuple[tuple[int, int], ...]
    explanation: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "step_index": self.step_index,
            "rule_id": self.rule_id,
            "rule_source": self.rule_source,
            "status": self.status,
            "input_segments": list(self.input_segments),
            "output_segments": list(self.output_segments),
            "locations": [list(loc) for loc in self.locations],
            "explanation": self.explanation,
        }


@dataclass(frozen=True)
class ForwardComplexityReport:
    """Rule complexity and lexical exception accounting for a forward hypothesis."""

    rule_count: int
    total_target_tokens: int
    total_replacement_tokens: int
    total_context_tokens: int
    boundary_constraint_count: int
    lexical_exception_count: int
    max_lexical_exceptions: int
    exception_bound_exceeded: bool
    single_etymon_dev_rule_ids: tuple[str, ...]
    zero_application_dev_rule_ids: tuple[str, ...]
    description_token_complexity: int
    assumptions_note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_count": self.rule_count,
            "total_target_tokens": self.total_target_tokens,
            "total_replacement_tokens": self.total_replacement_tokens,
            "total_context_tokens": self.total_context_tokens,
            "boundary_constraint_count": self.boundary_constraint_count,
            "lexical_exception_count": self.lexical_exception_count,
            "max_lexical_exceptions": self.max_lexical_exceptions,
            "exception_bound_exceeded": self.exception_bound_exceeded,
            "single_etymon_dev_rule_ids": list(self.single_etymon_dev_rule_ids),
            "zero_application_dev_rule_ids": list(
                self.zero_application_dev_rule_ids
            ),
            "description_token_complexity": self.description_token_complexity,
            "assumptions_note": self.assumptions_note,
        }


def classify_ancestor_source(
    ancestor_segments: Sequence[str],
    sister_forms_for_concept: Mapping[str, Sequence[str]],
    *,
    regime: str,
    source_sister_id: str | None = None,
) -> AncestorSourceKind:
    """Classify whether an ancestor form is unattested, daughter-attested, sister-copied, or oracle."""
    del source_sister_id
    if regime in ("given_ancestor_oracle", "given_ancestor_control"):
        return AncestorSourceKind.GIVEN_GENERATOR_ORACLE
    if regime == "historical_attestation":
        return AncestorSourceKind.HISTORICAL_ATTESTATION
    if regime == "direct_sister_baseline":
        return AncestorSourceKind.DIRECT_SISTER_COPY
    anc_tuple = tuple(ancestor_segments)
    for sister_segs in sister_forms_for_concept.values():
        if tuple(sister_segs) == anc_tuple:
            return AncestorSourceKind.INFERRED_DAUGHTER_ATTESTED
    return AncestorSourceKind.INFERRED_UNATTESTED


def check_forward_cascade_invertibility(
    rule_sources: Sequence[str],
    parent_forms: Mapping[str, Sequence[str]],
    child_forms: Mapping[str, Sequence[str]],
    *,
    parent_node_id: str = "r",
    child_node_id: str = "a",
) -> dict[str, Any]:
    """Check whether a forward parent-to-child cascade can be inverted child-to-parent.

    Identifies rules with no syntactic arrow-swap in the DSL (such as deletion
    rules ``x > Ø``), records contrast reductions (deletions and contextual or
    unconditional mergers) along the forward trajectory, tests whether the
    reversed arrow-swapped cascade recovers ``parent_forms`` from ``child_forms``
    via ``_verified_inverse``, and measures the recovery rate of naive arrow-swap
    inversion.
    """
    engine = RuleEngine()
    parsed_rules = tuple(parse_rule(src) for src in rule_sources)

    syntactically_non_invertible_rules: list[str] = []
    inverted_by_rule: list[str] = []
    for src in rule_sources:
        inv = _invert(src)
        if inv is None:
            syntactically_non_invertible_rules.append(src)
        else:
            inverted_by_rule.append(inv)

    common_concepts = tuple(
        cid for cid in parent_forms if cid in child_forms
    )
    parent_lexical_forms = tuple(
        LexicalForm(
            form_id=f"{parent_node_id}:{cid}",
            variety_id=parent_node_id,
            concept_id=cid,
            segments=tuple(parent_forms[cid]),
        )
        for cid in common_concepts
    )
    child_lexical_forms = tuple(
        LexicalForm(
            form_id=f"{child_node_id}:{cid}",
            variety_id=child_node_id,
            concept_id=cid,
            segments=tuple(child_forms[cid]),
        )
        for cid in common_concepts
    )

    current_forms = parent_lexical_forms
    reductions: list[dict[str, Any]] = []
    for rule in parsed_rules:
        reduction: ContrastReduction | None = rule_contrast_reduction(
            rule,
            current_forms,
            child_id=child_node_id,
            engine=engine,
        )
        if reduction is not None:
            reductions.append(
                {
                    "rule_id": reduction.rule_id,
                    "source": reduction.source,
                    "deletes": reduction.deletes,
                    "merges": reduction.merges,
                    "discarded_segments": list(reduction.discarded_segments),
                    "merged_into": list(reduction.merged_into),
                }
            )
        current_forms, _ = engine.apply_rules((rule,), current_forms)

    if not rule_sources:
        verified_inverse: tuple[str, ...] = ()
        invertible = all(
            tuple(parent_forms[cid]) == tuple(child_forms[cid])
            for cid in common_concepts
        )
    elif syntactically_non_invertible_rules:
        verified_inverse = ()
        invertible = False
    else:
        candidate = tuple(reversed(inverted_by_rule))
        verified_inverse, invertible = _verified_inverse(
            engine,
            parent_lexical_forms,
            child_lexical_forms,
            candidate,
        )

    def _recovery_rate(candidate_rules: Sequence[str]) -> float:
        if not common_concepts:
            return 0.0
        parsed_cand = tuple(parse_rule(r) for r in candidate_rules)
        recovered_forms, _ = engine.apply_rules(parsed_cand, child_lexical_forms)
        matches = sum(
            1
            for form in recovered_forms
            if form.segments == tuple(parent_forms[form.concept_id])
        )
        return matches / len(common_concepts)

    naive_reverse_rate = _recovery_rate(tuple(reversed(inverted_by_rule)))
    naive_forward_rate = _recovery_rate(tuple(inverted_by_rule))

    return {
        "invertible": invertible,
        "syntactically_non_invertible_rules": syntactically_non_invertible_rules,
        "contrast_reductions": reductions,
        "verified_inverse_rules": list(verified_inverse),
        "naive_arrow_swap_recovery_rate": naive_reverse_rate,
        "naive_reverse_recovery_rate": naive_reverse_rate,
        "naive_forward_recovery_rate": naive_forward_rate,
    }


def _strip_boundaries(segments: Sequence[str]) -> tuple[str, ...]:
    stripped = tuple(
        tok for tok in segments if tok not in MORPHOLOGICAL_BOUNDARY_TOKENS
    )
    return stripped if stripped else tuple(segments)


def compute_corpus_contrast_equivalence(
    inferred_forms: Mapping[str, Sequence[str] | None],
    reference_forms: Mapping[str, Sequence[str] | None],
    concept_ids: Sequence[str],
) -> dict[str, Any]:
    """Compare inferred vs. reference forms by both symbol identity and corpus-wide contrast structure.

    Because unanchored proto-reconstruction from daughter reflexes alone is
    identifiable only up to arbitrary proto-symbol relabelling unless anchored by
    typology or external attestations, this function reports both:
    - ``raw_exact_rate`` and ``mean_ned`` (which penalise unanchored symbol choice), and
    - ``corpus_bcubed_precision``, ``corpus_bcubed_recall``, ``corpus_bcubed_f1``, and
      ``is_bijective_relabelling`` computed over the concatenated alignment columns
      of the entire split.
    """
    evaluated_concepts: list[str] = []
    exact_count = 0
    ned_values: list[float] = []
    edit_distances: list[int] = []
    word_bcubed_f1s: list[float] = []
    corpus_columns: list[tuple[str, str]] = []
    has_gap_mismatch = False
    correspondence_counts: dict[str, dict[str, int]] = {}

    for cid in concept_ids:
        inf_raw = inferred_forms.get(cid)
        ref_raw = reference_forms.get(cid)
        if inf_raw is None or ref_raw is None:
            continue
        inf_segs = _strip_boundaries(inf_raw)
        ref_segs = _strip_boundaries(ref_raw)
        evaluated_concepts.append(cid)

        if inf_segs == ref_segs:
            exact_count += 1
        edit_distances.append(edit_distance(inf_segs, ref_segs))
        ned_values.append(normalized_edit_distance(inf_segs, ref_segs))
        word_bcubed_f1s.append(bcubed(inf_segs, ref_segs).f1)

        aligned_left, aligned_right = align(inf_segs, ref_segs)
        for a, b in zip(aligned_left, aligned_right, strict=True):
            if (a is None) != (b is None):
                has_gap_mismatch = True
            left_sym = GAP if a is None else a
            right_sym = GAP if b is None else b
            corpus_columns.append((left_sym, right_sym))
            correspondence_counts.setdefault(left_sym, {})[right_sym] = (
                correspondence_counts.get(left_sym, {}).get(right_sym, 0) + 1
            )

    if not corpus_columns:
        return {
            "evaluated_concept_count": 0,
            "raw_exact_count": 0,
            "raw_exact_rate": 0.0,
            "exact_count": 0,
            "exact_rate": 0.0,
            "mean_edit_distance": None,
            "mean_ned": None,
            "mean_word_bcubed_f1": None,
            "corpus_bcubed_precision": 0.0,
            "corpus_bcubed_recall": 0.0,
            "corpus_bcubed_f1": 0.0,
            "is_bijective_relabelling": False,
            "symbol_correspondence_map": {},
        }

    left_classes: dict[str, int] = {}
    right_classes: dict[str, int] = {}
    pair_counts: dict[tuple[str, str], int] = {}
    left_to_rights: dict[str, set[str]] = {}
    right_to_lefts: dict[str, set[str]] = {}

    for a, b in corpus_columns:
        left_classes[a] = left_classes.get(a, 0) + 1
        right_classes[b] = right_classes.get(b, 0) + 1
        pair_counts[(a, b)] = pair_counts.get((a, b), 0) + 1
        left_to_rights.setdefault(a, set()).add(b)
        right_to_lefts.setdefault(b, set()).add(a)

    corpus_precision = statistics.fmean(
        pair_counts[(a, b)] / left_classes[a] for a, b in corpus_columns
    )
    corpus_recall = statistics.fmean(
        pair_counts[(a, b)] / right_classes[b] for a, b in corpus_columns
    )
    denom = corpus_precision + corpus_recall
    corpus_f1 = (
        (2 * corpus_precision * corpus_recall / denom) if denom else 0.0
    )

    is_bijective = (
        not has_gap_mismatch
        and all(len(targets) == 1 for targets in left_to_rights.values())
        and all(len(sources) == 1 for sources in right_to_lefts.values())
    )

    count = len(evaluated_concepts)
    raw_rate = exact_count / count if count else 0.0
    return {
        "evaluated_concept_count": count,
        "raw_exact_count": exact_count,
        "raw_exact_rate": raw_rate,
        "exact_count": exact_count,
        "exact_rate": raw_rate,
        "mean_edit_distance": statistics.fmean(edit_distances),
        "mean_ned": statistics.fmean(ned_values),
        "mean_word_bcubed_f1": statistics.fmean(word_bcubed_f1s),
        "corpus_bcubed_precision": corpus_precision,
        "corpus_bcubed_recall": corpus_recall,
        "corpus_bcubed_f1": corpus_f1,
        "is_bijective_relabelling": is_bijective,
        "symbol_correspondence_map": correspondence_counts,
    }


def _compute_complexity_report(
    hypothesis: ForwardBranchHypothesis,
    *,
    dev_ancestor_forms: Mapping[str, Sequence[str] | None],
    dev_concept_to_etymon_id: Mapping[str, str],
) -> ForwardComplexityReport:
    rules = hypothesis.parsed_rules()
    engine = RuleEngine()

    total_target_tokens = sum(len(r.target.tokens) for r in rules)
    total_replacement_tokens = sum(len(r.replacement.tokens) for r in rules)
    total_context_tokens = sum(
        (len(r.environment.left.tokens) if r.environment.left else 0)
        + (len(r.environment.right.tokens) if r.environment.right else 0)
        for r in rules
    )
    boundary_constraint_count = sum(
        int(r.environment.word_initial) + int(r.environment.word_final)
        for r in rules
    )
    lexical_exception_tokens = sum(
        len(exc.override_segments) for exc in hypothesis.lexical_exceptions
    )
    description_token_complexity = (
        total_target_tokens
        + total_replacement_tokens
        + total_context_tokens
        + boundary_constraint_count
        + lexical_exception_tokens
    )

    current_forms = tuple(
        LexicalForm(
            form_id=f"{hypothesis.parent_node_id}:{cid}",
            variety_id=hypothesis.parent_node_id,
            concept_id=cid,
            segments=tuple(segs),
        )
        for cid, segs in dev_ancestor_forms.items()
        if segs is not None and len(segs) > 0
    )

    single_etymon_rule_ids: list[str] = []
    zero_application_rule_ids: list[str] = []
    for rule in rules:
        if not current_forms:
            zero_application_rule_ids.append(rule.rule_id)
            single_etymon_rule_ids.append(rule.rule_id)
            continue
        report = engine.apply_rule(rule, current_forms)
        applied_etymons: set[str] = set()
        for form, result in zip(current_forms, report.results, strict=True):
            if (
                result.status is ApplicationStatus.APPLIED
                and result.locations
            ):
                applied_etymons.add(
                    dev_concept_to_etymon_id.get(
                        form.concept_id, form.concept_id
                    )
                )
        if len(applied_etymons) == 0:
            zero_application_rule_ids.append(rule.rule_id)
        if len(applied_etymons) <= 1:
            single_etymon_rule_ids.append(rule.rule_id)
        current_forms = tuple(
            form.model_copy(update={"segments": result.output_segments})
            for form, result in zip(current_forms, report.results, strict=True)
        )

    exc_count = len(hypothesis.lexical_exceptions)
    return ForwardComplexityReport(
        rule_count=len(rules),
        total_target_tokens=total_target_tokens,
        total_replacement_tokens=total_replacement_tokens,
        total_context_tokens=total_context_tokens,
        boundary_constraint_count=boundary_constraint_count,
        lexical_exception_count=exc_count,
        max_lexical_exceptions=hypothesis.max_lexical_exceptions,
        exception_bound_exceeded=exc_count > hypothesis.max_lexical_exceptions,
        single_etymon_dev_rule_ids=tuple(single_etymon_rule_ids),
        zero_application_dev_rule_ids=tuple(zero_application_rule_ids),
        description_token_complexity=description_token_complexity,
        assumptions_note=(
            "description_token_complexity sums target tokens, replacement tokens, "
            "left/right environment tokens, word-boundary markers (#), and "
            "lexical-exception override tokens. single_etymon_dev_rule_ids flags "
            "rules whose APPLIED locations occur in <= 1 development etymon."
        ),
    )


def build_residual_autopsy(
    per_concept_results: Sequence[Mapping[str, Any]],
    *,
    evidence_channel: str,
) -> dict[str, Any]:
    """Group segment-level alignment residuals by mismatch pattern and local predicted context."""
    clusters: dict[str, dict[str, Any]] = {}
    mismatched_concept_ids: list[str] = []

    for item in per_concept_results:
        pred_raw = item.get("predicted_segments")
        obs_raw = item.get("target_segments")
        if pred_raw is None or obs_raw is None or item.get("exact", False):
            continue
        cid = str(item["concept_id"])
        etymon_id = str(item.get("etymon_id", cid))
        mismatched_concept_ids.append(cid)

        pred = tuple(pred_raw)
        obs = tuple(obs_raw)
        aligned_pred, aligned_obs = align(pred, obs)
        width = len(aligned_pred)

        for idx in range(width):
            p_tok = aligned_pred[idx]
            o_tok = aligned_obs[idx]
            if p_tok == o_tok:
                continue
            pred_sym = p_tok if p_tok is not None else "Ø"
            obs_sym = o_tok if o_tok is not None else "Ø"

            left_ctx = "#"
            for left_i in range(idx - 1, -1, -1):
                if aligned_pred[left_i] is not None:
                    left_ctx = str(aligned_pred[left_i])
                    break
            right_ctx = "#"
            for right_i in range(idx + 1, width):
                if aligned_pred[right_i] is not None:
                    right_ctx = str(aligned_pred[right_i])
                    break

            pattern = f"{pred_sym} != {obs_sym} / {left_ctx}_{right_ctx}"
            entry = clusters.setdefault(
                pattern,
                {
                    "pattern": pattern,
                    "predicted_token": pred_sym,
                    "observed_token": obs_sym,
                    "left_context": left_ctx,
                    "right_context": right_ctx,
                    "count": 0,
                    "concept_ids": [],
                    "etymon_ids": [],
                    "examples": [],
                },
            )
            entry["count"] += 1
            if cid not in entry["concept_ids"]:
                entry["concept_ids"].append(cid)
            if etymon_id not in entry["etymon_ids"]:
                entry["etymon_ids"].append(etymon_id)
            entry["examples"].append(
                {
                    "concept_id": cid,
                    "etymon_id": etymon_id,
                    "predicted": " ".join(pred),
                    "observed": " ".join(obs),
                }
            )

    sorted_clusters = sorted(
        clusters.values(),
        key=lambda c: (-int(c["count"]), str(c["pattern"])),
    )
    return {
        "evidence_channel": evidence_channel,
        "mismatched_concept_count": len(mismatched_concept_ids),
        "mismatched_concept_ids": mismatched_concept_ids,
        "recurring_mismatch_clusters": sorted_clusters,
    }


def _aggregate_subset_metrics(
    subset_cids: Sequence[str],
    results_by_cid: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    planned_count = len(subset_cids)
    items = [results_by_cid[cid] for cid in subset_cids if cid in results_by_cid]
    available = [item for item in items if not item["missing_output"]]
    available_count = len(available)
    missing_count = planned_count - available_count
    coverage = (available_count / planned_count) if planned_count else 0.0
    exact_count = sum(1 for item in available if item["exact"])
    exact_rate = (exact_count / planned_count) if planned_count else 0.0
    conditional_available_exact_rate = (
        (exact_count / available_count) if available_count else 0.0
    )

    if available:
        mean_ed: float | None = statistics.fmean(
            float(item["edit_distance"]) for item in available
        )
        mean_ned: float | None = statistics.fmean(
            float(item["normalized_edit_distance"]) for item in available
        )
        mean_bcubed_f1: float | None = statistics.fmean(
            float(item["bcubed_f1"]) for item in available
        )
    else:
        mean_ed = None
        mean_ned = None
        mean_bcubed_f1 = None

    unconditional_ned = (
        statistics.fmean(
            float(item["normalized_edit_distance"])
            if not item["missing_output"]
            else 1.0
            for item in items
        )
        if items
        else None
    )

    return {
        "planned_count": planned_count,
        "available_count": available_count,
        "missing_count": missing_count,
        "coverage": coverage,
        "exact_count": exact_count,
        "exact_rate": exact_rate,
        "conditional_available_exact_rate": conditional_available_exact_rate,
        "mean_edit_distance": mean_ed,
        "mean_ned": mean_ned,
        "unconditional_mean_ned": unconditional_ned,
        "mean_bcubed_f1": mean_bcubed_f1,
    }


def evaluate_forward_split(
    hypothesis: ForwardBranchHypothesis,
    *,
    split_name: str,
    concept_ids: Sequence[str],
    concept_to_etymon_id: Mapping[str, str],
    ancestor_forms: Mapping[str, Sequence[str] | None],
    target_daughter_forms: Mapping[str, Sequence[str]],
    underdetermined_concept_ids: Sequence[str] = (),
    sister_forms_by_concept: Mapping[str, Mapping[str, Sequence[str]]] | None = None,
    reference_ancestor_forms: Mapping[str, Sequence[str] | None] | None = None,
    dev_ancestor_forms_for_complexity: Mapping[str, Sequence[str] | None] | None = None,
    dev_concept_to_etymon_id: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Execute a forward branch hypothesis on ``concept_ids`` and grade against ``target_daughter_forms``."""
    engine = RuleEngine()
    parsed_rules = hypothesis.parsed_rules()
    exceptions_by_cid = {
        exc.concept_id: exc for exc in hypothesis.lexical_exceptions
    }
    underdetermined_set = set(underdetermined_concept_ids)
    sister_lookup = sister_forms_by_concept or {}

    per_concept_results: list[dict[str, Any]] = []
    results_by_cid: dict[str, dict[str, Any]] = {}
    ancestor_source_counts: dict[str, int] = {}
    unattested_inferred_input_count = 0
    unattested_predicted_reflex_count = 0

    for cid in concept_ids:
        if cid not in target_daughter_forms:
            raise KeyError(
                f"Concept {cid!r} is missing from target_daughter_forms"
            )
        target_segs = _strip_boundaries(target_daughter_forms[cid])
        etymon_id = concept_to_etymon_id.get(cid, cid)
        is_underdetermined = cid in underdetermined_set
        sisters_for_cid = {
            sis_id: _strip_boundaries(segs)
            for sis_id, segs in sister_lookup.get(cid, {}).items()
        }

        raw_anc = ancestor_forms.get(cid)
        if raw_anc is None or len(raw_anc) == 0:
            record: dict[str, Any] = {
                "concept_id": cid,
                "etymon_id": etymon_id,
                "underdetermined": is_underdetermined,
                "missing_output": True,
                "ancestor_segments": None,
                "ancestor_source_kind": None,
                "regular_cascade_segments": None,
                "predicted_segments": None,
                "target_segments": list(target_segs),
                "lexical_exception_applied": False,
                "would_empty_form_triggered": False,
                "predicted_unattested_in_sisters": False,
                "exact": False,
                "edit_distance": None,
                "normalized_edit_distance": None,
                "bcubed_precision": None,
                "bcubed_recall": None,
                "bcubed_f1": None,
                "rule_traces": [],
            }
            per_concept_results.append(record)
            results_by_cid[cid] = record
            continue

        anc_segs = _strip_boundaries(raw_anc)
        source_kind = classify_ancestor_source(
            anc_segs,
            sisters_for_cid,
            regime=hypothesis.ancestor_regime,
        )
        ancestor_source_counts[source_kind.value] = (
            ancestor_source_counts.get(source_kind.value, 0) + 1
        )
        if source_kind is AncestorSourceKind.INFERRED_UNATTESTED:
            unattested_inferred_input_count += 1

        current_form = LexicalForm(
            form_id=f"{hypothesis.parent_node_id}:{cid}",
            variety_id=hypothesis.parent_node_id,
            concept_id=cid,
            segments=anc_segs,
        )
        traces: list[dict[str, Any]] = []
        would_empty_triggered = False

        for step_idx, rule in enumerate(parsed_rules):
            report = engine.apply_rule(rule, (current_form,))
            res = report.results[0]
            if res.status is ApplicationStatus.WOULD_EMPTY_FORM:
                would_empty_triggered = True
            stage_trace = ForwardRuleStageTrace(
                step_index=step_idx,
                rule_id=rule.rule_id,
                rule_source=rule.source,
                status=res.status.value,
                input_segments=res.input_segments,
                output_segments=res.output_segments,
                locations=tuple(
                    (loc.start_token, loc.end_token) for loc in res.locations
                ),
                explanation=res.explanation,
            )
            traces.append(stage_trace.as_dict())
            current_form = current_form.model_copy(
                update={"segments": res.output_segments}
            )

        regular_segments = current_form.segments
        if cid in exceptions_by_cid:
            lexical_exception_applied = True
            predicted_segs = _strip_boundaries(
                exceptions_by_cid[cid].override_segments
            )
        else:
            lexical_exception_applied = False
            predicted_segs = regular_segments

        graded = compare_to_nearest(predicted_segs, (target_segs,))
        sister_segment_tuples = {
            tuple(segs) for segs in sisters_for_cid.values()
        }
        predicted_unattested = bool(sister_segment_tuples) and (
            predicted_segs not in sister_segment_tuples
        )
        if predicted_unattested:
            unattested_predicted_reflex_count += 1

        record = {
            "concept_id": cid,
            "etymon_id": etymon_id,
            "underdetermined": is_underdetermined,
            "missing_output": False,
            "ancestor_segments": list(anc_segs),
            "ancestor_source_kind": source_kind.value,
            "regular_cascade_segments": list(regular_segments),
            "predicted_segments": list(predicted_segs),
            "target_segments": list(target_segs),
            "lexical_exception_applied": lexical_exception_applied,
            "would_empty_form_triggered": would_empty_triggered,
            "predicted_unattested_in_sisters": predicted_unattested,
            "exact": graded.exact,
            "edit_distance": graded.edit_distance,
            "normalized_edit_distance": graded.normalized_edit_distance,
            "bcubed_precision": graded.bcubed_precision,
            "bcubed_recall": graded.bcubed_recall,
            "bcubed_f1": graded.bcubed_f1,
            "rule_traces": traces,
        }
        per_concept_results.append(record)
        results_by_cid[cid] = record

    validated_cids = tuple(
        cid for cid in concept_ids if cid not in underdetermined_set
    )
    underdetermined_cids = tuple(
        cid for cid in concept_ids if cid in underdetermined_set
    )

    all_planned_metrics = _aggregate_subset_metrics(concept_ids, results_by_cid)
    validated_metrics = _aggregate_subset_metrics(
        validated_cids, results_by_cid
    )
    underdetermined_metrics = _aggregate_subset_metrics(
        underdetermined_cids, results_by_cid
    )

    ancestor_evaluation: dict[str, Any] | None = None
    if reference_ancestor_forms is not None:
        ancestor_evaluation = compute_corpus_contrast_equivalence(
            ancestor_forms,
            reference_ancestor_forms,
            validated_cids,
        )

    complexity_report = _compute_complexity_report(
        hypothesis,
        dev_ancestor_forms=(
            dev_ancestor_forms_for_complexity
            if dev_ancestor_forms_for_complexity is not None
            else ancestor_forms
        ),
        dev_concept_to_etymon_id=(
            dev_concept_to_etymon_id
            if dev_concept_to_etymon_id is not None
            else concept_to_etymon_id
        ),
    )

    evidence_channel = (
        "development_fitting"
        if "dev" in split_name.lower()
        else "offline_held_out_scorer_only"
    )
    residual_autopsy = build_residual_autopsy(
        per_concept_results,
        evidence_channel=evidence_channel,
    )

    return {
        "evaluator_version": FORWARD_EVALUATOR_VERSION,
        "split_name": split_name,
        "hypothesis_id": hypothesis.hypothesis_id,
        "parent_node_id": hypothesis.parent_node_id,
        "child_node_id": hypothesis.child_node_id,
        "direction": hypothesis.direction,
        "ancestor_regime": hypothesis.ancestor_regime,
        "privileged_operator_control": hypothesis.privileged_operator_control,
        "deployable_baseline": hypothesis.deployable_baseline,
        "rule_sources": list(hypothesis.rule_sources),
        "lexical_exceptions": [
            exc.model_dump(mode="json") for exc in hypothesis.lexical_exceptions
        ],
        "all_planned": all_planned_metrics,
        "validated_only": validated_metrics,
        "underdetermined_only": underdetermined_metrics,
        "ancestor_source_kind_counts": ancestor_source_counts,
        "unattested_inferred_input_count": unattested_inferred_input_count,
        "unattested_predicted_reflex_count": unattested_predicted_reflex_count,
        "ancestor_evaluation": ancestor_evaluation,
        "complexity_report": complexity_report.as_dict(),
        "residual_autopsy": residual_autopsy,
        "per_concept": per_concept_results,
    }


def compare_forward_hypotheses(
    before_eval: Mapping[str, Any],
    after_eval: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare two ``evaluate_forward_split`` results on the same split."""
    before_by_cid = {
        str(item["concept_id"]): item
        for item in before_eval.get("per_concept", ())
    }
    after_by_cid = {
        str(item["concept_id"]): item
        for item in after_eval.get("per_concept", ())
    }
    common_cids = [cid for cid in before_by_cid if cid in after_by_cid]

    repaired: list[str] = []
    newly_broken: list[str] = []
    unchanged_exact: list[str] = []
    unchanged_wrong: list[str] = []
    per_concept_changes: list[dict[str, Any]] = []

    for cid in common_cids:
        b_item = before_by_cid[cid]
        a_item = after_by_cid[cid]
        b_exact = bool(b_item.get("exact", False))
        a_exact = bool(a_item.get("exact", False))
        if not b_exact and a_exact:
            repaired.append(cid)
            outcome = "repaired"
        elif b_exact and not a_exact:
            newly_broken.append(cid)
            outcome = "newly_broken"
        elif b_exact and a_exact:
            unchanged_exact.append(cid)
            outcome = "unchanged_exact"
        else:
            unchanged_wrong.append(cid)
            outcome = "unchanged_wrong"

        if b_item.get("predicted_segments") != a_item.get("predicted_segments"):
            per_concept_changes.append(
                {
                    "concept_id": cid,
                    "outcome": outcome,
                    "before_predicted": b_item.get("predicted_segments"),
                    "after_predicted": a_item.get("predicted_segments"),
                    "target_segments": a_item.get("target_segments"),
                }
            )

    b_val = before_eval.get("validated_only", {})
    a_val = after_eval.get("validated_only", {})
    b_ned = b_val.get("mean_ned")
    a_ned = a_val.get("mean_ned")
    delta_ned = (
        (float(a_ned) - float(b_ned))
        if (a_ned is not None and b_ned is not None)
        else None
    )

    return {
        "before_hypothesis_id": before_eval.get("hypothesis_id"),
        "after_hypothesis_id": after_eval.get("hypothesis_id"),
        "split_name": after_eval.get("split_name"),
        "repaired_concept_ids": repaired,
        "newly_broken_concept_ids": newly_broken,
        "unchanged_exact_concept_ids": unchanged_exact,
        "unchanged_wrong_concept_ids": unchanged_wrong,
        "delta_validated_exact_count": int(a_val.get("exact_count", 0))
        - int(b_val.get("exact_count", 0)),
        "delta_validated_exact_rate": float(a_val.get("exact_rate", 0.0))
        - float(b_val.get("exact_rate", 0.0)),
        "delta_validated_mean_ned": delta_ned,
        "per_concept_changes": per_concept_changes,
    }


def evaluate_rule_order_permutations(
    rule_sources: Sequence[str],
    *,
    ancestor_forms: Mapping[str, Sequence[str]],
    target_daughter_forms: Mapping[str, Sequence[str]],
    concept_ids: Sequence[str],
) -> dict[str, Any]:
    """Evaluate all ``k!`` permutations of a fixed forward rule set (auxiliary ordering check)."""
    engine = RuleEngine()
    parsed_by_source = {src: parse_rule(src) for src in rule_sources}

    base_forms = tuple(
        LexicalForm(
            form_id=f"anc:{cid}",
            variety_id="anc",
            concept_id=cid,
            segments=_strip_boundaries(ancestor_forms[cid]),
        )
        for cid in concept_ids
    )
    target_by_cid = {
        cid: _strip_boundaries(target_daughter_forms[cid])
        for cid in concept_ids
    }

    ranking: list[dict[str, Any]] = []
    for perm in itertools.permutations(rule_sources):
        rules = tuple(parsed_by_source[src] for src in perm)
        out_forms, _ = engine.apply_rules(rules, base_forms)
        exact_count = 0
        neds: list[float] = []
        mismatched: list[str] = []
        for form in out_forms:
            target = target_by_cid[form.concept_id]
            if form.segments == target:
                exact_count += 1
            else:
                mismatched.append(form.concept_id)
            neds.append(normalized_edit_distance(form.segments, target))
        total = len(concept_ids)
        ranking.append(
            {
                "order": list(perm),
                "exact_count": exact_count,
                "exact_rate": (exact_count / total) if total else 0.0,
                "mean_ned": statistics.fmean(neds) if neds else 0.0,
                "mismatched_concept_ids": mismatched,
            }
        )

    ranking.sort(
        key=lambda entry: (
            -int(entry["exact_count"]),
            float(entry["mean_ned"]),
            entry["order"],
        )
    )
    best_exact = ranking[0]["exact_count"] if ranking else 0
    winning_orders = [
        entry["order"]
        for entry in ranking
        if entry["exact_count"] == best_exact
    ]
    exact_match_permutation_count = sum(
        1
        for entry in ranking
        if entry["exact_count"] == len(concept_ids) and len(concept_ids) > 0
    )

    return {
        "task_kind": "auxiliary_rule_ordering",
        "rule_count": len(rule_sources),
        "permutation_count": len(ranking),
        "exact_match_permutation_count": exact_match_permutation_count,
        "unique_winning_order": len(winning_orders) == 1,
        "winning_orders": winning_orders,
        "permutation_ranking": ranking,
    }


__all__ = [
    "AncestorSourceKind",
    "ETYMON_SPLIT_VERSION",
    "EtymonClusterSplit",
    "FORWARD_EVALUATOR_VERSION",
    "ForwardBranchHypothesis",
    "ForwardComplexityReport",
    "ForwardLexicalException",
    "ForwardRuleStageTrace",
    "build_etymon_cluster_split",
    "build_residual_autopsy",
    "check_forward_cascade_invertibility",
    "classify_ancestor_source",
    "compare_forward_hypotheses",
    "compute_corpus_contrast_equivalence",
    "evaluate_forward_split",
    "evaluate_rule_order_permutations",
    "mask_target_daughter_in_payload",
    "verify_no_target_leakage",
]
