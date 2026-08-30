"""Did a committed node just copy one of its children?

`benchmarks/sweep.py` excludes an evaluation whose node fell back, and the
comment says why: "a fallback node's beam is the harness's identity commit, so
scoring it measures the fallback". This asks the same question of the nodes the
exclusion lets through. A node that *committed* can still hand back a lexicon
byte-identical to one of its children, and nothing in the aggregate says so.

**An identity commit is not proof of a bad reconstruction.** A proto-language
can be genuinely identical to a conservative daughter, and Proto-Polynesian is
close to Tongan for real reasons. What it is: a result indistinguishable, form
for form, from the thing the sweep refuses to score on principle. So the honest
treatment is the one §7.6 of `docs/proto_inventory_design.md` already asks for
the commit rate and the fallback score — publish it beside the accuracy number
rather than deciding what it means.

Two kinds are reported separately, because they say different things:

  * **leaf copy** — the node reproduces an attested daughter. The comparative
    step contributed nothing that a copy would not have.
  * **node copy** — the node reproduces another internal node, which is the
    parent-copies-its-own-child case. On a tree with gold at two depths this is
    condition 6's question answered in the least interesting way.

Agreement is per concept: a concept counts as agreeing when the node's form set
and the other lexicon's form set share a form. The reported fraction is over the
concepts both lexicons carry.

`--baseline` answers the question one step earlier, and needs no run at all:
**what does copying a daughter score against the gold?** That number is the bar
every live figure has to clear before it is evidence of reconstruction, and it
is not currently published anywhere. On Polynesian it is 0.587, which is above
every live figure this repository has recorded. On Burmish it is 0.000 at both
gold nodes, so any non-zero score there is reconstruction rather than copying.

Usage:
    python tools/identity_commit_probe.py burmish runs/sweeps/burmish-after
    python tools/identity_commit_probe.py polynesian runs/sweeps/poly-* --json
    python tools/identity_commit_probe.py burmish <run-dir> --threshold 0.9
    python tools/identity_commit_probe.py polynesian --baseline
"""

from __future__ import annotations

import argparse
import glob
import json
import os

import _bootstrap  # noqa: F401  (bind to this checkout; see module)


def _concept_forms(forms):
    """{concept_id: {form tuples}} — read from JSON, not through the schemas.

    These scripts are independent implementations on purpose, so a defect in
    the typed surface cannot hide from the thing that checks it.
    """
    out: dict[str, set[tuple[str, ...]]] = {}
    for form in forms:
        out.setdefault(str(form["concept_id"]), set()).add(
            tuple(form.get("segments") or ())
        )
    return out


def _agreement(left, right):
    shared = set(left) & set(right)
    if not shared:
        return 0.0, 0
    hits = sum(1 for concept in shared if left[concept] & right[concept])
    return hits / len(shared), len(shared)


def _seed_dirs(references):
    seen = []
    for reference in references:
        for path in sorted(glob.glob(reference)):
            if os.path.isfile(os.path.join(path, "result.json")):
                seen.append(path)
                continue
            for child in sorted(glob.glob(os.path.join(path, "seed-*"))):
                if os.path.isfile(os.path.join(child, "result.json")):
                    seen.append(child)
    return seen


def probe(payload_path, run_dirs, threshold):
    payload = json.loads(open(payload_path, encoding="utf-8").read())
    leaves = {
        lexicon["variety_id"]: _concept_forms(lexicon["forms"])
        for lexicon in payload["lexicons"]
    }
    gold_nodes = {
        binding["node_id"]
        for binding in payload.get("historical_form_bindings", ())
        if binding.get("role") == "target"
    }
    rows = []
    for run_dir in run_dirs:
        result = json.loads(
            open(os.path.join(run_dir, "result.json"), encoding="utf-8").read()
        )
        failed = {
            failure["node_id"] for failure in result.get("node_failures", ())
        }
        nodes = {
            node["node_id"]: _concept_forms(node["best_lexicon"]["forms"])
            for node in result["internal_nodes"]
        }
        scores = {
            evaluation["node_id"]: evaluation
            for evaluation in result.get("historical_target_evaluations", ())
        }
        for node_id, mine in nodes.items():
            if node_id in failed:
                continue
            best_leaf = max(
                ((name,) + _agreement(mine, other) for name, other in leaves.items()),
                key=lambda item: item[1],
                default=("", 0.0, 0),
            )
            best_node = max(
                (
                    (name,) + _agreement(mine, other)
                    for name, other in nodes.items()
                    if name != node_id
                ),
                key=lambda item: item[1],
                default=("", 0.0, 0),
            )
            evaluation = scores.get(node_id)
            rows.append(
                {
                    "run_dir": run_dir,
                    "node_id": node_id,
                    "is_gold_node": node_id in gold_nodes,
                    "closest_leaf": best_leaf[0],
                    "leaf_agreement": best_leaf[1],
                    "closest_node": best_node[0],
                    "node_agreement": best_node[1],
                    "concepts_compared": best_leaf[2] or best_node[2],
                    "leaf_copy": best_leaf[1] >= threshold,
                    "node_copy": best_node[1] >= threshold,
                    "scored_top_exact_rate": (
                        evaluation["top_exact_rate"] if evaluation else None
                    ),
                    "scored": bool(evaluation)
                    and not evaluation.get("failure_fallback", False),
                }
            )
    return rows


