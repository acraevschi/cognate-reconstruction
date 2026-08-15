"""Small, auditable CLDF ingestion compatibility rules.

These rules only repair classification lookup metadata. They never rewrite
source Glottocodes, tokens, concepts, or cognate assignments.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TreeGlottocodeRule:
    rule_id: str
    dataset_id: str
    tree_glottocode: str
    source_language_id: str | None = None
    language_name: str | None = None
    reason: str = ""

    def matches(
        self,
        *,
        dataset_id: str,
        source_language_id: str,
        language_name: str,
    ) -> bool:
        if self.dataset_id != dataset_id:
            return False
        return (
            self.source_language_id == source_language_id
            if self.source_language_id is not None
            else self.language_name == language_name
        )


TREE_GLOTTOCODE_RULES: tuple[TreeGlottocodeRule, ...] = (
    TreeGlottocodeRule(
        rule_id="tlopo-local-pan",
        dataset_id="tlopo",
        source_language_id="pan",
        tree_glottocode="aust1307",
        reason="The local ID pan is Proto-Austronesian, not a Glottocode.",
    ),
    TreeGlottocodeRule(
        rule_id="tlopo-local-poc",
        dataset_id="tlopo",
        source_language_id="poc",
        tree_glottocode="ocea1241",
        reason="The local ID poc is Proto-Oceanic, not a Glottocode.",
    ),
    *tuple(
        TreeGlottocodeRule(
            rule_id=f"tuled-name-{name.lower()}",
            dataset_id="tuled",
            language_name=name,
            tree_glottocode=glottocode,
            reason="The source variety lacks a usable Glottocode.",
        )
        for name, glottocode in (
            ("Tenharim", "tenh1241"),
            ("Wirafed", "wira1264"),
            ("OldGuarani", "oldg1234"),
            ("Kampe", "camp1260"),
            ("Ramarama", "itog1239"),
            ("Apapokuva", "apap1239"),
            ("Piripkura", "piri1253"),
            ("Kawahiva", "kawa1283"),
            ("Karipuna", "kari1312"),
            ("MaweNatterer", "sate1243"),
            ("MundurukuNatterer", "mund1330"),
            ("ApiakaNatterer", "apia1248"),
            ("Arawine", "araw1282"),
        )
    ),
)


def tree_glottocode_for(
    *,
    dataset_id: str,
    source_language_id: str,
    language_name: str,
    source_glottocode: str | None,
) -> tuple[str | None, tuple[str, ...]]:
    """Resolve tree lookup metadata while preserving its rule provenance."""
    matches = tuple(
        rule
        for rule in TREE_GLOTTOCODE_RULES
        if rule.matches(
            dataset_id=dataset_id,
            source_language_id=source_language_id,
            language_name=language_name,
        )
    )
    if len(matches) > 1:
        raise ValueError(
            f"multiple tree-Glottocode compatibility rules match "
            f"{dataset_id}:{source_language_id}"
        )
    if not matches:
        return source_glottocode, ()
    return matches[0].tree_glottocode, (matches[0].rule_id,)

