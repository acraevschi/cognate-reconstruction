"""Initial payload orchestration."""

from __future__ import annotations

from cognate_reconstruction.ingestion.tree_normalization import normalize_tree, to_newick
from cognate_reconstruction.ingestion.tree_induction import induce_tree
from cognate_reconstruction.schemas.ingestion import (
    IngestedDataset,
    TreeArtifact,
    TreeOrigin,
    WorkbenchPayload,
)
from cognate_reconstruction.schemas.historical import HistoricalFormRole
from cognate_reconstruction.tree import (
    assign_node_ids,
    parse_newick,
    validate_unique_leaf_labels,
)


def _validate_historical_bindings(
    payload: WorkbenchPayload,
    normalized_newick: str,
) -> None:
    if not payload.historical_form_bindings:
        return
    root = parse_newick(normalized_newick)
    node_ids = assign_node_ids(root)
    nodes_by_id = {node_id: key for key, node_id in node_ids.items()}
    objects_by_key = {}

    def collect(node) -> None:
        objects_by_key[id(node)] = node
        for child in node.children:
            collect(child)

    collect(root)
    valid_concepts = {
        form.concept_id
        for lexicon in payload.lexicons
        for form in lexicon.forms
    }
    for binding in payload.historical_form_bindings:
        key = nodes_by_id.get(binding.node_id)
        if key is None or objects_by_key[key].is_leaf:
            raise ValueError(
                f"historical target node {binding.node_id!r} is not an "
                "internal node in the normalized supplied tree"
            )
        unknown_concepts = sorted(
            {
                form.concept_id
                for form in binding.forms
                if form.concept_id not in valid_concepts
            }
        )
        if unknown_concepts and binding.role is HistoricalFormRole.ANCHOR:
            raise ValueError(
                f"historical anchors for {binding.node_id!r} contain concepts "
                f"absent from reconstruction evidence: {unknown_concepts}; "
                "targets may retain such forms for explicit missing-coverage "
                "evaluation"
            )
        target = objects_by_key[key]
        direct_branch_by_leaf = {}
        for child in target.children:
            child_id = node_ids[id(child)]
            for leaf_id in child.get_leaf_labels():
                direct_branch_by_leaf[leaf_id] = child_id
        declared_to_runtime: dict[str, str] = {}
        for relation in binding.lineage_relations:
            runtime_branch = direct_branch_by_leaf.get(
                relation.descendant_variety_id
            )
            if runtime_branch is None:
                raise ValueError(
                    f"lineage descendant {relation.descendant_variety_id!r} "
                    f"is not below historical node {binding.node_id!r} in the "
                    "normalized supplied tree"
                )
            previous = declared_to_runtime.setdefault(
                relation.branch_id, runtime_branch
            )
            if previous != runtime_branch:
                raise ValueError(
                    f"lineage branch {relation.branch_id!r} crosses multiple "
                    f"direct children of historical node {binding.node_id!r}"
                )
        if len(set(declared_to_runtime.values())) != len(declared_to_runtime):
            raise ValueError(
                f"distinct curated lineage branches for {binding.node_id!r} "
                "collapse to the same direct child in the supplied tree"
            )


def ingest_payload(payload: WorkbenchPayload) -> IngestedDataset:
    """Validate a supplied tree or induce one when it is absent."""
    usable_lexicons = tuple(lexicon for lexicon in payload.lexicons if lexicon.forms)
    expected = {lexicon.variety_id for lexicon in usable_lexicons}
    if len(expected) < 2:
        raise ValueError("ingestion requires at least two lexicons with usable forms")
    if payload.newick is None:
        tree = induce_tree(usable_lexicons, method=payload.tree_method)
    else:
        root = parse_newick(payload.newick)
        validate_unique_leaf_labels(root)
        actual = root.get_leaf_labels()
        if missing := sorted(expected - actual):
            raise ValueError(
                "tree/lexicon leaf mismatch: the supplied Newick is missing "
                f"dataset-scoped lexicon variety IDs {missing}. Tree leaves "
                "must use exact lexicon.variety_id values; extra leaves may be "
                "present and will be pruned"
            )
        normalized = normalize_tree(root, expected)
        tree = TreeArtifact(
            newick=to_newick(normalized),
            origin=TreeOrigin.PROVIDED,
            leaf_variety_ids=tuple(sorted(expected)),
        )
    _validate_historical_bindings(payload, tree.newick)
    return IngestedDataset(
        lexicons=usable_lexicons,
        tree=tree,
        concepts=payload.concepts,
        historical_form_bindings=payload.historical_form_bindings,
    )
