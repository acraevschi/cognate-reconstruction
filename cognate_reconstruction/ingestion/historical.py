"""Supported historical-lineage and form-binding preparation."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from cognate_reconstruction.schemas.historical import (
    HistoricalBindingFile,
    HistoricalBindingRequest,
    HistoricalFormBinding,
    HistoricalFormRole,
    HistoricalLineageRelation,
)
from cognate_reconstruction.schemas.lexicon import LanguageLexicon


_LINEAGE_COLUMNS = {
    "dataset",
    "target_variety_id",
    "branch_id",
    "descendant_variety_id",
}


def load_historical_lineage_bindings(
    path: str | Path,
    *,
    dataset_id: str,
    role: HistoricalFormRole | str,
) -> HistoricalBindingFile:
    """Interpret a curated lineage CSV as explicit node-role requests.

    The manifest supplies ancestry provenance only. It does not create or
    reorder the runtime tree: every target ID must independently resolve to an
    internal node in a supplied Newick classification.
    """
    source = Path(path).expanduser().resolve()
    requested_role = HistoricalFormRole(role)
    grouped: dict[str, list[HistoricalLineageRelation]] = defaultdict(list)
    with source.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = _LINEAGE_COLUMNS - set(reader.fieldnames or ())
        if missing:
            raise ValueError(
                f"historical lineage manifest {source} is missing columns: "
                f"{sorted(missing)}"
            )
        for row_number, row in enumerate(reader, start=2):
            row_dataset = (row.get("dataset") or "").strip()
            if row_dataset != dataset_id:
                continue
            target_id = (row.get("target_variety_id") or "").strip()
            branch_id = (row.get("branch_id") or "").strip()
            descendant_id = (row.get("descendant_variety_id") or "").strip()
            if not target_id or not branch_id or not descendant_id:
                raise ValueError(
                    f"historical lineage manifest {source} has an incomplete "
                    f"row at line {row_number}"
                )
            grouped[target_id].append(
                HistoricalLineageRelation(
                    branch_id=branch_id,
                    descendant_variety_id=descendant_id,
                    evidence=(row.get("evidence") or "").strip() or None,
                    source_reference=str(source),
                    source_row=row_number,
                )
            )
    if not grouped:
        raise ValueError(
            f"historical lineage manifest {source} has no rows for "
            f"dataset {dataset_id!r}"
        )
    return HistoricalBindingFile(
        bindings=tuple(
            HistoricalBindingRequest(
                source_variety_id=target_id,
                node_id=target_id,
                role=requested_role,
                lineage_relations=tuple(relations),
                source_reference=str(source),
            )
            for target_id, relations in sorted(grouped.items())
        )
    )


def materialize_historical_bindings(
    requests: HistoricalBindingFile,
    lexicons: tuple[LanguageLexicon, ...],
) -> tuple[HistoricalFormBinding, ...]:
    """Copy selected source forms to exact internal-node identities."""
    by_id = {lexicon.variety_id: lexicon for lexicon in lexicons}
    bindings = []
    for request in requests.bindings:
        try:
            source = by_id[request.source_variety_id]
        except KeyError as error:
            raise ValueError(
                f"historical source variety {request.source_variety_id!r} is "
                "not present in the loaded CLDF dataset"
            ) from error
        bindings.append(
            HistoricalFormBinding(
                node_id=request.node_id,
                role=request.role,
                source_variety_id=source.variety_id,
                source_declared_historical=source.is_historical,
                forms=tuple(
                    form.model_copy(update={"variety_id": request.node_id})
                    for form in source.forms
                ),
                lineage_relations=request.lineage_relations,
                source_reference=request.source_reference,
                gold_evidence_kind=request.gold_evidence_kind,
            )
        )
    return tuple(bindings)

