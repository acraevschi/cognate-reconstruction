"""Split a node's concepts into a development set and a held-out set.

The split exists to make "a confident rule generalised from one word" visible.
A rule fitted to the handful of concepts a session looked at should *look* bad
on the concepts it did not, and nothing in the harness could say so: every
diagnostic was computed over exactly the forms the model chose to reason about.

Three properties the split has to have, all of them mechanical:

- **Deterministic.** The membership of the held-out set is derived from the
  node ID and the concept IDs alone, so a resumed run, a re-run, and a
  `--resume` after a failed node all hold out the same concepts. Anything
  seeded from wall-clock time or iteration order would make the held-out number
  in a trajectory unreproducible, which is the same as not recording it.
- **Node-local.** Seeding from the node ID means sibling nodes hold out
  different concepts, so a family run is not evaluated on one fixed subset.
- **Visible.** The split is put in the prompt payload rather than hidden. It is
  a discipline device, not an adversarial test set: a model that decides to
  inspect a held-out concept is doing comparative work, not cheating, and a
  hidden split would only produce a number the session could not act on.

Nothing here rejects. The held-out summary is reported by `test_sound_law`,
`test_rule_cascade`, and `commit_reconstruction`, and recorded in the
trajectory metrics; see `docs/report_reject_or_score.md`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass

DEFAULT_HELD_OUT_SHARE = 0.3
"""Share of a node's concepts withheld from the development set.

Around 70/30 because the development set still has to be large enough to
establish recurrence — the comparative method's whole criterion — while the
held-out set has to be large enough that a rule fitted to one word visibly
fails on it. Neither bound is calibrated; it is a starting point, and the split
is reported rather than scored precisely because of that.
"""


@dataclass(frozen=True)
class ConceptSplit:
    """One node's concepts, divided once and reproducibly."""

    node_id: str
    development_concept_ids: tuple[str, ...]
    held_out_concept_ids: tuple[str, ...]
    held_out_share: float

    @property
    def held_out(self) -> frozenset[str]:
        return frozenset(self.held_out_concept_ids)

    @property
    def concept_count(self) -> int:
        return len(self.development_concept_ids) + len(self.held_out_concept_ids)


def split_concepts(
    node_id: str,
    concept_ids: Iterable[str],
    *,
    held_out_share: float = DEFAULT_HELD_OUT_SHARE,
) -> ConceptSplit:
    """Divide `concept_ids` deterministically, seeded from `node_id`.

    Concepts are ordered by the digest of the node ID and the concept ID, and
    the tail of that order is held out. A digest rather than a modulus so that
    the split does not correlate with anything about the ID text itself, and an
    exact count rather than a per-concept coin flip so that the sizes are the
    same however few concepts a node has.

    At least one concept always stays in the development set: a node with a
    single concept has nothing to hold out, and holding out its only concept
    would leave a session with no evidence at all.
    """
    if not 0.0 <= held_out_share < 1.0:
        raise ValueError("held_out_share must be in [0, 1)")
    unique = sorted(set(concept_ids))
    ordered = sorted(
        unique,
        key=lambda concept_id: hashlib.sha256(
            f"{node_id}\0{concept_id}".encode()
        ).hexdigest(),
    )
    held_out_count = min(
        max(len(ordered) - 1, 0), round(len(ordered) * held_out_share)
    )
    boundary = len(ordered) - held_out_count
    return ConceptSplit(
        node_id=node_id,
        development_concept_ids=tuple(sorted(ordered[:boundary])),
        held_out_concept_ids=tuple(sorted(ordered[boundary:])),
        held_out_share=held_out_share,
    )


__all__ = ["DEFAULT_HELD_OUT_SHARE", "ConceptSplit", "split_concepts"]
