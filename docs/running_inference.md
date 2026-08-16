# Running inference

## Inputs

The `infer` command accepts a strict `WorkbenchPayload`. Every form is already
tokenized:

```json
{
  "lexicons": [
    {
      "variety_id": "language_a",
      "name": "Language A",
      "forms": [
        {
          "form_id": "language_a:water",
          "variety_id": "language_a",
          "concept_id": "water",
          "segments": ["p", "a"],
          "cognate_set_id": "water-1"
        }
      ]
    },
    {
      "variety_id": "language_b",
      "name": "Language B",
      "forms": [
        {
          "form_id": "language_b:water",
          "variety_id": "language_b",
          "concept_id": "water",
          "segments": ["f", "a"],
          "cognate_set_id": "water-1"
        }
      ]
    }
  ],
  "concepts": [{"concept_id": "water", "gloss": "water"}],
  "newick": "(language_a,language_b)PROTO;"
}
```

Rules and alignments operate on `segments`, not characters. `+` and `-` are
structural morpheme boundaries. A supplied tree is recommended; name internal
nodes when stable anchor, checkpoint, and output IDs matter.

When `newick` is absent, `tree_method` may be `neighbor` or `upgma`. This path
is an exploratory lexical-distance induction, not a substitute for an
independently justified classification.

## Lexibank preparation

The adapter reads existing CLDF only. It does not clone datasets or run
`lexibank makecldf`.

```bash
cognate-reconstruct list-lexibank-varieties \
  --dataset data/lexibank/iecor
```

Output columns are:

```text
DATASET_SCOPED_ID  NAME  TOKENIZED_FORM_COUNT  SOURCE_GLOTTOCODE  TREE_GLOTTOCODE
```

Select exact IDs and validate a supplied tree:

```bash
cognate-reconstruct prepare-lexibank \
  --dataset data/lexibank/iecor \
  --variety-id iecor:25 \
  --variety-id iecor:42 \
  --concept-id 948 \
  --newick-file classifications/subset.nwk \
  --output runs/iecor-subset.json
```

`--concept-id` is repeatable and selects exact Concepticon IDs or the
dataset-scoped fallback IDs found in the prepared evidence. Use it for bounded
local-model experiments; unknown IDs and selections that leave a chosen
variety without tokenized cognate evidence are rejected.

The adapter prefers CLDF `Segments`, falls back to
`Phonemic_Segments`, applies NFC normalization, and skips unsegmented rows. It
never splits `Form`. Variety, cognate-set, and fallback parameter IDs are
dataset scoped. Source Glottocode and tree Glottocode are separate provenance
fields.

### Cognate memberships

`cognate_memberships` preserves every FormTable or CognateTable judgement.
Each record contains:

- a stable membership and dataset-scoped cognate-set ID;
- `whole_form` or `segment_slice` scope;
- `asserted`, `alternative_analysis`, or `partial_cognate` interpretation;
- normalized zero-based segment positions for partial judgements; and
- the source table, row, membership ID, original CLDF slice, alignment,
  sources, methods, doubt flag, comment, and metadata reference.

Standard CLDF slices are interpreted as one-based inclusive segment
indices/ranges. Lexibank datasets such as `liusinitic` and `tuled` use a
non-ontology custom column whose builders index boundary-delimited morphemes;
that convention is normalized to exact segment positions and tagged with the
`lexibank-custom-morpheme-slice` compatibility rule. Malformed, overlapping,
or out-of-range slices are rejected.
When more than one unsliced cognate set is supplied, all are alternatives; the
adapter does not select or weight one. `get_alignments` exposes membership IDs,
scope, interpretation, and segment positions and aligns only the selected
subsequence for explicit partial cognacy.

Two classification lookup repairs from the archived loader remain as explicit
compatibility rules: local `tlopo` IDs and missing `tuled` Glottocodes. They
change only `tree_glottocode`, retain the source value, and record the rule ID.
The heuristic `sidwellvietic` cognate-set merge is not applied.

The checked-in fixture can reproduce this workflow:

```bash
make smoke-lexibank
```

## Historical source roles

`prepare-lexibank` can remove an attested source variety from leaf evidence and
bind copies of its tokenized forms to an exact internal tree node:

```json
{
  "schema_version": "1.0",
  "bindings": [
    {
      "source_variety_id": "dataset:historical-language",
      "node_id": "explicit-internal-node",
      "role": "target",
      "source_reference": "Project configuration or citation"
    }
  ]
}
```

Pass this with `--historical-bindings`. A supplied tree is mandatory. The
source need not be marked historical by CLDF because the explicit binding is
authoritative; `source_declared_historical` records whether it was.

