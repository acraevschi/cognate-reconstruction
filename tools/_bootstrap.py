"""Make these scripts measure the checkout they live in.

`python tools/oracle_ceiling.py` puts `tools/` on `sys.path[0]` — not the
repository root — so `import cognate_reconstruction` falls through to the
installed distribution. With the usual editable install that resolves to
whatever checkout was installed, which is *not* necessarily the one holding the
script.

That silently breaks the one job these scripts have. Running the oracle from a
`git worktree` of an older commit to get a before/after baseline measures the
working tree instead, twice, and reports a difference of zero — which is exactly
what happened while the branch-support change was being measured, and it took a
per-node beam diff to notice.

Importing this module first puts the repository root ahead of everything else,
binding each script to the source next to it. Import it for the side effect,
before any `cognate_reconstruction` import:

    import _bootstrap  # noqa: F401
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

if str(REPO_ROOT) in sys.path:
    sys.path.remove(str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT))


def loaded_package_path() -> str:
    """Where `cognate_reconstruction` was actually imported from.

    Printed by the measurement tools so a recorded number always says which
    source produced it, rather than leaving it to be inferred from the shell
    prompt.
    """
    import cognate_reconstruction

    return str(Path(cognate_reconstruction.__file__).resolve().parent)


def resolve_benchmark(reference: str):
    """Interpret a script argument as a benchmark name or a payload path.

    Added so the analysis scripts and the multi-seed runner name a benchmark
    the same way the CLI does. Delegates to the package registry rather than
    reimplementing the convention, so a definition added under `benchmarks/`
    is immediately usable from every script.
    """
    from pathlib import Path as _Path

    from cognate_reconstruction.benchmarks import resolve_payload

    return _Path(resolve_payload(reference))


def measurement_envelope(benchmark_path=None) -> dict:
    """The provenance every recorded measurement has to carry.

    `measuring` is not decoration. `sys.path` used to resolve
    `cognate_reconstruction` through the editable install rather than the
    checkout beside the script, so a measurement taken in a `git worktree` of an
    older commit silently measured the working tree. The text output names the
    source it bound to; a `--json` mode that dropped that line would reintroduce
    the bug at one remove, and a machine consumer is exactly the reader least
    able to notice.
    """
    envelope = {"measuring": loaded_package_path()}
    if benchmark_path is not None:
        envelope["benchmark"] = str(benchmark_path)
    return envelope


def emit_json(payload: dict) -> None:
    import json as _json

    print(_json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
