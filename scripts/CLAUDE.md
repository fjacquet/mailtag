# scripts/

Shell helpers and taxonomy tooling.

## Shell Scripts

### start.sh

Start the main application.

### run.sh

Run classification with default settings (calls `cli.sh`).

### cli.sh

Launch the CLI: `uv run python src/main.py "$@"`.

### streamlit.sh

Start the Streamlit front end for `run`.

```bash
./scripts/streamlit.sh
# Equivalent to: streamlit run src/app.py
```

### webhook.sh

Start the FastAPI webhook server.

```bash
./scripts/webhook.sh
# Equivalent to: python src/main.py serve --reload
```

### test.sh

Run the test suite.

```bash
./scripts/test.sh
# Equivalent to: uv run pytest --cov-report=html
```

## Python Scripts

### taxonomy_setup.py

Taxonomy preparation, migration and bulk review. Subcommands: `scan`, `crosscheck`, `build`, `train`, `migrate`, `prune`, `reorganize`, `review-scan`, `refile-review`. Those that move mail (`migrate`, `prune`, `reorganize`, `refile-review`) are dry runs unless `--apply`; `scan`, `crosscheck`, `build`, `train` and `review-scan` move nothing. `train` fits `data/taxonomy_logreg.npz` from the corpus (`build` runs it).

### taxonomy_review.py

Local Streamlit review page (folder audit, scan senders, senders learned during runs, rule control, bulk review of `5-A revoir`): `uv run streamlit run scripts/taxonomy_review.py`.

### eval_embeddings.py

`chain` replays nomic and Gemma on verified mail and picks `nomic_threshold`. `logreg` trains per sender-grouped fold and proposes the `[logreg]` thresholds (`--min-precision`, default 0.85).

## Running Scripts

```bash
# Shell scripts
chmod +x scripts/*.sh
./scripts/start.sh

# Python scripts
uv run python scripts/taxonomy_setup.py scan
```

## Notes

- Shell scripts assume `uv` is available in PATH
- Python scripts should be run from project root
- Check script contents for specific arguments/options