Alternatively, pass `--historical-lineages` and `--historical-role target` or
`anchor`. The CSV target variety ID becomes the exact internal node ID.
Descendant and first-diverging branch declarations are validated against the
supplied tree but do not determine traversal.

Targets never enter the model prompt or tool context. Result JSON reports
top-candidate and beam-level exact token matches per concept. Target-only
concepts are retained and reported as missing reconstruction coverage. Anchors
do enter the prompt and trajectory, so their concepts must exist in the
evidence and they follow the configured anchor policy.

## External anchors

Anchor input is a strict node-to-form mapping:

```json
{
  "schema_version": "1.0",
  "anchors": {
    "PROTO": [
      {
        "form_id": "anchor:source:water",
        "variety_id": "PROTO",
        "concept_id": "water",
        "segments": ["p", "a"],
        "provenance": {
          "dataset_id": "historical-source",
          "source_form_id": "water-12",
          "source_reference": "Citation or stable catalog reference"
        }
      }
    ]
  }
}
```

Target IDs must be internal IDs in the normalized tree. Concepts must occur in
the lexical evidence. Forms must be token arrays, target ownership must be
exact, IDs must be unique, and provenance is required. No name, date, or tree
position is guessed.

Policies:

- `ignore`: retain the anchor in prompt/trajectory provenance but do not let it
  affect deterministic rule reports or scores;
- `advisory`: report matches and mismatches without score changes; and
- `scored`: apply `log(anchor_match_factor)` for a unique matching anchor.

## Generic LiteLLM configuration

```bash
export RECONSTRUCTION_API_KEY='...'

cognate-reconstruct infer \
  --input runs/input.json \
  --model '<litellm-model-identifier>' \
  --api-base 'https://provider.example/v1' \
  --api-key-env RECONSTRUCTION_API_KEY \
  --provider-config config/provider-options.json \
  --output runs/result.json \
  --trajectories runs/trajectories.jsonl \
  --events runs/events.jsonl
```

The provider options file contains only non-secret JSON options. `model`,
`messages`, `tools`, `tool_choice`, `api_key`, and secret-like nested keys are
rejected. API keys are read at runtime and never put in result, trajectory,
event, or checkpoint data.

The adapter constructs the OpenAI-shaped LiteLLM chat/tool contract and
normalizes assistant content, function names, JSON arguments, response ID,
provider/model IDs, finish reason, token counts, and reported cost. Invalid
tool IDs, names, arguments, or empty choices fail explicitly.

### LM Studio preset

With a model already loaded and the local server running:

```bash
cognate-reconstruct lm-studio-models

cognate-reconstruct infer \
  --preset lm-studio \
  --model '<model-id-from-discovery>' \
  --input examples/lm_studio_smoke_input.json
```

The preset uses `http://localhost:1234/v1`, validates the model against
`/models`, prefixes the LiteLLM identifier with `openai/`, and supplies the
non-secret local placeholder key expected by OpenAI-compatible clients.
Override the base with `--api-base`. Use `--no-preflight` only when discovery
is unavailable but the endpoint is otherwise known.

### Bounded Qwen/Tujia local smoke test

`starostintujia` is a useful small local test dataset: its LanguageTable has
five varieties and explicitly groups them as Northern (`nort2732`) or Southern
Tujia (`sout2739`). The checked-in
`examples/starostintujia_classification.nwk` expresses that supplied metadata
classification using exact dataset-scoped leaf IDs. Selecting only the two
Southern varieties prunes it to one reconstruction node.

The following preparation selects six shared Concepticon concepts (12 forms),
while retaining the original CLDF segments, expert cognate memberships, and
provenance:

```bash
cognate-reconstruct prepare-lexibank \
  --dataset data/lexibank/starostintujia \
  --variety-id starostintujia:boluotujia \
  --variety-id starostintujia:tanxitujia \
  --concept-id 1035 --concept-id 1040 --concept-id 1198 \
  --concept-id 1202 --concept-id 1203 --concept-id 1205 \
  --newick-file examples/starostintujia_classification.nwk \
  --output runs/qwen35-tujia/input.json

cognate-reconstruct infer \
  --preset lm-studio \
  --model qwen3.5-9b \
  --input runs/qwen35-tujia/input.json \
  --provider-config examples/lm_studio_qwen_config.json \
  --output runs/qwen35-tujia/result.json \
  --trajectories runs/qwen35-tujia/trajectories.jsonl \
  --events runs/qwen35-tujia/events.jsonl \
  --checkpoint runs/qwen35-tujia/checkpoint.json \
  --temperature 0 --timeout 120 \
  --max-turns 16 --max-tool-calls 32 --max-retries 1 \
  --max-run-seconds 600 --max-event-chars 3000
```

