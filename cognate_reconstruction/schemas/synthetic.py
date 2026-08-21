"""Declarative definition and answer key for a generated language family.

Every published benchmark in this repository has a leakage problem: a model
that has read the literature on Polynesian can produce `*ʔ` from memory rather
than from the correspondence set, and Latin is in everyone's training data. A
synthetic family is the one evaluation a model cannot have memorized, because
the proto-lexicon and the sound changes were written here.

What that buys, beyond a clean accuracy, is two measurements no published gold
can support:

- **the changes themselves are known**, so a committed cascade can be scored
  against the true one and a run that reached the right forms via the wrong
  changes is distinguishable from one that got both;
- **the direction is known by construction** — the branch that innovated is the
  branch the definition gave a rule to — so the directionality claim prompt 04
  forces the model to state, and which the harness deliberately never grades,
  can finally be checked without reading the prose.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from cognate_reconstruction.schemas.common import NonEmptyStr, WorkbenchModel
from cognate_reconstruction.schemas.lexicon import LanguageLexicon


class SyntheticProtoForm(WorkbenchModel):
    concept_id: NonEmptyStr
    segments: tuple[NonEmptyStr, ...] = Field(min_length=1)
    gloss: NonEmptyStr | None = None


class SyntheticBranchCascade(WorkbenchModel):
    """The ordered changes on the branch leading *to* `node_id`.

    A branch is named by its lower end, so a cascade on an internal node is a
    shared innovation inherited by everything below it. That is what makes
    subgrouping recoverable from the data rather than merely asserted by the
    tree.

    Rules run **forward**, parent to child — the opposite of the child-to-parent
    direction the harness commits — which is exactly why `RuleEngine` can
    generate a family: it applies an ordered literal cascade and does not care
    which way history runs.
    """

    node_id: NonEmptyStr
    rules: tuple[NonEmptyStr, ...] = ()
    inverse_rules: tuple[NonEmptyStr, ...] | None = None
    """Override for the child-to-parent cascade that undoes `rules`.

    The generator derives one automatically and verifies it against the actual
    forms; supply this only when the derived inverse fails and a
    context-sensitive one succeeds. A branch whose inverse cannot be verified is
    recorded as non-invertible rather than being silently trusted.
    """
    note: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_cascade(self) -> "SyntheticBranchCascade":
        if self.inverse_rules is not None and not self.rules:
            raise ValueError(
                "a branch with no rules has nothing to invert"
            )
        return self


class SyntheticNoise(WorkbenchModel):
    """Controlled residue, off by default and never accidental.

    A benchmark with no residue is not a test of the anomaly machinery, and a
    model that only ever sees perfect regularity learns the wrong lesson about
    what a comparative argument looks like. Every perturbation is recorded in
    the answer key, so a run's `anomalies` can be scored against what was
    actually done rather than against a guess.
    """

    seed: int = 0
    irregular_forms: int = Field(default=0, ge=0)
    """Forms in which one segment is replaced by another from the inventory."""
    loans: int = Field(default=0, ge=0)
    """Forms replaced by a sister branch's form, which is what a loan looks
    like from inside a correspondence set: a shape that belongs to the wrong
    branch."""
    semantic_mismatches: int = Field(default=0, ge=0)
    """Pairs of concepts whose forms are swapped in one daughter."""

    @property
    def enabled(self) -> bool:
        return bool(
            self.irregular_forms or self.loans or self.semantic_mismatches
        )


class SyntheticFamilyDefinition(WorkbenchModel):
    schema_version: Literal["1.0"] = "1.0"
    name: NonEmptyStr
    description: NonEmptyStr
    newick: NonEmptyStr
    proto_lexicon: tuple[SyntheticProtoForm, ...] = Field(min_length=2)
    branches: tuple[SyntheticBranchCascade, ...] = ()
    hidden_target_node_ids: tuple[NonEmptyStr, ...] = ()
    """Internal nodes bound as hidden gold; empty means the root alone.

    Every internal node's lexicon is known here, so binding several of them
    costs nothing and turns one family into a per-node accuracy curve.
    """
    noise: SyntheticNoise = Field(default_factory=SyntheticNoise)

    @model_validator(mode="after")
    def validate_family(self) -> "SyntheticFamilyDefinition":
        concepts = [form.concept_id for form in self.proto_lexicon]
        if len(concepts) != len(set(concepts)):
            raise ValueError("proto-lexicon concept IDs must be unique")
        nodes = [branch.node_id for branch in self.branches]
        if len(nodes) != len(set(nodes)):
            raise ValueError("each branch may be declared once")
        return self


class SyntheticBranchAnswer(WorkbenchModel):
    """The truth about one branch: what changed, and whether anything did."""

    node_id: NonEmptyStr
    parent_node_id: NonEmptyStr
    is_leaf: bool
    rules: tuple[NonEmptyStr, ...] = ()
    """The forward, parent-to-child cascade, in order."""
    inverse_rules: tuple[NonEmptyStr, ...] = ()
    """A child-to-parent cascade verified to recover the parent's forms."""
    invertible: bool
    """Whether `inverse_rules` was verified to recover every parent form.

    False for any branch containing a deletion: the DSL has no empty-target
    insertion, so a lost segment can never be restored by a rule. Such a branch
    is not unfair — the harness recovers the segment from a sister that kept it,
    through the beam — but no rule scoped to *this* branch can do it.
    """
    innovated: bool
    """Did this branch change anything at all?

    The measurement prompt 04 could not make: a rule the model scoped to a
    branch whose answer here is `False` is a rule pointed at a branch that did
    not change, whatever its `directionality_rationale` says.
    """


class SyntheticNoiseRecord(WorkbenchModel):
    kind: Literal["irregular_form", "loan", "semantic_mismatch"]
    node_id: NonEmptyStr
    concept_id: NonEmptyStr
    detail: NonEmptyStr


class SyntheticAnswerKey(WorkbenchModel):
    """Everything the model must not see, written where the payload is not.

    Kept a separate artifact on purpose. A key embedded in the payload — even in
    a field the prompt builder happens not to read today — is one refactor away
    from being the answer in the context window.
    """

    schema_version: Literal["1.0"] = "1.0"
    name: NonEmptyStr
    description: NonEmptyStr
    newick: NonEmptyStr
    proto_node_id: NonEmptyStr
    node_lexicons: tuple[LanguageLexicon, ...]
    """Every node's forms, internal nodes included, **before noise**.

    The regular output of the cascade, which is what a committed cascade should
    be scored against: a rule cannot be expected to undo a perturbation the
    definition introduced on purpose. `noise_records` names every leaf form that
    therefore differs from the payload the model actually saw.
    """
    branches: tuple[SyntheticBranchAnswer, ...]
    noise: SyntheticNoise
    noise_records: tuple[SyntheticNoiseRecord, ...] = ()

    def branch(self, node_id: str) -> SyntheticBranchAnswer | None:
        for answer in self.branches:
            if answer.node_id == node_id:
                return answer
        return None
