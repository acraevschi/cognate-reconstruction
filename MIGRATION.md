# Migration to the Reconstruction Harness

## Archived

The complete `cognate_reflexes` Stage-1/Stage-2 corpus pipeline is not carried
forward into this repository. It remains available in the archived
[predecessor repository](https://github.com/acraevschi/llm_cognate_reflexes):

- the `cognate_reflexes` package itself;
- generator commands and generator-only tests;
- the old split manifest and dataset-exception notes.

The curated lineage CSV is the one artifact still required at runtime and is
carried forward here as `data/historical_lineages.csv`.

## Reimplemented in the supported package

- CLDF ingestion now produces workbench-native schemas directly in
  `cognate_reconstruction/ingestion/cldf.py`.
- Newick parsing, quoted labels, node IDs, polytomies, and native post-order
  traversal now live in `cognate_reconstruction/tree/`.
- The CLI supports strict anchors, generic LiteLLM configuration, structured
  events, retries, run budgets, checkpoints/resume, and trajectory utilities.
- Every cognacy judgement now has a lossless membership record. Explicit
  segment slices become partial-cognate views; conflicting whole-form rows are
  retained as alternative analyses without inferred weights.
- Historical forms can be explicitly bound to an internal node as visible
  anchors or hidden evaluation targets. Curated lineage branches validate
  ancestry but do not define runtime traversal.
- Useful `tlopo` and `tuled` tree-Glottocode repairs became narrow, auditable
  ingestion compatibility rules that preserve source identity.
- The custom morpheme-indexed partial-cognacy convention used by `liusinitic`
  and `tuled` is explicitly normalized to segment positions and tagged in
  membership provenance; standard CLDF segment slices keep standard semantics.
- Rule outputs include transparent mechanical diagnostics and an ordered
  cascade preview tool.

## Deliberately not carried forward

Automatic historical-target discovery, temporal source-tree discovery,
binary-polytomy sampling, family splitting, and the original JSONL format
remain archived because they served corpus generation rather than live
reconstruction. The heuristic `sidwellvietic` cognate relinking also remains
archived: it changes linguistic judgements and is not required for faithful
CLDF ingestion.

Existing ignored multi-gigabyte Stage-1/Stage-2 JSONL files remain at their
current local paths. The migration does not copy, delete, or reinterpret them.

## Deliberate boundary

The runtime classification tree is still fundamental and is not legacy. A
supplied Newick classification is the recommended research path. Lexical tree
induction remains explicitly exploratory.
