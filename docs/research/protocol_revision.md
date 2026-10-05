# Task05 — instructions and exact hypothesis commitment

2026-10-05, `burmish-session-evaluation-units`, starting HEAD `7356f66`.
Task04's runtime/test hashes matched its delivery manifest without mismatches;
35 evidence-repair/evaluation checks passed before edits. Inherited local task01
audit files and handoff changes are preserved. This work is uncommitted and
separate from task04's saved commit. [Compact measurements](protocol_revision_results.json).

Offline delivery is verified: 633 portable checks pass and exact stored-hypothesis
commitment reaches parent propagation and normal evaluation. The sole local smoke
failed without a substantive preview or commit. Final clarifications are offline-
tested only; task05 remains partial at live usability and task07 is not ready.
The final [code manifest](protocol_revision_manifest.json) is distinct from the
smoke's frozen snapshot; the compact result records both hashes.

## Evidence and corrected claims

The task01 audit separates 35 rejected tool results from accepted decisions.
Only r2/00 Maruic failed a valid-run node; three fully committed runs still had
zero root exact hits. Maximum observed turns were 29/36, with no cap failure.
The task03 local smoke had two executable previews and no commit: duplicate
claims, wrong reflexes, missing reasoning, omitted proto values, invented
proto_segment_is_null and shortened tuples caused seven rejections. Those are
different problems from historical polarity and wrong accepted values.

The literal parser/engine mechanically executes `⁵⁵ > ⁴` on `a p ⁵⁵`, and can
expand a nonempty target into new token sequences. Cascades therefore can emit
symbols absent from every child. An empty target is forbidden; arbitrary
zero-position insertion is unavailable. Structural boundaries cannot be rule
targets/insertions, identity rules are refused, and deletion cannot empty a form.
These are actual restrictions, not restrictions on historical imagination.
Representational success does not license a tone-category mapping or historical
analysis. Runtime instructions, node commit notes and matching descriptions now
state that distinction; the old changelog claim has a dated correction.

An ordered cascade conveniently handles contexts created by earlier rewrites.
An inventory conveniently states local correspondence values and cross-child
assembly. No universal reasoning order or chronological interpretation follows.
The inventory's derived DSL omits unit/column scope and remains an unscoped view.
Operational child-to-parent rewrites are distinct from forward historical change.

Guidance now qualifies singleton support, outgroup gaps and retention. Under
independent-etyma-v1 a local singleton can be a valid but sparse observation.
Missing annotation or a witness gap does not establish innovation. Material at
a boundary is not automatically innovative, and retention is not mandatory
regardless of morphology. The global witness policy can emit a gap where other
children retain material; NEEDLE and STICKING motivate inspecting this possibility,
not inserting their reference values. I/SNOT remain examples of accepted wrong
values relative to gold, not evidence that protocol repair selects the right history.

Consult available, relevant scoped witnesses; do not demand a nonexistent root
outgroup. Presence supports a qualified history without proving inheritance;
absence leaves several histories possible. Prior reconstructed nodes are not
independent attestation. No sound-change database was added. Raw tone-token
agreement and task01-v1 diagnostics remain separate under task02-v1. FATHOM,
MONKEY and NEEDLE alternative/child-hit/root-miss regressions were reused. Target
content, source reference annotations and key-derived hints remain scorer-only.

## Protocol intervention

Default `stored-hypothesis` keeps the full-payload path and both commit shapes.
`test_proto_assembly` additionally accepts compact local `choices`: exact csu-*
set_id, required proto_segment including explicit null, required confidence,
optional conditioning/merger claim and explanations. Only reflexes/support are
resolved from the current harness inventory. Unknown IDs, csp-* used locally,
duplicate/overlapping claims and unstated linguistic decisions remain invalid.
Shared claims still explicitly select pattern/member collections; approved shared
selections and expanded local commitments retain task04's provenance contract.

Final stored previews require at least one explicitly stated claim collection
(choices, commitments or shared_claims). An explicit empty list remains deliberate
identity/abstention; omitting all three no longer infers an empty hypothesis.
Local choices are flat at the top level, one token-correspondence ID per item,
not nested per concept/whole form. Schema rejection remediation explains this
shape without flattening rejected calls, inventing IDs or filling decisions.

A successful preview reports `executable=true`. `commit_ready` additionally checks
the same multi-set rationale and actual loss/merger explanation gates as commit;
`missing_commit_requirements` identifies missing fields/sets before the terminal
call. A single full local choice can still use the final summary, as before.
Final summary and anomalies are always separately required. Missing explanations
do not prevent mechanical inspection and do not silently acquire defaults.

The preview returns an immutable, session-local hypothesis_id. The stored object
contains a serialized parsed full specification, node/child order, exact hypothesis
digest, active-column revision, supplementary witness/anchor digest, overlay and
validation ID. Identical reinspection preserves that snapshot. A ready handle
commits with node_id, hypothesis_id, summary and anomalies, without retranscribing
inventory data. Payload/overlay fields on a handle call are refused, including
explicit empty or null replacements. Editing a value, confidence, explanation,
conditioning, member selection, residue policy/disposition, restoration, order or
overlay requires another exact preview. New evidence requires one too.

