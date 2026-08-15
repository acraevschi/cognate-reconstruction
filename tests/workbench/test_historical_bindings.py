from __future__ import annotations

from collections.abc import Sequence

import pytest

from cognate_reconstruction.agent.orchestrator import AgentOrchestrator
from cognate_reconstruction.agent.reconstructor import AgenticNodeReconstructor
from cognate_reconstruction.agent.schemas import (
    LLMMessage,
    LLMToolCall,
    LLMToolDefinition,
    MessageRole,
)
from cognate_reconstruction.agent.service import ReconstructionService
from cognate_reconstruction.ingestion import ingest_payload
from cognate_reconstruction.ingestion.historical import (
    load_historical_lineage_bindings,
    materialize_historical_bindings,
)
from cognate_reconstruction.schemas.historical import (
    HistoricalBindingFile,
    HistoricalBindingRequest,
    HistoricalFormBinding,
    HistoricalFormRole,
    HistoricalLineageRelation,
)
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.schemas.lexicon import (
    FormProvenance,
    LanguageLexicon,
    LexicalForm,
)


def _lexicon(
    variety_id: str,
    segments: tuple[str, ...],
    *,
    historical: bool = False,
) -> LanguageLexicon:
    return LanguageLexicon(
        variety_id=variety_id,
        name=variety_id,
        is_historical=historical,
        forms=(
            LexicalForm(
                form_id=f"{variety_id}:water",
                variety_id=variety_id,
                concept_id="water",
                segments=segments,
                provenance=FormProvenance(
                    dataset_id="fixture",
                    source_language_id=variety_id,
                    source_form_id=f"{variety_id}:water",
                ),
            ),
        ),
    )


class _IdentityProvider:
    model = "scripted/identity"

    def complete(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[LLMToolDefinition],
    ) -> LLMMessage:
        assert tools
        return LLMMessage(
            role=MessageRole.ASSISTANT,
            tool_calls=(
                LLMToolCall(
                    call_id="commit",
                    name="commit_reconstruction",
                    arguments={
                        "node_id": "PROTO",
                        "rules": [],
                        "anomalies": [],
                        "summary": "Identity reconstruction for target test.",
                    },
                ),
            ),
        )


def _binding(role: HistoricalFormRole) -> HistoricalFormBinding:
    return HistoricalFormBinding(
        node_id="PROTO",
        role=role,
        source_variety_id="fixture:H",
        source_declared_historical=True,
        forms=(
            LexicalForm(
                form_id="fixture:H:water",
                variety_id="PROTO",
                concept_id="water",
                segments=("p", "a"),
                provenance=FormProvenance(
                    dataset_id="fixture",
                    source_language_id="H",
                    source_form_id="H:water",
                ),
            ),
        ),
        lineage_relations=(
            HistoricalLineageRelation(
                branch_id="left",
                descendant_variety_id="A",
                evidence="fixture",
            ),
            HistoricalLineageRelation(
                branch_id="right",
                descendant_variety_id="B",
                evidence="fixture",
            ),
        ),
        source_reference="fixture lineage",
    )


def _run(role: HistoricalFormRole):
    dataset = ingest_payload(
        WorkbenchPayload(
            lexicons=(
                _lexicon("A", ("p", "a")),
                _lexicon("B", ("p", "a")),
            ),
            newick="(A,B)PROTO;",
            historical_form_bindings=(_binding(role),),
        )
    )
    service = ReconstructionService(
        AgenticNodeReconstructor(
            AgentOrchestrator(
                _IdentityProvider(),
                run_id=f"historical-{role.value}",
                configuration_sha256="historical-config",
            )
        )
    )
    return service.reconstruct_family(dataset)


def test_target_forms_are_withheld_and_evaluated_after_reconstruction() -> None:
    result = _run(HistoricalFormRole.TARGET)
    trajectory = result.trajectories[0]
    assert trajectory.initial_payload.anchors == ()
    assert "fixture:H:water" not in trajectory.messages[1].content
    evaluation = result.historical_target_evaluations[0]
    assert evaluation.node_id == "PROTO"
    assert evaluation.top_exact_matches == 1
    assert evaluation.beam_exact_matches == 1
    assert evaluation.top_exact_rate == 1.0


def test_anchor_forms_are_visible_but_not_treated_as_hidden_targets() -> None:
    result = _run(HistoricalFormRole.ANCHOR)
    assert {
        anchor.form_id
        for anchor in result.trajectories[0].initial_payload.anchors
    } == {"fixture:H:water"}
    assert result.historical_target_evaluations == ()


def test_target_retains_unreconstructable_concepts_but_anchor_rejects_them() -> None:
    extra = LexicalForm(
        form_id="fixture:H:target-only",
        variety_id="PROTO",
        concept_id="target-only",
        segments=("x",),
        provenance=FormProvenance(
            dataset_id="fixture",
            source_language_id="H",
            source_form_id="H:target-only",
        ),
    )
    target = _binding(HistoricalFormRole.TARGET).model_copy(
        update={"forms": (*_binding(HistoricalFormRole.TARGET).forms, extra)}
    )
    dataset = ingest_payload(
        WorkbenchPayload(
            lexicons=(
                _lexicon("A", ("p", "a")),
                _lexicon("B", ("p", "a")),
            ),
            newick="(A,B)PROTO;",
            historical_form_bindings=(target,),
        )
    )
    result = ReconstructionService(
        AgenticNodeReconstructor(
            AgentOrchestrator(
                _IdentityProvider(),
                run_id="target-missing",
                configuration_sha256="historical-config",
            )
        )
    ).reconstruct_family(dataset)
    evaluation = result.historical_target_evaluations[0]
    assert evaluation.evaluated_concepts == 2
    assert evaluation.missing_reconstruction_concepts == 1

    anchor = target.model_copy(update={"role": HistoricalFormRole.ANCHOR})
    with pytest.raises(ValueError, match="targets may retain"):
        ingest_payload(
            WorkbenchPayload(
                lexicons=(
                    _lexicon("A", ("p", "a")),
                    _lexicon("B", ("p", "a")),
                ),
                newick="(A,B)PROTO;",
                historical_form_bindings=(anchor,),
            )
        )


def test_explicit_binding_materializes_source_forms_without_name_guessing() -> None:
    source = _lexicon("fixture:H", ("p", "a"), historical=False)
    requests = HistoricalBindingFile(
        bindings=(
            HistoricalBindingRequest(
                source_variety_id="fixture:H",
                node_id="PROTO",
                role=HistoricalFormRole.TARGET,
            ),
        )
    )
    binding = materialize_historical_bindings(requests, (source,))[0]
    assert not binding.source_declared_historical
    assert binding.forms[0].variety_id == "PROTO"
    assert binding.forms[0].provenance.source_language_id == "fixture:H"


def test_supported_lineage_manifest_preserves_branch_provenance() -> None:
    requests = load_historical_lineage_bindings(
        "data/historical_lineages.csv",
        dataset_id="iecor",
        role=HistoricalFormRole.ANCHOR,
    )
    assert requests.bindings[0].source_variety_id == "iecor:112"
    assert requests.bindings[0].node_id == "iecor:112"
    assert requests.bindings[0].role is HistoricalFormRole.ANCHOR
    assert {
        relation.branch_id
        for relation in requests.bindings[0].lineage_relations
    } == {
        "ibero_romance",
        "gallo_romance",
        "italo_romance",
        "eastern_romance",
    }
