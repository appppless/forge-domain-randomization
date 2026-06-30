"""Schema roundtrip tests for v0.2 DomainRandomizationRequest."""

import sys
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from forge_domain_randomization.schemas import (
    CameraSpec,
    DomainRandomizationRequest,
    DomainScanReport,
    LightSpec,
    ObjectSpec,
    VisibilityPool,
)


class TestSchemaRoundtrip(unittest.TestCase):
    def test_object_spec_roundtrip(self):
        d = {
            "prim_path": "/World/mug",
            "asset": {"reference_variants": ["/assets/mug.usd"]},
            "material": {"color_jitter": 0.05},
        }
        obj = ObjectSpec.from_dict(d)
        self.assertEqual(obj.prim_path, "/World/mug")
        self.assertEqual(obj.asset, {"reference_variants": ["/assets/mug.usd"]})
        self.assertEqual(obj.material, {"color_jitter": 0.05})
        self.assertIsNone(obj.pose)
        restored = ObjectSpec.from_dict(obj.to_dict())
        self.assertEqual(restored.prim_path, obj.prim_path)
        self.assertEqual(restored.asset, obj.asset)
        self.assertEqual(restored.material, obj.material)

    def test_light_spec_roundtrip(self):
        d = {"prim_path": "/World/DomeLight", "intensity_scale": [0.7, 1.3]}
        light = LightSpec.from_dict(d)
        self.assertEqual(light.prim_path, "/World/DomeLight")
        self.assertEqual(light.intensity_scale, [0.7, 1.3])
        restored = LightSpec.from_dict(light.to_dict())
        self.assertEqual(restored.intensity_scale, [0.7, 1.3])

    def test_camera_spec_roundtrip(self):
        d = {"prim_path": "/World/Camera", "fov_deg": [55, 75], "pose_jitter_m": [-0.02, 0.02]}
        cam = CameraSpec.from_dict(d)
        self.assertEqual(cam.fov_deg, [55, 75])
        self.assertEqual(cam.pose_jitter_m, [-0.02, 0.02])
        restored = CameraSpec.from_dict(cam.to_dict())
        self.assertEqual(restored.fov_deg, [55, 75])

    def test_camera_yaw_pitch_dict_roundtrip(self):
        d = {
            "prim_path": "/World/Camera",
            "yaw_pitch_jitter_deg": {"yaw": [-10, 10], "pitch": [-5, 5]},
        }
        cam = CameraSpec.from_dict(d)
        restored = CameraSpec.from_dict(cam.to_dict())
        self.assertEqual(restored.yaw_pitch_jitter_deg, d["yaw_pitch_jitter_deg"])

    def test_visibility_pool_roundtrip(self):
        d = {"id": "test_pool", "prims": ["/World/a", "/World/b", "/World/c"], "keep_visible": 2}
        pool = VisibilityPool.from_dict(d)
        self.assertEqual(pool.id, "test_pool")
        self.assertEqual(len(pool.prims), 3)
        self.assertEqual(pool.keep_visible, 2)
        restored = VisibilityPool.from_dict(pool.to_dict())
        self.assertEqual(restored.prims, pool.prims)
        self.assertEqual(restored.keep_visible, pool.keep_visible)

    def test_request_roundtrip(self):
        payload = {
            "request_id": "req_001",
            "variant_id": "var_001",
            "base_scene_usd": "/tmp/test.usd",
            "output_dir": "/tmp/out",
            "seed": 42,
            "objects": [{"prim_path": "/World/mug", "material": {"color_jitter": 0.05}}],
            "lights": [{"prim_path": "/World/DomeLight", "intensity_scale": [0.8, 1.2]}],
            "cameras": [{"prim_path": "/World/Camera", "fov_deg": [60, 70]}],
            "visibility_pools": [{"id": "pool1", "prims": ["/World/a"], "keep_visible": 1}],
        }
        req = DomainRandomizationRequest.from_dict(payload)
        self.assertEqual(len(req.objects), 1)
        self.assertEqual(len(req.lights), 1)
        self.assertEqual(len(req.cameras), 1)
        self.assertEqual(len(req.visibility_pools), 1)
        restored = DomainRandomizationRequest.from_dict(req.to_dict())
        self.assertEqual(restored.objects[0].prim_path, "/World/mug")
        self.assertEqual(restored.lights[0].intensity_scale, [0.8, 1.2])
        self.assertEqual(restored.seed, 42)

    def test_scan_report_roundtrip(self):
        payload = {
            "base_scene_usd": "/tmp/test.usd",
            "base_scene_hash": "sha256:abc",
            "prims": [{"prim_path": "/World/mug", "type_name": "Xform"}],
        }
        report = DomainScanReport.from_dict(payload)
        self.assertEqual(len(report.prims), 1)
        restored = DomainScanReport.from_dict(report.to_dict())
        self.assertEqual(restored.prims[0]["prim_path"], "/World/mug")

    def test_request_requires_required_fields(self):
        with self.assertRaises(ValueError):
            DomainRandomizationRequest.from_dict({"seed": 0})
        with self.assertRaises(ValueError):
            DomainRandomizationRequest.from_dict({"request_id": "", "variant_id": "", "base_scene_usd": "", "output_dir": "", "seed": 0})


