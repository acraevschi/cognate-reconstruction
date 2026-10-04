"""The `high_quality` gate must *see* an inventory session, not wave it through.

`high_quality` is this repository's only gate: `export-trajectories
--high-quality-only` selects a corpus with it. Three of its failure conditions
are keyed to rule-shaped counters, and a session that called
`test_proto_assembly` instead of `test_sound_law` has both of those counters at
zero. Widen `committed_reconstruction` to the union and leave the conditions
alone, and every inventory session passes all three unconditionally: the gate
becomes strictly more permissive, the suite stays green because nothing crashed,
and the corpora selected under the loosened gate cannot be un-selected.

So these tests do two things. They pin that equivalent workflow behaviour earns
the same verdict under either protocol, and they pin that a deficient inventory
session is genuinely caught rather than silently passed. Without the second,
nothing in the suite can tell "the gate passed this session" from "the gate could
not see this session".
"""

from __future__ import annotations

from datetime import UTC, datetime

from cognate_reconstruction.agent.schemas import (
    CommitReconstructionArgs,
    CommittedReconstruction,
    CommittedSoundRule,
    LLMMessage,
    LLMToolDefinition,
    MessageRole,
    NodeLexiconSummary,
    NodePromptPayload,
)
from cognate_reconstruction.agent.trajectory import (
    INVENTORY_SCHEMA_VERSION,
    AgentNodeMetrics,
    AgentTrajectory,
)
from cognate_reconstruction.rules.parser import parse_rule
from cognate_reconstruction.schemas.beam import (
    CandidateDerivation,
    ConceptCandidateDistribution,
    NodeBeamState,
    ReconstructionCandidate,
)
from cognate_reconstruction.schemas.inventory import (
    CommitProtoInventoryArgs,
    CommittedProtoInventory,
    CorrespondenceCommitment,
    ResiduePolicy,
    derive_set_id,
)
from cognate_reconstruction.schemas.rules import ReconstructionRule
from cognate_reconstruction.schemas.traversal import (
    ReconstructionDiagnostics,
    ReconstructionStep,
)

CHILDREN = ("A", "B")


