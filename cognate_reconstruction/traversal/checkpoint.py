"""Atomic family-run checkpoints at completed internal-node boundaries."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from cognate_reconstruction.schemas.common import NonEmptyStr, WorkbenchModel
from cognate_reconstruction.schemas.traversal import ReconstructionStep

CHECKPOINT_SCHEMA_VERSION = "1.0"


class FamilyCheckpoint(WorkbenchModel):
    schema_version: Literal["1.0"] = CHECKPOINT_SCHEMA_VERSION
    run_id: NonEmptyStr
    input_sha256: NonEmptyStr
    configuration_sha256: NonEmptyStr
    normalized_tree_sha256: NonEmptyStr
    configuration_components: dict[str, NonEmptyStr] = Field(
        default_factory=dict,
        description=(
            "Named digests of the configuration parts, so a resume can say "
            "which one changed. Defaulted and purely explanatory: "
            "'configuration_sha256' remains the decision, and a checkpoint "
            "written without these still resumes or refuses on it. Most "
            "components are parts of that hash; the advisory ones (see "
            "cli.ADVISORY_CONFIGURATION_COMPONENTS) are deliberately not, and "
            "are recorded here so a resume can report a change that does not "
            "block it."
        ),
    )
    completed_steps: tuple[ReconstructionStep, ...] = ()

    @model_validator(mode="after")
    def validate_unique_nodes(self) -> FamilyCheckpoint:
        node_ids = [step.parent_node_id for step in self.completed_steps]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("checkpoint contains duplicate completed node IDs")
        return self

    def with_step(self, step: ReconstructionStep) -> FamilyCheckpoint:
        if step.parent_node_id in {
            item.parent_node_id for item in self.completed_steps
        }:
            raise ValueError(
                f"checkpoint already contains node {step.parent_node_id!r}"
            )
        return self.model_copy(
            update={"completed_steps": (*self.completed_steps, step)}
        )

    @property
    def steps_by_node(self) -> dict[str, ReconstructionStep]:
        return {step.parent_node_id: step for step in self.completed_steps}


class CheckpointStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> FamilyCheckpoint:
        try:
            content = self.path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise ValueError(f"checkpoint does not exist: {self.path}") from error
        try:
            return FamilyCheckpoint.model_validate_json(content)
        except Exception as error:
            raise ValueError(f"invalid checkpoint {self.path}: {error}") from error

    def save(self, checkpoint: FamilyCheckpoint) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.tmp"
        )
        temporary.write_text(
            checkpoint.model_dump_json(
                indent=2,
                exclude_computed_fields=True,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
