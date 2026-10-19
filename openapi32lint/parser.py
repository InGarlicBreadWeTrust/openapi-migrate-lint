"""Safe loading and traversal for OpenAPI documents.

SECURITY POSTURE
----------------
* YAML is parsed with ``yaml.safe_load`` (from PyYAML), never ``full_load``.
  ``full_load`` would execute the ``!!python/object`` / ``!!python/object/apply``
  tags and let an attacker run arbitrary Python from a data file. ``safe_load``
  rejects any such tag with a LoaderError, which we surface as ``LoadError``.
* JSON is parsed with the stdlib ``json`` module.
* The module performs no network I/O, no filesystem writes, and no use of
  ``eval``/``exec``/``os.system``/``subprocess``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

try:  # PyYAML is the single declared runtime dependency.
    import yaml
except ModuleNotFoundError:  # pragma: no cover - only when YAML requested without dep
    yaml = None  # type: ignore


class OpenAPIDocError(Exception):
    """Base error for openapi32lint operations."""


class LoadError(OpenAPIDocError):
     """Raised when a document cannot be parsed into a mapping."""


class LintError(OpenAPIDocError):
     """Raised when a document is structurally wrong enough to lint (reserved).

     Currently unused by the rule set (findings carry the diagnostics instead),
     but kept in the public surface so future, fail-fast checks have a home.
     """


def load_document(path: str | Path) -> Any:
    """Load an OpenAPI document from a file path.

    ``.json`` files are parsed with the stdlib json parser; anything else is
    parsed with ``yaml.safe_load`` (safe — no code execution from YAML tags).
    """
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    parsed = load_text(raw, is_json=p.suffix.lower() == ".json", source=str(p))
    if not isinstance(parsed, dict):
        raise OpenAPIDocError(
            f"{p}: top level must be a mapping/object "
            f"(got {type(parsed).__name__})"
        )
    return parsed


def load_text(text: str, *, is_json: bool = False, source: str = "<input>") -> Any:
    """Parse a document from text. JSON when ``is_json`` else safe-load YAML."""
    if is_json:
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:  # pragma: no cover
            raise LoadError(f"Invalid JSON in {source}: {e}") from e
    if yaml is None:  # pragma: no cover
        raise LoadError(
            f"Cannot parse {source} as YAML: PyYAML is not installed. "
            "Install it with `pip install pyyaml`."
        )
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:  # type: ignore[union-attr]
        raise LoadError(f"Invalid YAML in {source}: {e}") from e


def iter_nodes(root: Any, prefix: str = "root") -> Iterator[tuple[str, Any]]:
    """Yield ``(path, node)`` for every node in the tree, depth-first.

    ``path`` is a human-readable JSON-pointer-ish dotted path (``components/
    schemas/Foo/type``), which we reuse as the logical location in findings and
    in SARIF ``message.text``.
    """
    yield prefix, root
    if isinstance(root, dict):
        for k, v in root.items():
            child = f"{prefix}/{k}" if prefix != "root" else str(k)
            yield from iter_nodes(v, child)
    elif isinstance(root, list):
        for i, v in enumerate(root):
            child = f"{prefix}[{i}]"
            yield from iter_nodes(v, child)


def json_pointer_unescape(token: str) -> str:
    """Unescape a single JSON Pointer path token per RFC 6901."""
    return token.replace("~1", "/").replace("~0", "~")


def resolve_ref(root: Any, ref: Any) -> Any | None:
    """Resolve a local ``#/pointer`` reference against ``root``.

    Returns the resolved value, or ``None`` if the pointer does not exist.
    External refs (``http(s)://`` or a filename) are returned as ``None`` — we
    never fetch them (no network in this tool).
    """
    if not isinstance(ref, str):
        return None
    if not ref.startswith("#/") and not ref.startswith("#"):
        return None
    pointer = ref[1:] or ""
    if pointer.startswith("/"):
        pointer = pointer[1:]
    cur: Any = root
    if pointer == "":
        return cur
    for token in pointer.split("/"):
        tok = json_pointer_unescape(token)
        if isinstance(cur, dict) and tok in cur:
            cur = cur[tok]
        elif isinstance(cur, list) and tok.isdigit() and int(tok) < len(cur):
            cur = cur[int(tok)]
        else:
            return None
    return cur
