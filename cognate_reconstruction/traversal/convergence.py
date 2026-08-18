"""Did the children end up agreeing on a parent form?

Every other diagnostic in `ReconstructionDiagnostics` measures the *rules* — how
many there were, how often they fired, what they cost. None of them measures the
thing a reconstruction is for, which is whether the branches converge on one
parent. A node can apply a flawless cascade and still leave every child saying
something different.

This module is deliberately free of beams, engines, and scores: it takes the
parent forms each child produced and counts agreement. Both the deterministic
reconstructor and the agent-facing tools build that mapping from their own data
and share this arithmetic, so the number the model sees at commit time and the
number the artifact records cannot drift apart.

Divergence is reported and scored, never rejected. A linguist may legitimately
commit a hypothesis under which some children disagree — an unexplained residue
is a normal state of a comparative argument, not a protocol error. See
`docs/report_reject_or_score.md`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

MAX_REPORTED_DIVERGENT_CONCEPTS = 20
"""Divergent concept IDs embedded in a persisted step before truncation.

The count is authoritative and unbounded; the list is a sample for a reader.
A node over a large lexicon can diverge on hundreds of concepts, and writing all
of them into every artifact would put a payload in the record that no reader
asked for — the same reasoning that keeps `correspondence_maps` compact.
"""


@dataclass(frozen=True)
class ConceptConvergence:
    """What the active children produced for one concept."""

    concept_id: str
    parent_forms: tuple[tuple[str, ...], ...]
    """Distinct parent forms, sorted. Length 1 means the children agreed."""
    child_count: int
    """Active children that attested this concept at all."""

    @property
    def converged(self) -> bool:
        return len(self.parent_forms) == 1


@dataclass(frozen=True)
class ConvergenceReport:
    concepts: tuple[ConceptConvergence, ...]

    @property
    def concepts_evaluated(self) -> int:
        return len(self.concepts)

    @property
    def converged_concept_count(self) -> int:
        return sum(concept.converged for concept in self.concepts)

    @property
    def divergent_concept_ids(self) -> tuple[str, ...]:
        return tuple(
            concept.concept_id for concept in self.concepts if not concept.converged
        )

    @property
    def divergent_concept_count(self) -> int:
        return len(self.divergent_concept_ids)

    @property
    def reported_divergent_concept_ids(self) -> tuple[str, ...]:
        """The bounded sample that fits in an artifact."""
        return self.divergent_concept_ids[:MAX_REPORTED_DIVERGENT_CONCEPTS]

    @property
    def rate(self) -> float:
        """Share of concepts on which every attesting child produced one form.

        A concept only one child attests is counted as converged: there is no
        second branch to disagree with it. That makes the rate a measure of
        *agreement* and not of *coverage*, which is why it is reported next to
        `mean_branch_support` — support is the number that separates "all five
        children said this" from "one child said this and the rest were silent".
        """
        if not self.concepts:
            return 0.0
        return self.converged_concept_count / len(self.concepts)


def report_convergence(
    outputs_by_concept: Mapping[str, Mapping[str, Sequence[tuple[str, ...]]]],
) -> ConvergenceReport:
    """Count agreement from `{concept_id: {child_id: parent forms}}`.

    A child contributing several forms for one concept — synonyms, or several
    retained beam candidates — diverges from itself, which is the honest reading:
    the node has not settled on a single parent form for that concept either.
    """
    concepts = []
    for concept_id in sorted(outputs_by_concept):
        by_child = outputs_by_concept[concept_id]
        forms = {
            segments for outputs in by_child.values() for segments in outputs
        }
        concepts.append(
            ConceptConvergence(
                concept_id=concept_id,
                parent_forms=tuple(sorted(forms)),
                child_count=len(by_child),
            )
        )
    return ConvergenceReport(concepts=tuple(concepts))
