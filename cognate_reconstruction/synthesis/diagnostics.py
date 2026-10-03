"""Compact diagnostic suite built with the existing forward generator.

Definitions and identifiability notes are operator-side. Only generated observed
lexicons, observed cognacy annotations and the tree become model evidence.
"""
from __future__ import annotations

import json
from pathlib import Path

from cognate_reconstruction.evaluation.diagnostics import pieces
from cognate_reconstruction.schemas.historical import TargetValidity
from cognate_reconstruction.schemas.lexicon import (
    CognateMembership, CognateMembershipInterpretation, CognateMembershipScope,
    CognateMembershipProvenance,
)
from cognate_reconstruction.schemas.synthetic import SyntheticFamilyDefinition
from cognate_reconstruction.synthesis.generator import generate_family, SyntheticBuildResult


def load_suite(path: str | Path) -> dict:
    suite = json.loads(Path(path).read_text())
    if suite["suite_version"] != "task02-v1":
        raise ValueError("unsupported diagnostic suite version")
    return suite


def build_case(case: dict) -> SyntheticBuildResult:
    definition = SyntheticFamilyDefinition.model_validate_json(json.dumps(case["family"]))
    built = generate_family(definition)
    payload = built.payload
    if "observed_unit_layouts" in case:
        lexicons = []
        for lexicon in payload.lexicons:
            forms = []
            for form in lexicon.forms:
                observed_pieces = case["observed_piece_forms"][lexicon.variety_id][form.concept_id]
                tokens = tuple(t for i, piece in enumerate(observed_pieces)
                               for t in (("+",) if i else ()) + tuple(piece))
                form = form.model_copy(update={"segments": tokens})
                layout = case["observed_unit_layouts"][lexicon.variety_id][form.concept_id]
                if len(layout) != len(pieces(form.segments)):
                    raise ValueError("observed unit layout does not match generated boundaries")
                indices = [[]]
                for index, token in enumerate(form.segments):
                    if token in {"+", "-"}:
                        indices.append([])
                    else:
                        indices[-1].append(index)
                memberships = tuple(CognateMembership(
                    membership_id=f"{form.form_id}:{i}", cognate_set_id=unit_id,
                    scope=CognateMembershipScope.SEGMENT_SLICE,
                    interpretation=CognateMembershipInterpretation.PARTIAL_COGNATE,
                    segment_indices=tuple(ix), slice_unit="morpheme",
                    provenance=CognateMembershipProvenance(
                        source_table="CognateTable", source_row=i+1,
                        source_cognateset_id=unit_id,
                        source_reference="declared observed diagnostic cognacy; not inferred from gold",
                    ),
                ) for i, (unit_id, ix) in enumerate(zip(layout, indices, strict=True)))
                forms.append(form.model_copy(update={"cognate_set_id": None,
                                                      "cognate_memberships": memberships}))
            lexicons.append(lexicon.model_copy(update={"forms": tuple(forms)}))
        payload = payload.model_copy(update={"lexicons": tuple(lexicons)})
    validity = (TargetValidity.UNDERDETERMINED if case["identifiability"] == "underdetermined"
                else TargetValidity.VALIDATED)
    bindings = tuple(b.model_copy(update={
        "target_validity": validity,
        "target_validity_note": case["independent_evidence"] + " " + case["equivalent_solutions"],
    }) for b in payload.historical_form_bindings)
    key = built.answer_key
    if "observed_unit_layouts" in case:
        observed_by_id = {l.variety_id: l for l in payload.lexicons}
        key = key.model_copy(update={
            "node_lexicons": tuple(observed_by_id.get(l.variety_id, l) for l in key.node_lexicons),
            "branches": tuple(b.model_copy(update={"innovated": True, "invertible": False})
                              if b.node_id in observed_by_id else b for b in key.branches),
        })
    return SyntheticBuildResult(payload=payload.model_copy(update={"historical_form_bindings": bindings}),
                                answer_key=key)
