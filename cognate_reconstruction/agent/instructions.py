"""Load the versioned behavioral instructions packaged with the agent."""

from __future__ import annotations

from importlib.resources import files

_STORED_HYPOTHESIS_V2_ADDENDUM = """

## Incremental Hypothesis Patching & Multi-Daughter Survey (stored-hypothesis-v2)

1. Build and revise large inventories incrementally with `base_hypothesis_id` on
   `test_proto_assembly` instead of re-emitting unchanged claims in monolithic
   JSON payloads. Establish `residue_policy` (and `residue_witness_child_id`
   when applicable) plus your initial batch of `shared_claims` or `choices`,
   then pass the returned `hypothesis_id` as `base_hypothesis_id` on subsequent
   calls together with only the delta (`shared_claims`, `choices`,
   `drop_set_ids`, `drop_pattern_ids`, or updated policy/dispositions/restorations).
2. Unchanged commitments, shared claims, overlays, `unit_orders`, and residue
   settings are inherited automatically from `base_hypothesis_id`. Incoming
   `shared_claims` supersede earlier local `choices` on the same `(set_id,
   conditioning)`, and an incoming local `choice` carves a single local
   exception out of an earlier `shared_claim` on the same `conditioning` without
   re-sending the pattern's member list. Never repeat the same `(set_id,
   conditioning)` in both `choices` and `shared_claims` within one call. When
   `missing_commit_requirements` lists sets needing `rationale` or
   `directionality_rationale`, patch `base_hypothesis_id` with only the updated
   claims. Changing `segmentation_overlay_id`, `alignment_overlay_id`, or
   `unit_orders` creates a new `evidence_revision`: re-survey and start a fresh
   preview without `base_hypothesis_id`.
3. On morpheme-sliced or compound-rich datasets, call
   `summarize_correspondences` with `min_attested_children=2` and
   `min_support=1` to inspect multi-daughter singleton correspondences (such as
   sparse phonation, register, or tonal splits) while excluding 1-daughter
   compound/affix noise. Use `min_attested_children=1` only when specifically
   inspecting 1-daughter material against gaps.
"""


def load_agent_instructions(*, inventory_protocol: str = "stored-hypothesis") -> str:
    if inventory_protocol not in {
        "full-payload",
        "stored-hypothesis",
        "stored-hypothesis-v2",
    }:
        raise ValueError("unknown inventory protocol")
    base = (
        files("cognate_reconstruction.agent")
        .joinpath("system_prompt.md")
        .read_text(encoding="utf-8")
    )
    if inventory_protocol == "stored-hypothesis-v2":
        return base.rstrip("\n") + _STORED_HYPOTHESIS_V2_ADDENDUM
    return base
