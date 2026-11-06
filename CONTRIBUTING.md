# Contributing

## Setup

Requires Python 3.10+ and `make`.

```bash
make setup    # creates .venv and installs the pinned versions from requirements-dev.txt
```

## Checks

```bash
make lint     # ruff check + ruff format --check
make test     # pytest: unit tests and the end-to-end pipeline tests
make check    # both; this is what CI runs, together with `make build`
make build    # runs the pipeline on the example spec for every locale
```

`ruff format .` fixes formatting. Dependencies are declared in `pyproject.toml` and pinned in `requirements*.txt`; after changing them, run `make lock` (needs [uv](https://docs.astral.sh/uv/)) and commit the regenerated files.

## Pull requests

- Branch from `main` and open a pull request into `main`. Direct pushes to `main` are blocked.
- CI (`.github/workflows/ci.yml`) must pass on Python 3.10 and 3.13; the `ci-ok` job is the required check.
- Pull requests are squash-merged, so the PR title becomes the commit subject.
- A change to a step's behaviour needs a test. Endpoint-specific fixes for the example belong in `example/corrections.yaml`, not in Python.

## Commit style

Short imperative subject in plain English (`Add REMOVE_HEADER action to step 3`), with a body that explains why when it is not obvious.
