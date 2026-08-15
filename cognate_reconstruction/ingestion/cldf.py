"""Strict CLDF/Lexibank ingestion into workbench-native lexical schemas."""

from __future__ import annotations

import unicodedata
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from pycldf import Dataset

from cognate_reconstruction.schemas.common import NonEmptyStr, WorkbenchModel
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.schemas.lexicon import (
    CognateMembership,
    CognateMembershipInterpretation,
    CognateMembershipProvenance,
    CognateMembershipScope,
    ConceptMetadata,
    FormProvenance,
    LanguageLexicon,
    LexicalForm,
)
from cognate_reconstruction.ingestion.compatibility import tree_glottocode_for


class CLDFIngestionError(ValueError):
    """A user-actionable failure while adapting local CLDF data."""


class CLDFLoadResult(WorkbenchModel):
    """One local dataset adapted without depending on legacy generator models."""

    dataset_id: NonEmptyStr
    metadata_path: NonEmptyStr
    lexicons: tuple[LanguageLexicon, ...]
    concepts: tuple[ConceptMetadata, ...] = ()

    @property
    def num_forms(self) -> int:
        return sum(len(lexicon.forms) for lexicon in self.lexicons)

    def to_payload(self, *, newick: str | None = None) -> WorkbenchPayload:
        return WorkbenchPayload(
            lexicons=self.lexicons,
            concepts=self.concepts,
            newick=newick,
        )


def _safe_str(value: Any) -> str:
    return str(value) if value is not None else ""


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _safe_str(value).strip().lower() in {"1", "true", "yes"}


def _nullable_bool(value: Any) -> bool | None:
    if value is None or _safe_str(value).strip() == "":
        return None
    return _as_bool(value)


def _tokens(value: Any) -> tuple[str, ...]:
    """Use existing CLDF tokens only; raw orthography is never segmented."""
    if isinstance(value, (list, tuple)):
        items = value
    elif isinstance(value, str):
        items = value.split()
    else:
        return ()
    return tuple(
        unicodedata.normalize("NFC", token)
        for item in items
        if (token := _safe_str(item).strip())
    )


def _values(value: Any, *, split_whitespace: bool = False) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        items = value
    elif isinstance(value, str):
        items = value.split() if split_whitespace else (value,)
    else:
        return ()
    return tuple(
        text
        for item in items
        if (text := _safe_str(item).strip())
    )


_SEGMENT_SLICE = re.compile(r"^(\d+)(?::(\d+))?$")


def _segment_indices(
    specifications: tuple[str, ...],
    *,
    segments: tuple[str, ...],
    slice_unit: str,
    membership_id: str,
) -> tuple[int, ...]:
    """Normalize one-based inclusive source slices to segment positions."""
    if slice_unit == "segment":
        units = tuple((index,) for index in range(len(segments)))
    elif slice_unit == "morpheme":
        groups: list[list[int]] = [[]]
        for index, segment in enumerate(segments):
            if segment in {"+", "-"}:
                if groups[-1]:
                    groups.append([])
                continue
            groups[-1].append(index)
        units = tuple(tuple(group) for group in groups if group)
    else:
        raise ValueError(f"unknown cognate slice unit {slice_unit!r}")
    indices: list[int] = []
    for specification in specifications:
        match = _SEGMENT_SLICE.fullmatch(specification)
        if match is None:
            raise CLDFIngestionError(
                f"cognate membership {membership_id!r} has malformed "
                f"Segment_Slice value {specification!r}"
            )
        start = int(match.group(1))
        stop = int(match.group(2) or start)
        if start < 1 or stop < start or stop > len(units):
            raise CLDFIngestionError(
                f"cognate membership {membership_id!r} has Segment_Slice "
                f"{specification!r} outside a {len(units)}-{slice_unit} form"
            )
        for unit in units[start - 1 : stop]:
            indices.extend(unit)
    if len(indices) != len(set(indices)):
        raise CLDFIngestionError(
            f"cognate membership {membership_id!r} has overlapping "
            "Segment_Slice ranges"
        )
    return tuple(indices)


def _find_metadata(dataset_path: Path) -> Path:
    if dataset_path.is_file():
        return dataset_path
    cldf_dir = dataset_path / "cldf"
    candidates = (
        sorted(cldf_dir.glob("*-metadata.json"))
        if cldf_dir.is_dir()
        else []
    )
    if not candidates:
        candidates = sorted(dataset_path.glob("*-metadata.json"))
    if not candidates:
        raise CLDFIngestionError(
            f"{dataset_path} contains no CLDF metadata JSON; pass a Lexibank "
            "dataset directory or a *-metadata.json file"
        )
    return candidates[0]


