"""Explicit analysis and column provenance, independent of reference forms."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import Field, model_validator

from .common import NonEmptyStr, WorkbenchModel

EVIDENCE_CONTRACT_VERSION = "units-v1"


def digest(value: object) -> str:
    import json
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()[:24]


class PieceSource(WorkbenchModel):
    form_id: NonEmptyStr
    membership_id: NonEmptyStr | None = None
    cognate_set_id: NonEmptyStr | None = None
    segment_indices: tuple[int, ...] = ()


class EvidencePiece(WorkbenchModel):
    unit_id: NonEmptyStr
    cognate_set_id: NonEmptyStr | None = None
    kind: Literal["whole", "cognate", "unknown", "boundary", "restoration"]
    segment_indices: tuple[int, ...] = Field(min_length=1)
    sources: tuple[PieceSource, ...] = ()
    column_ids: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def indices_in_order(self):
        if tuple(sorted(set(self.segment_indices))) != self.segment_indices:
            raise ValueError("piece positions must be unique, non-negative and ordered")
        if self.segment_indices[0] < 0:
            raise ValueError("piece positions must be non-negative")
        return self


class FormAnalysis(WorkbenchModel):
    version: Literal["units-v1"] = EVIDENCE_CONTRACT_VERSION
    pieces: tuple[EvidencePiece, ...] = Field(min_length=1)
    order_status: Literal["source", "model_claim", "unresolved"] = "source"
    notes: tuple[NonEmptyStr, ...] = ()
    claim: Literal["source", "model", "approved_assembly", "identity", "unresolved_rules"]

    @model_validator(mode="after")
    def unique_occurrences(self):
        ids = [piece.unit_id for piece in self.pieces]
        if len(set(ids)) != len(ids):
            raise ValueError("repeated units need distinct occurrence unit_ids; no piece may overwrite another")
        return self

    def validate_segments(self, length: int) -> None:
        positions = tuple(index for piece in self.pieces for index in piece.segment_indices)
        if positions != tuple(range(length)):
            raise ValueError("analysis must partition every segment in surface order")

    def compatibility_key(self) -> str:
        """Linguistic claims, excluding their separately retained histories."""
        return digest([self.order_status, [(p.unit_id, p.cognate_set_id, p.kind, p.segment_indices)
                                          for p in self.pieces]])


def merge_compatible_analyses(analyses):
    if not analyses or analyses[0] is None:
        return None
    if len({analysis.compatibility_key() for analysis in analyses}) != 1:
        raise ValueError("cannot merge incompatible unit claims")
    pieces = tuple(piece.model_copy(update={
        "sources": tuple(dict.fromkeys(source for analysis in analyses for source in analysis.pieces[index].sources)),
        "column_ids": tuple(dict.fromkeys(column for analysis in analyses for column in analysis.pieces[index].column_ids)),
    }) for index, piece in enumerate(analyses[0].pieces))
    claim = next((claim for claim in ("unresolved_rules", "approved_assembly", "model", "source")
                  if any(analysis.claim == claim for analysis in analyses)), analyses[0].claim)
    return analyses[0].model_copy(update={"pieces": pieces, "claim": claim,
        "notes": tuple(dict.fromkeys(note for analysis in analyses for note in analysis.notes))})


class PieceAnalysisClaim(WorkbenchModel):
    unit_id: NonEmptyStr
    cognate_set_id: NonEmptyStr | None = None
    segment_indices: tuple[int, ...] = Field(min_length=1)

class UnitOrderClaim(WorkbenchModel):
    concept_id: NonEmptyStr
    unit_ids: tuple[NonEmptyStr, ...] = Field(min_length=1)
    rationale: NonEmptyStr

    @model_validator(mode="after")
    def unique_units(self):
        if len(set(self.unit_ids)) != len(self.unit_ids):
            raise ValueError("unit order must name each unit once")
        return self


class EvidenceColumn(WorkbenchModel):
    column_id: NonEmptyStr
    unit_id: NonEmptyStr
    scope_id: NonEmptyStr
    sources: tuple[PieceSource, ...] = ()


class ColumnBinding(WorkbenchModel):
    column_id: NonEmptyStr
    set_id: NonEmptyStr
    reflexes: tuple[str | None, ...]


class AssemblyWork(WorkbenchModel):
    candidate_tuples: int = Field(default=0, ge=0)
    alignment_calls: int = Field(default=0, ge=0)
    cache_hits: int = Field(default=0, ge=0)
    pruned_candidates: int = Field(default=0, ge=0)
