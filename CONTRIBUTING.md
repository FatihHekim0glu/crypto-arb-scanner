# Contributing

Thanks for your interest in `crypto-arb-scanner`. This project uses
[uv](https://docs.astral.sh/uv/) for environment and dependency management.

## Dev setup

```bash
# 1. Install uv (https://docs.astral.sh/uv/getting-started/installation/)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Create the env and install the project with the data + viz extras + dev tooling.
uv venv
uv pip install -e '.[data,viz,dev]'
```

`uv venv` creates `.venv/`; `uv pip install -e '.[data,viz,dev]'` installs the
package in editable mode with the live-data, plotting, and developer extras.
Prefix commands with `uv run` to use that env without activating it.

## Quality gates

These are exactly what CI runs (see `.github/workflows/ci.yml`). Run them locally
before opening a pull request:

```bash
uv run ruff check src                                              # lint
uv run mypy src                                                    # types (strict)
uv run pytest -q --cov=cryptoarb --cov-report=term --cov-fail-under=85  # tests + coverage
```

- **Lint** (`ruff`) must pass.
- **Types** (`mypy --strict`) is run on every PR. It is currently non-blocking in
  CI while residual strict-mode issues are burned down, but new code should not
  add type errors.
- **Tests** (`pytest`) must pass with **coverage ≥ 85%** (the gate also lives in
  `[tool.coverage.report] fail_under` in `pyproject.toml`).

CI runs the full matrix on Python 3.11, 3.12, and 3.13.

## Import purity

`src/cryptoarb/` must have **zero import-time side effects**: no network calls,
no `ccxt` import at module top level (it is imported lazily inside functions),
no loops or data loads at import. Demos live behind `if __name__ == "__main__"`.

## Commit hygiene

- Use clear, present-tense commit messages.
- **Do not** add AI-attribution trailers — no `Co-Authored-By: Claude`,
  no "Generated with Claude", no robot-emoji attribution lines. The
  `.github/workflows/no-ai-attribution.yml` guard fails any PR that contains them.

## Pull requests

- Branch off `main`; keep PRs focused.
- Make sure the three quality gates above are green locally.
- Update `CHANGELOG.md` (under `[Unreleased]`) when behaviour changes.
