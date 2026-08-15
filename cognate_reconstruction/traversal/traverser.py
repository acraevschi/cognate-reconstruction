"""Bottom-up state manager for normalized native n-ary Newick trees."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from cognate_reconstruction.schemas.ingestion import IngestedDataset
from cognate_reconstruction.schemas.lexicon import LexicalForm
from cognate_reconstruction.schemas.rules import (
    AnomalyReport,
    ParsedSoundRule,
    ReconstructionRule,
)
from cognate_reconstruction.schemas.traversal import TraversalSnapshot
from cognate_reconstruction.schemas.traversal import (
    EvidenceKind,
    EvidenceRelation,
    NodeEvidence,
    NodeReconstructionContext,
)
from cognate_reconstruction.tree import (
    TreeNode,
    assign_node_ids,
    parse_newick,
    postorder_groups,
)
from cognate_reconstruction.traversal.beam import beam_to_lexicon, make_leaf_beam
from cognate_reconstruction.traversal.protocol import NodeReconstructor
from cognate_reconstruction.traversal.reconstructor import RuleBasedReconstructor
class TreeTraverser:
    def __init__(
        self,
        *,
        beam_width: int = 5,
        reconstructor: NodeReconstructor | None = None,
    ) -> None:
        self.beam_width = beam_width
        self.reconstructor = reconstructor or RuleBasedReconstructor(beam_width=beam_width)

    def traverse(
        self,
        dataset: IngestedDataset,
        *,
        rules_by_node: Mapping[
            str, Sequence[ReconstructionRule | ParsedSoundRule]
        ] | None = None,
        anomalies_by_node: Mapping[str, Sequence[AnomalyReport]] | None = None,
        anchors_by_node: Mapping[str, Sequence[LexicalForm]] | None = None,
        resume_steps: Mapping[str, ReconstructionStep] | None = None,
        on_step_complete: Callable[[ReconstructionStep], None] | None = None,
    ) -> TraversalSnapshot:
        root = parse_newick(dataset.tree.newick)
        node_ids = assign_node_ids(root)
        lexicons = {lexicon.variety_id: lexicon for lexicon in dataset.lexicons}
        beams = {}
        observed_evidence: dict[str, tuple[LanguageLexicon, tuple[str, ...]]] = {}
        for leaf in root.get_leaves():
            if leaf.label is None or leaf.label not in lexicons:
                raise ValueError(f"no lexicon for tree leaf {leaf.label!r}")
            beams[id(leaf)] = make_leaf_beam(
                lexicons[leaf.label], beam_width=self.beam_width
            )
            observed_evidence[leaf.label] = (lexicons[leaf.label], (leaf.label,))

        steps = []
        completed = []
        node_rules = rules_by_node or {}
        node_anomalies = anomalies_by_node or {}
        node_anchors = anchors_by_node or {}
        resumed = resume_steps or {}
        valid_internal_ids = {
            node_ids[id(parent)] for _, parent in postorder_groups(root)
        }
        if unknown := sorted(set(resumed) - valid_internal_ids):
            raise ValueError(f"checkpoint contains unknown internal node IDs: {unknown}")
        reconstructed_evidence: dict[str, tuple[LanguageLexicon, tuple[str, ...]]] = {}
        for children, parent in postorder_groups(root):
            parent_id = node_ids[id(parent)]
            active_child_ids = tuple(node_ids[id(child)] for child in children)
            parent_leaf_ids = tuple(sorted(parent.get_leaf_labels()))
            available_nodes = []
            for kind, evidence_items in (
                (EvidenceKind.OBSERVED, observed_evidence),
                (EvidenceKind.RECONSTRUCTED, reconstructed_evidence),
            ):
                for node_id, (lexicon, descendant_ids) in sorted(evidence_items.items()):
                    if node_id in active_child_ids:
                        relation = EvidenceRelation.ACTIVE_CHILD
                    elif set(descendant_ids) <= set(parent_leaf_ids):
                        relation = EvidenceRelation.DESCENDANT
                    else:
                        relation = EvidenceRelation.OUTGROUP
                    available_nodes.append(
                        NodeEvidence(
                            node_id=node_id,
                            kind=kind,
                            relation=relation,
                            lexicon=lexicon,
                            descendant_leaf_ids=descendant_ids,
                        )
                    )
            evidence_context = NodeReconstructionContext(
                parent_node_id=parent_id,
                active_child_ids=active_child_ids,
                available_nodes=tuple(available_nodes),
                concepts=dataset.concepts,
            )
            child_beams = tuple(beams[id(child)] for child in children)
            if parent_id in resumed:
                step = resumed[parent_id]
                if step.parent_node_id != parent_id:
                    raise ValueError(
                        f"checkpoint step {step.parent_node_id!r} is stored "
                        f"under node {parent_id!r}"
                    )
                if step.child_node_ids != active_child_ids:
                    raise ValueError(
                        f"checkpoint children for {parent_id!r} do not match "
                        "the normalized classification tree"
                    )
                if tuple(beam.node_id for beam in step.input_beams) != tuple(
                    beam.node_id for beam in child_beams
                ):
                    raise ValueError(
                        f"checkpoint inputs for {parent_id!r} are inconsistent "
                        "with completed child nodes"
                    )
            else:
                step = self.reconstructor.reconstruct(
                    parent_id,
                    child_beams,
                    rules=node_rules.get(parent_id, ()),
                    anomalies=node_anomalies.get(parent_id, ()),
                    anchors=node_anchors.get(parent_id, ()),
                    evidence_context=evidence_context,
                )
                if on_step_complete is not None:
                    on_step_complete(step)
            beams[id(parent)] = step.output_beam
            reconstructed_evidence[parent_id] = (
                beam_to_lexicon(step.output_beam),
                parent_leaf_ids,
            )
            steps.append(step)
            completed.append(parent_id)
        return TraversalSnapshot(
            root_node_id=node_ids[id(root)],
            completed_node_ids=tuple(completed),
            node_beams=tuple(beams[key] for key in sorted(beams, key=lambda key: node_ids[key])),
            steps=tuple(steps),
        )
