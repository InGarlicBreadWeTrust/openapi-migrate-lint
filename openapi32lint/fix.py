"""Safe auto-fixes for OpenAPI 3.1 -> 3.2 migration hazards.

Only *mechanically unambiguous* rewrites are applied automatically:
  * ``{type: "x", nullable: true}``        -> ``{type: ["x", "null"]}``
  * ``{type: ["x"], nullable: true}``       -> ``{type: ["x", "null"]}``
  * ``{...no type, nullable: true}``        -> ``{anyOf: [<rest>, {type:null}]}``
  * ``exclusiveMinimum: true`` + ``minimum: n``  -> ``exclusiveMinimum: n``
  * ``exclusive{Max/Minimum}: false``               -> removed

Fixes that *cannot* be made safely (e.g. ``allOf`` + ``nullable``) are left in
place and reported as "skipped" so a human can review them. ``apply_fixes``
never mutates its input — it returns a fresh document.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .rules import Finding


@dataclass
class FixResult:
    changed: bool
    document: Any
    applied: list[Finding] = field(default_factory=list)
    skipped: list[Finding] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.applied) + len(self.skipped)


def apply_fixes(root: Any) -> FixResult:
    """Return a :class:`FixResult` with a rewritten copy of ``root``.

    The input is not mutated (the tree is deep-copied before transformation).
    """
    applied, skipped = [], []
    new = _walk(deepcopy(root), applied, skipped, loc="root")
    return FixResult(changed=bool(applied or skipped),
                     document=new, applied=applied, skipped=skipped)


def _walk(obj: Any, applied, skipped, loc: str) -> Any:
    if isinstance(obj, dict):
        new: dict = {}
        # Recurse first so children are transformed before we fix this level.
        for k, v in obj.items():
            child = f"{loc}/{k}" if loc != "root" else str(k)
            new[k] = _walk(v, applied, skipped, child)
        _fix_nullable(new, loc, applied, skipped)
        _fix_exclusive(new, loc, applied, skipped)
        return new
    if isinstance(obj, list):
        return [_walk(v, applied, skipped, f"{loc}[{i}]")
                for i, v in enumerate(obj)]
    return obj


def _fix_nullable(new: dict, loc: str, applied, skipped) -> None:
    if new.get("nullable") is not True:
        return
    new.pop("nullable", None)
    # Unfixable: nullifying an allOf result is not something we rewrite blindly.
    if "allOf" in new:
        new["nullable"] = True   # leave in place; a human should rewrite to anyOf
        skipped.append(Finding(
             "R32-002", "unfixable: allOf + nullable", "high",
             "auto-fix skipped: nullifying an `allOf` needs a manual rewrite to "
             "`anyOf`. Left `nullable` in place so it is not silently lost.",
            loc, fixable=False,
            suggestion='Rewrite by hand as `anyOf: [ {$ref: "..."}, '
             '{type: "null"} ]`.'))
        return
    typ = new.get("type")
    if isinstance(typ, str):
        t = [typ, "null"] if typ != "null" else [typ]
        new["type"] = t
        applied.append(Finding(
             "R32-001", "nullable -> type list", "high",
             f"'nullable: true' replaced with `type: {t!r}`.",
            loc, fixable=True))
    elif isinstance(typ, list):
        if "null" not in typ:
            new["type"] = list(typ) + ["null"]
        applied.append(Finding(
             "R32-001", "nullable -> type list", "high",
             f"'nullable: true' folded into `type: {new['type']!r}`.",
            loc, fixable=True))
    else:
        # No explicit type: wrap the remaining schema in anyOf with a null branch.
        snapshot = {k: v for k, v in new.items() if k != "anyOf"}
        new["anyOf"] = [snapshot, {"type": "null"}]
        applied.append(Finding(
             "R32-001", "nullable -> anyOf", "high",
             "'nullable: true' (no type) replaced with an `anyOf` including a "
             "`{type: 'null'}` branch.", loc, fixable=True))


def _fix_exclusive(new: dict, loc: str, applied, skipped) -> None:
    for key, paired in (("exclusiveMinimum", "minimum"),
                        ("exclusiveMaximum", "maximum")):
        if key not in new or not isinstance(new[key], bool):
            continue
        truthy = new[key] is True
        paired_val = new.get(paired)
        numeric = isinstance(paired_val, (int, float)) and not isinstance(
            paired_val, bool)
        if truthy and numeric:
            new[key] = paired_val
            applied.append(Finding(
                 "R32-005", f"{key} boolean -> number", "medium",
                f"'{key}: true' + '{paired}: {paired_val}' rewritten to "
                f"'{key}: {paired_val}'.", f"{loc}/{key}", fixable=True))
        elif not truthy:
            del new[key]
            applied.append(Finding(
                 "R32-005", f"{key} removed", "medium",
                f"'{key}: false' removed (an inclusive bound needs no exclusive "
                f"flag).", f"{loc}/{key}", fixable=True))
        else:
            skipped.append(Finding(
                 "R32-005", f"cannot infer {key} bound", "medium",
                f"'{key}: true' found but no numeric '{paired}' to base it on; "
                 "left unchanged.", f"{loc}/{key}", fixable=False,
                suggestion=f"Set '{key}' to a numeric value explicitly."))
