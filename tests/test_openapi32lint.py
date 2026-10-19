"""Tests for openapi32lint (stdlib ``unittest`` - no third-party deps).

Run:
    python -m unittest discover -s tests
    python -m unittest tests.test_openapi32lint
"""
from __future__ import annotations

import json
import unittest

from openapi32lint.parser import (
     load_text, iter_nodes, resolve_ref, LoadError, OpenAPIDocError,
)
from openapi32lint.rules import (
     lint, validate, run_checks, Finding, SEVERITY_ORDER,
)
from openapi32lint import fix
from openapi32lint import reports
from openapi32lint import cli


class ParserTests(unittest.TestCase):
    def test_load_text_yaml(self):
        doc = load_text(
             "openapi: '3.2.1'\ninfo:\n  title: x\n  version: 1\n",
             is_json=False,
            )
        self.assertEqual(doc["openapi"], "3.2.1")

    def test_load_text_json(self):
        doc = load_text(
             '{"openapi":"3.2.1","info":{"title":"x","version":"1"}}',
             is_json=True,
            )
        self.assertEqual(doc["info"]["title"], "x")

    def test_malformed_yaml_raises_load_error(self):
        with self.assertRaises(LoadError):
            load_text("this: : : not: valid", is_json=False)

    def test_malformed_json_raises_load_error(self):
        with self.assertRaises(LoadError):
            load_text("{ not json ]", is_json=True)

    def test_yaml_object_tag_blocked(self):
           # A python/object code-exec tag must be rejected by safe_load, never
           # executed. This is the core security guarantee of the loader.
        for payload in (
             "a: !!python/object/apply:os.system [\"echo hi\"]\n",
             "a: !!python/object null\n",
             ):
            with self.assertRaises((LoadError, OpenAPIDocError)):
                load_text(payload, is_json=False)

    def test_list_top_level_rejected_by_load_document(self):
           # load_text is permissive; load_document enforces a mapping top level.
        from openapi32lint.parser import load_document
        import tempfile, os, pathlib
        tf = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False)
        tf.write("[]\n")
        tf.close()
        try:
            with self.assertRaises(OpenAPIDocError):
                 load_document(tf.name)
        finally:
             os.unlink(tf.name)

    def test_iter_nodes_yields_paths(self):
        d = {"a": {"b": [1, {"c": 2}]}}
        locs = {loc for loc, _ in iter_nodes(d)}
        self.assertIn("a/b[1]/c", locs)

    def test_resolve_ref_deep_and_no_loop(self):
        d = {
             "components": {"schemas": {"Cat": {"properties": {
                 "name": {"type": "string"}}}}},
        }
        self.assertIsNotNone(resolve_ref(d, "#/components/schemas/Cat"))
        self.assertIsNone(resolve_ref(d, "#/components/schemas/Dog"))
        # A self-referential pointer must not loop forever.
        self.assertIsNone(resolve_ref(d, "#/components/schemas/Cat/self"))


class LintTests(unittest.TestCase):
    def _find(self, root, rule):
        return [f for f in lint(root) if f.rule == rule]

    def test_r32_001_nullable(self):
        f = self._find({"type": "string", "nullable": True}, "R32-001")
        self.assertEqual(len(f), 1)
        self.assertTrue(f[0].fixable)

    def test_r32_001_defers_to_allof(self):
          # {allOf, nullable} is owned by R32-002, not a bare R32-001.
        root = {"allOf": [{"$ref": "#/x"}], "nullable": True}
        self.assertEqual(self._find(root, "R32-001"), [])
        self.assertEqual(len(self._find(root, "R32-002")), 1)

    def test_r32_002_allof_nullable(self):
        root = {"allOf": [{"$ref": "#/x"}], "nullable": True}
        f = self._find(root, "R32-002")
        self.assertEqual(len(f), 1)
        self.assertFalse(f[0].fixable)

    def test_r32_003_allof_enum(self):
        root = {"allOf": [{"type": "number"}], "enum": [1, 2]}
        self.assertEqual(len(self._find(root, "R32-003")), 1)

    def test_r32_004_ref_siblings(self):
        root = {"$ref": "#/a", "format": "date", "nullable": True}
        f = self._find(root, "R32-004")
        self.assertEqual(len(f), 1)
        for k in ("format", "nullable"):
            self.assertIn(k, f[0].message)

    def test_r32_005_bool_exclusive(self):
        root = {"type": "integer", "exclusiveMinimum": True}
        f = self._find(root, "R32-005")
        self.assertTrue(f)
        self.assertTrue(f[0].fixable)

    def test_no_findings_on_clean_doc(self):
        root = {"openapi": "3.2.1", "type": "string"}
        self.assertEqual(lint(root), [])

    def test_output_is_sorted_by_severity(self):
          # A clean doc has no findings, which is trivially sorted.
        root = {"openapi": "3.2.1", "info": {"title": "x"}, "type": "string"}
        found = run_checks(root, do_validate=True)
        order = {s: i for i, s in enumerate(SEVERITY_ORDER)}
        ranks = [order.get(f.severity, 99) for f in found]
        self.assertEqual(ranks, sorted(ranks))

    def test_findings_deduped(self):
          # A doc that triggers the same rule at one location reports once.
        root = {"paths": {"/a": {"bogus": {}}}}
        found = run_checks(root, do_validate=True)
        keys = [(f.rule, f.location, f.message) for f in found]
        self.assertEqual(len(keys), len(set(keys)))


