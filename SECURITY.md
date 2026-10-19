# Security posture of `openapi32lint`

This tool reads an OpenAPI document (`.yaml`/`.json`) and either reports issues or
writes a *fixed* copy to a path you name. The threat model is: **the document being
linted is untrusted data — it may come from a malicious or broken upstream, or from a
path supplied by a caller/CI job.** The code is written so that untrusted input can
never execute anything, escape the filesystem, or be exfiltrated.

## Design principles

1. **No execution of input.** The document is parsed with `yaml.safe_load`
   (or stdlib `json`), not `yaml.full_load`. The dangerous PyYAML tags that can run
   arbitrary code — `!!python/object`, `!!python/apply:os.system`,
   `!!python/object:subprocess...` — raise `ConstructorError`, which we catch and
   turn into a safe `LoadError`. There is no call anywhere to `eval`, `exec`,
   `os.system`, `subprocess`, or `compile`. The test `test_yaml_object_tag_blocked`
   asserts this for both YAML and JSON object payloads.

2. **No network, no shell.** The package has **zero** runtime dependencies beyond
   PyYAML (used only to *decode* `.yaml` input). It never opens a socket, calls a
   URL, or spawns a process. SARIF/JSON output is produced entirely in-process.

3. **Auto-fix never mutates your input.** `fix.apply_fixes()` deep-copies the
   document before transforming it, so the original tree is always intact. Only
   *mechanically unambiguous* rewrites are applied (`nullable` -> `type: [.., null]`,
   `exclusiveMinimum: true` + `minimum: n` -> `exclusiveMinimum: n`, removing
   `exclusive…: false`). The hazards that need judgement (e.g. `allOf` + `nullable`)
   are **left in place and skipped**, never guessed at.

4. **Output paths cannot escape the working directory.** A `--fix` target is
   *resolved* (following symlinks, collapsing `..`) before it is written, and must
   sit inside the current working directory, or the write is refused (exit code 3).
   This blocks path-traversal via a caller-supplied path
   (e.g. `--fix ../../etc/passwd`). Pass `--allow-outside` to opt out deliberately.
   `test_guard_blocks_out_of_cwd` and `test_main_blocks_fix_outside_cwd` cover this.

5. **Local `$ref` resolution is bounded.** `resolve_ref` walks the local document
   and caps the recursion depth (`_REF_DEPTH`) instead of following an arbitrary
   chain, so a cycle in a pathological document cannot hang the process.

## What it does *not* do
- It does not fetch anything, so it performs no SSRF and cannot leak secrets.
- It does not write to any path you did not name.
- It does not install or run any third-party code.

## Report a vulnerability
Open an issue labelled `security` (or email `rzl` — update as the project grows).
Do not file anything that includes production secrets.
