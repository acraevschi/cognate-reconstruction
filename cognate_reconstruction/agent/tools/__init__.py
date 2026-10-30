"""Default deterministic tool registry."""

from cognate_reconstruction.agent.schemas import (
    CommitReconstructionArgs,
    GetAlignmentsArgs,
    GetNodeReconstructionArgs,
    ListAvailableNodesArgs,
    ListConceptsArgs,
    PolarizeArgs,
    RealignArgs,
    SearchFormsArgs,
    SegmentMorphemesArgs,
    SummarizeCorrespondencesArgs,
    TestProtoAssemblyArgs,
    TestRuleCascadeArgs,
    TestSoundLawArgs,
)
from cognate_reconstruction.agent.tools.commit_reconstruction import (
    commit_reconstruction,
    describe_session_validations,
)
from cognate_reconstruction.agent.tools.correspondences import (
    summarize_correspondences,
)
from cognate_reconstruction.agent.tools.errors import ToolInputError
from cognate_reconstruction.agent.tools.get_alignments import get_alignments
from cognate_reconstruction.agent.tools.get_node_reconstruction import (
    get_node_reconstruction,
    summarize_commit,
    summarize_inventory,
)
from cognate_reconstruction.agent.tools.evidence import (
    list_available_nodes,
    list_concepts,
    search_forms,
)
from cognate_reconstruction.agent.tools.polarize import polarize
from cognate_reconstruction.agent.tools.proto_assembly import test_proto_assembly
from cognate_reconstruction.agent.tools.realign import realign
from cognate_reconstruction.agent.tools.registry import ToolRegistry, ToolSpec
from cognate_reconstruction.agent.tools.segment_morphemes import segment_morphemes
from cognate_reconstruction.agent.tools.test_sound_law import test_sound_law
from cognate_reconstruction.agent.tools.test_rule_cascade import test_rule_cascade