def _ned(left, right):
    """Normalized edit distance. Own implementation, per the `tools/` convention."""
    if not left and not right:
        return 0.0
    rows, cols = len(left), len(right)
    row = list(range(cols + 1))
    for i in range(1, rows + 1):
        previous, row[0] = row[0], i
        for j in range(1, cols + 1):
            current = row[j]
            row[j] = min(row[j] + 1, row[j - 1] + 1, previous + (left[i - 1] != right[j - 1]))
            previous = current
    return row[cols] / max(rows, cols, 1)


def best_form_baseline(payload_path):
    """The hard bar: the best attested form per concept, chosen against the gold.

    `copy_baseline` asks what one daughter scores if you copy all of it. This
    asks the stronger question the research owner posed: for each concept
    separately, take whichever daughter form sits closest to the gold, and score
    that composite. It is an **oracle over the daughters** — it reads the answer
    to make its choice, exactly as `oracle_ceiling.py` does — so it bounds what
    *selection among attested forms* can reach, with no reconstruction at all.

    A live figure below this line was beaten by picking an existing word.
    """
    payload = json.loads(open(payload_path, encoding="utf-8").read())
    leaves = {
        lexicon["variety_id"]: _concept_forms(lexicon["forms"])
        for lexicon in payload["lexicons"]
    }
    out = []
    for binding in payload.get("historical_form_bindings", ()):
        if binding.get("role") != "target":
            continue
        gold = _concept_forms(binding.get("forms", ()))
        exact = 0
        scored = 0
        distances = []
        winners: dict[str, int] = {}
        for concept, targets in gold.items():
            best = None
            for name, forms in leaves.items():
                for form in forms.get(concept, ()):
                    distance = min(_ned(list(form), list(target)) for target in targets)
                    if best is None or distance < best[0]:
                        best = (distance, name)
            if best is None:
                continue
            scored += 1
            distances.append(best[0])
            winners[best[1]] = winners.get(best[1], 0) + 1
            if best[0] == 0.0:
                exact += 1
        out.append(
            {
                "node_id": binding["node_id"],
                "concepts": scored,
                "top_exact_rate": exact / scored if scored else 0.0,
                "mean_ned": sum(distances) / len(distances) if distances else 0.0,
                "chosen_from": dict(
                    sorted(winners.items(), key=lambda item: -item[1])
                ),
            }
        )
    return out


def copy_baseline(payload_path):
    """What each daughter scores against each gold node, copied verbatim.

    Read the same way `HistoricalTargetEvaluation` reads a reconstruction: a
    concept counts when any form the daughter carries matches any gold
    alternative. Quoted without that reading the number means nothing.
    """
    payload = json.loads(open(payload_path, encoding="utf-8").read())
    leaves = {
        lexicon["variety_id"]: _concept_forms(lexicon["forms"])
        for lexicon in payload["lexicons"]
    }
    out = []
    for binding in payload.get("historical_form_bindings", ()):
        if binding.get("role") != "target":
            continue
        gold = _concept_forms(binding.get("forms", ()))
        scores = []
        for name, forms in leaves.items():
            rate, shared = _agreement(gold, forms)
            scores.append(
                {"variety_id": name, "top_exact_rate": rate, "concepts": shared}
            )
        scores.sort(key=lambda item: item["top_exact_rate"], reverse=True)
        out.append({"node_id": binding["node_id"], "daughters": scores})
    return out


