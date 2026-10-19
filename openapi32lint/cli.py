"""Command-line interface.

Usage:
  python -m openapi32lint <file|-> [options]
  python -m openapi32lint --validate <file|-> [--json|--sarif|--fix[=PATH]]

    -            read from stdin
  --validate     add structural checks
  --fix[=PATH]   apply safe auto-fixes (prints to stdout, or writes PATH)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import parser, reports, fix
from .rules import run_checks
from . import __version__


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="openapi32lint",
        description="Lint an OpenAPI 3.1->3.2 migration, validate structure, "
          "and emit text/JSON/SARIF. Safe auto-fix available.")
    ap.add_argument("input", nargs="?", default="-",
        help="OpenAPI file path, or '-' for stdin (default -).")
    ap.add_argument("--validate", action="store_true",
        help="Also run structural/spec validation rules.")
    ap.add_argument("--json", action="store_true",
        help="Emit machine-readable JSON findings.")
    ap.add_argument("--sarif", action="store_true",
        help="Emit SARIF 2.1.0 for CI / GitHub code scanning.")
    ap.add_argument("--fix", nargs="?", const="", default=None, metavar="PATH",
        help="Apply safe auto-fixes. With no PATH, print the fixed document "
        "to stdout.")
    ap.add_argument("--allow-outside", action="store_true",
        help="Permit a --fix output path that resolves outside the current "
        "working directory (off by default; blocks path traversal via a "
        "caller-supplied path).")
    ap.add_argument("--fail-on", choices=reports.SEVERITY_ORDER[:-1],
        default=None,
        help="Exit non-zero if any finding meets/exceeds this severity "
        "(use as a CI gate).")
    ap.add_argument("--quiet", action="store_true",
        help="Suppress the 'all clear' line on success.")
    ap.add_argument("--version", action="version",
        version=f"openapi32lint {__version__}")
    return ap


def _read_input(path: str) -> tuple[dict, str]:
    """Return (document, source_label). Handles stdin and file paths."""
    if path in ("-", None):
        raw = sys.stdin.read()
        is_json = ".json" in raw        # heuristic for stdin
        try:
            parsed = parser.load_text(raw, is_json=is_json, source="<stdin>")
        except parser.OpenAPIDocError:
            parsed = None        # fall back to the other parser
            parsed = parser.load_text(
                raw, is_json=not is_json, source="<stdin>")
        if not isinstance(parsed, dict):
            raise parser.OpenAPIDocError(
                "stdin top level must be a mapping/object")
        return parsed, "<stdin>"
    return parser.load_document(path), path


def _guard_output_path(path: str, allow_outside: bool) -> Path:
    """Resolve a ``--fix`` output path, refusing to write outside the CWD.

    The path is resolved (following symlinks and collapsing ``..``) *before* it is
    used as a write target, so a caller can't escape the project directory via a
    value such as ``../../etc/evil`` or a symlink. Pass ``allow_outside=True`` to
    opt out for a target that genuinely lives elsewhere. Raises
    :class:`~openapi32lint.parser.OpenAPIDocError` when the path escapes the CWD.
    """
    target = Path(path).resolve()
    if allow_outside:
        return target
    cwd = Path.cwd().resolve()
    if target == cwd or cwd in target.parents:
        return target
    raise parser.OpenAPIDocError(
        f"refusing to write outside the current directory: {path!r} -> "
        f"{target}. Pass --allow-outside to permit, or run from a "
        f"parent directory.")


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)

    try:
        doc, source = _read_input(args.input)
    except parser.LoadError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2
    except parser.OpenAPIDocError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2

    # --- auto-fix mode ---
    if args.fix is not None:
        result = fix.apply_fixes(doc)
        rendered = json.dumps(result.document, indent=2)
        if args.fix:          # explicit path
            try:
                out = _guard_output_path(args.fix, args.allow_outside)
            except parser.OpenAPIDocError as e:
                print(f"[error] {e}", file=sys.stderr)
                return 3
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(rendered + "\n", encoding="utf-8")
            _print_fix_summary(result, str(out))
        else:
            print(rendered)
            _print_fix_summary(result, "stdout")
        return 0

    # --- lint / validate mode ---
    findings = run_checks(doc, do_validate=args.validate)
    if args.sarif:
        print(reports.sarif_report(findings, source))
        return 1 if reports.threshold_met(findings, args.fail_on) else 0
    if args.json:
        print(reports.json_report(findings, source))
        return 1 if reports.threshold_met(findings, args.fail_on) else 0
    print(reports.text_report(
        findings, source, threshold=args.fail_on, quiet_all=args.quiet))
    return 1 if reports.threshold_met(findings, args.fail_on) else 0


def _print_fix_summary(result, where: str) -> None:
    print(
        f"[fix] {len(result.applied)} applied, "
        f"{len(result.skipped)} skipped (need manual review) -> {where}",
        file=sys.stderr, )
