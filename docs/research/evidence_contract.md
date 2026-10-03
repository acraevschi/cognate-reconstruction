# Evidence and execution contract — task03 units-v1

The bounded repair addresses two audited failures. In r2/01 CRAWL, the survey
places Achang/Xiandao's core against Rangoon's first cognate morpheme, whereas
whole-word execution places it against the second `tθ` morpheme at column 5.
FLOWER's core set 7 occurs before the boundary in Achang/Xiandao and after it in
Rangoon; whole-word execution couples the wrong onsets and leaves an orphan `w`.
See audit (`docs/research/failure_audit.md`, local only) and traces (`docs/research/failure_audit_traces.md`, local only). NEEDLE's
witness-gap loss is a separate sparse-material judgment: expose its exact column
and permit an explicit disposition; never insert the reference onset automatically.

Two practical designs were considered. A saved per-concept assembly plan alone
can freeze the inspected columns, but loses their meaning at the next node and
cannot distinguish identical surfaces with different analyses. Typed candidate
analysis alone preserves pieces, but matching commitments by reflex tuple still
allows one unit's decision to fire in another. The chosen small combination is
typed piece analysis plus exact column bindings built by a shared unit aligner.
The model approves these bindings by previewing and committing the hypothesis.
No new inference model or widened beam is proposed.

Source pieces carry source form, membership, cognate set, and exact zero-based
segment positions. Reconstructed pieces carry emitted positions and source/column
provenance, with cognacy inherited only from an explicit source unit. Unknown
pieces stay unknown. Whole-form and unannotated forms have a conservative whole
unit path. Alternative whole-form memberships become separate candidate analyses.
Uncovered segments and structural boundaries remain explicit, never discarded.

An evidence column names the concept, ordered child semantic inputs, piece,
alignment reading, overlays and column position. Equal reflex tuples are only
aggregated within compatible unit scopes. An inventory binds its set IDs to the
exact columns it surveyed; execution cannot apply a set outside that binding.
Survey, preview and commit use every retained candidate analysis, not a hidden
first/last reading. Paginated tools return compact sample pointers; full previews
return the source unit and column IDs needed to inspect a miss.

Piece order follows the union of source orders when those agree. Conflicting
orders require an explicit model claim specifying the unit order; no lexical
sorting or convenient splitting chooses ancestral morphology. That claim changes
the evidence reading and requires a new survey and preview. Realignment preserves
tokens and source positions; ambiguous whole-word edits on partial units are
refused with remediation to specify the unit. Segmentation remaps indices through
boundary-only edits and changes the evidence revision.

Candidates merge by surface plus compatible unit claims (unit ID, cognate ID,
kind, emitted positions and order status). Different source histories merge into
the candidate's source/column unions and remain separately recorded in derivations;
they do not split branch-support mass. Incompatible analyses with equal surfaces
remain separate. Distributions record pre-prune/pruned counts; rule diagnostics
also count pruned partial states. Cartesian work is counted before alignment:
4,096 tuples per concept, 65,536 per node and a conservative 250,000 projected
column limit. Exceeding a limit rejects the operation with required/allowed counts
rather than dropping an analysis. Rule combinations also refuse a product above
4,096. Caches include concept, child order, segments, full provenance and overlays.

Mixed, overlapping or discontinuous source annotations take an explicitly noted
unknown whole-form fallback, retaining every supplied membership as provenance.
The model can replace that unresolved partition through `analysis_claim`. This
does not import reference memberships or equate units from their spelling.

A validation is exact to hypothesis, evidence revision and overlays. Changing a
proto value, confidence, conditioning, residue disposition, restoration, piece
order or overlay requires previewing that hypothesis again. Re-surveying identical
evidence is idempotent. New trajectories identify changed semantics; 2.0/3.0
remain readable. Old inventories replay on their legacy execution path; old
checkpoints cannot resume into units-v1 without an explicit incompatibility error.

The model chooses proto values, deletions, residue witness, restorations,
conditioning and any unresolved ancestral order. The harness carries those
claims, aligns identified pieces, checks exact provenance and reports uncertainty.
It neither assigns cognacy from resemblance nor imports reference analysis.
Task02-v1 and task01-v1 diagnostics retain their definitions. Offline probes are
answer-key-assisted controls, not live quality estimates; real tone and OLD MAN
scope remain unresolved. Results, measured costs and migration details will be
recorded in the companion task 03 result document.

The conservative scope is an explicit tradeoff: partial-piece sets are scoped
to their supplied unit ID. Their support is counted within that scope, rather
than automatically pooling similar tuples across different etyma. Whole-form
patterns retain their ordinary recurrence reading. This can increase set/tool
size and lower reported support, and must be included in later cost/quality
comparisons. It does not license interpreting support-1 material as innovation.
`derived_rules_scope=unscoped_view` marks the inventory's DSL view: the DSL cannot
express exact column/unit restrictions, so it is an approximation rather than
an executable substitute for the approved assembly. Rule commits remain executable.

Runtime and migration details: [evidence migration](evidence_migration.md).
