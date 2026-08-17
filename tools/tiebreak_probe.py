"""Does branch support influence which parent form the beam reports?

The comparative method treats agreement across branches as evidence. This probe
asks the deterministic scorer the same question directly, with no model and no
network, and prints what it answers.

Read the second case first. It is the one that matters: renaming the *minority*
segment to one that sorts earlier in Unicode changes which form wins the node.

Usage:
    python tools/tiebreak_probe.py
"""

from __future__ import annotations

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


def report(label: str, children: list[LanguageLexicon], rules=()) -> None:
    beams = [make_leaf_beam(item, beam_width=5) for item in children]
    step = RuleBasedReconstructor(beam_width=5).reconstruct(
        "parent", beams, rules=rules
    )
    print(label)
    for candidate in step.output_beam.distributions[0].candidates:
        print(
            f"    {' '.join(candidate.segments):<10} "
            f"p={candidate.probability:.4f}  log={candidate.log_score:+.4f}"
        )
    print()


def main() -> None:
    majority = [lexicon(f"c{i}", "aka") for i in range(1, 5)]

    report(
        "A. four children [a k a] vs one [a ʔ a], identity reconstruction:",
        majority + [lexicon("c5", "aʔa")],
    )
    report(
        "B. same shape, but the minority segment sorts before 'k'.\n"
        "   If B disagrees with A about which form wins, the tie-break is\n"
        "   Unicode order rather than evidence:",
        majority + [lexicon("c5", "aWa")],
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
    )


if __name__ == "__main__":
    main()
