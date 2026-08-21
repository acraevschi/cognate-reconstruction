"""Turn a benchmark definition into a runnable, leak-checked payload."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from cognate_reconstruction.ingestion.cldf import load_cldf_dataset
from cognate_reconstruction.ingestion.preparation import prepare_payload
from cognate_reconstruction.schemas.benchmark import (
    BenchmarkDefinition,
    ConceptSelection,
)
from cognate_reconstruction.schemas.historical import (
    HistoricalBindingFile,
    HistoricalBindingRequest,
    HistoricalFormRole,
)
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.schemas.lexicon import LanguageLexicon


@dataclass(frozen=True)
class BenchmarkBuildReport:
    """What the build selected, for a human and for the run that quotes it."""

    name: str
    dataset_path: str
    daughter_count: int
    concept_count: int
    selected_concept_ids: tuple[str, ...]
    target_node_ids: tuple[str, ...]
    gold_evidence_kinds: tuple[str, ...]
    gold_form_counts: tuple[int, ...]

    def summary(self) -> str:
        kinds = ", ".join(
            f"{node}={kind} ({count} gold form(s))"
            for node, kind, count in zip(
                self.target_node_ids,
                self.gold_evidence_kinds,
                self.gold_form_counts,
                strict=True,
            )
        )
        return (
            f"{self.name}: {self.daughter_count} daughters, "
            f"{self.concept_count} concepts, gold at {kinds}"
        )


def load_definition(path: str | Path) -> BenchmarkDefinition:
    return BenchmarkDefinition.model_validate_json(
        Path(path).expanduser().read_text(encoding="utf-8")
    )


def _cognate_sets(lexicon: LanguageLexicon, concept_id: str) -> set[str]:
    return {
        cognate_set_id
        for form in lexicon.forms
        if form.concept_id == concept_id
        for cognate_set_id in form.cognate_set_ids
    }


def _attested_concepts(lexicon: LanguageLexicon) -> set[str]:
    return {form.concept_id for form in lexicon.forms}


def select_concepts(
    definition: BenchmarkDefinition,
    lexicons: Sequence[LanguageLexicon],
) -> tuple[str, ...]:
    """Concepts the benchmark scores over, in stable concept-ID order.

    `FULLY_COGNATE_WITH_TARGET` requires every chosen daughter to share a
    cognate set with the reference gold variety — not merely to have a form for
    the concept. That distinction is the whole design of the selection: a
    concept where one daughter has replaced the etymon is a lexical-replacement
    problem wearing a phonological benchmark's clothes.
    """
    by_id = {lexicon.variety_id: lexicon for lexicon in lexicons}
    missing = sorted(
        variety_id
        for variety_id in (
            *definition.daughters,
            *(target.source_variety_id for target in definition.targets),
        )
        if variety_id not in by_id
    )
    if missing:
        raise ValueError(
            f"benchmark {definition.name!r} names varieties absent from "
            f"{definition.dataset_path}: {missing}"
        )
    daughters = [by_id[variety_id] for variety_id in definition.daughters]
    if definition.concept_selection is ConceptSelection.ALL:
        selected = set().union(
            *(_attested_concepts(lexicon) for lexicon in daughters)
        )
    else:
        selected = set(_attested_concepts(daughters[0]))
        for lexicon in daughters[1:]:
            selected &= _attested_concepts(lexicon)
        if (
            definition.concept_selection
            is ConceptSelection.FULLY_COGNATE_WITH_TARGET
        ):
            gold = by_id[definition.selection_source_variety_id]
            selected &= _attested_concepts(gold)
            selected = {
                concept_id
                for concept_id in selected
                if (gold_sets := _cognate_sets(gold, concept_id))
                and all(
                    gold_sets & _cognate_sets(lexicon, concept_id)
                    for lexicon in daughters
                )
            }
    ordered = tuple(sorted(selected))
    if definition.max_concepts is not None:
        ordered = ordered[: definition.max_concepts]
    if not ordered:
        raise ValueError(
            f"benchmark {definition.name!r} selected no concepts; check the "
            "daughters, the gold variety, and the selection policy"
        )
    return ordered


def build_benchmark(
    definition: BenchmarkDefinition,
    *,
    base_path: Path | None = None,
) -> tuple[WorkbenchPayload, BenchmarkBuildReport]:
    """Build the payload a benchmark definition describes.

    Paths inside the definition resolve against `base_path` — the definition
    file's own directory by default — so a checked-in definition works from any
    working directory.
    """
    root = Path(base_path or Path.cwd())
    dataset_path = (root / definition.dataset_path).resolve()
    if not dataset_path.exists():
        raise FileNotFoundError(
            f"benchmark {definition.name!r} needs the local CLDF dataset "
            f"{dataset_path}, which is not present. The harness never "
            "downloads or builds Lexibank datasets; see data/README.md"
        )
    newick = (
        definition.newick
        if definition.newick is not None
        else (root / definition.newick_path)
        .resolve()
        .read_text(encoding="utf-8")
        .strip()
    )
    dataset = load_cldf_dataset(dataset_path)
    concepts = select_concepts(definition, dataset.lexicons)
    binding_requests = HistoricalBindingFile(
        bindings=tuple(
            HistoricalBindingRequest(
                source_variety_id=target.source_variety_id,
                node_id=target.node_id,
                role=HistoricalFormRole.TARGET,
                source_reference=target.source_reference,
                gold_evidence_kind=target.gold_evidence_kind,
            )
            for target in definition.targets
        )
    )
    payload = prepare_payload(
        dataset,
        variety_ids=definition.daughters,
        concept_ids=concepts,
        binding_requests=binding_requests,
        newick=newick,
    )
    bindings = payload.historical_form_bindings
    report = BenchmarkBuildReport(
        name=definition.name,
        dataset_path=str(dataset_path),
        daughter_count=len(payload.lexicons),
        concept_count=len(
            {
                form.concept_id
                for lexicon in payload.lexicons
                for form in lexicon.forms
            }
        ),
        selected_concept_ids=concepts,
        target_node_ids=tuple(binding.node_id for binding in bindings),
        gold_evidence_kinds=tuple(
            binding.gold_evidence_kind.value
            if binding.gold_evidence_kind is not None
            else "unspecified"
            for binding in bindings
        ),
        gold_form_counts=tuple(len(binding.forms) for binding in bindings),
    )
    return payload, report
