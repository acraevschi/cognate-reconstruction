"""Declarative definition of a reconstruction benchmark.

A benchmark is a dataset, a tree, a set of daughters, and one or more gold
nodes withheld from the model. All four are data, so a benchmark is a small
file rather than a script — which is what makes a second family a definition to
write instead of a program to debug.
"""

from __future__ import annotations

import datetime as _datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from cognate_reconstruction.schemas.common import NonEmptyStr, WorkbenchModel
from cognate_reconstruction.schemas.historical import GoldEvidenceKind


class ConceptSelection(StrEnum):
    """How the concepts a benchmark scores over are chosen.

    `FULLY_COGNATE_WITH_TARGET` is what makes a benchmark a test of
    *reconstruction* rather than a test of cognate judgement: every daughter is
    known to share a cognate set with the gold form, so the model's job is to
    recover the ancestor of forms already known to be related. Selecting on mere
    presence would silently mix in lexical replacement, which no phonological
    method recovers, and score a reconstruction system on a semantics problem.
    """

    FULLY_COGNATE_WITH_TARGET = "fully_cognate_with_target"
    SHARED_BY_ALL_DAUGHTERS = "shared_by_all_daughters"
    ALL = "all"


class BenchmarkProvenance(WorkbenchModel):
    """Where the gold came from, and what a reader must know before quoting it."""

    source: NonEmptyStr | None = None
    publication_date: _datetime.date | None = None
    """When the gold was published.

    Recorded because the one leakage control that needs no new code is a gold
    set published *after* a model's training cutoff: the definition states the
    date, the run records the model, and the comparison is then a fact rather
    than a hope.
    """
    leakage_note: NonEmptyStr | None = None
    note: NonEmptyStr | None = None


class BenchmarkTarget(WorkbenchModel):
    """One gold node: a source variety hidden and bound to an internal node."""

    source_variety_id: NonEmptyStr
    node_id: NonEmptyStr
    gold_evidence_kind: GoldEvidenceKind
    source_reference: NonEmptyStr | None = None


class BenchmarkDefinition(WorkbenchModel):
    """Everything needed to rebuild one benchmark payload from local CLDF.

    The harness never downloads or builds a Lexibank dataset; `dataset_path`
    must already exist locally. A definition is therefore a recipe over data the
    user supplied, not a data source of its own.
    """

    schema_version: Literal["1.0"] = "1.0"
    name: NonEmptyStr
    description: NonEmptyStr
    dataset_path: NonEmptyStr
    daughters: tuple[NonEmptyStr, ...] = Field(min_length=2)
    targets: tuple[BenchmarkTarget, ...] = Field(min_length=1)
    newick: NonEmptyStr | None = None
    newick_path: NonEmptyStr | None = None
    concept_selection: ConceptSelection = ConceptSelection.FULLY_COGNATE_WITH_TARGET
    concept_selection_source_variety_id: NonEmptyStr | None = None
    """Whose cognacy the selection requires the daughters to share.

    Defaults to the first target's source variety. It is explicit because a
    definition with two gold nodes has two candidate answers and picking one
    silently would make the concept count depend on list order.
    """
    max_concepts: int | None = Field(default=None, ge=1)
    """Optional cap, applied after selection in concept-ID order.

    For a family the size of Romance the full selection is thousands of
    concepts, which is a real benchmark and a slow one. Capping is a stated
    choice rather than a default: an uncapped definition is the faithful one.
    """
    provenance: BenchmarkProvenance = Field(default_factory=BenchmarkProvenance)

    @model_validator(mode="after")
    def validate_definition(self) -> "BenchmarkDefinition":
        if (self.newick is None) == (self.newick_path is None):
            raise ValueError(
                "a benchmark definition needs exactly one of 'newick' or "
                "'newick_path'"
            )
        if len(set(self.daughters)) != len(self.daughters):
            raise ValueError("benchmark daughters must be unique")
        sources = [target.source_variety_id for target in self.targets]
        if len(sources) != len(set(sources)):
            raise ValueError("each gold source variety may be bound once")
        node_ids = [target.node_id for target in self.targets]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("each gold node may carry one target binding")
        if overlap := sorted(set(sources) & set(self.daughters)):
            raise ValueError(
                "a gold source variety cannot also be a daughter; it would "
                f"stay in the lexicons and leak the answer: {overlap}"
            )
        if (
            self.concept_selection_source_variety_id is not None
            and self.concept_selection_source_variety_id not in sources
        ):
            raise ValueError(
                "concept_selection_source_variety_id must name one of this "
                "definition's targets"
            )
        return self

    @property
    def selection_source_variety_id(self) -> str:
        return (
            self.concept_selection_source_variety_id
            or self.targets[0].source_variety_id
        )
