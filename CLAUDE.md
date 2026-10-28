# Working in this repo

- Python 3.11+, managed with **uv**. Tests: `uv run pytest`. Keep CI (`.github/workflows/tests.yml`) green; it only installs the light dependencies, so pure modules must not import heavy libraries at module level.
- Package code lives in `src/edgar_agent/`; eval scripts in `eval/`; tests and fixtures in `tests/`.
- Never commit secrets (`.env`, Kubernetes Secrets, `*.tfstate`, `*.tfvars`).
- Don't re-run the full eval (`eval/run_eval.py` with no limit costs about $7). Use `--systems agent --limit 10`.
- Commits: one logical step per commit, imperative subject line, body explaining *why*. Jordan reviews before each commit.
- **Active plan:** `docs/PLATFORM_ROADMAP.md`. Follow its "How to work through this plan" rules: one step at a time, a checkpoint with explanations and interview questions, and no paid cloud resources without approval.