Readable tracing is enabled unless `--quiet` is supplied. If invoking through
`conda run`, add `--no-capture-output` so events appear immediately rather than
after the process exits.

## Retry, limits, and checkpoints

Per-node defaults are 24 turns and 64 tool calls. Transient provider errors
retry twice with exponential backoff.

Relevant controls:

```text
--max-turns
--max-tool-calls
--max-retries
--retry-backoff-seconds
--max-total-turns
--max-total-tool-calls
--max-run-seconds
--max-total-cost-usd
```

The cost budget is enforced only when response metadata reports a cost.

The thresholds that decide when a stuck node gives up are also flags, and all
of them are part of the checkpoint compatibility hash:

```text
--max-repeated-tool-failures    rejections sharing one (tool, error code)
                                signature inside the window (default 3)
--stall-window-calls            trailing tool calls remembered, successes
                                included (default 3x the above)
--max-truncated-responses       truncated responses carrying no tool call
                                before the node stops (default 3)
```

### Truncation recovery

A response with `finish_reason="length"` and no tool call is usually the model
spending its whole output budget on reasoning prose. The turn immediately after
one is sent with `tool_choice="required"` instead of `"auto"`. This needs no
configuration, is attempted once per node, and falls back to the ordinary
request if the provider raises or still returns no tool call. It appears in the
event stream as `truncation_recovery` and in the metrics as
`forced_tool_choice_count`.

The second recovery is opt-in because it overrides an option you supplied:

```text
--allow-truncation-backoff          off by default
--truncation-max-tokens-ceiling     required whenever the flag is set
```

With it enabled, a truncated no-tool response doubles the effective
`max_tokens` for the remainder of that node, never above the ceiling. `max_tokens`
belongs to your `--provider-config`, so nothing is raised unless you ask; your
stored options are not modified, and the raised value is merged into the
affected requests only. The base for doubling is the truncated response's
reported output length, so a provider that reports no token usage gets no
backoff rather than a raise that might land below your configured value. Each
raise is counted in `truncation_backoff_applied` and emitted as an event, so a
run that only succeeded because of backoff is visible as such in its
trajectory.

`--max-truncated-responses` bounds how far backoff can get, since the node
stops once that many truncated no-tool responses have accumulated. At the
default of 3 the value doubles at most twice, so a ceiling above 4x your
configured `max_tokens` is unreachable unless you raise both flags together.

Enable node-boundary recovery:

```bash
cognate-reconstruct infer \
  ... \
  --checkpoint runs/family.checkpoint.json
```

The checkpoint is replaced atomically after each completed internal node and
contains deterministic reconstruction steps, not secrets or partial LLM
state. Resume with the same input and configuration:

```bash
cognate-reconstruct infer \
  ... \
  --checkpoint runs/family.checkpoint.json \
  --resume
```

Already completed nodes are replayed from deterministic steps. The next
unfinished internal node starts a fresh provider loop.

A resume is rejected when the input, the normalized tree, the CLI and provider
settings, **the agent instruction text, the tool schemas, or the `--anchors`
file** changed since the checkpoint was written. The error names which of those
moved, for example:

```text
error: checkpoint cannot be resumed because these changed: the agent instructions
```

A checkpoint written before this behaviour existed refuses correctly but can
only report `the configuration`, because it never recorded the individual
digests to compare against.

Resuming also reads `--trajectories` back and restores the hypotheses committed
at the nodes it is skipping, so `get_node_reconstruction` still returns them in
the resumed process. A record is used only if it is completed with its commit
present, belongs to a node in the checkpoint, and was written under both the
same configuration hash **and** the same run ID; the count is printed. The run
ID matters because two invocations over the same input with the same settings
produce the same configuration hash, and `--trajectories` defaults to one file
in the working directory — without it, one run's rules could be paired with
another run's checkpointed forms.

A missing or unreadable trajectory file warns and the run continues without
prior hypotheses. A file that fails schema validation stops the run instead of
being ignored, which is also why the whole file is validated and held in memory
during seeding.

## Events and failures

Readable events go to stderr unless `--quiet` is set. Structured events append
to `reconstruction_events.jsonl` unless `--no-events` is set. They include:

- run and node IDs and timestamps;
- provider adapter/model and response usage;
- node start, model turns/responses, tool calls/results, commits, retries,
  completion, and failure;
