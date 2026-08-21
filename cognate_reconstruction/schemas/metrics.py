"""A reusable summary of one metric's spread over many measurements."""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from pydantic import Field

from cognate_reconstruction.schemas.common import WorkbenchModel


class MetricDistribution(WorkbenchModel):
    """Mean, spread, and quartiles for one metric over a set of measurements.

    A pooled mean cannot distinguish a family whose root is good and whose lower
    nodes are bad from a uniformly mediocre one, and that is exactly the
    distinction a reader of a reconstruction report needs. Every aggregate in
    this repository that reports a mean should carry one of these beside it.

    Quartiles use `statistics.quantiles(..., method="inclusive")`, so a single
    measurement reports itself at every quantile rather than raising.
    """

    count: int = Field(ge=0)
    mean: float
    standard_deviation: float = Field(ge=0.0)
    minimum: float
    p25: float
    median: float
    p75: float
    maximum: float

    @classmethod
    def of(cls, values: Sequence[float]) -> "MetricDistribution | None":
        """Summarize `values`, or `None` when there is nothing to summarize.

        `None` rather than a zeroed record: a metric nobody measured and a
        metric measured as zero are different facts, and collapsing them is how
        an empty run comes to read as a perfect one.
        """
        materialized = [float(value) for value in values]
        if not materialized:
            return None
        ordered = sorted(materialized)
        if len(ordered) == 1:
            quartiles = [ordered[0], ordered[0], ordered[0]]
        else:
            quartiles = statistics.quantiles(ordered, n=4, method="inclusive")
        return cls(
            count=len(ordered),
            mean=statistics.fmean(ordered),
            standard_deviation=(
                statistics.stdev(ordered) if len(ordered) > 1 else 0.0
            ),
            minimum=ordered[0],
            p25=quartiles[0],
            median=quartiles[1],
            p75=quartiles[2],
            maximum=ordered[-1],
        )

    def compact(self) -> str:
        """One line: mean, spread, and range, for a text report."""
        return (
            f"mean {self.mean:.3f} (sd {self.standard_deviation:.3f}, "
            f"median {self.median:.3f}, range {self.minimum:.3f}–"
            f"{self.maximum:.3f}, n={self.count})"
        )
