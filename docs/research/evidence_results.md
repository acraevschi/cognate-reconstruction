# Task 03 — evidence units reaching execution

Implemented 2026-10-02/03, checkout `partial-cognacy-and-tool-use` at `25f8c93`
plus preserved uncommitted 01/02 work. [Design](evidence_contract.md),
[migration](evidence_migration.md) and [compact measurements](evidence_offline_results.json).
All changes remain uncommitted. No new model/training system, paid call or sweep.

## Delivered behavior

Survey, preview and execution share the bounded unit aligner. Source/model-approved
pieces retain cognate identity, exact spans, child order, alignment backend/version,
overlays and column bindings. Identical tokens cannot redirect a decision into a
different unit. Source position and approved column provenance reach a parent
through beam analysis, input beams and derivations. Unknown analyses remain unknown,
including overlapping/discontinuous source annotations and changed rule outputs.
Source/model alternatives remain distinct when their claims differ; compatible
claims merge their source histories without splitting branch-support mass.

The model chooses correspondence values, deletion, conditioning, conservative
witness, restorations, explicit analysis changes and ancestral unit order when
needed. The harness carries and validates those claims. It neither assigns cognacy
from resemblance nor imports target analysis. Empty identity and rule commits,
boundaries, polytomies, missing daughters and restorations remain supported.

Validation now requires the exact hypothesis and evidence, including confidence,
residue choices and overlays. Re-surveying unchanged evidence is safe. Ambiguous
position exceptions require exact evidence column IDs. Summary tools return
bounded unmatched-column pointers and counts; full traces are optional. New
trajectories are 4.0, checkpoints 2.0; 2.0/3.0 trajectories and legacy inventories
remain readable/replayable. Checkpoint 1.0 resume refuses the named incompatibility.

## Frozen before/after controls

The checked-in redacted r2/01 Burmic fixture preserves three observed concepts,
legacy inputs/commitment and reports. `tools/evidence_contract_probe.py --json`
replays its old outputs and reports exactly. New controls explicitly retain named
source cores, delete other units and transfer legacy values only within those
cores, falling to the specified witness value where absent. Those hypotheses are
operator controls, not decisions the old model approved. Reference forms are in a
separate scorer-only file read after execution.

| Concept | Saved legacy top | Source-unit control | Segment edit distance to provisional proxy, old → control |
| --- | --- | --- | --- |
| CRAWL | `w t w o ³¹` | `t w o ³¹` | 3 → 2 |
| FLOWER | `k ă n ⁵⁵ + t w a m ³¹` | `p w a n ⁵⁵` | 7 → 1 |
| NEEDLE | `a p ⁴` | `a p ⁴` | 0 → 0 |

CRAWL's core now uses Rangoon positions 0–3, never the second morpheme's `tθ`.
FLOWER's output carries one identified core; its retained `w` is inside that core,
rather than an orphan produced after deleting another unit. Its glide and tone
remain independent phonological decisions. Exact proxy hits remain 1/3, rather
than increasing. The proxy is Old Burmese at Burmic, explicitly provisional;
this is not validated Proto-Burmish/root quality or causal model improvement.
NEEDLE's Achang set 932 stays separate from set 930 until an explicit model claim.
Support-1 witness gaps are exposed, not repaired by inserting the reference onset.

These controls establish a segment/morphology mechanism benefit on the audited
failures, so the repair remains justified under 01's falsifier. They do not show
that a local model will choose the beneficial analysis. OLD MAN scope and tone/
phonation equivalences remain unresolved. No beam widening was introduced.

## Work and practical costs

For three frozen tuples: 33 scoped sets/bindings, about 0.012 s survey and 0.020 s
cached execution; peak Python-traced allocation about 0.64 MB. Execution reported
six cache hits and zero additional alignment calls. These are one small fixture,
not a scalability estimate; warm caching and Python allocation differ from total
process memory. Full details live in the compact measurement.

Default caps are 4,096 tuples/concept, 65,536/node and 250,000 projected columns.
Excess work is rejected before alignment with actual counts; no analysis is
silently removed to meet a cap. Ordinary beam/partial pruning is reported.
The flat Polynesian fixture's 32,768-tuple concept is explicitly refused; the
matching regression uses a separately declared first-form input control.
Partial-unit scopes also separate etyma, reducing automatic cross-etymon pooling
and increasing set/tool burden. Support-1 now needs careful interpretation; it
does not mean innovation. The derived DSL is labelled an unscoped view, since
global rewrite rules cannot encode the exact unit/column restrictions.

Historical whole-string oracle probes retain their original reading and width
curves. The legacy assembly probe remains 39/46 top and beam exact; these figures
are neither a units-v1 ceiling nor expected model scores. New source-unit controls
are reported beside them. task02-v1's six identity/perfect/wrong controls retain
their readings and scorer-only keys.

## Verification and local smoke

Behavioral regressions cover shared pieces in different positions, compound/simplex,
equal tuples with incompatible unit claims, exact overlays and stale validation,
unknown/whole-form fallback, identical surfaces with different analyses, two levels,
both commit shapes, held-out/selected concepts, polytomies and missing daughters.
Existing target-sentinel tests continue to exclude keys/reference hints from tools.
Independent complete pieces enable task02-v1 cognate-unit comparisons; missing or
ambiguous target analysis and OLD MAN scope stay unknown.

Final portable suite: **588 passed, 41 deselected (52.94 s)**. A final contradictory
unit-claim guard received **41 focused checks (2.09 s)**. All eleven old committed
beams **and reports** replay exactly; all four result/event hash pairs are unchanged.
The four banked raw scores retain root 0/216, proxy 1/148; six diagnostic controls
and legacy oracle curves were rechecked offline. An earlier portable pass exposed
and led to correction of provenance-only mass splitting and pairwise-detail loss;
assertions were preserved after fixing those mechanics.

Exactly one serial local smoke ran on three concepts (nine observed forms), without targets,
using loaded idle `google/gemma-4-26b-a4b`, 6-bit, context 262144. Inventory workflow
was explicitly requested to exercise the interface, so this differs from an
unrestricted production prompt. Manifest/input/instructions/schema hashes and raw
artifacts are under `runs/experiments/task03-interface-smoke-20261003/`.
Caps: one node/run, 24 turns, 60 calls, 900 s between requests, 300 s request timeout,
zero retries. No model switch, download or paid request occurred.

Outcome: **ProtocolStallError after 597.3 s**, 13 turns/calls, seven rejected calls.
Two surveys, alignment inspection and two assembly previews succeeded; no commit
did. Failures included duplicated commitments, reflex mismatch, missing rationale,
invented `proto_segment_is_null`, shortened reflex tuples and omitted proto values.
This is incomplete interface evidence, not a quality claim or provider outage.
No second smoke ran. Reported input/output tokens were 464,341/18,190 across turns;
cached-token and provider-cost metadata were null. Local cost is not a paid charge;
null provider cost is not treated as measured zero billing.

The smoke froze a separate code manifest before final legacy-report compatibility,
order-only execution and view-label/contradictory-claim guards. Those final paths
received portable/focused offline checks; no further live confirmation is claimed.
The delivery code manifest hash is recorded in the compact result; detailed
manifest and replay exports remain under `/tmp`.

Task 04 is ready to use these concrete malformed-call cases and the new strict
contract. Task 05 should retain the new version/hash/resume boundary. Task 06 must
compare readings and costs explicitly and still awaits 04/05 or a scope-out.
