"""The measurement scripts must measure the checkout they live in.

`python tools/oracle_ceiling.py` puts `tools/` on `sys.path[0]`, not the
repository root, so `import cognate_reconstruction` falls through to the
installed distribution — which under an editable install is whatever checkout was
installed, not necessarily this one. A before/after comparison run from a `git
worktree` of an older revision then measures the working tree twice and reports
no difference, silently. `tools/_bootstrap.py` exists to prevent that, and this
pins it.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"

BOOTSTRAPPED_SCRIPTS = (
    "oracle_ceiling.py",
    "tiebreak_probe.py",
    "correspondence_inventory.py",
    "branch_recoverability.py",
    "outgroup_probe.py",
)


def test_every_measurement_script_binds_to_its_own_checkout() -> None:
    for name in BOOTSTRAPPED_SCRIPTS:
        source = (TOOLS / name).read_text(encoding="utf-8")
        bootstrap = source.index("import _bootstrap")
        package = source.index("from cognate_reconstruction")
        assert bootstrap < package, (
            f"{name} imports cognate_reconstruction before _bootstrap, so the "
            "path fix cannot take effect"
        )


def test_running_a_script_resolves_the_package_next_to_it() -> None:
    """Run as a script, exactly as the documented invocation does."""
    probe = TOOLS / "_bootstrap_probe.py"
    probe.write_text(
        "import _bootstrap  # noqa: F401\n"
        "import cognate_reconstruction\n"
        "print(cognate_reconstruction.__file__)\n",
        encoding="utf-8",
    )
    try:
        completed = subprocess.run(
            [sys.executable, str(probe)],
            capture_output=True,
            text=True,
            check=True,
            # A working directory that is not the repository, so nothing but the
            # bootstrap can put this checkout on the path.
            cwd=probe.parent.parent.parent,
        )
    finally:
        probe.unlink()
    resolved = Path(completed.stdout.strip()).resolve()
    assert resolved == (REPO_ROOT / "cognate_reconstruction" / "__init__.py").resolve()