def render_baseline(baselines, best_forms):
    lines = [f"measuring: {_bootstrap.loaded_package_path()}"]
    lines.append(
        "copy baseline: what one daughter scores against the gold, unchanged."
    )
    lines.append(
        "Read as HistoricalTargetEvaluation reads it -- any form of the "
        "daughter against any gold alternative."
    )
    for entry in baselines:
        lines.append("")
        lines.append(f"  gold node {entry['node_id']}")
        for row in entry["daughters"]:
            lines.append(
                f"    {row['variety_id']:38s} {row['top_exact_rate']:.3f} "
                f"over {row['concepts']} concepts"
            )
        best = entry["daughters"][0] if entry["daughters"] else None
        if best:
            lines.append(
                f"    -> copying one whole daughter reaches "
                f"{best['top_exact_rate']:.3f}"
            )
        for hard in best_forms:
            if hard["node_id"] != entry["node_id"]:
                continue
            lines.append(
                f"    -> BEST ATTESTED FORM PER CONCEPT, chosen against the "
                f"gold: {hard['top_exact_rate']:.3f} exact, "
                f"mean NED {hard['mean_ned']:.3f}, over {hard['concepts']} concepts"
            )
            picks = ", ".join(
                f"{name} {count}" for name, count in list(hard["chosen_from"].items())[:4]
            )
            lines.append(f"       chosen from: {picks}")
            lines.append(
                "       This is the bar to beat. It is an oracle over the "
                "daughters and it reconstructs nothing."
            )
    return "\n".join(lines)


def render(rows, threshold):
    lines = [f"measuring: {_bootstrap.loaded_package_path()}"]
    lines.append(
        f"committed nodes: {len(rows)}   copy threshold: {threshold:.2f}"
    )
    leaf = [row for row in rows if row["leaf_copy"]]
    node = [row for row in rows if row["node_copy"] and not row["leaf_copy"]]
    lines.append(
        f"  leaf copies (node reproduces an attested daughter): {len(leaf)}"
    )
    lines.append(
        f"  node copies (node reproduces another internal node): {len(node)}"
    )
    lines.append("")
    header = (
        f"  {'run':38s} {'node':18s} {'closest lexicon':30s} "
        f"{'agree':>6s} {'gold':>5s} {'scored':>7s}"
    )
    lines.append(header)
    for row in rows:
        leaf_wins = row["leaf_agreement"] >= row["node_agreement"]
        closest = row["closest_leaf"] if leaf_wins else row["closest_node"]
        agreement = row["leaf_agreement"] if leaf_wins else row["node_agreement"]
        mark = "  <== COPY" if (row["leaf_copy"] or row["node_copy"]) else ""
        score = (
            f"{row['scored_top_exact_rate']:.3f}"
            if row["scored_top_exact_rate"] is not None
            else "-"
        )
        lines.append(
            f"  {row['run_dir'][-38:]:38s} {row['node_id']:18s} "
            f"{closest[-30:]:30s} {agreement:6.3f} "
            f"{'yes' if row['is_gold_node'] else '-':>5s} {score:>7s}{mark}"
        )
    scored_copies = [
        row
        for row in rows
        if row["scored"] and (row["leaf_copy"] or row["node_copy"])
    ]
    if scored_copies:
        lines.append("")
        lines.append(
            "  These entered the SCORED set, so an accuracy number rests on them:"
        )
        for row in scored_copies:
            leaf_wins = row["leaf_agreement"] >= row["node_agreement"]
            closest = row["closest_leaf"] if leaf_wins else row["closest_node"]
            lines.append(
                f"    {row['run_dir']} {row['node_id']} == {closest}"
                f"   top-1 {row['scored_top_exact_rate']:.3f}"
            )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("benchmark", help="A benchmark name or a payload path.")
    parser.add_argument(
        "run_dirs",
        nargs="*",
        help="Run directories, or sweep directories holding seed-NN/. "
        "Not needed with --baseline.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=1.0,
        help="Agreement at or above this counts as a copy. Default 1.0, "
        "which is verbatim.",
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Report what each daughter scores against the gold, copied "
        "verbatim, and exit. Needs no run directory.",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload_path = _bootstrap.resolve_benchmark(args.benchmark)
    if args.baseline:
        baselines = copy_baseline(payload_path)
        best_forms = best_form_baseline(payload_path)
        if args.json:
            print(
                json.dumps(
                    {
                        "measuring": _bootstrap.loaded_package_path(),
                        "copy_baseline": baselines,
                        "best_form_baseline": best_forms,
                    },
                    indent=2,
                )
            )
        else:
            print(render_baseline(baselines, best_forms))
        return
    run_dirs = _seed_dirs(args.run_dirs)
    if not run_dirs:
        parser.error("no run directory holding a result.json was found")
    rows = probe(payload_path, run_dirs, args.threshold)
    if args.json:
        print(
            json.dumps(
                {
                    "measuring": _bootstrap.loaded_package_path(),
                    "threshold": args.threshold,
                    "rows": rows,
                },
                indent=2,
            )
        )
    else:
        print(render(rows, args.threshold))


if __name__ == "__main__":
    main()
