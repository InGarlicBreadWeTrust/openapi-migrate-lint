"""openapi32lint - lint & validate OpenAPI 3.1 -> 3.2 migrations.

A pure-Python, dependency-light linter for the migration hazards that break
when an OpenAPI document moves from 3.0/3.1 to 3.2 (JSON-Schema-2020-12).
No network. No subprocess. ``yaml.safe_load`` only (no ``!!python/object``
tags). Stdlib + PyYAML only.
"""
from __future__ import annotations

__version__ = "0.1.0"

__all__ = [
     "__version__",
     "load_document",
     "load_text",
     "iter_nodes",
     "LintError",
     "OpenAPIDocError",
     "LoadError",
     "run_checks",
     "lint",
     "validate",
     "apply_fixes",
     "FixResult",
     "Finding",
     "SEVERITY_ORDER",
     "PER_NODE_RULES",
]

from .parser import (
     load_document, load_text, iter_nodes,
     LintError, OpenAPIDocError, LoadError,
)
from .rules import (
     run_checks, lint, validate,
     Finding, SEVERITY_ORDER, PER_NODE_RULES,
)
from .fix import apply_fixes, FixResult