def _table_has_column(
    dataset: Dataset,
    table_name: str,
    column_name: str,
) -> bool:
    try:
        table = dataset[table_name]
    except KeyError:
        return False
    return any(
        column.name == column_name or column.header == column_name
        for column in table.tableSchema.columns
    )


def _column_property_url(
    dataset: Dataset,
    table_name: str,
    column_name: str,
) -> str | None:
    try:
        table = dataset[table_name]
    except KeyError:
        return None
    for column in table.tableSchema.columns:
        if column.name == column_name or column.header == column_name:
            return str(column.propertyUrl) if column.propertyUrl else None
    return None


def _has_table(dataset: Dataset, table_name: str) -> bool:
    try:
        dataset[table_name]
    except KeyError:
        return False
    return True


def _concept_id(dataset_id: str, parameter_id: str, concepticon_id: str) -> str:
    return concepticon_id or f"{dataset_id}:{parameter_id}"


def load_cldf_dataset(dataset_path: str | Path) -> CLDFLoadResult:
    """Load a local Lexibank/CLDF wordlist with tokenized cognate evidence.

    Identity is dataset scoped. ``source_glottocode`` records the language
    table value, while ``tree_glottocode`` remains a separate field that a
    later classification adapter may explicitly override.
    """
    requested_path = Path(dataset_path).expanduser().resolve()
    metadata_path = _find_metadata(requested_path)
    dataset_root = (
        metadata_path.parent.parent
        if metadata_path.parent.name == "cldf"
        else metadata_path.parent
    )
    dataset_id = dataset_root.name
    try:
        dataset = Dataset.from_metadata(metadata_path)
    except Exception as error:
        raise CLDFIngestionError(
            f"could not read CLDF metadata {metadata_path}: {error}"
        ) from error

    has_inline_cognates = _table_has_column(
        dataset, "FormTable", "Cognateset_ID"
    )
    has_cognate_table = _has_table(dataset, "CognateTable")
    cognate_slice_unit = (
        "segment"
        if _column_property_url(
            dataset,
            "CognateTable",
            "Segment_Slice",
        )
        == "http://cldf.clld.org/v1.0/terms.rdf#segmentSlice"
        else "morpheme"
    )
    if not has_inline_cognates and not has_cognate_table:
        raise CLDFIngestionError(
            f"{dataset_id!r} has neither FormTable Cognateset_ID values nor "
            "a CognateTable; the reconstruction harness requires cognate evidence"
        )

    languages: dict[str, dict[str, Any]] = {}
    try:
        language_rows = dataset["LanguageTable"]
    except KeyError as error:
        raise CLDFIngestionError(
            f"{dataset_id!r} has no CLDF LanguageTable"
        ) from error
    for row in language_rows:
        source_id = _safe_str(row.get("ID")).strip()
        if not source_id:
            continue
        source_glottocode = _safe_str(row.get("Glottocode")).strip() or None
        language_name = _safe_str(row.get("Name")).strip() or source_id
        tree_glottocode, compatibility_rule_ids = tree_glottocode_for(
            dataset_id=dataset_id,
            source_language_id=source_id,
            language_name=language_name,
            source_glottocode=source_glottocode,
        )
        languages[source_id] = {
            "variety_id": f"{dataset_id}:{source_id}",
            "name": language_name,
            "source_glottocode": source_glottocode,
            "tree_glottocode": tree_glottocode,
            "compatibility_rule_ids": compatibility_rule_ids,
            "family": (
                _safe_str(row.get("Family") or row.get("family")).strip() or None
            ),
            "is_historical": _as_bool(
                row.get("historical", row.get("Historical"))
            ),
        }

    parameters: dict[str, dict[str, str | None]] = {}
    try:
        for row in dataset["ParameterTable"]:
            parameter_id = _safe_str(row.get("ID")).strip()
            if not parameter_id:
                continue
            concepticon_id = (
                _safe_str(row.get("Concepticon_ID")).strip() or None
            )
            gloss = (
                _safe_str(
                    row.get("Concepticon_Gloss") or row.get("Name") or parameter_id
                ).strip()
                or parameter_id
            )
            parameters[parameter_id] = {
                "concept_id": _concept_id(
                    dataset_id,
                    parameter_id,
                    concepticon_id or "",
                ),
                "concepticon_id": concepticon_id,
                "gloss": gloss,
            }
    except KeyError:
        pass

    cognate_rows_by_form: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if has_cognate_table:
        for row_number, row in enumerate(dataset["CognateTable"], start=2):
            form_id = _safe_str(row.get("Form_ID")).strip()
            raw_cognate_id = _safe_str(row.get("Cognateset_ID")).strip()
            if not form_id or not raw_cognate_id:
                continue
            source_membership_id = (
                _safe_str(row.get("ID")).strip() or f"row-{row_number}"
            )
            cognate_rows_by_form[form_id].append(
                {
                    "membership_id": (
                        f"{dataset_id}:cognate-membership:{source_membership_id}"
                    ),
                    "source_membership_id": source_membership_id,
                    "raw_cognate_id": raw_cognate_id,
                    "segment_slice": _values(
                        row.get("Segment_Slice"),
                        split_whitespace=True,
                    ),
                    "alignment": _tokens(row.get("Alignment")),
                    "sources": _values(row.get("Source")),
                    "cognate_detection_method": (
                        _safe_str(row.get("Cognate_Detection_Method")).strip()
                        or None
                    ),
                    "alignment_method": (
                        _safe_str(row.get("Alignment_Method")).strip() or None
                    ),
                    "alignment_source": (
                        _safe_str(row.get("Alignment_Source")).strip() or None
                    ),
                    "doubt": _nullable_bool(row.get("Doubt")),
                    "comment": _safe_str(row.get("Comment")).strip() or None,
                    "source_table": "CognateTable",
                    "source_row": row_number,
                }
            )

    has_segments = _table_has_column(dataset, "FormTable", "Segments")
    has_phonemic_segments = _table_has_column(
        dataset, "FormTable", "Phonemic_Segments"
    )
    if not has_segments and not has_phonemic_segments:
        raise CLDFIngestionError(
            f"{dataset_id!r} exposes neither CLDF Segments nor "
            "Phonemic_Segments. Raw Form orthography is not split automatically; "
            "supply profile-tokenized segments first"
        )

    forms_by_variety: dict[str, list[LexicalForm]] = defaultdict(list)
    for row_number, row in enumerate(dataset["FormTable"], start=2):
        raw_form_id = _safe_str(row.get("ID")).strip()
        source_language_id = _safe_str(row.get("Language_ID")).strip()
        parameter_id = _safe_str(row.get("Parameter_ID")).strip()
        language = languages.get(source_language_id)
        if language is None or not raw_form_id or not parameter_id:
            continue

        segments = _tokens(row.get("Segments")) if has_segments else ()
        segment_source = "Segments"
        if not segments and has_phonemic_segments:
            segments = _tokens(row.get("Phonemic_Segments"))
            segment_source = "Phonemic_Segments"
        if not segments:
            continue

        membership_rows = list(cognate_rows_by_form.get(raw_form_id, ()))
        if has_inline_cognates:
            inline_ids = _values(row.get("Cognateset_ID"))
            for index, raw_cognate_id in enumerate(inline_ids, start=1):
                membership_rows.append(
                    {
                        "membership_id": (
                            f"{dataset_id}:form-membership:{raw_form_id}:{index}"
                        ),
                        "source_membership_id": raw_form_id,
                        "raw_cognate_id": raw_cognate_id,
                        "segment_slice": (),
                        "alignment": (),
                        "sources": _values(row.get("Source")),
                        "cognate_detection_method": None,
                        "alignment_method": None,
                        "alignment_source": None,
                        "doubt": None,
                        "comment": _safe_str(row.get("Comment")).strip() or None,
                        "source_table": "FormTable",
                        "source_row": row_number,
                    }
                )
        if not membership_rows:
            continue

        whole_form_cognate_ids = {
            str(item["raw_cognate_id"])
            for item in membership_rows
            if not item["segment_slice"]
        }
        whole_form_alternatives = len(whole_form_cognate_ids) > 1
        memberships = []
        for item in membership_rows:
            membership_id = str(item["membership_id"])
            raw_slice = tuple(item["segment_slice"])
            if raw_slice:
                scope = CognateMembershipScope.SEGMENT_SLICE
                interpretation = (
                    CognateMembershipInterpretation.PARTIAL_COGNATE
                )
                segment_indices = _segment_indices(
                    raw_slice,
                    segments=segments,
                    slice_unit=cognate_slice_unit,
                    membership_id=membership_id,
                )
            else:
                scope = CognateMembershipScope.WHOLE_FORM
                interpretation = (
                    CognateMembershipInterpretation.ALTERNATIVE_ANALYSIS
                    if whole_form_alternatives
                    else CognateMembershipInterpretation.ASSERTED
                )
                segment_indices = ()
            raw_cognate_id = str(item["raw_cognate_id"])
            memberships.append(
                CognateMembership(
                    membership_id=membership_id,
                    cognate_set_id=f"{dataset_id}:{raw_cognate_id}",
                    scope=scope,
                    interpretation=interpretation,
                    segment_indices=segment_indices,
                    slice_unit=cognate_slice_unit if raw_slice else None,
                    provenance=CognateMembershipProvenance(
                        dataset_id=dataset_id,
                        source_table=item["source_table"],
                        source_row=int(item["source_row"]),
                        source_membership_id=item["source_membership_id"],
                        source_cognateset_id=raw_cognate_id,
                        source_segment_slice=raw_slice,
                        source_slice_unit=(
                            cognate_slice_unit if raw_slice else None
                        ),
                        alignment=tuple(item["alignment"]),
                        sources=tuple(item["sources"]),
                        cognate_detection_method=item[
                            "cognate_detection_method"
                        ],
                        alignment_method=item["alignment_method"],
                        alignment_source=item["alignment_source"],
                        doubt=item["doubt"],
                        comment=item["comment"],
                        source_reference=str(metadata_path),
                        compatibility_rule_ids=(
                            ("lexibank-custom-morpheme-slice",)
                            if raw_slice and cognate_slice_unit == "morpheme"
                            else ()
                        ),
                    ),
                )
            )
        unique_sets = {item.cognate_set_id for item in memberships}
        cognate_set_id = (
            next(iter(unique_sets))
            if len(unique_sets) == 1
            and all(
                item.scope is CognateMembershipScope.WHOLE_FORM
                and item.interpretation
                is CognateMembershipInterpretation.ASSERTED
                for item in memberships
            )
            else None
        )

        parameter = parameters.get(parameter_id)
        concept_id = (
            str(parameter["concept_id"])
            if parameter is not None
            else f"{dataset_id}:{parameter_id}"
        )
        variety_id = str(language["variety_id"])
        forms_by_variety[variety_id].append(
            LexicalForm(
                form_id=f"{dataset_id}:{raw_form_id}",
                variety_id=variety_id,
                concept_id=concept_id,
                segments=segments,
                cognate_set_id=cognate_set_id,
                cognate_memberships=tuple(memberships),
                provenance=FormProvenance(
                    dataset_id=dataset_id,
                    source_form_id=raw_form_id,
                    source_language_id=source_language_id,
                    source_glottocode=language["source_glottocode"],
                    tree_glottocode=language["tree_glottocode"],
                    source_row=row_number,
                    segment_source=segment_source,
                    source_reference=str(metadata_path),
                    compatibility_rule_ids=language[
                        "compatibility_rule_ids"
                    ],
                ),
            )
        )

    lexicons = tuple(
        LanguageLexicon(
            variety_id=str(language["variety_id"]),
            name=str(language["name"]),
            forms=tuple(forms_by_variety[str(language["variety_id"])]),
            dataset_id=dataset_id,
            source_language_id=source_id,
            source_glottocode=language["source_glottocode"],
            tree_glottocode=language["tree_glottocode"],
            compatibility_rule_ids=language["compatibility_rule_ids"],
            family=language["family"],
            is_historical=bool(language["is_historical"]),
        )
        for source_id, language in sorted(languages.items())
        if forms_by_variety.get(str(language["variety_id"]))
    )
    if not lexicons:
        raise CLDFIngestionError(
            f"{dataset_id!r} has no usable tokenized forms with cognate "
            "assignments. The harness uses Segments, then Phonemic_Segments, "
            "and never guesses tokens from raw Form orthography"
        )

    used_concepts = {
        form.concept_id for lexicon in lexicons for form in lexicon.forms
    }
    concepts = tuple(
        ConceptMetadata(
            concept_id=str(parameter["concept_id"]),
            gloss=str(parameter["gloss"]),
            concepticon_id=parameter["concepticon_id"],
        )
        for _, parameter in sorted(parameters.items())
        if str(parameter["concept_id"]) in used_concepts
    )
    return CLDFLoadResult(
        dataset_id=dataset_id,
        metadata_path=str(metadata_path),
        lexicons=lexicons,
        concepts=concepts,
    )