Commit resolves the snapshot and runs the ordinary full commit/assembly checks.
The handle does not bypass validation, stale-evidence checks, restoration licensing
or anomaly references. The persisted commitment contains the full resolved request
and original assembly validation ID; preview arguments in the trajectory preserve
submitted compact choices, and approved_shared_claims preserves shared selections.
Handles never enter checkpoints or cross node/session/resume boundaries. Rule
commitment remains the existing individually validated DSL path; no rule-handle
framework was added. Empty identity/qualified abstention remains valid.

An additional protocol guard freezes supplementary witnesses/anchors. The existing
active-column revision did not cover those changing independently. Both inventory
paths now require the same supplementary digest as the successful preview. This
is exact-validation strengthening, not a linguistic evidence inference.

## Smaller payloads and cost interpretation

Measurements use the unchanged nine-form, three-concept observed Burmic input
(SHA-256 `44c08e488d907ad9ec5e9cedef89ebd282606f220d47f410c3f75c517e7ed97e`).
They sum packaged system text, sorted JSON native definitions and the indented
node payload including commit notes. Provider envelopes/history are excluded.
Serialized sizes, not tokenizer estimates, are reported:

| Component, characters | Task04 starting checkout | Current full-payload | Current stored-hypothesis |
| --- | ---: | ---: | ---: |
| System text | 39,981 | 12,803 | 12,803 |
| Native definitions | 63,324 | 50,532 | 52,938 |
| Node payload | 4,103 | 2,047 | 2,047 |
| Combined | 107,408 | 65,382 | 67,788 |
| Combined UTF-8 bytes | 107,667 | 65,405 | 67,811 |

Stored schemas add 2,406 characters over the current full path, while avoiding
repeated linguistic payloads at final commit. The combined reduction from the
starting checkout is about 36.9% in characters. This is not a token-saving estimate
across models or evidence of better science.

The saved executable eleven-choice preview is 1,448 characters; the same decisions
without reflex/support retranscription use 955. It was missing explanations, so
neither is a ready commit. A separately labelled operator control retains those
values and adds explicit uncertainty explanations: its compact preview is 2,924
characters and it commits successfully. Its normalized/default-filled full commit
object is 4,428 characters; the handle call is 177. These are serialized objects,
not observed model output-token costs or a minimum possible full payload.
No target was supplied and no historical correctness is inferred.

Reproduce current sizes and the saved-value transcription control:

```sh
conda run -n llm_reconstruction python tools/protocol_revision_probe.py --measure-only
```

The compact result retains before/after hashes, fixture identity and all seven
saved rejection classes. Exact old calls are replayed first; an explicit second
pass changes only harness IDs through exact saved scope/reflex/concept identity.
Wrong tuples, missing values and malformed fields stay wrong. All seven rebound
codes match their saved classes; old semantic IDs are never migrated for execution.

## Verification and live usability

Semantic tests cover real novel-token/sequence execution and empty-target refusal,
required values/nulls/confidence, missing rationale/directionality, immutable/repeated
handles, cross-session refusal, stale active/supplementary evidence, deliberate
value/confidence/context/reason/policy edits, overlapping shared/local claims,
full-payload compatibility, rules and independent instruction/schema hashes.
No tests assert entire prompt paragraphs or require live model strings to match gold.

Five scripted survey/compact-preview/handle-commit controls traverse `((a,b)x,c)p`,
serialize JSONL and use the normal evaluator. All ten nodes commit without protocol
failures. Correct/wrong/extra/missing/reordered root exact counts are 4/0/0/0/0;
the validated whole-word denominator remains zero because order is underdetermined.
These establish instrument/propagation mechanics, not model quality. Reproduce
with a fresh output directory:

```sh
conda run -n llm_reconstruction python tools/protocol_revision_probe.py --output-dir /tmp/task05-controls-new
```

Pre-smoke focused checks: 173 passed. First portable run: 627 passed, three failed,
41 excluded; failures concerned two description contracts and an incorrect demand
that the optional installed skill match the tracked source. Those were repaired;
the driver now reports same/stale/missing installation status. Pre-smoke portable:
630 passed, 41 excluded, 57.21 seconds. The second full run was justified by those
failures. CLI/driver help and whitespace checks pass. Post-smoke collection/shape/
isolation repairs received 162 focused passes and one justified additional portable
run: **633 passed, 41 excluded, 60.96 seconds**. The later operator-only catalogue/
loaded/busy guard received 52 focused passes, including three no-launch controls;
the full harness suite was not repeated for that operator refinement.

Exactly one local smoke ran at `runs/experiments/task05-interface-smoke-20261005/`.
Its manifest freezes the same observed input, requested inventory workflow, explicit
sparse inspection, runtime/schema hashes and caps. Loaded idle Gemma 4 26B A4B,
6-bit, context 262144, used temperature .1, top_p .95, top_k 64, repeat_penalty 1,
max_tokens 8192, timeout 300, zero retries, 24 turns/60 calls and 1800 seconds.
Server/template thinking settings were not exposed; no setting/model switch occurred.

