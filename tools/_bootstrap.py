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
