"""Validation tests for domain-randomization release gates."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from forge_domain_randomization.commands import run_domain_randomization
from forge_domain_randomization.sampler import sample_randomization
from forge_domain_randomization.schemas import DomainRandomizationRequest
from forge_domain_randomization.validator import controllability_score, validate_randomization


SCAN_FIXTURE = {
    "base_scene_usd": "/tmp/test.usd",
    "base_scene_hash": "sha256:base",
    "prims": [
        {
            "prim_path": "/World/Cube",
            "type_name": "Mesh",
            "world_transform": {"translation": [0.0, 0.0, 0.5]},
            "material_bindings": [],
        },
        {
            "prim_path": "/World/Target",
            "type_name": "Xform",
            "world_transform": {"translation": [1.0, 0.0, 0.5]},
            "material_bindings": [
                {"material_path": "/World/Looks/Target", "base_color": [0.8, 0.1, 0.1]}
            ],
        },
    ],
    "lights": [],
    "cameras": [],
}


def _request(**overrides):
    base = {
        "request_id": "req_validation",
        "variant_id": "var_validation",
        "base_scene_usd": "/tmp/test.usd",
        "output_dir": "/tmp/out",
        "seed": 1,
        "base_scene_hash": "sha256:base",
        "config_hash": "sha256:config",
        "objects": [],
        "lights": [],
        "cameras": [],
        "visibility_pools": [],
    }
    base.update(overrides)
    return DomainRandomizationRequest.from_dict(base)


class TestValidator(unittest.TestCase):
    def test_missing_requested_prim_is_blocking_by_default(self):
        req = _request(objects=[
            {"prim_path": "/World/Missing", "material": {"color_jitter": 0.05}}
        ])
        plan = sample_randomization(req, SCAN_FIXTURE)
        validation = validate_randomization(req, SCAN_FIXTURE, plan)

        self.assertFalse(validation["success"])
        self.assertTrue(any(
            issue["type"] == "prim_not_on_stage"
            and issue["prim_path"] == "/World/Missing"
            and issue["blocking"]
            for issue in validation["issues"]
        ))

    def test_permissive_policy_keeps_missing_prim_non_blocking(self):
        req = _request(
            validation_policy={"mode": "permissive"},
            objects=[{"prim_path": "/World/Missing", "material": {"color_jitter": 0.05}}],
        )
        plan = sample_randomization(req, SCAN_FIXTURE)
        validation = validate_randomization(req, SCAN_FIXTURE, plan)

        self.assertTrue(validation["success"])
        self.assertTrue(any(
            issue["type"] == "prim_not_on_stage"
            and issue["prim_path"] == "/World/Missing"
            and not issue["blocking"]
            for issue in validation["issues"]
        ))

    def test_unsupported_requested_domain_is_blocking(self):
        req = _request(objects=[
            {"prim_path": "/World/Cube", "material": {"color_jitter": 0.05}}
        ])
        plan = sample_randomization(req, SCAN_FIXTURE)
        validation = validate_randomization(req, SCAN_FIXTURE, plan)

        self.assertFalse(validation["success"])
        self.assertTrue(any(
            issue["type"] == "unsupported_domain"
            and issue["domain"] == "material"
            and issue["prim_path"] == "/World/Cube"
            and issue["blocking"]
            for issue in validation["issues"]
        ))
        self.assertTrue(any(
            issue["type"] == "requested_domain_unachieved"
            and issue["domain"] == "material"
            and issue["blocking"]
            for issue in validation["issues"]
        ))

    def test_visibility_pool_missing_prims_are_blocking(self):
        req = _request(visibility_pools=[
            {"id": "distractors", "prims": ["/World/Target", "/World/Ghost"], "keep_visible": 1}
        ])
        plan = sample_randomization(req, SCAN_FIXTURE)
        validation = validate_randomization(req, SCAN_FIXTURE, plan)

        self.assertFalse(validation["success"])
        self.assertTrue(any(
            issue["type"] == "visibility_pool_missing_prims"
            and issue["missing_prims"] == ["/World/Ghost"]
            and issue["blocking"]
            for issue in validation["issues"]
        ))

    def test_empty_request_is_valid_noop(self):
        req = _request()
        plan = sample_randomization(req, SCAN_FIXTURE)
        validation = validate_randomization(req, SCAN_FIXTURE, plan)

        self.assertTrue(validation["success"])
        self.assertEqual(validation["coverage"]["enabled_domains"], 0)
        self.assertEqual(controllability_score(req, plan), 1.0)

    def test_command_success_follows_blocking_validation(self):
        with tempfile.TemporaryDirectory() as out:
            payload = {
                "request_id": "req_validation",
                "variant_id": "var_validation",
                "base_scene_usd": "/tmp/test.usd",
                "output_dir": out,
                "seed": 1,
                "layer_policy": {"mode": "single", "writer": "text"},
                "objects": [
                    {"prim_path": "/World/Missing", "material": {"color_jitter": 0.05}}
                ],
                "_injected_scan": SCAN_FIXTURE,
            }

            result = run_domain_randomization(payload)
            report = json.loads((Path(out) / "achieved_domain_report.json").read_text())

        self.assertFalse(result["success"])
        self.assertFalse(report["validation"]["success"])


if __name__ == "__main__":
    unittest.main()
