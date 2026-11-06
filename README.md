# openapi-fixer

A four-step Python pipeline that turns the OpenAPI spec your backend generates into one you can publish: translated, complete, and valid.

```text
example/openapi.json ──► 1 hydrate ──► 2 fix names & $refs ──► 3 targeted fixes ──► 4 lint + validate ──► build/openapi.<locale>.json
   (as generated)        config.yaml     components.*            corrections.yaml     openapi-spec-validator
                         dictionary.json
                         summaries.json
```

## Why this exists

I built this while working as a Support Engineer on a SaaS API. The spec exported by the backend was technically "OpenAPI", but you could not ship it: descriptions were i18n keys, operations had no titles, schema names had spaces, several paths declared parameters that did not exist (or forgot ones that did), and some `DELETE`s carried a body. Fixing it by hand after every release was not an option, so the fixes became code and config.

This repository is a cleaned-up version of that toolkit. The original spec is **not** included; the example is **Shelfline Field API**, a fictional retail field-execution API that reproduces the same classes of problems. Its output feeds [api-docs-starter](https://github.com/rafactx/api-docs-starter), a multilingual docs portal.

## Quickstart

Requires Python 3.10+.

```bash
git clone https://github.com/rafactx/openapi-fixer.git
cd openapi-fixer
make setup    # .venv with the pinned dependencies from requirements-dev.txt
make build    # runs steps 1-4 for en, pt-BR, es, fr -> build/openapi.<locale>.json
make check    # ruff, unit tests, and the end-to-end pipeline tests
```

Without `make`:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python run_pipeline.py --locale en
.venv/bin/python -m pytest -q
```

## What is broken in the example, and which step fixes it

`example/openapi.json` is shaped like the output of a Spring/springdoc backend: 15 paths, 21 operations, 20 schemas. It fails `openapi-spec-validator` as shipped.

| Problem in the input | Example | Fixed by |
| --- | --- | --- |
| Descriptions and tag names are i18n keys | `api.doc.v3.store.get.description` | 1 hydrate |
| No operation summaries (sidebar shows `findById_1`) | `operationId: findById_1` | 1 hydrate |
| Placeholder `info`, localhost server, no auth, no error responses | `"title": "OpenAPI definition"` | 1 hydrate |
| Component names with spaces, refs raw or URL-encoded | `Store V1`, `#/components/schemas/Chain%20V3` | 2 names & refs |
| `DELETE` with a body (IDs should be a query parameter) | `DELETE .../reps/{repId}/scheduled-visits` | 3 targeted |
| Filter declared as a path parameter | `name` (in: path) on `/brands` | 3 targeted |
| URL variable never declared | `{workspaceId}` on `/v1/{workspaceId}/malls/{mallId}` | 3 targeted |
| `DELETE` with a body that nobody listed in the corrections | `DELETE /v1/{workspaceId}/stores/{storeId}` | 4 safety net |
| Path parameter without `required: true` | `productId` | 4 safety net |

## How it works

### 1. Hydrate (`1_hydrate_openapi.py`)

```bash
python 1_hydrate_openapi.py spec.json config.yaml locales/en/dictionary.json locales/en/summaries.json --strict
```

Injects `info`, `servers`, security, reusable components, summaries (by `operationId`), default error responses (chosen by path prefix, so v3 and legacy v1 endpoints get their own error shapes), global headers and an ordered tag list. **Translation runs last**, so text that comes from `config.yaml` (tag names, error descriptions, header docs) is localised too. With `--strict`, any leftover placeholder or missing summary fails the step: this is how missing translations are caught before they reach the docs.

### 2. Component names and refs (`2_fix_schema_names_and_refs.py`)

Renames every invalid key under `components.*` (`Store Patch V3` → `StorePatchV3`) and rewrites every `$ref` to it, whether the generator wrote it raw or percent-encoded. It refuses to run if two names would collide, and it refuses to save if any local `$ref` is left dangling. `--camel-case` switches the naming strategy.

### 3. Targeted fixes (`3_fix_semantic_paths.py`)

Some fixes need a human decision: is that `DELETE` body really a list of IDs that should move to the query string? Those decisions live in `example/corrections.yaml`, not in Python:

```yaml
- id: brands-name-is-not-a-path-param
  path: /v3/workspaces/{workspaceId}/brands
  method: get
  action: REMOVE_PARAMETER        # also: ADD_PARAMETER, REMOVE_KEY, SET_KEY
  match: { name: name, in: path }
```

Added parameters are `$ref`s to components injected in step 1, so they arrive already translated. `--export-config template.yaml` writes a starter file.

### 4. Lint, fix and validate (`4_final_verification.py`)

A generic pass over every operation for problems nobody listed. It rewrites the file in place to fix four of them: request bodies on GET/HEAD/DELETE are removed, path parameters missing from the URL are removed, URL variables never declared are added, and path parameters get `required: true`. Duplicate `operationId`s and invalid component names are only reported. It then runs `openapi-spec-validator`. It exits 1 on any error, so it can gate CI or a docs deploy.

### Design choices

- **Steps 2-4 are idempotent.** Running them again on the output changes nothing. Step 1 expects the generator's raw output, since it translates the tag names it matches on.
- **Config over code.** Endpoint-specific knowledge lives in `config.yaml` and `corrections.yaml`. Adding a fix is a reviewed config change.
- **One input, many locales.** Locale-specific text lives only in `locales/<locale>/`. `make build` writes one spec per locale from the same input.
- **Fail loudly.** Name collisions, dangling refs, missing translations (`--strict`) and validator errors stop the pipeline.

## Tests

`make check` runs ruff and pytest; CI runs it plus `make build` on Python 3.10 and 3.13.

- `tests/test_common.py`: unit tests for the shared helpers (`$ref` resolution, path templates, JSON I/O).
- `tests/test_pipeline.py`: builds every locale end to end and checks that the example input fails validation, each output passes `openapi-spec-validator` with no untranslated keys, invalid names or missing summaries, the locales differ, steps 2-4 are idempotent, step 2 refuses name collisions, and step 4 exits 1 on an invalid spec.

## Repository layout

```text
1_hydrate_openapi.py            step 1
2_fix_schema_names_and_refs.py  step 2
3_fix_semantic_paths.py         step 3
4_final_verification.py         step 4
common.py                       helpers shared by the steps
run_pipeline.py                 runs 1-4 per locale into build/
example/
  openapi.json                  broken input (fictional Shelfline Field API)
  config.yaml                   metadata, components, error rules, tag order
  corrections.yaml              reviewed fixes for step 3
  locales/{en,pt-BR,es,fr}/     dictionary.json + summaries.json
tests/                          unit and end-to-end tests
pyproject.toml                  metadata, dependency ranges, ruff and pytest config
requirements*.txt               exact pins compiled from pyproject.toml (make lock)
```

## Using it on your own spec

1. Copy `example/` to a new folder and drop in your generated `openapi.json`.
2. Run step 1 without `--strict`: the warnings list every placeholder and operation that still needs text. Fill in `dictionary.json` and `summaries.json`.
3. Run step 3 with `--export-config` to get a template, then run step 4. Leave anything step 4 fixes automatically; put fixes that need a human decision in `corrections.yaml`.
4. `python run_pipeline.py --example my-api --out dist`

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, the checks CI runs, and the pull request flow. Report vulnerabilities as described in [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) © 2025 Rafael Teixeira