def default_tool_registry(*, inventory_protocol: str = "stored-hypothesis") -> ToolRegistry:
    if inventory_protocol not in {"full-payload", "stored-hypothesis"}:
        raise ValueError("unknown inventory protocol")
    from cognate_reconstruction.agent.tools.stored_hypothesis import (
        StoredAssemblyArgs, StoredCommitArgs, test_stored_assembly, commit_stored_hypothesis,
        describe_inventory_input,
    )
    stored = inventory_protocol == "stored-hypothesis"
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="summarize_correspondences",
            description=(
                'Survey descriptive recurrence (csp-*), or exact local sets (csu-*). Start here; inspect filters/pagination. support counts supplied etyma plus unresolved units; alternatives/source columns are separate. min_support=2 is a filter, not a sparse-value prohibition; use 1 to inspect singleton material. shared_claims must explicitly select local pattern members.'
            ),
            args_model=SummarizeCorrespondencesArgs,
            handler=summarize_correspondences,
        )
    )
    registry.register(
        ToolSpec(
            name="get_alignments",
            description=(
                'Inspect unit alignments and source positions for at most 24 concepts or 48 forms. Summary gives counts and column pointers; full adds contexts and occurrences. Select concepts from the survey or a specific evidence question.'
            ),
            args_model=GetAlignmentsArgs,
            handler=get_alignments,
        )
    )
    registry.register(
        ToolSpec(
            name="list_concepts",
            description="List searchable concept metadata and form counts.",
            args_model=ListConceptsArgs,
            handler=list_concepts,
        )
    )
    registry.register(
        ToolSpec(
            name="search_forms",
            description=(
                "Search active or available-tree forms by semantics, segments, "
                "position, node, or cognate set."
            ),
            args_model=SearchFormsArgs,
            handler=search_forms,
        )
    )
    registry.register(
        ToolSpec(
            name="polarize",
            description=(
                'Describe witnesses for one scoped correspondence using set_id, overlays and unit_orders; tuple/pattern queries are recurrence summaries. It does not choose historical polarity. Read relation, observed/reconstructed status, full counts and truncation. Descendants are inside the subtree; the root has no outgroup. Missing witnesses or gaps do not establish innovation. Prior reconstructed nodes are hypotheses, not independent attestation.'
            ),
            args_model=PolarizeArgs,
            handler=polarize,
        )
    )
    registry.register(
        ToolSpec(
            name="list_available_nodes",
            description=(
                'List observed and completed reconstructed nodes, their relations and retrievable hypotheses.'
            ),
            args_model=ListAvailableNodesArgs,
            handler=list_available_nodes,
        )
    )
    registry.register(
        ToolSpec(
            name="get_node_reconstruction",
            description=(
                "Retrieve one completed node's inventory or rules. This is a previous hypothesis, not independent attestation; use it to inspect consistency, not add support."
            ),
            args_model=GetNodeReconstructionArgs,
            handler=get_node_reconstruction,
        )
    )
    registry.register(
        ToolSpec(
            name="test_sound_law",
            description=(
                'Parse and execute one literal child-to-parent rule. Replacement tokens/sequences may be new. Empty targets and identity rules are refused; commit rules=[] for identity. Execution does not establish historical truth.'
            ),
            args_model=TestSoundLawArgs,
            handler=test_sound_law,
        )
    )
    registry.register(
        ToolSpec(
            name="test_rule_cascade",
            description=(
                'Preview at least one ordered, branch-scoped child-to-parent rule, intermediate effects and final forms. Each rule takes DSL and active source_child_ids; no validation_call_id belongs in this test. Its rules also count as individual validations. Empty rules are committed directly for identity.'
            ),
            args_model=TestRuleCascadeArgs,
            handler=test_rule_cascade,
        )
    )
    registry.register(
        ToolSpec(
            name="test_proto_assembly",
            description=(
                ('Execute the exact inventory and report forms, unit/column traces, residue and commit readiness. Executable is distinct from commit_ready: supply missing rationales/directionality in a new preview. Changed decisions, member selections, policy, orders, overlays or evidence need exact revalidation; identical evidence reinspection is safe. Full commitments copy reflexes/support exactly; explicit null/value and confidence are always required. Shared claims select pattern members explicitly.' + (" The choices field resolves local reflexes/support from IDs. A returned hypothesis_id freezes the preview for commit without retranscription." if stored else ""))          ),
            args_model=StoredAssemblyArgs if stored else TestProtoAssemblyArgs,
            handler=test_stored_assembly if stored else test_proto_assembly,
            remediation=describe_inventory_input if stored else None,
        )
    )
    registry.register(
        ToolSpec(
            name="realign",
            description=(
                "Repair a specific unit alignment while preserving each selected child's tokens in order. Partial evidence requires unit_id; ambiguous readings need analysis_ids. joins_set_id verifies source-column gain, reported separately from independent-support gain; null permits first attestation. Use the resulting overlay consistently, re-survey for new IDs and preview again."
            ),
            args_model=RealignArgs,
            handler=realign,
        )
    )
    registry.register(
        ToolSpec(
            name="segment_morphemes",
            description="Create a temporary boundary-only segmentation overlay.",
            args_model=SegmentMorphemesArgs,
            handler=segment_morphemes,
        )
    )
    registry.register(
        ToolSpec(
            name="commit_reconstruction",
            description=(
                ('Commit the exact inspected hypothesis with node_id, summary and anomalies. Both inventory and ordered rules are supported. Nonempty choices require same-session validation; multi-choice reasoning and mechanically detected loss/merger explanations are required. Unexplained residue is reported, not rejected. Full inventory/rule payloads remain supported; never submit both shapes.' + (" A commit_ready hypothesis_id commits its immutable inventory without payload or overlays; edits need a new preview." if stored else ""))
            ),
            args_model=StoredCommitArgs if stored else CommitReconstructionArgs,
            handler=commit_stored_hypothesis if stored else commit_reconstruction,
            remediation=describe_session_validations,
        )
    )
    return registry


__all__ = [
    "ToolInputError",
    "ToolRegistry",
    "ToolSpec",
    "default_tool_registry",
    "describe_session_validations",
    "polarize",
    "realign",
    "summarize_commit",
    "summarize_inventory",
    "summarize_correspondences",
    "test_proto_assembly",
]