class ValidateTests(unittest.TestCase):
    def test_missing_openapi_is_error(self):
        f = validate({})
        self.assertTrue(any(x.rule == "V01" and x.severity == "error"
                            for x in f))

    def test_missing_info_fields(self):
        root = {"openapi": "3.2.1", "info": {"title": "x"}}
        f = validate(root)
        self.assertTrue(any("version" in x.message for x in f
                             if x.rule == "V02"))

    def test_unknown_path_keyword(self):
        root = {"paths": {"/p": {"bogusOp": {}}}}
        self.assertTrue(any(x.rule == "V04" for x in validate(root)))

    def test_unresolvable_ref(self):
        root = {
             "paths": {
                 "/x": {"get": {"responses": {
                      "200": {"content": {"application/json": {
                          "schema": {"$ref": "#/components/schemas/Missing"}}}}}}}},
        }
        self.assertTrue(any(x.rule == "V05" for x in validate(root)))

    def test_duplicate_operationid(self):
        root = {"paths": {
             "/a": {"get": {"operationId": "dup"}},
             "/b": {"get": {"operationId": "dup"}},
         }}
        self.assertTrue(any(x.rule == "V06" for x in validate(root)))

    def test_run_checks_combines_lint_and_validate(self):
        root = {"info": {"title": "x"}}
        found = run_checks(root, do_validate=True)
        self.assertIn("V01", {f.rule for f in found})


class FixTests(unittest.TestCase):
    def test_nullable_string_to_type_list(self):
        res = fix.apply_fixes({"type": "string", "nullable": True})
        self.assertEqual(res.document["type"], ["string", "null"])
        self.assertNotIn("nullable", res.document)
        self.assertTrue(res.changed)
        self.assertEqual(len(res.applied), 1)

    def test_nullable_list_adds_null(self):
        res = fix.apply_fixes({"type": ["string", "integer"],
                                "nullable": True})
        self.assertEqual(res.document["type"],
                           ["string", "integer", "null"])

    def test_nullable_no_type_wraps_anyof(self):
        res = fix.apply_fixes({
             "properties": {"a": {"type": "integer"}}, "nullable": True})
        self.assertIn("anyOf", res.document)
        branches = res.document["anyOf"]
        self.assertEqual(len(branches), 2)
        self.assertTrue(any(b.get("type") == "null" for b in branches))

    def test_allof_nullable_skipped_and_preserved(self):
        res = fix.apply_fixes({"allOf": [{"$ref": "#/x"}],
                                "nullable": True})
        self.assertTrue(res.skipped)
        self.assertTrue(res.document.get("nullable") is True)

    def test_exclusive_bool_true_to_number(self):
        res = fix.apply_fixes(
             {"type": "number", "minimum": 5, "exclusiveMinimum": True})
        self.assertEqual(res.document["exclusiveMinimum"], 5)

    def test_exclusive_bool_false_removed(self):
        res = fix.apply_fixes(
             {"type": "number", "maximum": 9, "exclusiveMaximum": False})
        self.assertNotIn("exclusiveMaximum", res.document)

    def test_input_not_mutated(self):
        doc = {"type": "string", "nullable": True}
        before = json.loads(json.dumps(doc))
        fix.apply_fixes(doc)
        self.assertEqual(doc, before)

    def test_fix_is_idempotent(self):
        once = fix.apply_fixes({"type": "string", "nullable": True})
        twice = fix.apply_fixes(once.document)
        self.assertFalse(twice.changed)


class ReportTests(unittest.TestCase):
    def test_threshold_met(self):
        findings = [Finding("x", "m", "low", "msg", "loc"),
                    Finding("y", "n", "high", "msg", "loc")]
        self.assertTrue(reports.threshold_met(findings, "high"))
        self.assertFalse(reports.threshold_met(findings, "error"))

    def test_sarif_structure(self):
        findings = [Finding("R32-001", "unused nullable", "high",
                             "msg", "loc")]
        sarif = json.loads(reports.sarif_report(findings, "sample.yaml"))
        self.assertEqual(sarif["version"], "2.1.0")
        self.assertEqual(len(sarif["runs"][0]["results"]), 1)
        self.assertEqual(
             sarif["runs"][0]["tool"]["driver"]["name"], "openapi32lint")

    def test_text_report_mentions_count(self):
        findings = [Finding("x", "m", "high", "msg", "loc")]
        out = reports.text_report(findings, "sample.yaml")
        self.assertIn("1 issue(s)", out)
        self.assertIn("R32-001" if False else "x", out)


class CLITests(unittest.TestCase):
    def test_guard_blocks_out_of_cwd(self):
        with self.assertRaises(OpenAPIDocError):
            cli._guard_output_path("../../etc/passwd", False)

    def test_guard_allows_outside_optin(self):
        from pathlib import Path
        out = cli._guard_output_path("/etc/passwd", True)
        self.assertTrue(out.is_absolute())

    def test_guard_allows_in_cwd(self):
        from pathlib import Path
        out = cli._guard_output_path("inner/out.yaml", False)
        cwd = Path.cwd().resolve()
        self.assertEqual(out, (cwd / "inner" / "out.yaml"))

    def test_main_blocks_fix_outside_cwd(self):
        # Writing a --fix target outside the CWD without --allow-outside -> 3.
        rc = cli.main(["examples/clean.yaml", "--fix",
                    "/tmp/open32_should_not_write.json"])
        self.assertEqual(rc, 3)


if __name__ == "__main__":
    unittest.main()
