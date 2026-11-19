"""Pure JSON bridge contract, using the real exact mathematical runtime."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from support import ensure_runtime, large_integer_schema

ensure_runtime()

from template_dataset import solve as atomic_solve
from composite_dataset import build_schema, instantiate, solve
from composite_dataset import profiles
from template_dataset.registry import registry
from math_demo.api import dispatch_json

PROBLEM_ID = "prealgebra/test/11"
MAX_SEED = "18446744073709551615"
BUILD = "/api/composite/build"
INSTANCE = "/api/composite/instantiate"
PRESENTATION = "/api/composite/presentation"
VARIANT = "/api/composite/variant"
STRUCTURE = {"depth": 2, "width": 2, "seed": MAX_SEED,
             "split": "train", "allow_template_reuse": False}


def request(method, path, query="", fields=None):
    status, raw = dispatch_json(method, path, query, None if fields is None else json.dumps(fields))
    assert type(status) is int
    assert type(raw) is str
    return status, json.loads(raw)


class AtomicApiTests(unittest.TestCase):
    def get(self, action, **query):
        return request("GET", "/api/" + action, urlencode(query))

    def test_catalogue_matches_registry(self):
        status, payload = self.get("catalogue")
        self.assertEqual(status, 200)
        self.assertEqual(sorted(p["id"] for p in payload["problems"]), sorted(registry()))
        self.assertIn({"id": PROBLEM_ID, "split": "test", "subject": "prealgebra"}, payload["problems"])

    def test_full_width_seed_preserves_exact_generated_instance(self):
        status, variant = self.get("generate", id=PROBLEM_ID, seed=MAX_SEED)
        self.assertEqual(status, 200)
        self.assertEqual(variant["seed"], MAX_SEED)
        self.assertEqual(variant["parameters"], {"n1": 17, "n2": 10, "n3": 8, "n4": 15})
        self.assertEqual(variant["answer"], "3/4")
        self.assertEqual(variant["answer"], atomic_solve(PROBLEM_ID, variant["parameters"]))
        self.assertEqual(self.get("generate", id=PROBLEM_ID, seed=MAX_SEED), (status, variant))
        status, description = self.get("describe", id=PROBLEM_ID)
        self.assertEqual(status, 200)
        self.assertEqual(set(variant["parameters"]), set(description["parameters"]))

    def test_template_starts_bare_and_generation_fills_named_slots(self):
        status, bare = self.get("template", id=PROBLEM_ID)
        self.assertEqual(status, 200)
        self.assertEqual(bare["presentation"]["mode"], "template")
        self.assertTrue(all(i["text"] is None for i in bare["presentation"]["inputs"]))
        status, filled = self.get("generate", id=PROBLEM_ID, seed=MAX_SEED)
        self.assertEqual(status, 200)
        self.assertEqual(filled["presentation"]["mode"], "instance")
        self.assertEqual("".join(p["text"] for p in filled["presentation"]["segments"]), filled["problem"])
        self.assertEqual(self.get("template", id=PROBLEM_ID)[1], bare)

    def test_random_seed_is_replayable(self):
        with patch("math_demo.api.randbits", return_value=int(MAX_SEED)):
            status, variant = self.get("generate", id=PROBLEM_ID)
        self.assertEqual(status, 200)
        self.assertEqual(variant["seed"], MAX_SEED)
        self.assertIsInstance(variant["seed"], str)
        self.assertTrue(0 <= int(variant["seed"]) <= int(MAX_SEED))
        self.assertEqual(self.get("generate", id=PROBLEM_ID, seed=variant["seed"]), (status, variant))

    def test_parameter_display_preserves_integers_above_javascript_safe_range(self):
        status, variant = self.get("generate", id="algebra/train/1316", seed="0")
        self.assertEqual(status, 200)
        value = variant["parameters"]["squared_number"]
        self.assertGreater(value, 2**53)
        self.assertEqual(variant["parameter_display"]["squared_number"], str(value))

    def test_malformed_ids_seeds_and_queries_are_rejected(self):
        for problem_id in ("", "../data/train/problems.jsonl", "<script>alert(1)</script>"):
            with self.subTest(problem_id=problem_id):
                self.assertEqual(self.get("generate", id=problem_id)[0], 400)
        for seed in ("", "-1", "+42", "1.5", "２", "18446744073709551616", "9" * 500):
            with self.subTest(seed=seed):
                self.assertEqual(self.get("generate", id=PROBLEM_ID, seed=seed)[0], 400)
        self.assertEqual(self.get("describe", id="prealgebra/test/999999")[0], 404)
        for query in ("id=" + PROBLEM_ID + "&seed=0&seed=1", "id", "id=%ff", "extra=0"):
            with self.subTest(query=query):
                self.assertEqual(request("GET", "/api/generate", query)[0], 400)

    def test_unknown_routes_and_methods_cannot_expose_local_files(self):
        for method, path in (("GET", "/data/train/problems.jsonl"), ("GET", "/__main__.py"),
                             ("POST", "/api/generate"), ("PUT", BUILD)):
            self.assertEqual(request(method, path)[0], 404)
        self.assertEqual(request("GET", "/api/catalogue", fields={})[0], 400)

    def test_internal_failure_has_a_fixed_message(self):
        for error in (ValueError, RuntimeError, IndexError, ZeroDivisionError):
            with self.subTest(error=error.__name__):
                with patch("math_demo.api.generate", side_effect=error("private diagnostic")):
                    status, payload = self.get("generate", id=PROBLEM_ID, seed="0")
                self.assertEqual(status, 500)
                self.assertNotIn("private diagnostic", payload["error"])


class CataloguePackagingTests(unittest.TestCase):
    def test_loads_the_packaged_catalogue_without_rebuilding(self):
        profiles._default_catalogue.cache_clear()
        self.addCleanup(profiles._default_catalogue.cache_clear)
        with patch.object(profiles, '_build_catalogue', side_effect=AssertionError('packaged catalogue rejected')):
            self.assertTrue(profiles.get_catalogue())


class CompositeApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = build_schema(2, 2, int(MAX_SEED))

    def post(self, path, fields):
        return request("POST", path, fields=fields)

    def test_build_and_instantiate_keep_structure_and_parameter_seeds_separate(self):
        status, schema = self.post(BUILD, STRUCTURE)
        self.assertEqual((status, schema), (200, self.schema))
        self.assertEqual(schema["seed"], MAX_SEED)
        for seed in ("7", MAX_SEED):
            status, instance = self.post(INSTANCE, {"schema": schema, "seed": seed})
            self.assertEqual(status, 200)
            self.assertEqual(instance, instantiate(schema, int(seed)))
            self.assertEqual(instance["parameter_seed"], seed)
            self.assertEqual(instance["answer"], solve(schema, instance["bottom_parameters"])["answer"])
            for row in instance["trace"]:
                self.assertEqual(json.loads(row["parameters_text"]), row["parameters"])

    def test_variant_matches_primitive_operations_and_instantiates_only_once(self):
        body = {"schema": self.schema, "seed": MAX_SEED}
        with patch("math_demo.api.instantiate", wraps=instantiate) as computation:
            with patch("math_demo.presentation.instantiate", side_effect=AssertionError("second instantiation")):
                status, result = self.post(VARIANT, body)
        self.assertEqual(status, 200)
        self.assertEqual(computation.call_count, 1)
        self.assertEqual(result["instance"], self.post(INSTANCE, body)[1])
        self.assertEqual(result["presentation"], self.post(PRESENTATION, body)[1])
        self.assertEqual(result["presentation"]["mode"], "instance")

    def test_build_rejects_invalid_fields(self):
        for changes in ({"seed": 1}, {"seed": "18446744073709551616"}, {"seed": "２"},
                        {"depth": 0}, {"depth": True}, {"width": "2"}, {"width": 0},
                        {"split": []}, {"split": "all"}, {"allow_template_reuse": 1}, {"extra": 0}):
            with self.subTest(changes=changes):
                self.assertEqual(self.post(BUILD, dict(STRUCTURE, **changes))[0], 400)
        self.assertEqual(self.post(BUILD, {k: v for k, v in STRUCTURE.items() if k != "seed"})[0], 400)
        self.assertEqual(request("POST", BUILD, "seed=1", STRUCTURE)[0], 400)

    def test_instance_routes_reject_invalid_schema_and_seed(self):
        for route in (INSTANCE, PRESENTATION, VARIANT):
            for fields in ({}, {"schema": [], "seed": "1"}, {"schema": {}, "seed": 1},
                           {"schema": {}, "seed": "1"}, {"schema": {}, "seed": "1", "extra": 0}):
                with self.subTest(route=route, fields=fields):
                    self.assertEqual(self.post(route, fields)[0], 400)
        self.assertEqual(self.post(PRESENTATION, {"schema": self.schema, "seed": None})[1]["mode"], "template")
        self.assertEqual(self.post(VARIANT, {"schema": self.schema, "seed": None})[0], 400)
        bad = deepcopy(self.schema)
        bad["nodes"][0]["arity"] = 1.0
        self.assertEqual(self.post(INSTANCE, {"schema": bad, "seed": "0"})[0], 400)
        bad = deepcopy(self.schema)
        bad["problem_template"] = "tampered but same schema id"
        self.assertEqual(self.post(VARIANT, {"schema": bad, "seed": "0"})[0], 400)

    def test_body_is_bounded_strict_json(self):
        payloads = (None, "", "[]", "{", '{"seed":"0","seed":"1"}',
                    '{"seed":NaN}', '{"seed":Infinity}', '{"seed":1e9999}',
                    b"\xff", '[' * 129 + '0' + ']' * 129,
                    " " * (9 * 1024 * 1024 + 1))
        for payload in payloads:
            with self.subTest(payload=repr(payload)[:80]):
                status, raw = dispatch_json("POST", BUILD, body=payload)
                self.assertEqual(status, 400)
                self.assertIn("error", json.loads(raw))
        body = json.dumps(STRUCTURE)
        body += " " * (9 * 1024 * 1024 - len(body.encode()))
        self.assertEqual(dispatch_json("POST", BUILD, body=body)[0], 200)

    def test_schema_size_limit_is_independent_of_request_limit(self):
        schema = deepcopy(self.schema)
        schema["problem_template"] = "x" * (8 * 1024 * 1024)
        body = json.dumps({"schema": schema, "seed": "0"})
        self.assertLess(len(body.encode()), 9 * 1024 * 1024)
        status, raw = dispatch_json("POST", VARIANT, body=body)
        self.assertEqual(status, 400)
        self.assertIn("size limit", json.loads(raw)["error"])

    def test_raw_json_schema_preserves_integers_larger_than_javascript_safe_range(self):
        expected = large_integer_schema(self.schema)
        raw_schema = json.dumps(expected, ensure_ascii=False, separators=(",", ":"))
        divisor = expected["nodes"][0]["profile"]["classifier"]["divisor"]
        self.assertGreater(divisor, 2**53)
        token = '"divisor":' + str(divisor)
        self.assertIn(token, raw_schema)
        rounded = raw_schema.replace(token, '"divisor":' + str(float(divisor)))
        body = '{"schema":' + raw_schema + ',"seed":"7"}'
        status, raw_instance = dispatch_json("POST", VARIANT, body=body)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw_instance)["instance"], instantiate(expected, 7))
        self.assertEqual(dispatch_json("POST", VARIANT, body=body.replace(raw_schema, rounded))[0], 400)


if __name__ == "__main__":
    unittest.main()
