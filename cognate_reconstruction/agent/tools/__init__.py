"""Default deterministic tool registry."""

from cognate_reconstruction.agent.schemas import (
    CommitReconstructionArgs,
    GetAlignmentsArgs,
    GetNodeReconstructionArgs,
    ListAvailableNodesArgs,
    ListConceptsArgs,
    SearchFormsArgs,
    SegmentMorphemesArgs,
    SummarizeCorrespondencesArgs,
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
)
from cognate_reconstruction.agent.tools.evidence import (
    list_available_nodes,
    list_concepts,
    search_forms,
)
from cognate_reconstruction.agent.tools.registry import ToolRegistry, ToolSpec
from cognate_reconstruction.agent.tools.segment_morphemes import segment_morphemes
from cognate_reconstruction.agent.tools.test_sound_law import test_sound_law
from cognate_reconstruction.agent.tools.test_rule_cascade import test_rule_cascade


def default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="summarize_correspondences",
            description=(
                "Survey every recurring segment correspondence across the whole "
                "evidence set at once: the n-tuple of aligned segments over the "
                "selected nodes, its support count, and example concepts, "
                "ordered by support. Start here. Filter with min_support "
                "(default 2, because a correspondence attested once is residue) "
                "or with segment/segment_node_id to ask which sets show one "
                "segment in one node, then pull get_alignments for the concepts "
                "a set names."
            ),
            args_model=SummarizeCorrespondencesArgs,
            handler=summarize_correspondences,
        )
    )
    registry.register(
        ToolSpec(
            name="get_alignments",
            description=(
                "Align forms from any two or more available nodes and return an "
                "n-way MSA plus derived pairwise correspondences. For specific "
                "cognate sets, after summarize_correspondences has shown which "
                "are worth looking at: this call needs an explicit selection of "
                "at most 24 concept_ids or 48 form_ids, and never shows "
                "recurrence across the whole evidence set. detail='summary' "
                "(the default) returns correspondence counts with example "
                "column references; detail='full' adds every column occurrence "
                "with its contexts and is orders of magnitude larger."
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
            name="list_available_nodes",
            description=(
                "List observed and already reconstructed evidence nodes. "
                "has_committed_hypothesis marks nodes whose committed rules "
                "get_node_reconstruction can retrieve."
            ),
            args_model=ListAvailableNodesArgs,
            handler=list_available_nodes,
        )
    )
    registry.register(
        ToolSpec(
            name="get_node_reconstruction",
            description=(
                "Return the rules, anomalies, and summary committed at one "
                "node already reconstructed in this run. This is a previous "
                "hypothesis, not attestation and not evidence: it does not "
                "affect scoring and must not be cited as support. Use it to "
                "check whether a correspondence you are proposing agrees with "
                "one already claimed below this node."
            ),
            args_model=GetNodeReconstructionArgs,
            handler=get_node_reconstruction,
        )
    )
    registry.register(
        ToolSpec(
            name="test_sound_law",
            description=(
                "Parse and apply one child-to-parent DSL rule, returning exact "
                "diffs. A rule must change its target; use an empty committed "
                "rule set for identity reconstruction."
            ),
            args_model=TestSoundLawArgs,
            handler=test_sound_law,
        )
    )
    registry.register(
        ToolSpec(
            name="test_rule_cascade",
            description=(
                "Preview a complete ordered, branch-scoped sound-law cascade "
                "and return every intermediate diff plus final forms. No-op "
                "rules are invalid; an empty cascade represents identity. Each "
                "rule takes only dsl and source_child_ids: this call is itself "
                "the test, so a rule here carries no validation_call_id."
            ),
            args_model=TestRuleCascadeArgs,
            handler=test_rule_cascade,
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
                "Commit ordered individually validated rules and anomalies. "
                "Rules must change their targets; use rules=[] for identity. "
                "Each rule needs a successful same-session test_sound_law "
                "validation: give its ID as the per-rule validation_call_id, "
                "or omit that field and the harness resolves the unique "
                "validation with the identical DSL and child scope. "
                "supporting_form_ids defaults to that validation's forms. "
                "Set cascade_validation_call_id only to an ID returned by "
                "test_rule_cascade; omit it if no cascade preview was run."
            ),
            args_model=CommitReconstructionArgs,
            handler=commit_reconstruction,
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
    "summarize_commit",
    "summarize_correspondences",
]
