"""`build-benchmark` must reproduce the selection, and must refuse to leak.

The Polynesian benchmark used to be a one-family script. Generalising it into a
subcommand driven by a declarative file is only worth anything if the
subcommand produces the *same* input the script did — 46 concepts where all ten
daughters share a cognate set with the Proto-Polynesian entry, and the proto
variety bound as a hidden target.

The second half is the one that matters more. A benchmark whose gold variety
stays in the lexicons is not a benchmark, it is a lookup table, and every
number measured on it is meaningless. That failure is silent, so it is checked
here and refused in `ingestion/preparation.py` rather than trusted to a
definition being written carefully.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cognate_reconstruction.benchmarks import (
    available_definitions,
    build_benchmark,
    load_definition,
)
from cognate_reconstruction.ingestion.preparation import assert_targets_are_hidden
from cognate_reconstruction.schemas.benchmark import (
    BenchmarkDefinition,
    BenchmarkTarget,
)
from cognate_reconstruction.schemas.historical import (
    GoldEvidenceKind,
    HistoricalFormBinding,
    HistoricalFormRole,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFINITIONS = REPO_ROOT / "benchmarks"


@pytest.mark.parametrize("name", ["polynesian", "romance"])
def test_every_checked_in_definition_is_valid(name: str) -> None:
    definition = load_definition(DEFINITIONS / f"{name}.json")
    assert definition.name == name
    assert len(definition.daughters) >= 2
    assert definition.targets
    # Provenance is not decoration. A gold set published after a model's
    # training cutoff is the one leakage control that needs no new code, and it
    # needs the date to be recorded.
    assert definition.provenance.publication_date is not None
    assert definition.provenance.leakage_note


def test_both_definitions_are_discoverable_by_name() -> None:
    assert {"polynesian", "romance"} <= set(available_definitions())


def test_a_definition_cannot_name_its_gold_variety_as_a_daughter() -> None:
    """Refused in the schema, before any data is read.

    This is the mistake that turns a benchmark into a lookup, and it is one
    line in a JSON file.
    """
    with pytest.raises(ValueError, match="leak the answer"):
        BenchmarkDefinition(
            name="broken",
            description="gold is also a daughter",
            dataset_path="somewhere",
            daughters=("x:A", "x:GOLD"),
            targets=(
                BenchmarkTarget(
                    source_variety_id="x:GOLD",
                    node_id="PROTO",
                    gold_evidence_kind=GoldEvidenceKind.RECONSTRUCTED,
                ),
            ),
            newick="(x:A,x:GOLD)PROTO;",
        )


def test_a_payload_whose_gold_stayed_visible_is_refused() -> None:
    """The same guard one layer down, over an assembled payload.

    A definition can be right and the assembly still wrong — a variety filter
    that stopped removing bound sources, say. The check is on the artifact, so
    it catches that too.
    """
    from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
    from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm

    def lexicon(variety_id: str) -> LanguageLexicon:
        return LanguageLexicon(
            variety_id=variety_id,
            name=variety_id,
            forms=(
                LexicalForm(
                    form_id=f"{variety_id}:water",
                    variety_id=variety_id,
                    concept_id="water",
                    segments=("p", "a"),
                ),
            ),
        )

    leaked = WorkbenchPayload(
        lexicons=(lexicon("A"), lexicon("B"), lexicon("GOLD")),
        newick="(A,B,GOLD)PROTO;",
        historical_form_bindings=(
            HistoricalFormBinding(
                node_id="PROTO",
                role=HistoricalFormRole.TARGET,
                source_variety_id="GOLD",
                forms=(
                    LexicalForm(
                        form_id="GOLD:water",
                        variety_id="PROTO",
                        concept_id="water",
                        segments=("p", "a"),
                    ),
                ),
            ),
        ),
    )
    with pytest.raises(ValueError, match="still present in the lexicons"):
        assert_targets_are_hidden(leaked)


def _requires_corpus(name: str) -> BenchmarkDefinition:
    definition = load_definition(DEFINITIONS / f"{name}.json")
    dataset = (DEFINITIONS / definition.dataset_path).resolve()
    if not dataset.exists():
        pytest.skip(
            f"{dataset} is a user-managed local corpus and is not committed"
        )
    return definition


def test_polynesian_reproduces_the_forty_six_concept_selection() -> None:
    """The claim the analysis baselines rest on, checked rather than assumed.

    `data/lexibank/` is a user-managed local corpus and is deliberately not
    committed, so this skips where it is absent. The oracle-ceiling regression
    test does not depend on it — it uses a checked-in fixture — but the numbers
    in `docs/analysis_tools.md` are quoted against this selection.
    """
    definition = _requires_corpus("polynesian")
    payload, report = build_benchmark(definition, base_path=DEFINITIONS)
    assert report.concept_count == 46
    assert report.daughter_count == 10
    assert len(report.selected_concept_ids) == 46
    assert {lexicon.variety_id for lexicon in payload.lexicons} == set(
        definition.daughters
    )
    binding = payload.historical_form_bindings[0]
    assert binding.role is HistoricalFormRole.TARGET
    assert binding.node_id == "proto_polynesian"
    # A published proto-form is somebody's reconstruction, and the score has to
    # keep saying so wherever it is reported.
    assert binding.gold_evidence_kind is GoldEvidenceKind.RECONSTRUCTED
    assert "walworthpolynesian:Polynesian" not in {
        lexicon.variety_id for lexicon in payload.lexicons
    }


def test_romance_binds_an_attested_gold_and_a_second_family_builds() -> None:
    """Two families, one code path — which is the point of the generalisation.

    Latin is the exception to "a published proto-form is a reconstruction": it
    is attested, and the binding says so.
    """
    definition = _requires_corpus("romance")
    payload, report = build_benchmark(definition, base_path=DEFINITIONS)
    assert report.daughter_count == 5
    assert report.concept_count > 100
    binding = payload.historical_form_bindings[0]
    assert binding.node_id == "latin"
    assert binding.gold_evidence_kind is GoldEvidenceKind.ATTESTED
    assert "meloniromance:Latin" not in {
        lexicon.variety_id for lexicon in payload.lexicons
    }
