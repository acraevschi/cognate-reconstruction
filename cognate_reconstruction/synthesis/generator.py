"""Run a sound-change cascade forward, parent to child, and emit the family.

The harness already contains everything this needs. `RuleEngine.apply_rules`
applies an ordered literal cascade and has no opinion about which direction
history runs, so pointing it down the tree instead of up produces daughters
from a proto-lexicon. `parse_rule` is the same DSL the model commits in, which
means a synthetic family is expressed in exactly the language a reconstruction
has to be expressed in — and a change the DSL cannot state is a change this
generator cannot make either, which is the right constraint rather than a
limitation to work around.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from cognate_reconstruction.ingestion.service import ingest_payload
from cognate_reconstruction.rules.engine import RuleEngine
from cognate_reconstruction.rules.parser import NoOpRuleError, parse_rule
from cognate_reconstruction.schemas.historical import (
    GoldEvidenceKind,
    HistoricalFormBinding,
    HistoricalFormRole,
)
from cognate_reconstruction.schemas.ingestion import WorkbenchPayload
from cognate_reconstruction.schemas.lexicon import (
    ConceptMetadata,
    LanguageLexicon,
    LexicalForm,
)
from cognate_reconstruction.schemas.synthetic import (
    SyntheticAnswerKey,
    SyntheticBranchAnswer,
    SyntheticFamilyDefinition,
    SyntheticNoiseRecord,
)
from cognate_reconstruction.tree import (
    TreeNode,
    assign_node_ids,
    parse_newick,
    validate_unique_leaf_labels,
)


@dataclass(frozen=True)
class SyntheticBuildResult:
    payload: WorkbenchPayload
    answer_key: SyntheticAnswerKey

    def summary(self) -> str:
        leaves = len(self.payload.lexicons)
        innovating = sum(
            answer.innovated for answer in self.answer_key.branches
        )
        non_invertible = [
            answer.node_id
            for answer in self.answer_key.branches
            if answer.innovated and not answer.invertible
        ]
        line = (
            f"{self.answer_key.name}: {leaves} daughters, "
            f"{len(self.payload.concepts)} concepts, "
            f"{innovating} of {len(self.answer_key.branches)} branches "
            "innovated"
        )
        if non_invertible:
            line += (
                "; no child-to-parent cascade can undo "
                + ", ".join(non_invertible)
                + " (the DSL has no insertion, so a deleted segment is "
                "recoverable only from a sister branch)"
            )
        if self.answer_key.noise.enabled:
            line += f"; {len(self.answer_key.noise_records)} noise perturbation(s)"
        return line


def _form(
    node_id: str,
    concept_id: str,
    segments: tuple[str, ...],
    *,
    cognate_set_id: str,
) -> LexicalForm:
    return LexicalForm(
        form_id=f"{node_id}:{concept_id}",
        variety_id=node_id,
        concept_id=concept_id,
        segments=segments,
        cognate_set_id=cognate_set_id,
    )


def _invert(rule_text: str) -> str | None:
    """The obvious child-to-parent spelling of a forward rule, or None.

    `a > b / X_Y` becomes `b > a / X_Y`. This is a *candidate*, never a claim:
    it is wrong whenever the parent already contained the replacement segment,
    or the environment was itself altered by another rule in the cascade. The
    caller verifies every derived inverse against the real forms and keeps it
    only if it reproduces them exactly.

    Returns None for a deletion, because the DSL has no empty-target insertion
    and there is nothing to spell.
    """
    parsed = parse_rule(rule_text)
    if not parsed.replacement.tokens:
        return None
    left = " ".join(parsed.environment.left.tokens) if parsed.environment.left else ""
    right = (
        " ".join(parsed.environment.right.tokens)
        if parsed.environment.right
        else ""
    )
    if parsed.environment.word_initial:
        left = f"# {left}".strip()
    if parsed.environment.word_final:
        right = f"{right} #".strip()
    environment = ""
    if left or right or parsed.environment.word_initial or parsed.environment.word_final:
        environment = f" / {left}_{right}".rstrip()
    inverted = (
        f"{' '.join(parsed.replacement.tokens)} > "
        f"{' '.join(parsed.target.tokens)}{environment}"
    )
    try:
        parse_rule(inverted)
    except (NoOpRuleError, ValueError):
        return None
    return inverted


def _apply(
    engine: RuleEngine,
    rule_texts: tuple[str, ...],
    forms: tuple[LexicalForm, ...],
) -> tuple[LexicalForm, ...]:
    if not rule_texts:
        return forms
    parsed = tuple(parse_rule(text) for text in rule_texts)
    transformed, _ = engine.apply_rules(parsed, forms)
    return transformed


def _verified_inverse(
    engine: RuleEngine,
    parent_forms: tuple[LexicalForm, ...],
    child_forms: tuple[LexicalForm, ...],
    candidate: tuple[str, ...] | None,
) -> tuple[tuple[str, ...], bool]:
    """Keep an inverse cascade only if it actually recovers the parent forms.

    This is the soundness check the whole synthetic benchmark rests on. If the
    declared inverse of a branch does not reproduce the parent, then a model
    that committed exactly the right rules would still be scored wrong, and
    every number built on the family would be meaningless.
    """
    if candidate is None:
        return (), False
    recovered = _apply(engine, candidate, child_forms)
    expected = {form.concept_id: form.segments for form in parent_forms}
    ok = all(
        expected.get(form.concept_id) == form.segments for form in recovered
    ) and len(recovered) == len(parent_forms)
    return (candidate, True) if ok else ((), False)


def _perturb(
    definition: SyntheticFamilyDefinition,
    leaf_forms: dict[str, list[LexicalForm]],
) -> tuple[SyntheticNoiseRecord, ...]:
    """Apply the controlled residue, deterministically in the declared seed."""
    noise = definition.noise
    if not noise.enabled:
        return ()
    rng = random.Random(noise.seed)
    node_ids = sorted(leaf_forms)
    inventory = sorted(
        {
            segment
            for forms in leaf_forms.values()
            for form in forms
            for segment in form.segments
            if segment not in {"+", "-"}
        }
    )
    records: list[SyntheticNoiseRecord] = []

    def index_of(node_id: str, concept_id: str) -> int:
        for index, form in enumerate(leaf_forms[node_id]):
            if form.concept_id == concept_id:
                return index
        raise KeyError(concept_id)

    for _ in range(noise.irregular_forms):
        node_id = rng.choice(node_ids)
        index = rng.randrange(len(leaf_forms[node_id]))
        form = leaf_forms[node_id][index]
        position = rng.randrange(len(form.segments))
        replacement = rng.choice(
            [seg for seg in inventory if seg != form.segments[position]]
            or inventory
        )
        segments = list(form.segments)
        original = segments[position]
        segments[position] = replacement
        leaf_forms[node_id][index] = form.model_copy(
            update={"segments": tuple(segments)}
        )
        records.append(
            SyntheticNoiseRecord(
                kind="irregular_form",
                node_id=node_id,
                concept_id=form.concept_id,
                detail=(
                    f"segment {position} changed {original!r} -> "
                    f"{replacement!r} against the regular cascade"
                ),
            )
        )

    for _ in range(noise.loans):
        if len(node_ids) < 2:
            break
        borrower, donor = rng.sample(node_ids, 2)
        index = rng.randrange(len(leaf_forms[borrower]))
        form = leaf_forms[borrower][index]
        donor_index = index_of(donor, form.concept_id)
        donor_form = leaf_forms[donor][donor_index]
        leaf_forms[borrower][index] = form.model_copy(
            update={"segments": donor_form.segments}
        )
        records.append(
            SyntheticNoiseRecord(
                kind="loan",
                node_id=borrower,
                concept_id=form.concept_id,
                detail=(
                    f"form replaced by {donor}'s shape "
                    f"{' '.join(donor_form.segments)}, so it does not fit this "
                    "branch's correspondences"
                ),
            )
        )

    for _ in range(noise.semantic_mismatches):
        node_id = rng.choice(node_ids)
        if len(leaf_forms[node_id]) < 2:
            break
        first, second = rng.sample(range(len(leaf_forms[node_id])), 2)
        left = leaf_forms[node_id][first]
        right = leaf_forms[node_id][second]
        leaf_forms[node_id][first] = left.model_copy(
            update={"segments": right.segments}
        )
        leaf_forms[node_id][second] = right.model_copy(
            update={"segments": left.segments}
        )
        records.append(
            SyntheticNoiseRecord(
                kind="semantic_mismatch",
                node_id=node_id,
                concept_id=left.concept_id,
                detail=(
                    f"forms for {left.concept_id!r} and {right.concept_id!r} "
                    "are swapped in this daughter"
                ),
            )
        )
    return tuple(records)


def generate_family(
    definition: SyntheticFamilyDefinition,
) -> SyntheticBuildResult:
    """Build daughter lexicons, hidden gold bindings, and the answer key."""
    root = parse_newick(definition.newick)
    validate_unique_leaf_labels(root)
    node_ids = assign_node_ids(root)
    proto_node_id = node_ids[id(root)]
    cascades = {branch.node_id: branch for branch in definition.branches}
    all_node_ids = set(node_ids.values())
    if unknown := sorted(set(cascades) - all_node_ids):
        raise ValueError(
            f"synthetic family {definition.name!r} declares cascades for nodes "
            f"absent from its tree: {unknown}"
        )
    if proto_node_id in cascades:
        raise ValueError(
            "the root has no incoming branch, so it cannot carry a cascade"
        )

    engine = RuleEngine()
    forms_by_node: dict[str, tuple[LexicalForm, ...]] = {
        proto_node_id: tuple(
            _form(
                proto_node_id,
                entry.concept_id,
                entry.segments,
                cognate_set_id=f"{definition.name}:{entry.concept_id}",
            )
            for entry in definition.proto_lexicon
        )
    }
    answers: list[SyntheticBranchAnswer] = []

    def descend(node: TreeNode) -> None:
        parent_id = node_ids[id(node)]
        for child in node.children:
            child_id = node_ids[id(child)]
            cascade = cascades.get(child_id)
            rules = cascade.rules if cascade is not None else ()
            parent_forms = forms_by_node[parent_id]
            child_forms = tuple(
                form.model_copy(
                    update={"form_id": f"{child_id}:{form.concept_id}",
                            "variety_id": child_id}
                )
                for form in _apply(engine, rules, parent_forms)
            )
            forms_by_node[child_id] = child_forms
            declared = cascade.inverse_rules if cascade is not None else None
            if declared is None and rules:
                derived = tuple(
                    inverted
                    for inverted in (_invert(text) for text in reversed(rules))
                    if inverted is not None
                )
                declared = derived if len(derived) == len(rules) else None
            inverse, invertible = _verified_inverse(
                engine, parent_forms, child_forms, declared
            )
            answers.append(
                SyntheticBranchAnswer(
                    node_id=child_id,
                    parent_node_id=parent_id,
                    is_leaf=child.is_leaf,
                    rules=rules,
                    inverse_rules=inverse,
                    # A branch that changed nothing is trivially invertible by
                    # the empty cascade, which is the true child-to-parent
                    # claim for it.
                    invertible=invertible or not rules,
                    innovated=bool(rules),
                )
            )
            descend(child)

    descend(root)

    leaf_ids = sorted(node_ids[id(leaf)] for leaf in root.get_leaves())
    leaf_forms = {
        leaf_id: list(forms_by_node[leaf_id]) for leaf_id in leaf_ids
    }
    noise_records = _perturb(definition, leaf_forms)
    lexicons = tuple(
        LanguageLexicon(
            variety_id=leaf_id,
            name=leaf_id,
            family=definition.name,
            forms=tuple(leaf_forms[leaf_id]),
        )
        for leaf_id in leaf_ids
    )
    concepts = tuple(
        ConceptMetadata(concept_id=entry.concept_id, gloss=entry.gloss)
        for entry in definition.proto_lexicon
    )
    hidden = definition.hidden_target_node_ids or (proto_node_id,)
    if unknown := sorted(set(hidden) - all_node_ids):
        raise ValueError(f"hidden target nodes are not in the tree: {unknown}")
    if leaked := sorted(set(hidden) & set(leaf_ids)):
        raise ValueError(
            f"hidden target nodes must be internal, not observed leaves: {leaked}"
        )
    bindings = tuple(
        HistoricalFormBinding(
            node_id=node_id,
            role=HistoricalFormRole.TARGET,
            # Namespaced away from every leaf ID so the gold can never be
            # mistaken for, or collide with, an observed lexicon.
            source_variety_id=f"synthetic:{definition.name}:{node_id}",
            forms=forms_by_node[node_id],
            source_reference=(
                f"synthetic family {definition.name!r}: gold by construction"
            ),
            gold_evidence_kind=GoldEvidenceKind.SYNTHETIC,
        )
        for node_id in sorted(hidden)
    )
    payload = WorkbenchPayload(
        lexicons=lexicons,
        concepts=concepts,
        newick=definition.newick,
        historical_form_bindings=bindings,
    )
    # Ingest at build time so a malformed definition fails here rather than at
    # the start of a run, and store the normalized tree the traversal will
    # actually walk. This is also what checks that every hidden target resolves
    # to an internal node.
    payload = payload.model_copy(
        update={"newick": ingest_payload(payload).tree.newick}
    )
    answer_key = SyntheticAnswerKey(
        name=definition.name,
        description=definition.description,
        newick=definition.newick,
        proto_node_id=proto_node_id,
        node_lexicons=tuple(
            LanguageLexicon(
                variety_id=node_id,
                name=node_id,
                family=definition.name,
                forms=forms_by_node[node_id],
            )
            for node_id in sorted(forms_by_node)
        ),
        branches=tuple(
            sorted(answers, key=lambda answer: answer.node_id)
        ),
        noise=definition.noise,
        noise_records=noise_records,
    )
    return SyntheticBuildResult(payload=payload, answer_key=answer_key)
