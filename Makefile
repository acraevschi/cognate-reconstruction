PYTHON := conda run -n llm_reconstruction python
PYTEST := conda run -n llm_reconstruction pytest
FIXTURE_OUTPUT ?= /tmp/cognate-reconstruction-fixture.json
IECOR_HISTORICAL_OUTPUT ?= /tmp/cognate-reconstruction-iecor-latin.json

.PHONY: help env install test prepare-fixture smoke-lexibank smoke-iecor-historical cli-help

help:  ## Show supported harness targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-22s %s\n", $$1, $$2}'

env:  ## Update the llm_reconstruction Conda environment
	conda env update -f environment.yml --prune

install:  ## Install the harness and LiteLLM adapter in editable mode
	$(PYTHON) -m pip install -e '.[agent]'

test:  ## Run the complete supported harness suite
	$(PYTEST) -q

prepare-fixture:  ## Convert the checked-in CLDF fixture with its supplied tree
	$(PYTHON) -m cognate_reconstruction.cli prepare-lexibank \
		--dataset examples/lexibank_fixture \
		--newick-file examples/lexibank_fixture/tree.nwk \
		--output $(FIXTURE_OUTPUT)

smoke-lexibank:  ## List and prepare the checked-in local Lexibank fixture
	$(PYTHON) -m cognate_reconstruction.cli list-lexibank-varieties \
		--dataset examples/lexibank_fixture
	$(MAKE) prepare-fixture

smoke-iecor-historical:  ## Prepare the local IE-CoR Latin held-out-target subset
	$(PYTHON) -m cognate_reconstruction.cli prepare-lexibank \
		--dataset data/lexibank/iecor \
		--variety-id iecor:17 \
		--variety-id iecor:56 \
		--variety-id iecor:68 \
		--variety-id iecor:25 \
		--variety-id iecor:39 \
		--variety-id iecor:59 \
		--newick-file examples/iecor_latin_smoke_tree.nwk \
		--historical-lineages data/historical_lineages.csv \
		--historical-role target \
		--output $(IECOR_HISTORICAL_OUTPUT)

cli-help:  ## Show the supported command-line workflow
	$(PYTHON) -m cognate_reconstruction.cli --help