class TestPosePayloadRoundtrip(unittest.TestCase):
    """pose is an open dict; T / R / S keys must round-trip verbatim."""

    def test_translation_jitter_roundtrip(self):
        d = {"prim_path": "/World/mug", "pose": {"translation_jitter_m": [-0.05, 0.05]}}
        obj = ObjectSpec.from_dict(d)
        self.assertEqual(obj.pose, {"translation_jitter_m": [-0.05, 0.05]})
        restored = ObjectSpec.from_dict(obj.to_dict())
        self.assertEqual(restored.pose, {"translation_jitter_m": [-0.05, 0.05]})

    def test_rotation_jitter_shorthand_roundtrip(self):
        d = {"prim_path": "/World/mug", "pose": {"rotation_jitter_deg": [-15.0, 15.0]}}
        obj = ObjectSpec.from_dict(d)
        self.assertEqual(obj.pose, {"rotation_jitter_deg": [-15.0, 15.0]})
        restored = ObjectSpec.from_dict(obj.to_dict())
        self.assertEqual(restored.pose, {"rotation_jitter_deg": [-15.0, 15.0]})

    def test_rotation_jitter_dict_roundtrip(self):
        d = {
            "prim_path": "/World/mug",
            "pose": {"rotation_jitter_deg": {"x": [-5, 5], "z": [-90, 90]}},
        }
        obj = ObjectSpec.from_dict(d)
        restored = ObjectSpec.from_dict(obj.to_dict())
        self.assertEqual(
            restored.pose,
            {"rotation_jitter_deg": {"x": [-5, 5], "z": [-90, 90]}},
        )

    def test_scale_jitter_roundtrip(self):
        d = {
            "prim_path": "/World/mug",
            "pose": {"scale_jitter": {"x": [0.9, 1.1], "z": [0.95, 1.05]}},
        }
        obj = ObjectSpec.from_dict(d)
        restored = ObjectSpec.from_dict(obj.to_dict())
        self.assertEqual(
            restored.pose,
            {"scale_jitter": {"x": [0.9, 1.1], "z": [0.95, 1.05]}},
        )

    def test_mixed_trs_payload_roundtrip(self):
        d = {
            "prim_path": "/World/mug",
            "pose": {
                "translation_jitter_m": [-0.02, 0.02],
                "rotation_jitter_deg": [-30.0, 30.0],
                "scale_jitter": [0.95, 1.05],
            },
        }
        obj = ObjectSpec.from_dict(d)
        restored = ObjectSpec.from_dict(obj.to_dict())
        self.assertEqual(restored.pose, d["pose"])


if __name__ == "__main__":
    unittest.main()
