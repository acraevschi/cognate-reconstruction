"""Assemble one runnable payload from a loaded CLDF dataset.

Extracted from `cli.prepare-lexibank` when `build-benchmark` needed the same
work. Two commands selecting varieties, filtering concepts, removing bound
historical sources, and validating the tree in two places is two chances to
remove the source variety from one of them and not the other — which is the
single defect that would turn a benchmark into a lookup.
"""

from __future__ import annotations

from collections.abc import Sequence

from cognate_reconstruction.ingestion.historical import (
    materialize_historical_bindings,
)
from cognate_reconstruction.ingestion.service import ingest_payload
from cognate_reconstruction.schemas.historical import (
    HistoricalBindingFile,
    HistoricalFormBinding,
    HistoricalFormRole,
)
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.schemas.lexicon import LanguageLexicon


def prepare_payload(
    dataset,
    *,
    variety_ids: Sequence[str] | None = None,
    concept_ids: Sequence[str] | None = None,
    binding_requests: HistoricalBindingFile | None = None,
    newick: str | None = None,
    tree_method: str = "neighbor",
) -> WorkbenchPayload:
    """Select varieties and concepts, bind historical forms, normalize the tree.

    `dataset` is a `CLDFLoadResult`. Bound historical source varieties are
    removed from `lexicons` unconditionally: a `target` variety left in the
    evidence would let the model read the answer, and an `anchor` variety left
    in as a leaf would be reconstructed as its own ancestor.
    """
    historical_bindings: tuple[HistoricalFormBinding, ...] = (
        materialize_historical_bindings(binding_requests, dataset.lexicons)
        if binding_requests is not None
        else ()
    )
    bound_source_ids = {
        binding.source_variety_id for binding in historical_bindings
    }
    lexicons: tuple[LanguageLexicon, ...] = dataset.lexicons
    if variety_ids:
        selected = set(variety_ids)
        available = {lexicon.variety_id for lexicon in lexicons}
        if unknown := sorted(selected - available):
            raise ValueError(
                f"unknown dataset-scoped variety IDs: {unknown}. Use "
                "`list-lexibank-varieties --dataset ...` and include the "
                f"{dataset.dataset_id!r} dataset prefix"
            )
        lexicons = tuple(
            lexicon for lexicon in lexicons if lexicon.variety_id in selected
        )
    lexicons = tuple(
        lexicon
        for lexicon in lexicons
        if lexicon.variety_id not in bound_source_ids
    )
    concepts = dataset.concepts
    if concept_ids:
        selected_concepts = set(concept_ids)
        available_concepts = {
            form.concept_id
            for lexicon in dataset.lexicons
            for form in lexicon.forms
        }
        if unknown := sorted(selected_concepts - available_concepts):
            raise ValueError(
                f"unknown concept IDs: {unknown}. Concept IDs are the exact "
                "Concepticon IDs or dataset-scoped fallback IDs shown in the "
                "prepared evidence"
            )
        lexicons = tuple(
            lexicon.model_copy(
                update={
                    "forms": tuple(
                        form
                        for form in lexicon.forms
                        if form.concept_id in selected_concepts
                    )
                }
            )
            for lexicon in lexicons
        )
        empty_varieties = sorted(
            lexicon.variety_id for lexicon in lexicons if not lexicon.forms
        )
        if empty_varieties:
            raise ValueError(
                "selected concepts leave no tokenized cognate evidence for "
                f"varieties: {empty_varieties}"
            )
        concepts = tuple(
            concept
            for concept in concepts
            if concept.concept_id in selected_concepts
        )
        filtered_bindings = []
        for binding in historical_bindings:
            forms = tuple(
                form
                for form in binding.forms
                if form.concept_id in selected_concepts
            )
            if not forms:
                raise ValueError(
                    f"selected concepts leave historical {binding.role.value} "
                    f"binding {binding.source_variety_id!r} without forms"
                )
            filtered_bindings.append(
                binding.model_copy(update={"forms": forms})
            )
        historical_bindings = tuple(filtered_bindings)
    if len(lexicons) < 2:
        raise ValueError(
            "preparation requires at least two selected varieties with "
            "tokenized cognate forms"
        )
    if historical_bindings and newick is None:
        raise ValueError(
            "historical target/anchor roles require a supplied Newick with "
            "exact internal node IDs; lineage metadata never induces "
            "traversal order"
        )
    payload = WorkbenchPayload(
        lexicons=lexicons,
        concepts=concepts,
        newick=newick,
        historical_form_bindings=historical_bindings,
        tree_method=tree_method,
    )
    if newick is not None:
        ingested = ingest_payload(payload)
        payload = payload.model_copy(update={"newick": ingested.tree.newick})
    assert_targets_are_hidden(payload)
    return payload


def assert_targets_are_hidden(payload: WorkbenchPayload) -> None:
    """Refuse a payload whose gold variety is still readable as evidence.

    The one failure that silently turns a benchmark into a lookup table: if the
    variety supplying the answer key is still a lexicon, the model can search
    it, and every number the run produces is meaningless. Checked here rather
    than trusted to the caller, and checked for *every* binding rather than the
    first, because a second target added to an existing definition is exactly
    when this gets forgotten.
    """
    present = {lexicon.variety_id for lexicon in payload.lexicons}
    leaked = sorted(
        binding.source_variety_id
        for binding in payload.historical_form_bindings
        if binding.role is HistoricalFormRole.TARGET
        and binding.source_variety_id in present
    )
    if leaked:
        raise ValueError(
            "held-out target source varieties are still present in the "
            f"lexicons and would be visible to the model: {leaked}"
        )
    node_targets = {
        binding.node_id
        for binding in payload.historical_form_bindings
        if binding.role is HistoricalFormRole.TARGET
    }
    if bound_leaves := sorted(node_targets & present):
        raise ValueError(
            "target node IDs collide with lexicon variety IDs, so the gold "
            f"node is also an observed leaf: {bound_leaves}"
        )
