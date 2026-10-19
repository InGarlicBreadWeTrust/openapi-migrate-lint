"""Lint rules (3.1 -> 3.2 migration hazards) and structural validation.

Each rule produces :class:`Finding` objects. Per-node rules run over the whole
document tree via :func:`parser.iter_nodes`; structural rules inspect the tree
once.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Callable

from . import parser

# Severities, most-severe first (used for ordering and for --fail-on).
SEVERITY_ORDER = ["error", "high", "medium", "low", "note"]

OPERATION_KEYWORDS = {
    "get", "put", "post", "delete", "patch", "head", "options", "trace",
}
RESERVED_PATH_ITEM_KEYS = OPERATION_KEYWORDS | {
    "summary", "description", "parameters", "servers", "$ref",
}


@dataclass
class Finding:
    """A single diagnostic produced by a rule."""

    rule: str
    title: str
    severity: str           # one of SEVERITY_ORDER
    message: str
    location: str           # logical JSON-pointer-ish path
    fixable: bool = False
    suggestion: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# Per-node lint rules.   Signature: (node, location) -> list[Finding] | None    #
# --------------------------------------------------------------------------- #

def det_allof_nullable(node: Any, loc: str):
    """R32-002 — nullifying a $ref via `allOf` silently fails in 3.2."""
    if (
        isinstance(node, dict)
        and "allOf" in node
        and node.get("nullable") is True
    ):
        return [Finding(
            "R32-002", "nullified via allOf (silently broken)", "high",
            "'allOf' combined with a sibling 'nullable' was the common 3.0 way "
            "to make a $ref nullable. 3.2 ignores the sibling keyword, so this "
            "will no longer admit null.",
            loc, fixable=False,
            suggestion='Rewrite as `anyOf: [ {$ref: "..."}, {type: "null"} ]`.',
        )]
    return None


def det_allof_enum(node: Any, loc: str):
    """R32-003 — `allOf` + sibling `enum`/`const` shifts semantics in 2020-12."""
    if (
        isinstance(node, dict)
        and "allOf" in node
        and ("enum" in node or "const" in node)
    ):
        return [Finding(
            "R32-003", "allOf with sibling enum/const", "medium",
            "In JSON Schema 2020-12 (OpenAPI 3.2) 'enum'/'const' apply to the "
            "result of 'allOf', not to each subschema. This usually changes "
            "validation behaviour versus 3.0/3.1.",
            loc, fixable=False,
            suggestion="If you meant to restrict the composed result, that is now "
            "the intended behaviour; otherwise move the enum/const into the "
            "subschema.",
        )]
    return None


def det_ref_siblings(node: Any, loc: str):
    """R32-004 — keywords next to `$ref` are ignored as siblings in 2019/2020."""
    if isinstance(node, dict) and "$ref" in node and len(node) > 1:
        siblings = sorted(k for k in node if k != "$ref")
        return [Finding(
            "R32-004", "$ref ignored with sibling keywords", "medium",
            "In JSON Schema 2019/2020 the following keyword(s) next to '$ref' "
            f"are ignored: {', '.join(siblings)}. In 3.0 many were honoured; in "
            "3.2 they are silently dropped.",
            loc, fixable=False,
            suggestion="Move the sibling keywords (e.g. 'format', 'description', "
            "'nullable') into the referenced schema, or drop them.",
        )]
    return None


def det_exclusive_bool(node: Any, loc: str):
    """R32-005 — boolean `exclusiveMinimum`/`Maximum` is a 3.0 relic."""
    if not isinstance(node, dict):
        return None
    out = []
    for key in ("exclusiveMinimum", "exclusiveMaximum"):
        val = node.get(key)
        if isinstance(val, bool):
            out.append(Finding(
                "R32-005", f"{key} must be a number in 3.2", "medium",
                f"'{key}' was a boolean in OpenAPI 3.0; in 3.1/3.2 it is a "
                "number giving the exclusive bound. A boolean here is ignored "
                "and the bound may be wrong.",
                f"{loc}/{key}", fixable=True,
                suggestion="Replace with the numeric bound, e.g. set the same "
                "value as 'minimum'/'maximum' when the boolean was true.",
            ))
    return out or None


def det_nullable(node: Any, loc: str):
    """R32-001 — a top-level 'nullable' keyword is silently ignored in 3.2."""
    if isinstance(node, dict) and node.get("nullable") is True:
        if "allOf" in node:   # let the allOf rules own it; avoids a double report
            return None
        return [Finding(
            "R32-001", "unused nullable keyword", "high",
            "'nullable' has no effect in OpenAPI 3.2 (JSON Schema 2020-12 has "
            "no 'nullable'); this schema will no longer accept null.",
            loc, fixable=True,
            suggestion='Use `type: ["<type>", "null"]` or `anyOf: [ .., '
            '{type: "null"} ]` instead.',
        )]
    return None


PER_NODE_RULES: list[Callable[[Any, str], Any]] = [
    det_allof_nullable,
    det_allof_enum,
    det_ref_siblings,
    det_exclusive_bool,
    det_nullable,   # last: defers to the allOf cases above
]


# --------------------------------------------------------------------------- #
# Structural / validation rules (whole document, run once)                     #
# --------------------------------------------------------------------------- #

def v_openapi(root, loc):
    vals = []
    ver = root.get("openapi")
    if not isinstance(ver, str):
        vals.append(Finding(
            "V01", "missing 'openapi' version", "error",
            "Document has no string 'openapi' field.", loc,
            suggestion='Add `openapi: "3.2.1"`.'))
    elif not ver.startswith("3.2"):
        vals.append(Finding(
            "V01", "not on OpenAPI 3.2", "medium",
            f"'openapi' is '{ver}', not 3.2.*. Some lints below assume 3.2 "
            "semantics.", loc, suggestion='Bump to `openapi: "3.2.1"`.'))
    return vals


def v_info(root, loc):
    info = root.get("info", {})
    out = []
    if not isinstance(info, dict):
        out.append(Finding(
            "V02", "'info' must be an object", "error",
            "'info' is missing or not an object.", f"{loc}/info"))
        return out
    for req in ("title", "version"):
        if not info.get(req):
            out.append(Finding(
                "V02", f"'info.{req}' missing", "high",
                f"'info.{req}' is required by the OpenAPI specification.",
                f"{loc}/info/{req}"))
    return out


def v_paths_or_components(root, loc):
    if "paths" not in root and "components" not in root:
        return [Finding(
            "V03", "no paths and no components", "medium",
            "Document has neither 'paths' nor 'components'; it describes "
            "nothing usable.", loc)]
    return []


def v_operation_keys(root, loc):
    out = []
    paths = root.get("paths")
    if not isinstance(paths, dict):
        return out
    for pkey, item in paths.items():
        locp = f"paths/{pkey}"
        if not isinstance(item, dict):
            out.append(Finding(
                "V04", f'"{pkey}" path item not an object', "medium",
                "Path item must be an object.", locp))
            continue
        for opkey, _op in item.items():
            if opkey in RESERVED_PATH_ITEM_KEYS:
                continue
            out.append(Finding(
                "V04", f"unknown path key '{opkey}'", "high",
                f"'{opkey}' under path '{pkey}' is not a valid OpenAPI "
                f"operation keyword or reserved key.", locp,
                fixable=False,
                suggestion=f"Remove it, or did you mean one of "
                f"{sorted(OPERATION_KEYWORDS)}?"))
    return out


def v_refs(root, loc):
    out = []
    for locp, node in parser.iter_nodes(root):
        if isinstance(node, dict) and "$ref" in node:
            ref = node["$ref"]
            if isinstance(ref, str) and ref.startswith("#"):
                if parser.resolve_ref(root, ref) is None:
                    out.append(Finding(
                        "V05", f"unresolvable $ref '{ref}'", "high",
                        f"'$ref' '{ref}' does not resolve to a value in the "
                        "document.", f"{locp}/$ref", fixable=False,
                        suggestion="Check the pointer, or define the referenced "
                        "component."))
    return out


def v_dup_operationid(root, loc):
    seen = {}
    out = []
    paths = root.get("paths", {})
    if isinstance(paths, dict):
        for pkey, item in paths.items():
            if not isinstance(item, dict):
                continue
            for opkey, op in item.items():
                if opkey in OPERATION_KEYWORDS and isinstance(op, dict):
                    oid = op.get("operationId")
                    l = f"paths/{pkey}/{opkey}"
                    if isinstance(oid, str):
                        if oid in seen:
                            out.append(Finding(
                                "V06", f"duplicate operationId '{oid}'",
                                "medium",
                                f"'{oid}' is also used at {seen[oid]}.",
                                f"{l}/operationId", fixable=False))
                        else:
                            seen[oid] = l
    return out


def v_security_refs(root, loc):
    out = []
    components = root.get("components", {})
    defined = set()
    if isinstance(components, dict):
        ss = components.get("securitySchemes", {})
        if isinstance(ss, dict):
            defined = set(ss)
    refs = list(root.get("security", []) or [])
    paths = root.get("paths", {})
    if isinstance(paths, dict):
        for pkey, item in paths.items():
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("security"), list):
                refs.extend(item["security"])
            for opkey in OPERATION_KEYWORDS:
                op = item.get(opkey)
                if isinstance(op, dict) and isinstance(op.get("security"), list):
                    refs.extend(op["security"])
    for req in refs:
        if isinstance(req, dict):
            for name in req:
                if name not in defined and defined:
                    out.append(Finding(
                        "V07", f"undefined security scheme '{name}'",
                        "medium",
                        f"'security' references '{name}', which is not defined "
                        "in components.securitySchemes.", "security",
                        fixable=False,
                        suggestion="Define the scheme or remove the reference."))
    return out


WHOLE_DOC_RULES: list[Callable[[dict, str], list[Finding]]] = [
    v_openapi, v_info, v_paths_or_components,
    v_operation_keys, v_refs, v_dup_operationid, v_security_refs,
]


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def _dedupe(findings):
    key = lambda f: (f.rule, f.location, f.message)
    seen, out = set(), []
    for f in findings:
        k = key(f)
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


def _sort(findings):
    order = {s: i for i, s in enumerate(SEVERITY_ORDER)}
    return sorted(
        findings,
        key=lambda f: (order.get(f.severity, 99), f.rule, f.location),
    )


def lint(root, loc="root"):
    """Run the per-node migration-hazard rules over the whole document."""
    out = []
    for locp, node in parser.iter_nodes(root):
        for rule in PER_NODE_RULES:
            res = rule(node, locp)
            if res:
                out.extend(res)
    return _sort(_dedupe(out))


def validate(root, loc="root"):
    """Run the structural / spec rules over the document once."""
    out = []
    for rule in WHOLE_DOC_RULES:
        try:
            found = rule(root, loc)
            if found:
                out.extend(found)
        except Exception as e:   # a rule must never crash the run
            out.append(Finding(
                "V99", f"validator error in {rule.__name__}", "low",
                f"{type(e).__name__}: {e}", loc))
    return _sort(_dedupe(out))


def run_checks(root, *, do_validate=False, loc="root"):
    """Run lint rules and, optionally, structural validation. Deduped."""
    findings = lint(root, loc)
    if do_validate:
        findings = findings + validate(root, loc)
    return _sort(_dedupe(findings))