Outcome: **ProtocolStallError**, 1171.75 seconds at the node (1172.21 process seconds),
15 turns/attempts, 13 calls, seven protocol rejections, two truncated no-tool
responses and two forced-tool recoveries. One accepted preview omitted all claim
lists and produced empty identity; no substantive preview or commit succeeded.
The model nested choices under per-concept commitments, then used whole-word
reflexes and IDs absent from every successful tool result. Strict validation held.
There was no turn-cap failure, provider retry, paid call, second smoke or broad sweep.
No result.json was written; the failed trajectory/events and empty checkpoint remain.

Reported cumulative tokens: **631,609 input**, **37,966 output**, **669,575 total**.
Largest request: **56,233 input**; largest reported input+output total: **57,589**.
Those are distinct from configured context capacity **262,144**. Reasoning tokens
were 32,599, a subset of output; cached input and provider costs were null, not
measured zero. Shorter static text did not establish lower cumulative cost or
scientific improvement. The earlier task03 smoke is not a controlled comparator.

The failed smoke supplied the final explicit-list/flat-shape remediation regressions.
The frozen mechanical example also coincided with the provisional NEEDLE reference;
final runtime instructions now use abstract symbols, and a semantic isolation test
excludes complete fixture reference words. Reference bindings/keys were never supplied,
but the frozen run is not a target-isolated quality sample. Its raw artifacts are
unchanged. Final collection/shape/isolation clarifications are **offline-tested only**;
the one-smoke limit precludes a second attempt. Live substantive commit usability
therefore remains unresolved, and task05 is partial at that gate.

## Operator changes, switches and next comparisons

Change boundaries: linguistic/wording repair is in system_prompt.md, node commit
notes, native descriptions and their schema prose. Protocol implementation is in
stored_hypothesis.py, context.py, proto_assembly.py, commit_reconstruction.py and
error_codes.py; CLI hashes/profiles are in cli.py. Operator changes are confined
to the tracked skill/driver. No rule-parser/engine, unit aligner, traversal assembler,
candidate selection or evaluator execution code changed. Shared description/schema
surfaces are named explicitly because a Git file alone does not isolate an arm.

The tracked skill describes both shapes, current driver paths, local-first policy,
dynamic test counts, real loaded-ID discovery and model-specific sampler provenance.
Driver run flags now expose timeout/retries/time cap/provider-config and the two
independent controls below; its deterministic smoke uses the portable suite.
The driver now reads actual local `lms ps --json` instances and refuses catalogue-
only or busy models before creating a run. This loaded-state guard is local to
the operator's LM Studio instance.
The installed `.claude` SKILL.md and driver.py are stale. That directory is read-only
under this session's permission profile; it was not synchronized and permissions
were not changed. Use the tracked source. preflight explicitly reports divergence.
The server catalogue is not proof of loaded status: lms ps confirmed one loaded idle
`google/gemma-4-26b-a4b`, 6-bit, context 262144, despite six catalogue entries.

No countdown was implemented. The banked audit supplies no cap-failure evidence,
and the primary repair addresses observed preview-to-commit failures. Counts still
come from actual orchestrator turns and tool calls; batching does not grant turns.

| Question for task07 | Independent control | Attribution limit |
| --- | --- | --- |
| Compact choices plus immutable commitment | `--inventory-protocol full-payload` versus `stored-hypothesis`, same current instructions/input/settings | Protocol package including its two schema/description changes; not handle-only causality |
| System-text wording | `--agent-instructions PATH`, holding protocol, backend, node notes and schemas fixed | System text only; other guidance surfaces remain common; prepare and review a compatible frozen control text before inference |
| Task03/04 evidence changes | Original checkout versus final units-v2/count package | Required count/shared-ID/scoping instruction/schema adaptations prevent a pure assembly-only arm |

The full-payload profile shares current readiness and supplementary-validation
guards. They are a common task05 protocol-contract prerequisite, not toggled by
the ergonomic switch. An old checkout comparison changes that package too.
All arm choices need actual schema/input-cap preflight and a final manifest.
Historical instructions may be read as controls but must not be silently mixed
with current node notes or described as a pure all-guidance ablation.

System text content, native schemas, node commit requirements and selected protocol
are strict configuration inputs. The new node-checklist hash closes an earlier
unhashed model-visible surface. Changing them refuses resume; use a new run and
checkpoint. Trajectories/checkpoints stay 5.0/3.0 with additive result fields;
historical null readiness is unknown, not ready. Preserve old readers and units-v2's
old-resume refusal. No mid-node resume was added.

Task06 remains independent and must preserve those boundaries and outcome/fallback
semantics. Task07 requires final local usability, normal-evaluator/cap/manifest
checks and task06 completion or its bounded explicit exception. Recommend a focused
independent review of the final interface and comparison manifest before inference.
Review exact-reference safety, explanation readiness, hidden-target isolation,
submitted/expanded claims and package versus isolated attribution. The owner
chooses when to begin; no downstream chat or experiment was dispatched.
