import sys
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from forge_domain_randomization.ui_models import (
    UIFactorSelection,
    UIPrimRandomization,
    UIRunSettings,
    UITargetSelection,
    build_request_payload,
    format_current_values,
    prim_config_from_metadata,
    summarize_result,
    summarize_targets,
)


class TestUIModels(unittest.TestCase):
    def test_build_request_payload_with_default_factors(self):
        payload = build_request_payload(
            UIRunSettings(
                base_scene_usd="/tmp/base.usd",
                output_dir="/tmp/out",
                request_id="req",
                variant_id="var",
                seed=5,
                variants=2,
                writer="pxr",
                scene_manifest="/tmp/scene_manifest.json",
            ),
            UITargetSelection(
                objects=["/World/Cup"],
                lights=["/World/KeyLight"],
                cameras=["/World/Camera"],
            ),
            UIFactorSelection(),
        )

        self.assertEqual(payload["seed"], 5)
        self.assertEqual(payload["variants"], 2)
        self.assertEqual(payload["layer_policy"]["writer"], "pxr")
        self.assertEqual(payload["scene_manifest"], "/tmp/scene_manifest.json")
        self.assertEqual(payload["objects"][0]["prim_path"], "/World/Cup")
        self.assertIn("material", payload["objects"][0])
        self.assertIn("pose", payload["objects"][0])
        self.assertEqual(payload["lights"][0]["prim_path"], "/World/KeyLight")
        self.assertEqual(payload["cameras"][0]["prim_path"], "/World/Camera")

    def test_build_request_payload_respects_factor_toggles(self):
        payload = build_request_payload(
            UIRunSettings(
                base_scene_usd="/tmp/base.usd",
                output_dir="/tmp/out",
                request_id="req",
                variant_id="var",
            ),
            UITargetSelection(
                objects=["/World/Cup"],
                lights=["/World/KeyLight"],
                cameras=["/World/Camera"],
            ),
            UIFactorSelection(object_material=False, object_pose=False, light=False, camera=True),
        )

        self.assertEqual(payload["objects"], [])
        self.assertEqual(payload["lights"], [])
        self.assertEqual(len(payload["cameras"]), 1)
        self.assertNotIn("variants", payload)

    def test_build_request_payload_uses_prim_level_selection(self):
        payload = build_request_payload(
            UIRunSettings(
                base_scene_usd="/tmp/base.usd",
                output_dir="/tmp/out",
                request_id="req",
                variant_id="var",
            ),
            UITargetSelection(
                objects=["/World/Cup", "/World/Plate"],
                lights=["/World/KeyLight"],
                cameras=["/World/Camera"],
                prims=[
                    UIPrimRandomization(
                        prim_path="/World/Cup",
                        prim_kind="object",
                        enabled=True,
                        material=True,
                        pose=False,
                    ),
                    UIPrimRandomization(
                        prim_path="/World/Plate",
                        prim_kind="object",
                        enabled=False,
                        material=True,
                        pose=True,
                    ),
                    UIPrimRandomization(
                        prim_path="/World/KeyLight",
                        prim_kind="light",
                        enabled=True,
                        light=True,
                    ),
                    UIPrimRandomization(
                        prim_path="/World/Camera",
                        prim_kind="camera",
                        enabled=True,
                        camera_pose=False,
                        camera_fov=True,
                    ),
                ],
            ),
            UIFactorSelection(object_material=False, object_pose=False, light=False, camera=False),
        )

        self.assertEqual(len(payload["objects"]), 1)
        self.assertEqual(payload["objects"][0]["prim_path"], "/World/Cup")
        self.assertIn("material", payload["objects"][0])
        self.assertNotIn("pose", payload["objects"][0])
        self.assertEqual(payload["lights"][0]["prim_path"], "/World/KeyLight")
        self.assertEqual(payload["cameras"][0]["prim_path"], "/World/Camera")
        self.assertEqual(payload["cameras"][0]["fov_deg"], [45.0, 65.0])
        self.assertNotIn("pose_jitter_m", payload["cameras"][0])

    def test_build_request_payload_uses_prim_level_custom_ranges(self):
        payload = build_request_payload(
            UIRunSettings(
                base_scene_usd="/tmp/base.usd",
                output_dir="/tmp/out",
                request_id="req",
                variant_id="var",
            ),
            UITargetSelection(
                prims=[
                    UIPrimRandomization(
                        prim_path="/World/Cup",
                        prim_kind="object",
                        enabled=True,
                        material=True,
                        pose=True,
                        visibility=True,
                        asset=True,
                        visibility_mode="hidden",
                        copy_count=2,
                        copy_radius_min_m=0.2,
                        copy_radius_max_m=0.8,
                        copy_max_attempts=7,
                        copy_collision_check=False,
                        copy_suffix="_ui_copy",
                        material_color_jitter=0.12,
                        roughness_min=0.2,
                        roughness_max=0.6,
                        translation_min_m=-0.04,
                        translation_max_m=0.01,
                        rotation_min_deg=-30.0,
                        rotation_max_deg=10.0,
                    ),
                    UIPrimRandomization(
                        prim_path="/World/KeyLight",
                        prim_kind="light",
                        enabled=True,
                        light=True,
                        intensity_min=0.5,
                        intensity_max=1.5,
                        color_temperature_min=2500.0,
                        color_temperature_max=7000.0,
                    ),
                    UIPrimRandomization(
                        prim_path="/World/Camera",
                        prim_kind="camera",
                        enabled=True,
                        camera_pose=True,
                        camera_fov=True,
                        camera_pose_min_m=-0.1,
                        camera_pose_max_m=0.1,
                        camera_yaw_pitch_min_deg=-2.0,
                        camera_yaw_pitch_max_deg=8.0,
                        camera_fov_min_deg=50.0,
                        camera_fov_max_deg=80.0,
                    ),
                ],
            ),
            UIFactorSelection(),
        )

        obj = payload["objects"][0]
        self.assertEqual(obj["material"]["color_jitter"], 0.12)
        self.assertEqual(obj["material"]["roughness"], [0.2, 0.6])
        self.assertEqual(obj["pose"]["translation_jitter_m"]["x"], [-0.04, 0.01])
        self.assertEqual(obj["pose"]["translation_jitter_m"]["y"], [-0.04, 0.01])
        self.assertEqual(obj["pose"]["translation_jitter_m"]["z"], [-0.04, 0.01])
        self.assertEqual(obj["pose"]["rotation_jitter_deg"]["z"], [-30.0, 10.0])
        self.assertEqual(obj["pose"]["scale_jitter"]["x"], [1.0, 1.0])
        self.assertEqual(obj["visibility"]["mode"], "hidden")
        self.assertFalse(obj["visibility"]["visible"])
        self.assertEqual(obj["asset"]["copy_count"]["count"], 2)
        self.assertEqual(obj["asset"]["copy_count"]["suffix"], "_ui_copy")
        self.assertEqual(obj["asset"]["copy_placement"]["radius_m"], [0.2, 0.8])
        self.assertEqual(obj["asset"]["copy_placement"]["max_attempts"], 7)
        self.assertFalse(obj["asset"]["copy_placement"]["collision_check"])
        self.assertEqual(payload["lights"][0]["intensity_scale"], [0.5, 1.5])
        self.assertEqual(payload["lights"][0]["color_temperature"], [2500.0, 7000.0])
        self.assertEqual(payload["cameras"][0]["pose_jitter_m"], [-0.1, 0.1])
        self.assertEqual(payload["cameras"][0]["yaw_pitch_jitter_deg"], [-2.0, 8.0])
        self.assertEqual(payload["cameras"][0]["fov_deg"], [50.0, 80.0])

    def test_summaries_are_human_readable(self):
        target_summary = summarize_targets(UITargetSelection(objects=["/World/A"], lights=[], cameras=[]))
        self.assertIn("Objects: 1", target_summary)
        target_summary = summarize_targets(UITargetSelection(
            prims=[
                UIPrimRandomization("/World/A", "object", enabled=True),
                UIPrimRandomization("/World/B", "object", enabled=False),
            ]
        ))
        self.assertIn("Enabled prims: 1", target_summary)
        result_summary = summarize_result({"success": True, "variant_id": "var", "result_path": "/tmp/report.json"})
        self.assertIn("Success: True", result_summary)
        self.assertIn("/tmp/report.json", result_summary)

    def test_prim_config_disables_unavailable_object_domains(self):
        prim = prim_config_from_metadata(
            "/World/Cube",
            "object",
            UIFactorSelection(),
            {
                "prim_path": "/World/Cube",
                "material_bindings": [],
                "world_transform": {"translation": [1.0, 2.0, 3.0]},
                "physics": {"has_rigid_body": False, "mass": None},
            },
        )

        self.assertFalse(prim.available_material)
        self.assertFalse(prim.material)
        self.assertTrue(prim.available_pose)
        self.assertTrue(prim.pose)
        self.assertFalse(prim.available_physics)
        self.assertIn("translation", prim.current_values)

    def test_request_payload_omits_unavailable_domains(self):
        payload = build_request_payload(
            UIRunSettings(
                base_scene_usd="/tmp/base.usd",
                output_dir="/tmp/out",
                request_id="req",
                variant_id="var",
            ),
            UITargetSelection(
                objects=["/World/Cube"],
                metadata={
                    "/World/Cube": {
                        "material_bindings": [],
                        "world_transform": {"translation": [1.0, 2.0, 3.0]},
                    }
                },
                prims=[
                    UIPrimRandomization(
                        "/World/Cube",
                        "object",
                        enabled=True,
                        material=True,
                        pose=True,
                        available_material=False,
                        available_pose=True,
                    )
                ],
            ),
            UIFactorSelection(),
        )

        self.assertEqual(len(payload["objects"]), 1)
        self.assertNotIn("material", payload["objects"][0])
        self.assertIn("pose", payload["objects"][0])

    def test_prim_config_uses_current_material_and_camera_values(self):
        obj = prim_config_from_metadata(
            "/World/Cup",
            "object",
            UIFactorSelection(),
            {
                "material_bindings": [{
                    "material_path": "/World/Looks/Cup/Shader",
                    "base_color": [0.1, 0.2, 0.3],
                    "roughness": 0.42,
                }],
                "world_transform": {"translation": [0.0, 0.0, 0.0]},
                "physics": {"has_rigid_body": True, "mass": 1.5},
            },
        )
        cam = prim_config_from_metadata(
            "/World/Camera",
            "camera",
            UIFactorSelection(),
            {
                "world_transform": {"translation": [1.0, 2.0, 3.0]},
                "focal_length": 18.0,
                "horizontal_aperture": 20.955,
            },
        )

        self.assertTrue(obj.available_material)
        self.assertEqual(obj.roughness_min, 0.42)
        self.assertEqual(obj.roughness_max, 0.42)
        self.assertEqual(obj.current_values["base_color"], [0.1, 0.2, 0.3])
        self.assertTrue(cam.available_camera_fov)
        self.assertGreater(cam.camera_fov_min_deg, 0.0)
        self.assertIn("fov_deg", format_current_values(cam.current_values))


if __name__ == "__main__":
    unittest.main()
