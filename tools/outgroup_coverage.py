"""How much of what a node committed was ever checked against anything outside it?

`tools/outgroup_probe.py` asks whether out-group evidence *could* separate
candidates the scorer breaks blindly. This asks the prior question about live
runs: **when a node committed, how much of what it committed had out-group
evidence retrieved for it?**

§7.17 and §7.19 of `docs/proto_inventory_design.md` measured that the three
*browsing* tools — `search_forms(scope="available_tree")`,
`list_available_nodes`, `get_node_reconstruction` — account for about 2% of all
tool calls, and read that as the model not reaching for material outside its own
group. That reading is incomplete in both directions, and this script exists to
say so with numbers rather than with an argument.

**Per node, the reaching is complete.** `polarize` is the *structured*
out-group tool: it takes one correspondence the model already holds and reports
what every node outside the active children shows in the same columns. On the
banked Polynesian sweep every one of the 18 non-root nodes called it and every
one got an out-group back. Not 14% of nodes — all of them.

**Per correspondence, the reaching is thin.** Each call covers exactly one
correspondence, and a node commits many. That ratio is the number this script
reports and it is the one that bears on whether widening the evidence view
changes anything:

    polynesian, inventory, 3 seeds :  28 calls against 254 committed sets = 11.0%
    burmish,    inventory, 3 seeds :  12 calls against  78 committed sets = 15.4%
    burmish,    cascade,   3 seeds :   6 calls against  12 committed rules = 50.0%

So under the inventory shape roughly **six of every seven committed
correspondence sets were committed with no out-group evidence retrieved for that
set.** The model is not failing to look outside; it is looking outside once and
committing fifteen times.

**The gap between the shapes is the part worth carrying away.** The cascade
commits few units and polarizes about half of them. The inventory commits about
six times as many units per node for twice the polarize calls, so per-unit
coverage falls from 50% to 15%. That is mechanical rather than behavioural — a
model that inspects one correspondence and then commits an inventory covering
fifteen has looked outside exactly as often as one that inspects one and commits
one rule. It is worth reading beside §7.20's copy rates, which split the same
way and on the same sweeps, without treating either as explaining the other:
n is small and nodes within a seed are not independent.

Two things this deliberately does not do. It does not read a
`directionality_rationale`'s prose — every count here is structural, from the
tool result's own `relation` tag, for the reason `polarize`'s docstring gives.
And it does not treat a low ratio as a defect: a node may have one correspondence
whose direction is in doubt and fourteen that are not, and nothing here can tell
that from fourteen unexamined ones. It is a coverage measure, and coverage is
the denominator a change to the evidence view has to move.

**The root is excluded from the per-node figures and reported apart.** Nothing
lies outside the root, so every available node there is a descendant and no call
can return an out-group. Pooling the root with the rest reads as a failure to
retrieve evidence when it is the absence of evidence to retrieve.

Usage:
    python tools/outgroup_coverage.py runs/sweeps/polynesian-after-toolstep
    python tools/outgroup_coverage.py runs/sweeps/burmish-* --json
"""

from __future__ import annotations

import argparse
import glob
import json
import os

import _bootstrap  # noqa: F401  (bind to this checkout; see module)

# The tools that require the model to decide, unprompted, that material outside
# the active children is worth fetching. §7.17's finding is about these.
BROWSING_TOOLS = ("search_forms", "list_available_nodes", "get_node_reconstruction")
# The tool that answers one question about one correspondence the model already
# holds. The distinction between this and the three above is the whole point.
STRUCTURED_TOOL = "polarize"


def _seed_dirs(references):
    """Same walk `identity_commit_probe.py` uses; kept local, not imported.

    The `tools/` scripts are independent implementations on purpose, so a defect
    in one does not propagate into the instrument that would catch it.
    """
    seen = []
    for reference in references:
        for path in sorted(glob.glob(reference)):
            if os.path.isfile(os.path.join(path, "trajectories.jsonl")):
                seen.append(path)
                continue
            for child in sorted(glob.glob(os.path.join(path, "seed-*"))):
                if os.path.isfile(os.path.join(child, "trajectories.jsonl")):
                    seen.append(child)
    return seen


def _root_node_id(run_dir):
    """The last node the traversal reached, which is the root it reconstructed.

    Read from `result.json` where there is one. A run that failed before writing
    it has no known root, and every node in it is then treated as below the
    root — which is the safe direction: it can only make the coverage figure
    look worse, never better.
    """
    path = os.path.join(run_dir, "result.json")
    if not os.path.isfile(path):
        return None
    result = json.loads(open(path, encoding="utf-8").read())
    nodes = [node["node_id"] for node in result.get("internal_nodes", ())]
    return nodes[-1] if nodes else None


def _tool_messages(record):
    for message in record.get("messages", ()):
        if message.get("role") == "tool":
            yield message


def _returned_an_outgroup(message):
    """Structural, from the tool result's own `relation` tag.

    A rejected call carries `error` instead of `result` and reports no nodes, so
    it counts as a call that retrieved nothing — which is what it is.
    """
    try:
        envelope = json.loads(message.get("content") or "{}")
    except json.JSONDecodeError:
        return False
    nodes = (envelope.get("result") or {}).get("nodes") or []
    return any(
        isinstance(node, dict) and node.get("relation") == "outgroup"
        for node in nodes
    )


