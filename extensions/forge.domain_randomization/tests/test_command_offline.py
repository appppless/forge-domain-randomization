"""Offline command tests using injected scan (no Isaac runtime)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from forge_domain_randomization.commands import run_domain_randomization


SCAN_FIXTURE = {
    "base_scene_usd": "/tmp/test.usd",
    "base_scene_hash": "sha256:base",
    "prims": [
        {
            "prim_path": "/World/red_mug",
            "type_name": "Xform",
            "world_transform": {"translation": [0.0, 0.0, 0.5]},
            "physics": {"has_rigid_body": True, "has_collision": True, "mass": 0.25},
            "material_bindings": [
                {"material_path": "/World/Looks/red_mug_mat", "base_color": [0.8, 0.1, 0.1], "roughness": 0.5}
            ],
        },
        {"prim_path": "/World/a", "type_name": "Xform"},
        {"prim_path": "/World/b", "type_name": "Xform"},
        {"prim_path": "/World/c", "type_name": "Xform"},
    ],
    "lights": [
        {"prim_path": "/World/DomeLight", "type_name": "DomeLight", "intensity": 1000.0, "color": [1.0, 1.0, 1.0]}
    ],
    "cameras": [
        {
            "prim_path": "/World/Camera",
            "type_name": "Camera",
            "world_transform": {"translation": [1.0, 1.0, 1.0]},
            "horizontal_aperture": 20.955,
            "focal_length": 18.0,
        }
    ],
}


class TestCommandOffline(unittest.TestCase):
    def test_single_variant(self):
        with tempfile.TemporaryDirectory() as out:
            payload = {
                "request_id": "req_001",
                "variant_id": "var_001",
                "base_scene_usd": "/tmp/test.usd",
                "output_dir": out,
                "seed": 1,
                "layer_policy": {"mode": "single", "writer": "text"},
                "objects": [
                    {"prim_path": "/World/red_mug", "material": {"color_jitter": 0.05, "roughness": [0.3, 0.7]}}
                ],
                "lights": [
                    {"prim_path": "/World/DomeLight", "intensity_scale": [0.7, 1.3]}
                ],
                "cameras": [
                    {"prim_path": "/World/Camera", "fov_deg": [55, 75]}
                ],
                "_injected_scan": SCAN_FIXTURE,
            }
            result = run_domain_randomization(payload)
            self.assertTrue(result["success"])
            self.assertEqual(result["variant_id"], "var_001")

            out_path = Path(out)
            self.assertTrue((out_path / "domain_scan.json").exists())
            self.assertTrue((out_path / "achieved_domain_report.json").exists())
            self.assertTrue((out_path / "layer_stack.json").exists())

            report = json.loads((out_path / "achieved_domain_report.json").read_text())
            self.assertGreater(len(report["achieved_parameters"]), 0)
            # No role/asset_level/placement_level prefix should leak through.
            for key in report["achieved_parameters"]:
                self.assertFalse(key.startswith("asset_level."))
                self.assertFalse(key.startswith("placement_level."))
                self.assertFalse(key.startswith("simulator_level."))

    def test_batch_variants(self):
        with tempfile.TemporaryDirectory() as out:
            payload = {
                "request_id": "req_001",
                "variant_id": "var",
                "base_scene_usd": "/tmp/test.usd",
                "output_dir": out,
                "seed": 1,
                "variants": 3,
                "layer_policy": {"mode": "single", "writer": "text"},
                "objects": [
                    {"prim_path": "/World/red_mug", "material": {"color_jitter": 0.05}}
                ],
                "_injected_scan": SCAN_FIXTURE,
            }
            result = run_domain_randomization(payload)
            self.assertTrue(result["success"])
            self.assertEqual(len(result["variants"]), 3)
            for i, sub in enumerate(result["variants"]):
                seed = 1 + i
                expected_dir = Path(out) / f"variant_{seed:04d}"
                self.assertTrue(expected_dir.exists())
                self.assertTrue((expected_dir / "achieved_domain_report.json").exists())

    def test_visibility_pool(self):
        with tempfile.TemporaryDirectory() as out:
            payload = {
                "request_id": "req_001",
                "variant_id": "var_001",
                "base_scene_usd": "/tmp/test.usd",
                "output_dir": out,
                "seed": 1,
                "layer_policy": {"mode": "single", "writer": "text"},
                "visibility_pools": [
                    {"id": "distractors", "prims": ["/World/a", "/World/b", "/World/c"], "keep_visible": 1}
                ],
                "_injected_scan": SCAN_FIXTURE,
            }
            result = run_domain_randomization(payload)
            self.assertTrue(result["success"])
            report = json.loads((Path(out) / "achieved_domain_report.json").read_text())
            pool_keys = [k for k in report["achieved_parameters"] if k.startswith("visibility_pool.distractors")]
            self.assertEqual(len(pool_keys), 3)
            visible_count = sum(1 for k in pool_keys if report["achieved_parameters"][k])
            self.assertEqual(visible_count, 1)

    def test_layer_files_written(self):
        with tempfile.TemporaryDirectory() as out:
            payload = {
                "request_id": "req_001",
                "variant_id": "var_001",
                "base_scene_usd": "/tmp/test.usd",
                "output_dir": out,
                "seed": 1,
                "layer_policy": {"mode": "single", "writer": "text"},
                "objects": [
                    {"prim_path": "/World/red_mug", "material": {"color_jitter": 0.05}}
                ],
                "_injected_scan": SCAN_FIXTURE,
            }
            run_domain_randomization(payload)
            layer_files = list((Path(out) / "randomization_layers").glob("*.usda"))
            self.assertGreater(len(layer_files), 0)
            content = layer_files[0].read_text()
            self.assertIn("#usda", content)
            self.assertIn("over", content)
