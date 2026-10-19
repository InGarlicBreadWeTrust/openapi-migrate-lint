# openapi32lint

> Lint & validate your **OpenAPI 3.1 -> 3.2** migration. Catch the hazards that
> break silently when JSON-Schema-2020-12 replaces draft-4, and auto-fix the safe
> ones — before your API contract stops admitting null.

OpenAPI 3.2 was finalised in September 2025 and switched the schema model to
JSON-Schema-2020-12. As of mid-2026 a large share of the major consumers
(parallel, OpenAPI tooling, SDK generators) still cannot fully read 3.2, and the
migration itself is a known pit mine. The most painful break is this:

```yaml
# OpenAPI 3.1  (this used to work)
Pet:
      nullable: true
      $ref: "#/components/schemas/Owner"          # "make the referenced type nullable"

# OpenAPI 3.2  (this now DOES nothing — 3.2 silently ignores the sibling)
Pet:
      $ref: "#/components/schemas/Owner"
```

In 3.1 a `nullable` sibling next to a `$ref` (or a `nullable` under `allOf`) was
the common way to make a referenced type nullable. In 3.2 the sibling keyword is
**ignored** and the ref no longer accepts `null` — your request/response contracts
break at runtime in ways no parser tells you about. `openapi32lint` finds these
*and* the other breaking changes, and rewrites the ones that are safe to rewrite.

---

## Why it exists
- **3.2 is the new default and the tooling is behind it.** 13+ months after the
  spec, most consumers don't fully read 3.2 yet — so the documents *you* write to
  migrate are where the bugs live.
- **The breaks are silent.** A `$ref` with ignored siblings, or `allOf` +
  `nullable`, compiles fine; only *runtime* traffic exposes it. A linter moves the
  failure left, into CI, where it's cheap.
- **No heavyweight engine required.** The whole point is a dependency-light,
  offline, auditable check you can drop into any pipeline.

## What it catches

### Migration hazards (`--lint` / default)
| Rule | Sev | What | Auto-fix |
|------|-----|------|----------|
| `R32-001` | high | Bare `nullable: true` next to `type` — no effect in 3.2 | yes -> `type: [.., "null"]` |
| `R32-002` | high | `allOf` + `nullable` sibling — the broken "nullable $ref" path | no (manual) |
| `R32-003` | high | `enum` as a sibling of `allOf` — ignored in 3.2 | no (manual) |
| `R32-004` | medium | `$ref` with sibling keywords (`format`, `nullable`, …) — all ignored | no (manual) |
| `R32-005` | medium | `exclusiveMinimum`/`exclusiveMaximum` as a boolean — must be a number | yes (if a numeric bound is present) |

### Structural validation (`--validate`)
`V01` missing/`openapi` version, `V02` incomplete `info`, `V03` missing responses,
`V04` unknown `paths` keywords (typo like `get` -> `gett`), `V05` unresolvable
local `$ref`, `V06` duplicate `operationId`, `V07` duplicate tag, `V08` duplicate
path.

## Install

```bash
# Core needs ONLY PyYAML. Pure stdlib otherwise.
pip install .
# Or, no install: run from a checkout
PYTHONPATH=. python -m openapi32lint <file>
```

Zero runtime deps besides PyYAML (used only to *read* `.yaml` input). No network.

## Usage

```bash
# Human report
python -m openapi32lint openapi.yaml

# Machine / CI report
python -m openapi32lint openapi.yaml --json
python -m openapi32lint openapi.yaml --sarif        # GitHub code scanning

# Gate a build on high+ issues (exit 0 = clean, 1 = issues found)
python -m openapi32lint openapi.yaml --fail-on high

# Auto-rewrite the safe fixes, writing a new file (input is never mutated)
python -m openapi32lint openapi.yaml --fix openapi.fixed.yaml

# Read from stdin (great for pipes)
cat openapi.yaml | python -m openapi32lint - --sarif
```

Flags: `--validate` (structural checks), `--json`, `--sarif`, `--fix [OUT]`,
`--fail-on {note,low,medium,high,error}` (CI exit threshold), `--quiet`.

## How it works (6 modules, ~830 LOC)

```
parser.py   safe loader: yaml.safe_load + stdlib json only; iter_nodes / resolve_ref
rules.py    Finding dataclass, per-node + structural rules, dedup, sort, run_checks
fix.py      NON-MUTATING auto-fix on a deepcopy; safe fixes apply, unsafe skip
reports.py  text / JSON / SARIF 2.1.0 emitters; threshold_met
cli.py      argparse front-end, -m entrypoint
__init__    public API re-exports
```

**Fixes are conservative by design.** R32-001 and a numeric R32-005 are rewritten;
R32-002/003/004 are *left in place and skipped* with a manual-rewrite hint. The tool
would never guess at a rewrite that could silently change your contract.

## Security posture (see `SECURITY.md` for the full audit)
- `yaml.safe_load` **only** — the `!!python/object`, `!!python/apply` code-exec
  tags are *rejected*, never evaluated. (There is a test for it.)
- No `eval`, `exec`, `os.system`, `subprocess`, no network I/O, no shell.
- `--fix` deep-copies and writes to a caller-named path only; your input is never
  mutated. Output paths are validated to stay inside the CWD (see `Security` notes).
- 34 stdlib `unittest` tests, all green.

## License
MIT — see `LICENSE`.
