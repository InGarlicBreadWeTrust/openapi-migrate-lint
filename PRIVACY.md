# Privacy

`openapi-migrate-lint` is an **offline** static linter/migrator for OpenAPI
documents. It handles no network and collects no data of its own.

## In one line
It reads the OpenAPI file you give it and writes nothing you did not ask for — to
no one, over no network.

## What the tool does NOT do
- **No telemetry, no analytics, no crash reporting, no usage tracking.** Nothing in
   the code measures or reports what you lint.
- **No network of any kind.** No sockets, no HTTP/HTTPS, no background sync;
   `pyproject.toml` declares no runtime dependencies and the source opens no
   network. Even `http(s)://` **external `$ref`s are not fetched** — they are left
   as values in the document.
- **It never exfiltrates your document.** Because there is no network, the document
   you lint cannot leave your machine.

## What the tool DOES do
Only the file you give it:
- it parses the `.yaml`/`.json` you hand it (with PyYAML's `safe_load`, or stdlib
   `json`), and
- on `--fix`, writes the *fixed* copy **only to the path you name**, contained by
   `_guard_output_path` (refuses to escape the current working directory unless you
   pass `--allow-outside`).
Nothing is aggregated, retained, or sent for any purpose. The tool does not remember
between runs or index your documents.

## Data sensitivity
An OpenAPI document is usually **public interface design**, not personal data — so
this is the lowest-sensitivity tool in the set. Still, a document may expose
internal endpoints, parameter names, or business logic; keep `--fix` output under
your access control like any internal config.

## Your controls
- Decide where the fixed copy lives; the tool writes only the path you give it, and
   will not touch files you did not name.
- If a document is internal, keep the report/fixed copy out of public
   repositories.
- Retention is yours: delete the file and it is gone; the tool keeps no copy, backup,
   or cache.

## Data sharing
None. The tool contacts no third party, has no accounts or API keys, and retains no
data itself — the document lives only in the file you create on your own machine.
The only "third party" in scope is the upstream you may fetch the raw document from
*yourself*, outside this tool.

---

## Independent privacy audit (2026-10-21)

**Performed by:** `InGarlicBreadWeTrust` · **Type:** static source + dependency
review · **Result:** no privacy leakage; posture strong.

- No telemetry / analytics / crash reporting / background sync.
- No network I/O anywhere; external `http(s)://` refs are **not** fetched. Zero
   runtime dependencies.
- No data leaves the machine; the (optional) fixed document is written only to an
   explicit, contained path.
- No third-party services or accounts.

**Verdict:** no leakage and the lowest sensitivity of the set. No code change
   required; the only suggestion is to keep internal documents and their
   `--fix` output out of public repositories.
