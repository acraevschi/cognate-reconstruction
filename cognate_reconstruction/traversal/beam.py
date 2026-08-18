"""Numerically stable beam construction, merging, and pruning."""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from collections.abc import Iterable

from cognate_reconstruction.schemas.beam import (
    CandidateDerivation,
    ConceptCandidateDistribution,
    NodeBeamState,
    ReconstructionCandidate,
)
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm

RawCandidate = tuple[tuple[str, ...], float, CandidateDerivation]

TIE_BREAK_POLICY = "segment-lexicographic"
"""How equal-mass candidates are ordered, chosen rather than inherited.

Candidates that score exactly the same still have to come out of the sort in
some order, and whichever comes first wins the node. That order used to be a
side effect of putting `segments` in the sort key for determinism; naming it
makes it a decision someone can disagree with.

The policy is: **ascending lexicographic order of the segment tuple, by Unicode
code point.** It is arbitrary. It is not parsimony, not markedness, not
directionality, and it carries no linguistic claim whatsoever — under it `a W a`
beats `a k a` because `W` sorts before `k`, which is a fact about Unicode and
about nothing else.

It is kept because reproducibility is worth more here than a guess: the same
inputs must produce the same beam on every machine and every run, and an
arbitrary rule stated out loud is safer than a plausible-sounding rule that
would quietly encode a theory of sound change into the scorer. Choosing among
equally supported reconstructions on linguistic grounds is a real problem and a
separate one — it belongs with directionality, not in a sort key.

Ties reaching this policy are now rarer than they were: branch support weighting
in `traversal/reconstructor.py` separates candidates the flat branch penalty used
to leave exactly equal. What remains genuinely tied — two branches, one each —
is decided here, blindly and on purpose.
"""


def _logsumexp(values: Iterable[float]) -> float:
    materialized = tuple(values)
    maximum = max(materialized)
    return maximum + math.log(sum(math.exp(value - maximum) for value in materialized))


def _candidate_id(node_id: str, concept_id: str, segments: tuple[str, ...]) -> str:
    digest = hashlib.sha256("\u241f".join(segments).encode()).hexdigest()[:12]
    return f"{node_id}:{concept_id}:{digest}"


TIE_BREAK_EPSILON = 1e-9
"""Log-mass difference below which two candidates count as tied.

Exact ties come out bit-identical when the arithmetic is symmetric, but log-sum-
exp over differently ordered inputs need not be, so equality is not tested with
`==`. The tolerance is far below any score difference the scorer produces on
purpose and far above float noise.
"""


def _tie_break_key(segments: tuple[str, ...]) -> tuple[str, ...]:
    """The `TIE_BREAK_POLICY` sort key: the segment tuple itself."""
    return segments


def decided_by_tie_break(distribution: ConceptCandidateDistribution) -> bool:
    """Was this concept's reported form chosen by `TIE_BREAK_POLICY`?

    True when the top two candidates carry the same mass, so the winner was
    picked by segment order and nothing else. Counting these is the only way a
    reader can tell an evidenced reconstruction from an arbitrary one — the beam
    prints two probabilities of 0.50 either way, and on the Polynesian benchmark
    this fires on 22 of 46 concepts at one leaf-adjacent binary node.

    A report, never a score: nothing consumes it, and a tie is not a defect. It
    is the honest output when the evidence genuinely does not separate two
    reconstructions.
    """
    candidates = distribution.candidates
    if len(candidates) < 2:
        return False
    return abs(candidates[0].log_score - candidates[1].log_score) < TIE_BREAK_EPSILON


def normalize_and_prune(
    node_id: str,
    concept_id: str,
    raw_candidates: Iterable[RawCandidate],
    *,
    beam_width: int,
) -> ConceptCandidateDistribution:
    """Merge identical strings, retain top N by log mass, and normalize.

    Ordering is by descending log mass, and equal masses are broken by
    `TIE_BREAK_POLICY` — ascending lexicographic order of the segment tuple.
    That tie-break is deliberate and deliberately arbitrary: it exists so runs
    reproduce, and it asserts nothing about which of two equally supported
    reconstructions is the better historical hypothesis. Read `TIE_BREAK_POLICY`
    before treating the winner of a tie as a finding.
    """
    grouped_scores: dict[tuple[str, ...], list[float]] = defaultdict(list)
    grouped_derivations: dict[tuple[str, ...], list[CandidateDerivation]] = defaultdict(list)
    for segments, log_score, derivation in raw_candidates:
        if not segments or not math.isfinite(log_score):
            continue
        grouped_scores[segments].append(log_score)
        grouped_derivations[segments].append(derivation)
    if not grouped_scores:
        raise ValueError(f"no viable candidates for concept {concept_id!r}")
    merged = sorted(
        ((segments, _logsumexp(scores)) for segments, scores in grouped_scores.items()),
        key=lambda item: (-item[1], _tie_break_key(item[0])),
    )[:beam_width]
    normalizer = _logsumexp(score for _, score in merged)
    candidates = tuple(
        ReconstructionCandidate(
            candidate_id=_candidate_id(node_id, concept_id, segments),
            segments=segments,
            probability=math.exp(score - normalizer),
            log_score=score,
            derivations=tuple(grouped_derivations[segments]),
        )
        for segments, score in merged
    )
    return ConceptCandidateDistribution(concept_id=concept_id, candidates=candidates)


def make_leaf_beam(lexicon: LanguageLexicon, *, beam_width: int) -> NodeBeamState:
    """Represent observed forms as an initial per-concept distribution."""
    by_concept: dict[str, list[tuple[str, ...]]] = defaultdict(list)
    for form in lexicon.forms:
        by_concept[form.concept_id].append(form.segments)
    distributions: list[ConceptCandidateDistribution] = []
    for concept_id, sequences in sorted(by_concept.items()):
        log_prior = -math.log(len(sequences))
        raw = (
            (
                segments,
                log_prior,
                CandidateDerivation(
                    derivation_id=f"observed:{lexicon.variety_id}:{concept_id}:{index}",
                    child_candidate_ids=(),
                    note="observed leaf form",
                ),
            )
            for index, segments in enumerate(sequences)
        )
        distributions.append(
            normalize_and_prune(
                lexicon.variety_id, concept_id, raw, beam_width=beam_width
            )
        )
    return NodeBeamState(
        node_id=lexicon.variety_id,
        distributions=tuple(distributions),
        beam_width=beam_width,
    )


def beam_to_lexicon(beam: NodeBeamState) -> LanguageLexicon:
    """Expose every retained candidate as a read-only node lexicon."""
    return LanguageLexicon(
        variety_id=beam.node_id,
        name=beam.node_id,
        forms=tuple(
            LexicalForm(
                form_id=candidate.candidate_id,
                variety_id=beam.node_id,
                concept_id=distribution.concept_id,
                segments=candidate.segments,
            )
            for distribution in beam.distributions
            for candidate in distribution.candidates
        ),
    )