- duration, turn/tool/retry counts;
- rules, structural rule complexity, anomalies, coverage, and output counts;
- optional tokens and reported cost.

Provider failures, malformed responses, run budgets, and loop limits append an
incomplete trajectory before propagating the failure. Completed earlier nodes
remain checkpointed.

## Deterministic tools

The node prompt contains compact active-child summaries and anchors. Evidence
is retrieved on demand.

| Tool | Deterministic result |
| --- | --- |
| `list_concepts` | Paginated concepts, glosses, counts, and node IDs. |
| `search_forms` | Exact semantic/segment/cognate/node filtering. |
| `list_available_nodes` | Observed and completed internal evidence only, flagging nodes with a retrievable hypothesis. |
| `get_node_reconstruction` | Rules, anomalies, and summary committed at one already-reconstructed node; read-only and never scored. |
| `get_alignments` | LingPy MSA plus pairwise correspondence summaries. |
| `segment_morphemes` | Immutable boundary-only overlay; phonetic tokens cannot change. |
| `test_sound_law` | Parsed literal DSL and exact per-form diff. |
| `test_rule_cascade` | Ordered, branch-scoped full-cascade preview and final forms. |
| `commit_reconstruction` | Exact validation references, scopes, order, support, anomalies, and optional cascade check. |

Rule IDs are optional labels in cascade and commit calls. If omitted, the
harness deterministically derives a stable ID from the exact DSL and ordered
child scope; no linguistic content is inferred.

A committed rule needs only `dsl`, `source_child_ids`, and `confidence`. The
per-rule `validation_call_id` may be omitted, in which case the harness resolves
the unique same-session `test_sound_law` validation whose DSL, child scope, and
segmentation overlay are identical, and stores the resolved ID in the request;
zero or several matches are rejected rather than guessed. `supporting_form_ids`
defaults to that validation's forms and `rationale` is optional. Rejected tool
calls carry a `remediation` field listing the session's recorded
`(validation_call_id, dsl, source_child_ids)` triples.

Sound laws are operational child-to-parent transformations:

```text
f > p / #_
```

The deterministic engine applies the committed cascade, combines child beam
scores, adds confidence only for rules that apply, applies optional scored
anchors, merges equivalent outputs, and prunes.

Alignment inspection is deliberately incremental. The hypothesis-manager
prompt tells the model to work in small concept batches, and the
`get_alignments` schema requires an explicit selection of at most 12 concept
IDs or 48 exact form IDs. An unfiltered whole-family alignment request is
rejected as a tool error even when the provider offers a 128k-or-larger
context window.

## Outputs and trajectory curation

The result JSON includes the full traversal snapshot, each best internal
lexicon, beams, rule reports, anomaly reports, mechanical diagnostics, and
held-out historical target evaluations where configured.

Trajectory schema 2.0 contains run/configuration identifiers, instruction/tool/
payload/schema hashes, provider response metadata, the complete validated
message/tool history, commit, deterministic step, failure state, and metrics.
JSONL is append-only.

```bash
cognate-reconstruct validate-trajectories --input runs/trajectories.jsonl
cognate-reconstruct summarize-trajectories --input runs/trajectories.jsonl
cognate-reconstruct export-trajectories \
  --input runs/trajectories.jsonl \
  --output runs/examples.jsonl \
  --high-quality-only \
  --max-anomaly-rate 0.1
```

The export is generic multi-turn tool supervision, not a training backend.
Legacy Stage-1/Stage-2 examples are not silently converted into this contract.
The validator reports `committed_no_op_rules` and
`trajectories_with_no_op_rules`. New no-op rules such as `p > p` are rejected
by rule testing, cascade preview, and commit; identity reconstruction uses an
empty `rules` array. Historical append-only records with no-op rules remain
schema-valid for audit but cannot pass the `high_quality` filter.

## Diagnostics

Each step reports:

- committed rule count;
- `rule_complexity_cost`, defined as one per rule plus target, replacement,
  left/right context tokens, and word-edge constraints;
- unique evaluated rule results;
- successful mechanical applications;
- target-absent, context-mismatch, and anchor-mismatch counts;
- `applicable_rule_results`, the evaluated results whose form actually
  contained the rule's target;
- `rule_coverage`, successful applications over `applicable_rule_results`, so a
  child that never showed the target is vacuous for that rule rather than a
  counterexample to it;
- anomaly count and anomalies per reconstructed concept; and
- whether the cascade was empty identity reconstruction.

This cost is visible but does not change default scoring. A future parsimony
objective could combine description cost, exceptions, residual mismatch, and
regular coverage only after that objective is explicitly chosen and tested.
