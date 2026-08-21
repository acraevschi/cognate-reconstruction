"""Does branch support influence which parent form the beam reports?

The comparative method treats agreement across branches as evidence. This probe
asks the deterministic scorer the same question directly, with no model and no
network, and prints what it answers.

Read the second case first. It is the one that matters: renaming the *minority*
segment to one that sorts earlier in Unicode changes which form wins the node.

Usage:
    python tools/tiebreak_probe.py
    python tools/tiebreak_probe.py --json
"""

from __future__ import annotations

import argparse

import _bootstrap  # noqa: F401  (bind to this checkout; see module)

from cognate_reconstruction.rules.parser import parse_rule
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm
from cognate_reconstruction.schemas.rules import ReconstructionRule
from cognate_reconstruction.traversal.beam import make_leaf_beam
from cognate_reconstruction.traversal.reconstructor import RuleBasedReconstructor


def lexicon(variety_id: str, segments: str) -> LanguageLexicon:
    return LanguageLexicon(
        variety_id=variety_id,
        name=variety_id,
        forms=(
            LexicalForm(
                form_id=f"{variety_id}:probe",
                variety_id=variety_id,
                concept_id="probe",
                segments=tuple(segments),
            ),
        ),
    )


def report(
    label: str,
    children: list[LanguageLexicon],
    rules=(),
    *,
    case: str = "",
    collected: list | None = None,
) -> None:
    beams = [make_leaf_beam(item, beam_width=5) for item in children]
    step = RuleBasedReconstructor(beam_width=5).reconstruct(
        "parent", beams, rules=rules
    )
    candidates = [
        {
            "segments": list(candidate.segments),
            "probability": candidate.probability,
            "log_score": candidate.log_score,
        }
        for candidate in step.output_beam.distributions[0].candidates
    ]
    if collected is not None:
        collected.append({"case": case, "candidates": candidates})
        return
    print(label)
    for candidate in candidates:
        print(
            f"    {' '.join(candidate['segments']):<10} "
            f"p={candidate['probability']:.4f}  "
            f"log={candidate['log_score']:+.4f}"
        )
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit one machine-readable object, including the measured source.",
    )
    args = parser.parse_args()
    collected: list | None = [] if args.json else None
    if not args.json:
        print(f"measuring: {_bootstrap.loaded_package_path()}\n")
    majority = [lexicon(f"c{i}", "aka") for i in range(1, 5)]

    report(
        "A. four children [a k a] vs one [a ʔ a], identity reconstruction:",
        majority + [lexicon("c5", "aʔa")],
        case="A",
        collected=collected,
    )
    report(
        "B. same shape, but the minority segment sorts before 'k'.\n"
        "   If B disagrees with A about which form wins, the tie-break is\n"
        "   Unicode order rather than evidence:",
        majority + [lexicon("c5", "aWa")],
        case="B",
        collected=collected,
    )
    report(
        "C. control: a rule maps the deviant child onto the majority form,\n"
        "   so the children converge and there is nothing to break:",
        majority + [lexicon("c5", "aʔa")],
        rules=[
            ReconstructionRule(
                rule=parse_rule("ʔ > k"), source_child_ids=("c5",), confidence=0.9
            )
        ],
        case="C",
        collected=collected,
    )
    if collected is not None:
        _bootstrap.emit_json(
            {
                **_bootstrap.measurement_envelope(),
                "measurement": "tiebreak_probe",
                "cases": collected,
                "note": (
                    "Cases A and B are the same shape with the minority "
                    "segment renamed to one that sorts earlier in Unicode. If "
                    "they disagree about the winner, the winner is being "
                    "chosen by string ordering rather than by evidence."
                ),
            }
        )


if __name__ == "__main__":
    main()