def _beam(node_id: str, segments: tuple[str, ...]) -> NodeBeamState:
    return NodeBeamState(
        node_id=node_id,
        beam_width=5,
        distributions=(
            ConceptCandidateDistribution(
                concept_id="water",
                candidates=(
                    ReconstructionCandidate(
                        candidate_id=f"{node_id}:water",
                        segments=segments,
                        probability=1.0,
                        log_score=0.0,
                        derivations=(
                            CandidateDerivation(
                                derivation_id=f"observed:{node_id}",
                                child_candidate_ids=(),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )


def _step(**diagnostics) -> ReconstructionStep:
    base = {
        "rule_count": 0,
        "rule_complexity_cost": 0,
        "rule_results_evaluated": 0,
        "successful_applications": 0,
        "target_absent": 0,
        "context_mismatches": 0,
        "anchor_mismatches": 0,
        "rule_coverage": 0.0,
        "anomaly_count": 0,
        "anomaly_rate": 0.0,
        "identity_reconstruction": False,
    }
    base.update(diagnostics)
    return ReconstructionStep(
        parent_node_id="PROTO",
        child_node_ids=CHILDREN,
        input_beams=(_beam("A", ("p", "a")), _beam("B", ("f", "a"))),
        output_beam=_beam("PROTO", ("p", "a")),
        diagnostics=ReconstructionDiagnostics(**base),
    )


def _metrics(**overrides) -> AgentNodeMetrics:
    now = datetime.now(UTC)
    base = {
        "started_at": now,
        "finished_at": now,
        "duration_seconds": 1.0,
        "turn_count": 4,
        "provider_attempts": 4,
        "retry_count": 0,
        "tool_call_count": 6,
        "failed_tool_call_count": 0,
        "protocol_failure_count": 0,
        "inspection_tool_calls": 2,
        "sound_law_tests": 0,
        "cascade_tests": 0,
        "assembly_tests": 0,
        "committed_rule_count": 0,
        "committed_anomaly_count": 0,
        "committed_without_inspection": False,
        "identity_without_testing": False,
    }
    base.update(overrides)
    return AgentNodeMetrics(**base)


def _payload() -> NodePromptPayload:
    return NodePromptPayload(
        node_id="PROTO",
        active_children=tuple(
            NodeLexiconSummary(
                node_id=child, name=child, form_count=1, concept_count=1
            )
            for child in CHILDREN
        ),
    )


def _trajectory(commit, metrics, *, schema_version="2.0") -> AgentTrajectory:
    return AgentTrajectory(
        trajectory_id="trajectory:test",
        schema_version=schema_version,
        run_id="run:test",
        configuration_sha256="0" * 64,
        node_id="PROTO",
        provider_adapter="ScriptedProvider",
        instruction_sha256="1" * 64,
        tool_schema_sha256="2" * 64,
        payload_schema_sha256="3" * 64,
        trajectory_schema_sha256="4" * 64,
        initial_payload=_payload(),
        tool_definitions=(
            LLMToolDefinition(
                name="commit_reconstruction",
                description="commit",
                parameters={"type": "object"},
            ),
        ),
        messages=(LLMMessage(role=MessageRole.SYSTEM, content="system"),),
        metrics=metrics,
        committed_reconstruction=commit,
        reconstruction_step=_step(
            rule_count=2 if isinstance(commit, CommittedReconstruction) else 0,
            committed_set_count=(
                None if isinstance(commit, CommittedReconstruction) else 2
            ),
        ),
        completed=True,
    )


def _rule_commit() -> CommittedReconstruction:
    rules = (
        CommittedSoundRule(
            dsl="f > p / #_",
            source_child_ids=("B",),
            confidence=0.9,
            rationale="B lenited the initial stop.",
        ),
        CommittedSoundRule(
            dsl="e > a / #_",
            source_child_ids=("B",),
            confidence=0.8,
            rationale="B lowered the vowel.",
        ),
    )
    return CommittedReconstruction(
        request=CommitReconstructionArgs(
            node_id="PROTO",
            rules=rules,
            anomalies=(),
            summary="Two regular changes on B.",
        ),
        parsed_rules=tuple(
            ReconstructionRule(
                rule=parse_rule(rule.dsl),
                source_child_ids=rule.source_child_ids,
                confidence=rule.confidence,
            )
            for rule in rules
        ),
    )


def _inventory_commit() -> CommittedProtoInventory:
    commitments = tuple(
        CorrespondenceCommitment(
            set_id=derive_set_id(
                reflexes,
                CHILDREN,
                segmentation_overlay_id=None,
                alignment_overlay_id=None,
            ),
            reflexes=reflexes,
            proto_segment=proto,
            support=2,
            confidence=0.9,
            rationale="one of two committed sets",
        )
        for reflexes, proto in ((("p", "f"), "p"), (("a", "e"), "a"))
    )
    return CommittedProtoInventory(
        request=CommitProtoInventoryArgs(
            node_id="PROTO",
            child_node_ids=CHILDREN,
            commitments=commitments,
            residue_policy=ResiduePolicy.DROP,
            assembly_validation_call_id="preview",
            summary="Two correspondence sets.",
        ),
        proto_phonemes=("a", "p"),
    )


def test_equivalent_workflow_behaviour_earns_the_same_verdict() -> None:
    """A well-formed session passes under either protocol, for no reasons."""
    rules = _trajectory(
        _rule_commit(),
        _metrics(committed_rule_count=2, sound_law_tests=2, cascade_tests=1),
    )
    inventory = _trajectory(
        _inventory_commit(),
        _metrics(committed_rule_count=2, assembly_tests=1),
        schema_version=INVENTORY_SCHEMA_VERSION,
    )
    assert rules.high_quality_failure_reasons == ()
    assert inventory.high_quality_failure_reasons == ()
    assert rules.high_quality is inventory.high_quality is True


def test_an_inventory_committed_without_a_preview_is_caught() -> None:
    """The condition that would silently pass if nothing dispatched on shape."""
    inventory = _trajectory(
        _inventory_commit(),
        _metrics(committed_rule_count=2, assembly_tests=0),
        schema_version=INVENTORY_SCHEMA_VERSION,
    )
    assert inventory.high_quality is False
    assert inventory.high_quality_failure_reasons == (
        "2 correspondence set(s) committed without a same-session "
        "test_proto_assembly preview",
    )
    # And the rule-shaped session with the equivalent defect fails too, so the
    # gate is not merely stricter on one shape than the other.
    rules = _trajectory(
        _rule_commit(),
        _metrics(committed_rule_count=2, sound_law_tests=0, cascade_tests=0),
    )
    assert rules.high_quality is False


def test_the_rule_shaped_conditions_do_not_fire_on_an_inventory() -> None:
    """They have no subject there, and firing would be a different bug.

    An inventory session calls `test_sound_law` zero times by construction. If
    the sound-law condition were left applying to it, every inventory node would
    fail the gate for not having done something the protocol does not ask for —
    the mirror image of the hazard, and just as wrong.
    """
    inventory = _trajectory(
        _inventory_commit(),
        _metrics(committed_rule_count=2, assembly_tests=1, sound_law_tests=0),
        schema_version=INVENTORY_SCHEMA_VERSION,
    )
    reasons = " ".join(inventory.high_quality_failure_reasons)
    assert "sound-law" not in reasons
    assert "test_rule_cascade" not in reasons


def test_no_op_rule_counting_returns_zero_for_an_inventory_deliberately() -> None:
    """0 because the check is meaningless, not because the attribute was absent.

    A commitment whose `proto_segment` equals every child's reflex derives no
    rule at all; that is an ordinary identity correspondence, not a defect.
    """
    inventory = _trajectory(
        _inventory_commit(),
        _metrics(committed_rule_count=2, assembly_tests=1),
        schema_version=INVENTORY_SCHEMA_VERSION,
    )
    assert inventory.committed_no_op_rule_count == 0
    assert inventory.commit_shape == "inventory"
    assert _trajectory(_rule_commit(), _metrics()).commit_shape == "rules"


def test_the_other_gate_conditions_still_apply_to_an_inventory() -> None:
    """Dispatching on shape must not skip the shape-independent checks."""
    inventory = _trajectory(
        _inventory_commit(),
        _metrics(
            committed_rule_count=2,
            assembly_tests=1,
            committed_without_inspection=True,
            tool_call_count=8,
            failed_tool_call_count=6,
            protocol_failure_count=6,
        ),
        schema_version=INVENTORY_SCHEMA_VERSION,
    )
    reasons = inventory.high_quality_failure_reasons
    assert any("inspected no evidence" in reason for reason in reasons)
    assert any("protocol failures" in reason for reason in reasons)


def test_the_summary_splits_committed_units_by_the_shape_that_gives_them_a_unit() -> (
    None
):
    """"247 committed rules" over a mixed corpus is not a quantity.

    §12.2 fixed `committed_rule_count` to mean `len(commitments)` under an
    inventory and rewrite rules under a cascade, and kept the field name. That
    was a transitional inaccuracy while one shape was scheduled to replace the
    other. §7.22 item 2 records that both are permanent, so the pooled total is
    permanently a sum over two units and the split is what a reader can quote.

    The pooled key stays: removing a key from a summary breaks a consumer
    silently, which is a worse failure than an ambiguous one that is documented.
    """
    from cognate_reconstruction.cli import _trajectory_summary

    summary = _trajectory_summary(
        [
            _trajectory(
                _rule_commit(),
                _metrics(committed_rule_count=2, sound_law_tests=2, cascade_tests=1),
            ),
            _trajectory(
                _inventory_commit(),
                _metrics(committed_rule_count=5, assembly_tests=1),
                schema_version=INVENTORY_SCHEMA_VERSION,
            ),
        ]
    )
    assert summary["committed_rules"] == 7
    assert summary["committed_units_by_shape"] == {"rules": 2, "inventory": 5}
    assert summary["commit_shapes"] == {"inventory": 1, "rules": 1}


def test_the_no_op_count_carries_the_denominator_it_applies_to() -> None:
    """0 no-op rules over a corpus of inventories is not a finding.

    `committed_no_op_rule_count` is 0 for an inventory by decision — there is no
    analogue of a rule that cannot change any token sequence. Pooled, that makes
    "0 committed no-op rules" read as a clean corpus when it may mean the check
    had no subject. The denominator distinguishes the two.
    """
    from cognate_reconstruction.cli import _trajectory_summary

    inventories_only = _trajectory_summary(
        [
            _trajectory(
                _inventory_commit(),
                _metrics(committed_rule_count=5, assembly_tests=1),
                schema_version=INVENTORY_SCHEMA_VERSION,
            )
        ]
    )
    assert inventories_only["committed_no_op_rules"] == 0
    assert inventories_only["trajectories_the_no_op_check_applies_to"] == 0

    with_a_cascade = _trajectory_summary(
        [
            _trajectory(
                _rule_commit(),
                _metrics(committed_rule_count=2, sound_law_tests=2, cascade_tests=1),
            )
        ]
    )
    assert with_a_cascade["committed_no_op_rules"] == 0
    assert with_a_cascade["trajectories_the_no_op_check_applies_to"] == 1
