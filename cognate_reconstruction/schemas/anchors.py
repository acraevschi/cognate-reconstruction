"""Strict, provenance-bearing historical anchor input."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from cognate_reconstruction.schemas.common import NonEmptyStr, WorkbenchModel
from cognate_reconstruction.schemas.ingestion import IngestedDataset
from cognate_reconstruction.schemas.lexicon import LexicalForm
from cognate_reconstruction.tree import internal_node_ids, parse_newick


class AnchorFile(WorkbenchModel):
    """Tokenized anchor forms keyed by an exact reconstruction-node ID."""

    schema_version: Literal["1.0"] = "1.0"
    anchors: dict[NonEmptyStr, tuple[LexicalForm, ...]] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_local_identity_and_provenance(self) -> AnchorFile:
        form_ids: set[str] = set()
        for node_id, forms in self.anchors.items():
            if not forms:
                raise ValueError(f"anchor node {node_id!r} has no forms")
            for form in forms:
                if form.variety_id != node_id:
                    raise ValueError(
                        f"anchor form {form.form_id!r} has variety_id "
                        f"{form.variety_id!r}, expected target node {node_id!r}"
                    )
                if form.form_id in form_ids:
                    raise ValueError(
                        f"anchor form_id {form.form_id!r} is not globally unique"
                    )
                form_ids.add(form.form_id)
                provenance = form.provenance
                if not (
                    provenance.source_reference
                    or provenance.dataset_id
                    or provenance.source_form_id
                ):
                    raise ValueError(
                        f"anchor form {form.form_id!r} needs source provenance"
                    )
        return self

    def validate_for_dataset(
        self,
        dataset: IngestedDataset,
    ) -> dict[str, tuple[LexicalForm, ...]]:
        """Resolve target nodes and concepts without inferring either."""
        valid_nodes = set(internal_node_ids(parse_newick(dataset.tree.newick)))
        unknown_nodes = sorted(set(self.anchors) - valid_nodes)
        if unknown_nodes:
            raise ValueError(
                "anchor target IDs are not internal nodes in the normalized "
                f"classification tree: {unknown_nodes}; valid IDs: "
                f"{sorted(valid_nodes)}"
            )
        valid_concepts = {
            form.concept_id
            for lexicon in dataset.lexicons
            for form in lexicon.forms
        }
        unknown_concepts = sorted(
            {
                form.concept_id
                for forms in self.anchors.values()
                for form in forms
                if form.concept_id not in valid_concepts
            }
        )
        if unknown_concepts:
            raise ValueError(
                "anchor concepts are absent from the ingested lexical evidence: "
                f"{unknown_concepts}"
            )
        return {node_id: tuple(forms) for node_id, forms in self.anchors.items()}
