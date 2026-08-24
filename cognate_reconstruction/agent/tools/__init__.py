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
            name="polarize",
            description=(
                "Ask what the rest of the tree shows where the active children "
                "disagree. Give it one correspondence — the children and the "
                "segment each shows, a row of summarize_correspondences pasted "
                "back — and it returns, for every node outside the active "
                "children, what that node shows in the same aligned columns, "
                "how often, and whether it is observed or reconstructed. Call "
                "it before committing any rule whose direction the children "
                "alone do not force. It reports a distribution and never says "
                "which value is original: that judgement is yours and belongs "
                "in the committed rule's directionality_rationale. Count "
                "support per clade rather than per daughter, and read presence "
                "as evidence and absence as nothing; the result fields say how. "
                "A reconstructed node is a prior hypothesis, not attestation, "
                "and carries no independent evidential weight. The argument is "
                "only as good as the supplied classification and is circular if "
                "that tree was induced from the same distance data. Only an "
                "'outgroup' entry can polarize anything; a 'descendant' lies "
                "inside this node's subtree and shows what these children "
                "became. At the root every entry is a descendant, because "
                "nothing lies outside the root."
            ),
            args_model=PolarizeArgs,
            handler=polarize,
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
                "the test, so a rule here carries no validation_call_id. The "
                "result also reports, per concept, whether the children now "
                "agree on one parent form, and lists those that do not."
            ),
            args_model=TestRuleCascadeArgs,
            handler=test_rule_cascade,
        )
    )
    registry.register(
        ToolSpec(
            name="test_proto_assembly",
            description=(
                "Assemble this node's parent forms from a proposed inventory: "
                "a proto-phoneme for each correspondence set, plus the policy "
                "for columns no set explains. Returns the assembled form per "
                "concept, how many columns went unaccounted, which columns two "
                "of your sets both matched, and the per-branch rules the "
                "inventory implies. This is the call a commit is checked "
                "against and the call to refine against: read the unaccounted "
                "columns, condition a set, split one, change a value, and run "
                "it again. Coverage is over sets rather than concepts, so "
                "batching a large family across several calls is fine — their "
                "coverage unions. detail='summary' (the default) omits the "
                "per-column resolutions; ask for 'full' when a form came out "
                "wrong and you need to see which column did it. Every "
                "commitment needs the set_id, the reflexes and the support "
                "count copied back from the survey exactly — support is the "
                "harness's own count and is re-derived — plus your own "
                "confidence. Write a gap as null, 'Ø' or '∅'."
            ),
            args_model=TestProtoAssemblyArgs,
            handler=test_proto_assembly,
        )
    )
    registry.register(
        ToolSpec(
            name="realign",
            description=(
                "Re-lay the aligner's columns for one or more concepts, and "
                "return an alignment_overlay_id to cite in later calls. For the "
                "case where the aligner has misaligned a form — a compound "
                "against a simplex, two lexemes in one concept — and not a "
                "routine step; the default is to accept the aligner's output. "
                "Dropping the nulls from each row must reproduce that child's "
                "own form: you may move material between columns, never invent, "
                "delete, or reorder a segment. Say which correspondence set the "
                "moved column joins in joins_set_id and the harness verifies "
                "that the set really gains that support, refusing the call if "
                "it does not; use null for the first attestation of a "
                "correspondence, which is counted separately. A realignment "
                "invalidates every set_id derived under the previous alignment."
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
                "Commit this node's hypothesis, as either an 'inventory' or a "
                "'rules' cascade — never both. An inventory gives each "
                "correspondence set a proto-phoneme and states what happens to "
                "columns no set explains; every committed set must have been "
                "exercised by a same-session test_proto_assembly, its support "
                "must match the harness's own count, and a set that deletes or "
                "merges a distinction needs a directionality_rationale. A rules "
                "cascade commits ordered individually validated rules: each "
                "needs a successful same-session test_sound_law validation, "
                "given as the per-rule validation_call_id or resolved by the "
                "harness from the identical DSL and child scope, and "
                "cascade_validation_call_id may name a test_rule_cascade "
                "preview of the whole order. Either shape may be empty for an "
                "identity reconstruction. A successful commit reports what the "
                "hypothesis actually produced; an unexplained residue is "
                "recorded, never rejected."
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
    "polarize",
    "realign",
    "summarize_commit",
    "summarize_inventory",
    "summarize_correspondences",
    "test_proto_assembly",
]