def rows(run_dirs):
    out = []
    for run_dir in run_dirs:
        root = _root_node_id(run_dir)
        path = os.path.join(run_dir, "trajectories.jsonl")
        for line in open(path, encoding="utf-8"):
            record = json.loads(line)
            metrics = record.get("metrics") or {}
            commit = record.get("committed_reconstruction")
            calls = [m for m in _tool_messages(record) if m.get("name") == STRUCTURED_TOOL]
            browsing = sum(
                1
                for m in _tool_messages(record)
                if m.get("name") in BROWSING_TOOLS
            )
            out.append(
                {
                    "run_dir": run_dir,
                    "node_id": record.get("node_id"),
                    "is_root": record.get("node_id") == root,
                    "committed": commit is not None,
                    # Under an inventory this is the number of correspondence
                    # sets; under a cascade, of rules. §12.2 fixed the meaning
                    # and kept the name, so the shape is reported beside it.
                    "commit_shape": (commit or {}).get("commit_shape"),
                    "committed_units": (
                        metrics.get("committed_rule_count", 0) if commit else 0
                    ),
                    "polarize_calls": len(calls),
                    "polarize_calls_with_outgroup": sum(
                        1 for m in calls if _returned_an_outgroup(m)
                    ),
                    "browsing_calls": browsing,
                    "tool_calls": metrics.get("tool_call_count", 0),
                }
            )
    return out


def summarize(all_rows):
    below = [row for row in all_rows if not row["is_root"]]
    root = [row for row in all_rows if row["is_root"]]
    committed_below = [row for row in below if row["committed"]]
    units = sum(row["committed_units"] for row in committed_below)
    calls = sum(row["polarize_calls"] for row in committed_below)
    return {
        "node_records": len(all_rows),
        "below_the_root": len(below),
        "root_records": len(root),
        # The §7.17 reading, per node rather than per call.
        "below_the_root_calling_polarize": sum(1 for r in below if r["polarize_calls"]),
        "below_the_root_receiving_an_outgroup": sum(
            1 for r in below if r["polarize_calls_with_outgroup"]
        ),
        "below_the_root_using_a_browsing_tool": sum(
            1 for r in below if r["browsing_calls"]
        ),
        # The reading this script exists for.
        "committed_units_below_the_root": units,
        "polarize_calls_below_the_root": calls,
        "correspondence_coverage": calls / units if units else None,
        "total_tool_calls": sum(row["tool_calls"] for row in all_rows),
        "browsing_calls": sum(row["browsing_calls"] for row in all_rows),
        "polarize_calls": sum(row["polarize_calls"] for row in all_rows),
    }


def run(references, as_json):
    run_dirs = _seed_dirs(references)
    if not run_dirs:
        raise SystemExit(f"no run directory with trajectories.jsonl under {references}")
    all_rows = rows(run_dirs)
    summary = summarize(all_rows)
    if as_json:
        _bootstrap.emit_json(
            {
                **_bootstrap.measurement_envelope(),
                "measurement": "outgroup_coverage",
                "run_dirs": run_dirs,
                "summary": summary,
                "rows": all_rows,
            }
        )
        return 0
    print(f"measuring: {_bootstrap.loaded_package_path()}")
    print(f"runs: {len(run_dirs)}   node records: {summary['node_records']}")
    print()
    print("  per node, below the root (the root can retrieve no out-group at all):")
    below = summary["below_the_root"]
    print(
        f"    called polarize            {summary['below_the_root_calling_polarize']:>3}"
        f"/{below}"
    )
    print(
        f"    got an out-group back      "
        f"{summary['below_the_root_receiving_an_outgroup']:>3}/{below}"
    )
    print(
        f"    used a browsing tool       "
        f"{summary['below_the_root_using_a_browsing_tool']:>3}/{below}"
        "   (search_forms, list_available_nodes, get_node_reconstruction)"
    )
    print()
    print("  per correspondence, below the root — the number a wider evidence view")
    print("  would have to move:")
    coverage = summary["correspondence_coverage"]
    print(
        f"    committed sets or rules    "
        f"{summary['committed_units_below_the_root']:>4}"
    )
    print(f"    polarize calls             {summary['polarize_calls_below_the_root']:>4}")
    print(
        f"    coverage                   "
        + (f"{coverage:>7.1%}" if coverage is not None else "      n/a")
        + "   share of committed units with out-group evidence retrieved"
    )
    print()
    print("  share of all tool calls:")
    total = summary["total_tool_calls"] or 1
    print(
        f"    polarize                   {summary['polarize_calls']:>4}"
        f"  {summary['polarize_calls']/total:>6.1%}"
    )
    print(
        f"    browsing tools             {summary['browsing_calls']:>4}"
        f"  {summary['browsing_calls']/total:>6.1%}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dirs", nargs="+", help="Run or sweep directories; globs allowed.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return run(args.run_dirs, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
