# Sampling configurations for `--provider-config`

Every live figure in `docs/` was produced under one of these. They are tracked
because a figure whose sampling is not stated cannot be compared, and until
2026-08-31 they lived only in the gitignored `runs/` tree — so the numbers were
published and the sampler that produced them was not.

**Why these files exist at all.** LM Studio applies its own Inference panel to
any parameter the client omits, and `configuration_sha256` cannot see it. Two
runs at an identical configuration hash can therefore have been produced under
different samplers, with nothing in the artifact saying so. Sending the values
explicitly is the only way to close that, and `--provider-config` is how they
are sent. `docs/analysis_tools.md` and the operator skill both record the
measurement behind this: `repeat_penalty` is a logit modifier applied *before*
selection, so even greedy decoding is not immune to LM Studio's 1.1 default.

**Each file holds that model's own published values, not a house style.**
`top_k`/`top_p` truncate a distribution and are no-ops only at temperature 0, so
at the temperature these sweeps use they are part of the measurement. Copying
one model's file onto another model is a silent change of sampler.

| file | source of the values |
| --- | --- |
| `gemma-4-26b-a4b.json` | Gemma's published `generation_config` — `top_k 64`, `top_p 0.95`, no repetition penalty (1.0 disables LM Studio's 1.1 default) |
| `qwen3.6-35b-a3b.json` | The Qwen family's published sampling. This MLX conversion ships no `generation_config.json`, so the values come from the family's model cards: `top_k 20`, `top_p 0.95`, `min_p 0` |

**Temperature is not in these files, deliberately.** Pass it as `--temperature`:
`_provider_and_configuration` sets `options["temperature"]` *after* loading the
provider config, so the flag wins and a value here would be silently ignored.
Every sweep since 2026-08-24 pins `--temperature 1.0`.

That pin is Gemma's published temperature and is **not** Qwen's, which is 0.6
for thinking mode. §7.24 of `docs/proto_inventory_design.md` runs Qwen at 1.0
anyway, because the protocol pins it and because a temperature above zero is
what makes `--provider-seed-base` buy independent draws at all — and it states
the deviation beside the figure rather than burying it. A comparison of those
two models is a comparison at one sampler, not at each model's own.

**Verify rather than assume.** Nothing in a trajectory records what the server
actually received. LM Studio's own request log does:

```bash
grep -o '"min_p"[^,]*\|"top_k"[^,]*' "$(ls -t ~/.lmstudio/server-logs/*/* | head -1)"
```

`min_p` and `repeat_penalty` are not OpenAI parameters and survive only as
LiteLLM passthroughs, so they are the two worth re-checking after a LiteLLM
upgrade.
