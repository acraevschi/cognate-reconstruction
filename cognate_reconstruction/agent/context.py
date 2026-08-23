"""Mutable, node-local state used only by deterministic tool adapters."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from cognate_reconstruction.agent.error_codes import ToolInputError
from cognate_reconstruction.agent.holdout import (
    DEFAULT_HELD_OUT_SHARE,
    ConceptSplit,
    split_concepts,
)
from cognate_reconstruction.alignment.protocol import AlignmentProvider
from cognate_reconstruction.rules.engine import RuleEngine
from cognate_reconstruction.schemas.rules import AnchorPolicy
from cognate_reconstruction.schemas.lexicon import LanguageLexicon, LexicalForm
from cognate_reconstruction.schemas.lexicon import ConceptMetadata
from cognate_reconstruction.schemas.traversal import NodeEvidence

from cognate_reconstruction.schemas.inventory import AlignmentOverride

from .schemas import (
    CommittedHypothesis,
    PriorNodeInventory,
    PriorNodeReconstruction,
    TestProtoAssemblyResult,
    TestRuleCascadeResult,
    TestSoundLawResult,
)


@dataclass
class AgentContext:
    node_id: str
    child_lexicons: tuple[LanguageLexicon, ...]
    aligner: AlignmentProvider
    anchors: tuple[LexicalForm, ...] = ()
    anchor_policy: AnchorPolicy = AnchorPolicy.ADVISORY
    evidence: tuple[NodeEvidence, ...] = ()
    concepts: tuple[ConceptMetadata, ...] = ()
    # Read-only hypotheses committed at nodes already completed in this run.
    # They are prior claims, never evidence, and never influence scoring.
    prior_reconstructions: tuple[PriorNodeReconstruction, ...] = ()
    prior_inventories: tuple[PriorNodeInventory, ...] = ()
    rule_engine: RuleEngine = field(default_factory=RuleEngine)
    overlays: dict[str, dict[str, LexicalForm]] = field(default_factory=dict)
    # Alignment overlays are the same shape as segmentation overlays one level
    # up: immutable, ID'd, session-local, never crossing a node boundary and
    # never entering a checkpoint. Nothing a model does to an alignment persists.
    alignment_overlays: dict[str, dict[str, AlignmentOverride]] = field(
        default_factory=dict
    )
    validations: dict[str, TestSoundLawResult] = field(default_factory=dict)
    cascade_validations: dict[str, TestRuleCascadeResult] = field(default_factory=dict)
    assembly_validations: dict[str, TestProtoAssemblyResult] = field(
        default_factory=dict
    )
    commit: CommittedHypothesis | None = None
    held_out_share: float = DEFAULT_HELD_OUT_SHARE
    # Derived, never supplied: the split is a function of the node ID and the
    # children's concepts, which is what makes it survive a resume unchanged.
    concept_split: ConceptSplit = field(init=False)

    def __post_init__(self) -> None:
        ids = [lexicon.variety_id for lexicon in self.child_lexicons]
        if len(ids) < 2 or len(ids) != len(set(ids)):
            raise ValueError("an agent context needs at least two distinct children")
        self.concept_split = split_concepts(
            self.node_id,
            (form.concept_id for form in self.all_forms),
            held_out_share=self.held_out_share,
        )

    @property
    def child_ids(self) -> tuple[str, ...]:
        return tuple(lexicon.variety_id for lexicon in self.child_lexicons)

    @property
    def all_forms(self) -> tuple[LexicalForm, ...]:
        return tuple(form for lexicon in self.child_lexicons for form in lexicon.forms)

    @property
    def available_lexicons(self) -> tuple[LanguageLexicon, ...]:
        """Every node this session can see, for counting attestation.

        Falls back to the active children when no evidence set was supplied. A
        traversal always supplies one — it holds every observed leaf and every
        node already reconstructed — but a context built directly still has
        children, and reporting "attested in 0 of 0 nodes" for a segment the
        children plainly show would be a worse answer than a narrow one.
        """
        if self.evidence:
            return tuple(item.lexicon for item in self.evidence)
        return self.child_lexicons

    @property
    def active_anchors(self) -> tuple[LexicalForm, ...]:
        """Anchors available to deterministic tools under the selected policy."""
        if self.anchor_policy is AnchorPolicy.IGNORE:
            return ()
        return self.anchors

    def evidence_lexicon(
        self,
        node_id: str,
        overlay_id: str | None = None,
    ) -> LanguageLexicon:
        if node_id in self.child_ids:
            return self.lexicon(node_id, overlay_id)
        try:
            return next(item.lexicon for item in self.evidence if item.node_id == node_id)
        except StopIteration as error:
            raise ToolInputError(
                f"unknown or unavailable evidence node {node_id!r}",
                code="unknown-node",
            ) from error

    def forms_for_overlay(self, overlay_id: str | None) -> dict[str, LexicalForm]:
        forms = {form.form_id: form for form in self.all_forms}
        if overlay_id is None:
            return forms
        try:
            forms.update(self.overlays[overlay_id])
        except KeyError as error:
            raise ToolInputError(
                f"unknown segmentation overlay {overlay_id!r}",
                code="unknown-overlay",
            ) from error
        return forms

    def lexicon(self, child_id: str, overlay_id: str | None = None) -> LanguageLexicon:
        try:
            original = next(
                lexicon for lexicon in self.child_lexicons if lexicon.variety_id == child_id
            )
        except StopIteration as error:
            raise ToolInputError(
                f"unknown child {child_id!r}",
                code="unknown-node",
            ) from error
        forms = self.forms_for_overlay(overlay_id)
        return original.model_copy(
            update={"forms": tuple(forms[form.form_id] for form in original.forms)}
        )

    def store_overlay(
        self,
        forms: tuple[LexicalForm, ...],
        *,
        base_overlay_id: str | None,
    ) -> str:
        base = dict(self.overlays.get(base_overlay_id, {})) if base_overlay_id else {}
        base.update({form.form_id: form for form in forms})
        material = "\n".join(
            f"{form_id}\t{' '.join(form.segments)}"
            for form_id, form in sorted(base.items())
        )
        overlay_id = f"seg-{hashlib.sha256(material.encode()).hexdigest()[:12]}"
        self.overlays[overlay_id] = base
        return overlay_id

    def alignment_overrides(
        self,
        overlay_id: str | None,
    ) -> tuple[AlignmentOverride, ...]:
        """Every override an alignment overlay carries, in concept order."""
        if overlay_id is None:
            return ()
        try:
            overrides = self.alignment_overlays[overlay_id]
        except KeyError as error:
            raise ToolInputError(
                f"unknown alignment overlay {overlay_id!r}",
                code="unknown-overlay",
            ) from error
        return tuple(overrides[concept_id] for concept_id in sorted(overrides))

    def store_alignment_overlay(
        self,
        overrides: tuple[AlignmentOverride, ...],
        *,
        base_overlay_id: str | None,
    ) -> str:
        """Record one immutable alignment overlay and return its ID.

        Cumulative over a base, exactly as `store_overlay` is: a session that
        repairs three concepts in three calls ends with one overlay carrying all
        three, so a commit cites one ID rather than reconciling several.
        """
        base = (
            dict(self.alignment_overlays[base_overlay_id])
            if base_overlay_id is not None
            else {}
        )
        if base_overlay_id is not None and base_overlay_id not in self.alignment_overlays:
            raise ToolInputError(
                f"unknown alignment overlay {base_overlay_id!r}",
                code="unknown-overlay",
            )
        base.update({override.concept_id: override for override in overrides})
        material = "\n".join(
            f"{concept_id}\t"
            + "|".join(
                " ".join("Ø" if segment is None else segment for segment in row)
                for row in override.rows
            )
            for concept_id, override in sorted(base.items())
        )
        overlay_id = f"aln-{hashlib.sha256(material.encode()).hexdigest()[:12]}"
        self.alignment_overlays[overlay_id] = base
        return overlay_id
