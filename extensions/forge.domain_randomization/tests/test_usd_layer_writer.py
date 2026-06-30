"""Tests for the pxr-backed online USD layer writer."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

try:
    from pxr import Usd
except Exception:  # pragma: no cover - exercised only in non-USD environments
    Usd = None

from forge_domain_randomization.commands import run_domain_randomization
from forge_domain_randomization.sampler import LayerEdit, RandomizationPlan
from forge_domain_randomization.schemas import DomainRandomizationRequest
from forge_domain_randomization.usd_layer_writer import write_randomization_layers_pxr


def _request(output_dir: str, *, mode: str = "single") -> DomainRandomizationRequest:
    return DomainRandomizationRequest.from_dict({
        "request_id": "req_pxr",
        "variant_id": "var_pxr",
        "base_scene_usd": "/tmp/base.usd",
        "output_dir": output_dir,
        "seed": 7,
        "layer_policy": {"mode": mode, "writer": "pxr"},
    })


@unittest.skipIf(Usd is None, "pxr.Usd is not available")
class TestPXRLayerWriter(unittest.TestCase):
    def test_scale_only_layer_authors_only_scale_attr(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = _request(tmp)
            plan = RandomizationPlan(edits=[
                LayerEdit(
                    domain="placement",
                    prim_path="/World/mug",
                    attribute="xformOp:scale",
                    value=[1.08, 1.08, 1.08],
                    value_type="double3",
                )
            ])

            paths = write_randomization_layers_pxr(request, plan)
            self.assertEqual(len(paths), 1)
            stage = Usd.Stage.Open(paths[0])
            prim = stage.GetPrimAtPath("/World/mug")
            self.assertTrue(prim.IsValid())
            self.assertTrue(prim.GetAttribute("xformOp:scale").HasAuthoredValue())
            self.assertFalse(prim.GetAttribute("xformOp:translate").HasAuthoredValue())
            self.assertFalse(prim.GetAttribute("xformOp:rotateXYZ").HasAuthoredValue())

            text = Path(paths[0]).read_text()
            self.assertIn("double3 xformOp:scale", text)
            self.assertNotIn("xformOp:translate", text)
            self.assertNotIn("xformOp:rotateXYZ", text)

    def test_current_value_types_round_trip_through_usd(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = _request(tmp)
            matrix = [
                1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                0.1, 0.2, 0.3, 1.0,
            ]
            plan = RandomizationPlan(edits=[
                LayerEdit("placement", "/World/mug", "xformOp:transform", matrix, "matrix4d"),
                LayerEdit("placement", "/World/mug", "xformOp:orient", [0.0, 0.0, 0.70710678, 0.70710678], "quatf"),
                LayerEdit("placement", "/World/mug", "xformOpOrder", ["xformOp:transform"], "token[]"),
                LayerEdit("placement", "/World/mug", "visibility", "invisible", "token"),
                LayerEdit("asset", "/World/Looks/mat", "inputs:diffuseColor", [0.2, 0.3, 0.4], "color3f"),
                LayerEdit("asset", "/World/Looks/mat", "inputs:diffuse_texture", "/textures/wood.png", "asset"),
                LayerEdit("asset", "/World/mug", "references", {
                    "items": [{"asset_path": "/tmp/base.usd", "prim_path": "/World/source_mug"}],
                }, "references"),
                LayerEdit("asset", "/World/payload_mug", "payloads", {
                    "items": [{"asset_path": "/tmp/base.usd", "prim_path": "/World/source_mug"}],
                }, "payloads"),
                LayerEdit("asset", "/World/mug", "material:binding", ["/World/Looks/mat"], "relationship"),
                LayerEdit("simulator", "/World/Light", "inputs:intensity", 500.0, "float"),
                LayerEdit("simulator", "/World/body", "physics:mass", 2.0, "float"),
            ])

            paths = write_randomization_layers_pxr(request, plan)
            stage = Usd.Stage.Open(paths[0])
            self.assertTrue(stage.GetPrimAtPath("/World/mug").GetAttribute("xformOp:transform").HasAuthoredValue())
            orient = stage.GetPrimAtPath("/World/mug").GetAttribute("xformOp:orient").Get()
            self.assertAlmostEqual(orient.GetReal(), 0.70710678)
            self.assertAlmostEqual(orient.GetImaginary()[2], 0.70710678)
            self.assertEqual(
                list(stage.GetPrimAtPath("/World/mug").GetAttribute("xformOpOrder").Get()),
                ["xformOp:transform"],
            )
            self.assertEqual(stage.GetPrimAtPath("/World/mug").GetAttribute("visibility").Get(), "invisible")
            self.assertEqual(
                [str(t) for t in stage.GetPrimAtPath("/World/mug").GetRelationship("material:binding").GetTargets()],
                ["/World/Looks/mat"],
            )
            self.assertEqual(
                stage.GetPrimAtPath("/World/Looks/mat").GetAttribute("inputs:diffuse_texture").Get().path,
                "/textures/wood.png",
            )
            self.assertAlmostEqual(
                stage.GetPrimAtPath("/World/Light").GetAttribute("inputs:intensity").Get(),
                500.0,
            )
            text = Path(paths[0]).read_text()
            self.assertIn("references = @/tmp/base.usd@</World/source_mug>", text)
            self.assertIn("payload = @/tmp/base.usd@</World/source_mug>", text)

    def test_command_uses_pxr_writer_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base.usd"
            base.write_text("#usda 1.0\n", encoding="utf-8")
            payload = {
                "request_id": "req_pxr",
                "variant_id": "var_pxr",
                "base_scene_usd": str(base),
                "output_dir": str(root / "out"),
                "seed": 1,
                "layer_policy": {"mode": "single"},
                "objects": [
                    {"prim_path": "/World/mug", "pose": {"scale_jitter": [1.1, 1.1]}}
                ],
                "_injected_scan": {
                    "base_scene_usd": str(base),
                    "base_scene_hash": "sha256:base",
                    "prims": [{
                        "prim_path": "/World/mug",
                        "type_name": "Xform",
                        "world_transform": {"translation": [0.0, 0.0, 0.0]},
                        "physics": {},
                        "material_bindings": [],
                    }],
                    "lights": [],
                    "cameras": [],
                },
            }
            result = run_domain_randomization(payload)
            self.assertTrue(result["success"])
            report = json.loads(Path(result["result_path"]).read_text())
            self.assertIn("/World/mug.pose.scale_factors", report["achieved_parameters"])
            layer = Path(report["randomization_layers"][0])
            self.assertTrue(layer.exists())
            self.assertIn('string writer = "pxr"', layer.read_text())


if __name__ == "__main__":
    unittest.main()
