"""Deterministic sampling tests for v0.2 sampler."""

import sys
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from forge_domain_randomization.sampler import sample_randomization
from forge_domain_randomization.schemas import DomainRandomizationRequest
from forge_domain_randomization.validator import validate_randomization


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
                {
                    "material_path": "/World/Looks/red_mug_mat/Shader",
                    "base_color": [0.8, 0.1, 0.1],
                    "base_color_attr": "inputs:diffuse_color_constant",
                    "roughness": 0.5,
                    "roughness_attr": "inputs:reflection_roughness_constant",
                    "diffuse_texture_attr": "inputs:diffuse_texture",
                }
            ],
        },
        {
            "prim_path": "/World/blue_mug",
            "type_name": "Xform",
            "world_transform": {"translation": [0.5, 0.5, 0.5]},
            "physics": {"has_rigid_body": True, "has_collision": True, "mass": 0.3},
            "material_bindings": [
                {"material_path": "/World/Looks/blue_mug_mat", "base_color": [0.1, 0.1, 0.8], "roughness": 0.4}
            ],
        },
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


def _request(**overrides):
    base = {
        "request_id": "req_test",
        "variant_id": "var_test",
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


class TestSamplerV02(unittest.TestCase):
    def test_asset_reference_variant(self):
        req = _request(objects=[
            {"prim_path": "/World/red_mug", "asset": {
                "reference_variants": [
                    {"asset_path": "/assets/red_mug_a.usd", "prim_path": "/Model"},
                    {"asset_path": "/assets/red_mug_b.usd", "prim_path": "/Model"},
                ]
            }}
        ])
        plan = sample_randomization(req, SCAN_FIXTURE)
        reference_edits = [e for e in plan.edits if e.value_type == "references"]
        self.assertEqual(len(reference_edits), 1)
        self.assertEqual(reference_edits[0].prim_path, "/World/red_mug")
        self.assertIn(
            reference_edits[0].value["items"][0]["asset_path"],
            {"/assets/red_mug_a.usd", "/assets/red_mug_b.usd"},
        )
        self.assertIn("/World/red_mug.asset.references", plan.achieved_parameters)

    def test_asset_copy_to_reference(self):
        req = _request(objects=[
            {"prim_path": "/World/red_mug", "asset": {
                "copy_to": {"prim_path": "/World/red_mug_copy", "translation": [1.0, 2.0, 3.0]}
            }}
        ])
        plan = sample_randomization(req, SCAN_FIXTURE)
        reference_edits = [e for e in plan.edits if e.value_type == "references"]
        self.assertEqual(len(reference_edits), 1)
        self.assertEqual(reference_edits[0].prim_path, "/World/red_mug_copy")
        self.assertEqual(reference_edits[0].value["items"][0]["asset_path"], "/tmp/test.usd")
        self.assertEqual(reference_edits[0].value["items"][0]["prim_path"], "/World/red_mug")
        self.assertTrue(any(e.prim_path == "/World/red_mug_copy" and e.attribute == "xformOp:translate" for e in plan.edits))
        self.assertIn("/World/red_mug.asset.copy./World/red_mug_copy", plan.achieved_parameters)

    def test_asset_copy_count_samples_nearby_translation(self):
        req = _request(objects=[
            {"prim_path": "/World/red_mug", "asset": {"copy_count": 1}}
        ])
        plan = sample_randomization(req, SCAN_FIXTURE)
        reference_edits = [e for e in plan.edits if e.value_type == "references"]
        self.assertEqual(len(reference_edits), 1)
        self.assertEqual(reference_edits[0].prim_path, "/World/red_mug_copy")
        self.assertEqual(reference_edits[0].value["items"][0]["asset_path"], "/tmp/test.usd")
        self.assertEqual(reference_edits[0].value["items"][0]["prim_path"], "/World/red_mug")
        placement_edits = [
            e for e in plan.edits
            if e.prim_path == "/World/red_mug_copy" and e.attribute == "xformOp:translate"
        ]
        self.assertEqual(len(placement_edits), 1)
        self.assertNotEqual(placement_edits[0].value, [0.0, 0.0, 0.5])

    def test_asset_copy_count_rejected_by_bbox_collision(self):
        scan = {
            **SCAN_FIXTURE,
            "prims": [
                {
                    **SCAN_FIXTURE["prims"][0],
                    "bounds": {"aabb_min": [-0.1, -0.1, 0.0], "aabb_max": [0.1, 0.1, 1.0]},
                    "world_transform": {"translation": [0.0, 0.0, 0.5]},
                },
            ],
        }
        req = _request(objects=[
            {"prim_path": "/World/red_mug", "asset": {
                "copy_count": 1,
                "copy_placement": {"radius_m": [0.0, 0.0], "max_attempts": 1},
            }}
        ])
        plan = sample_randomization(req, scan)
        self.assertFalse(any(e.prim_path == "/World/red_mug_copy" for e in plan.edits))
        self.assertTrue(any("copy" in s["reason"].lower() and "aabb" in s["reason"].lower() for s in plan.skipped_prims))

    def test_asset_relationship_targets(self):
        req = _request(objects=[
            {"prim_path": "/World/red_mug", "asset": {
                "relationships": {"name": "material:binding", "targets": "/World/Looks/red"}
            }}
        ])
        plan = sample_randomization(req, SCAN_FIXTURE)
        relationship_edits = [e for e in plan.edits if e.value_type == "relationship"]
        self.assertEqual(len(relationship_edits), 1)
        self.assertEqual(relationship_edits[0].attribute, "material:binding")
        self.assertEqual(relationship_edits[0].value, ["/World/Looks/red"])

    def test_material_color_jitter(self):
        req = _request(objects=[
            {"prim_path": "/World/red_mug", "material": {"color_jitter": 0.05, "roughness": [0.3, 0.7]}}
        ])
        plan = sample_randomization(req, SCAN_FIXTURE)
        keys = list(plan.achieved_parameters.keys())
        self.assertTrue(any("red_mug.material" in k and "base_color" in k for k in keys))
        self.assertTrue(any("red_mug.material" in k and "roughness" in k for k in keys))
        self.assertTrue(any(e.attribute == "inputs:diffuse_color_constant" for e in plan.edits))
        self.assertTrue(any(e.attribute == "inputs:reflection_roughness_constant" for e in plan.edits))
        self.assertFalse(any(e.attribute == "inputs:diffuseColor" for e in plan.edits))

    def test_material_request_without_binding_is_reported_as_unsupported(self):
        scan = {
            **SCAN_FIXTURE,
            "prims": [{
                **SCAN_FIXTURE["prims"][0],
                "prim_path": "/World/Cube",
                "type_name": "Mesh",
                "material_bindings": [],
            }],
        }
        req = _request(objects=[
            {"prim_path": "/World/Cube", "material": {"color_jitter": 0.05, "roughness": [0.3, 0.7]}}
        ])
        plan = sample_randomization(req, scan)
        validation = validate_randomization(req, scan, plan)

        self.assertEqual(plan.edits, [])
        self.assertTrue(any(
            issue.get("type") == "unsupported_domain"
            and issue.get("domain") == "material"
            and issue.get("prim_path") == "/World/Cube"
            for issue in validation["issues"]
        ))

    def test_material_texture_variants(self):
        req = _request(objects=[
            {"prim_path": "/World/red_mug", "material": {
                "color_jitter": 0.0,
                "texture_variants": ["/textures/a.png", {"path": "/textures/b.png"}],
            }}
        ])
        plan = sample_randomization(req, SCAN_FIXTURE)
        texture_edits = [e for e in plan.edits if e.attribute == "inputs:diffuse_texture"]
        self.assertEqual(len(texture_edits), 1)
        self.assertEqual(texture_edits[0].value_type, "asset")
        self.assertIn(texture_edits[0].value, {"/textures/a.png", "/textures/b.png"})
        self.assertIn(
            "/World/red_mug.material./World/Looks/red_mug_mat/Shader.diffuse_texture",
            plan.achieved_parameters,
        )

    def test_omnipbr_model_overrides_stale_preview_attrs(self):
        scan = {
            **SCAN_FIXTURE,
            "prims": [{
                **SCAN_FIXTURE["prims"][0],
                "material_bindings": [{
                    "material_path": "/World/Looks/knife/Shader",
                    "material_model": "omni_pbr",
                    "base_color": [0.8, 0.1, 0.1],
                    "base_color_attr": "inputs:diffuseColor",
                    "roughness": 0.5,
                    "roughness_attr": "inputs:roughness",
                }],
            }],
        }
        req = _request(objects=[
            {"prim_path": "/World/red_mug", "material": {"color_jitter": 0.01, "roughness": [0.3, 0.7]}}
        ])
        plan = sample_randomization(req, scan)
        attrs = {e.attribute for e in plan.edits}
        self.assertIn("inputs:diffuse_color_constant", attrs)
        self.assertIn("inputs:reflection_roughness_constant", attrs)
        self.assertNotIn("inputs:diffuseColor", attrs)
        self.assertNotIn("inputs:roughness", attrs)

    def test_textured_omnipbr_color_jitter_uses_diffuse_tint(self):
        scan = {
            **SCAN_FIXTURE,
            "prims": [{
                **SCAN_FIXTURE["prims"][0],
                "material_bindings": [{
                    "material_path": "/World/Looks/knife/Shader",
                    "material_model": "omni_pbr",
                    "diffuse_texture": "/textures/knife_albedo.png",
                    "diffuse_texture_attr": "inputs:diffuse_texture",
                }],
            }],
        }
        req = _request(objects=[
            {"prim_path": "/World/red_mug", "material": {"color_jitter": 0.01}}
        ])
        plan = sample_randomization(req, scan)
        attrs = {e.attribute for e in plan.edits}
        self.assertIn("inputs:diffuse_tint", attrs)
        self.assertNotIn("inputs:diffuse_color_constant", attrs)
        self.assertNotIn("inputs:diffuseColor", attrs)

    def test_lighting(self):
        req = _request(lights=[
            {"prim_path": "/World/DomeLight", "intensity_scale": [0.7, 1.3], "color_temperature": [3200, 6500]}
        ])
        plan = sample_randomization(req, SCAN_FIXTURE)
        keys = list(plan.achieved_parameters.keys())
        self.assertTrue(any("DomeLight.light.intensity" in k for k in keys))
        self.assertTrue(any("DomeLight.light.color_temperature" in k for k in keys))

    def test_camera_fov(self):
        req = _request(cameras=[
            {"prim_path": "/World/Camera", "fov_deg": [55, 75], "pose_jitter_m": [-0.02, 0.02]}
        ])
        plan = sample_randomization(req, SCAN_FIXTURE)
        keys = list(plan.achieved_parameters.keys())
        self.assertTrue(any("Camera.camera.fov_deg" in k for k in keys))
        self.assertTrue(any("Camera.camera.translation" in k for k in keys))

    def test_camera_yaw_pitch_jitter(self):
        req = _request(cameras=[
            {"prim_path": "/World/Camera", "yaw_pitch_jitter_deg": [-5.0, 5.0]}
        ])
        plan = sample_randomization(req, SCAN_FIXTURE)
        self.assertTrue(any(e.attribute == "xformOp:rotateXYZ" for e in plan.edits))
        self.assertIn("/World/Camera.camera.rotation_delta_deg", plan.achieved_parameters)
        delta = plan.achieved_parameters["/World/Camera.camera.rotation_delta_deg"]
        self.assertEqual(delta[0], 0.0)
        self.assertGreaterEqual(delta[1], -5.0)
        self.assertLessEqual(delta[1], 5.0)
        self.assertGreaterEqual(delta[2], -5.0)
        self.assertLessEqual(delta[2], 5.0)

    def test_camera_translation_and_rotation_share_one_matrix_edit(self):
        scan = {
            **SCAN_FIXTURE,
            "cameras": [{
                **SCAN_FIXTURE["cameras"][0],
                "xform": {
                    "layout": "matrix",
                    "op_order": ["xformOp:transform"],
                    "translate_op_name": "xformOp:transform",
                    "local_transform_4x4": [
                        1.0, 0.0, 0.0, 0.0,
                        0.0, 1.0, 0.0, 0.0,
                        0.0, 0.0, 1.0, 0.0,
                        1.0, 1.0, 1.0, 1.0,
                    ],
                    "parent_world_transform_4x4": [
                        1.0, 0.0, 0.0, 0.0,
                        0.0, 1.0, 0.0, 0.0,
                        0.0, 0.0, 1.0, 0.0,
                        0.0, 0.0, 0.0, 1.0,
                    ],
                },
            }],
        }
        req = _request(cameras=[
            {"prim_path": "/World/Camera", "pose_jitter_m": [0.0, 0.0], "yaw_pitch_jitter_deg": {"yaw": [10.0, 10.0]}}
        ])
        plan = sample_randomization(req, scan)
        matrix_edits = [e for e in plan.edits if e.attribute == "xformOp:transform"]
        self.assertEqual(len(matrix_edits), 1)
        self.assertIn("/World/Camera.camera.translation", plan.achieved_parameters)
        self.assertIn("/World/Camera.camera.rotation_delta_deg", plan.achieved_parameters)

    def test_pose_translation_jitter(self):
        req = _request(objects=[
            {"prim_path": "/World/blue_mug", "pose": {"translation_jitter_m": [-0.05, 0.05]}}
        ])
        plan = sample_randomization(req, SCAN_FIXTURE)
        keys = list(plan.achieved_parameters.keys())
        self.assertTrue(any("blue_mug.pose.translation" in k for k in keys))

    def test_pose_translation_jitter_per_axis(self):
        req = _request(objects=[
            {"prim_path": "/World/blue_mug", "pose": {"translation_jitter_m": {
                "x": [0.1, 0.1],
                "y": [0.0, 0.0],
                "z": [-0.2, -0.2],
            }}}
        ])
        plan = sample_randomization(req, SCAN_FIXTURE)
        value = plan.achieved_parameters["/World/blue_mug.pose.translation"]
        self.assertAlmostEqual(value[0], 0.6)
        self.assertAlmostEqual(value[1], 0.5)
        self.assertAlmostEqual(value[2], 0.3)

    def test_pose_translation_toward(self):
        req = _request(objects=[
            {"prim_path": "/World/blue_mug", "pose": {"translation_toward": {
                "target_prim": "/World/red_mug", "distance_m": [0.1, 0.2]
            }}}
        ])
        plan = sample_randomization(req, SCAN_FIXTURE)
        keys = list(plan.achieved_parameters.keys())
        self.assertTrue(any("blue_mug.pose.translation" in k for k in keys))

    def test_pose_rotation_jitter(self):
        req = _request(objects=[
            {"prim_path": "/World/blue_mug", "pose": {"rotation_jitter_deg": [-15.0, 15.0]}}
        ])
        plan = sample_randomization(req, SCAN_FIXTURE)
        self.assertTrue(any(e.attribute == "xformOp:rotateXYZ" for e in plan.edits))
        self.assertIn("/World/blue_mug.pose.rotation_delta_deg", plan.achieved_parameters)
        delta = plan.achieved_parameters["/World/blue_mug.pose.rotation_delta_deg"]
        self.assertEqual(delta[0], 0.0)
        self.assertEqual(delta[1], 0.0)
        self.assertGreaterEqual(delta[2], -15.0)
        self.assertLessEqual(delta[2], 15.0)

    def test_pose_scale_jitter(self):
        req = _request(objects=[
            {"prim_path": "/World/blue_mug", "pose": {"scale_jitter": [0.9, 1.1]}}
        ])
        plan = sample_randomization(req, SCAN_FIXTURE)
        self.assertTrue(any(e.attribute == "xformOp:scale" for e in plan.edits))
        self.assertIn("/World/blue_mug.pose.scale_factors", plan.achieved_parameters)
        factors = plan.achieved_parameters["/World/blue_mug.pose.scale_factors"]
        self.assertEqual(factors[0], factors[1])
        self.assertEqual(factors[1], factors[2])
        self.assertGreaterEqual(factors[0], 0.9)
        self.assertLessEqual(factors[0], 1.1)

    def test_pose_rotation_and_scale_share_one_matrix_edit(self):
        scan = {
            **SCAN_FIXTURE,
            "prims": [
                {
                    **SCAN_FIXTURE["prims"][1],
                    "xform": {
                        "layout": "matrix",
                        "op_order": ["xformOp:transform"],
                        "translate_op_name": "xformOp:transform",
                        "local_transform_4x4": [
                            1.0, 0.0, 0.0, 0.0,
                            0.0, 1.0, 0.0, 0.0,
                            0.0, 0.0, 1.0, 0.0,
                            0.5, 0.5, 0.5, 1.0,
                        ],
                        "parent_world_transform_4x4": [
                            1.0, 0.0, 0.0, 0.0,
                            0.0, 1.0, 0.0, 0.0,
                            0.0, 0.0, 1.0, 0.0,
                            0.0, 0.0, 0.0, 1.0,
                        ],
                    },
                }
            ],
        }
        req = _request(objects=[
            {"prim_path": "/World/blue_mug", "pose": {
                "rotation_jitter_deg": {"z": [10.0, 10.0]},
                "scale_jitter": [1.2, 1.2],
            }}
        ])
        plan = sample_randomization(req, scan)
        matrix_edits = [e for e in plan.edits if e.attribute == "xformOp:transform"]
        self.assertEqual(len(matrix_edits), 1)
        self.assertIn("/World/blue_mug.pose.rotation_delta_deg", plan.achieved_parameters)
        self.assertIn("/World/blue_mug.pose.scale_factors", plan.achieved_parameters)

    def test_pose_translation_rejected_by_bbox_collision(self):
        scan = {
            **SCAN_FIXTURE,
            "prims": [
                {
                    **SCAN_FIXTURE["prims"][0],
                    "bounds": {"aabb_min": [0.0, 0.0, 0.0], "aabb_max": [1.0, 1.0, 1.0]},
                    "world_transform": {"translation": [0.5, 0.5, 0.5]},
                },
                {
                    **SCAN_FIXTURE["prims"][1],
                    "bounds": {"aabb_min": [2.0, 2.0, 2.0], "aabb_max": [3.0, 3.0, 3.0]},
                    "world_transform": {"translation": [2.5, 2.5, 2.5]},
                },
            ],
        }
        req = _request(objects=[
            {"prim_path": "/World/blue_mug", "pose": {"translation_jitter_m": [-2.0, -2.0], "collision_max_attempts": 1}}
        ])
        plan = sample_randomization(req, scan)
        self.assertFalse(any(e.attribute == "xformOp:translate" for e in plan.edits))
        self.assertNotIn("/World/blue_mug.pose.translation", plan.achieved_parameters)
        self.assertTrue(any("bbox" in s["reason"].lower() or "aabb" in s["reason"].lower() for s in plan.skipped_prims))

    def test_pose_rotation_rejected_by_bbox_collision(self):
        scan = {
            **SCAN_FIXTURE,
            "prims": [
                {
                    **SCAN_FIXTURE["prims"][0],
                    "bounds": {"aabb_min": [-0.2, 0.75, -0.2], "aabb_max": [0.2, 1.2, 0.2]},
                    "world_transform": {"translation": [0.0, 0.975, 0.0]},
                },
                {
                    **SCAN_FIXTURE["prims"][1],
                    "bounds": {"aabb_min": [-1.0, -0.1, -0.1], "aabb_max": [1.0, 0.1, 0.1]},
                    "world_transform": {"translation": [0.0, 0.0, 0.0]},
                },
            ],
        }
        req = _request(objects=[
            {"prim_path": "/World/blue_mug", "pose": {"rotation_jitter_deg": {"z": [90.0, 90.0]}, "collision_max_attempts": 1}}
        ])
        plan = sample_randomization(req, scan)
        self.assertFalse(any(e.attribute == "xformOp:rotateXYZ" for e in plan.edits))
        self.assertNotIn("/World/blue_mug.pose.rotation_delta_deg", plan.achieved_parameters)
        self.assertTrue(any("bbox" in s["reason"].lower() or "aabb" in s["reason"].lower() for s in plan.skipped_prims))

    def test_pose_scale_rejected_by_bbox_collision(self):
        scan = {
            **SCAN_FIXTURE,
            "prims": [
                {
                    **SCAN_FIXTURE["prims"][0],
                    "bounds": {"aabb_min": [1.2, -0.2, -0.2], "aabb_max": [1.5, 0.2, 0.2]},
                    "world_transform": {"translation": [1.35, 0.0, 0.0]},
                },
                {
                    **SCAN_FIXTURE["prims"][1],
                    "bounds": {"aabb_min": [-0.5, -0.1, -0.1], "aabb_max": [0.5, 0.1, 0.1]},
                    "world_transform": {"translation": [0.0, 0.0, 0.0]},
                },
            ],
        }
        req = _request(objects=[
            {"prim_path": "/World/blue_mug", "pose": {"scale_jitter": [3.0, 3.0], "collision_max_attempts": 1}}
        ])
        plan = sample_randomization(req, scan)
        self.assertFalse(any(e.attribute == "xformOp:scale" for e in plan.edits))
        self.assertNotIn("/World/blue_mug.pose.scale_factors", plan.achieved_parameters)
        self.assertTrue(any("bbox" in s["reason"].lower() or "aabb" in s["reason"].lower() for s in plan.skipped_prims))

    def test_visibility_pool(self):
        req = _request(visibility_pools=[
            {"id": "p1", "prims": ["/World/red_mug", "/World/blue_mug"], "keep_visible": 1}
        ])
        plan = sample_randomization(req, SCAN_FIXTURE)
        keys = [k for k in plan.achieved_parameters.keys() if k.startswith("visibility_pool.p1")]
        self.assertEqual(len(keys), 2)
        visible_count = sum(1 for k in keys if plan.achieved_parameters[k])
        self.assertEqual(visible_count, 1)

    def test_object_visibility_modes(self):
        hidden = _request(objects=[
            {"prim_path": "/World/red_mug", "visibility": {"mode": "hidden"}}
        ])
        random_mode = _request(objects=[
            {"prim_path": "/World/red_mug", "visibility": {"mode": "random"}}
        ])

        hidden_plan = sample_randomization(hidden, SCAN_FIXTURE)
        random_plan = sample_randomization(random_mode, SCAN_FIXTURE)

        self.assertFalse(hidden_plan.achieved_parameters["/World/red_mug.visibility.visible"])
        self.assertIn("/World/red_mug.visibility.visible", random_plan.achieved_parameters)
        self.assertIn("/World/red_mug.visibility", random_plan.requested_parameters)

    def test_physics(self):
        req = _request(objects=[
            {"prim_path": "/World/red_mug", "physics": {
                "mass_scale": [0.8, 1.2], "friction": [0.4, 0.8], "restitution": [0.0, 0.5]
            }}
        ])
        plan = sample_randomization(req, SCAN_FIXTURE)
        keys = list(plan.achieved_parameters.keys())
        self.assertTrue(any("red_mug.physics.mass" in k for k in keys))
        self.assertTrue(any("red_mug.physics.friction" in k for k in keys))
        self.assertTrue(any("red_mug.physics.restitution" in k for k in keys))

    def test_deterministic_same_seed(self):
        req = _request(objects=[
            {"prim_path": "/World/red_mug", "material": {"color_jitter": 0.05}}
        ])
        plan_a = sample_randomization(req, SCAN_FIXTURE)
        plan_b = sample_randomization(req, SCAN_FIXTURE)
        self.assertEqual(plan_a.achieved_parameters, plan_b.achieved_parameters)

    def test_different_seed_different_output(self):
        objs = [{"prim_path": "/World/red_mug", "material": {"color_jitter": 0.1}}]
        plan_1 = sample_randomization(_request(seed=1, objects=objs), SCAN_FIXTURE)
        plan_2 = sample_randomization(_request(seed=2, objects=objs), SCAN_FIXTURE)
        self.assertNotEqual(plan_1.achieved_parameters, plan_2.achieved_parameters)

    def test_empty_request_produces_empty_plan(self):
        plan = sample_randomization(_request(), SCAN_FIXTURE)
        self.assertEqual(plan.edits, [])
        self.assertEqual(plan.achieved_parameters, {})

    def test_unlisted_prims_are_not_touched(self):
        # Only red_mug is in objects; blue_mug should not appear in any edit
        req = _request(objects=[
            {"prim_path": "/World/red_mug", "material": {"color_jitter": 0.05}}
        ])
        plan = sample_randomization(req, SCAN_FIXTURE)
        for edit in plan.edits:
            self.assertNotIn("blue_mug", edit.prim_path)

    def test_object_missing_from_scan_is_skipped(self):
        req = _request(objects=[
            {"prim_path": "/World/ghost", "material": {"color_jitter": 0.05}},
            {"prim_path": "/World/red_mug", "material": {"color_jitter": 0.05}},
        ])
        plan = sample_randomization(req, SCAN_FIXTURE)
        for edit in plan.edits:
            self.assertNotIn("ghost", edit.prim_path)
        self.assertTrue(any(s["prim_path"] == "/World/ghost" for s in plan.skipped_prims))

    def test_light_missing_from_scan_is_skipped(self):
        req = _request(lights=[
            {"prim_path": "/World/MissingLight", "intensity_scale": [0.7, 1.3]},
        ])
        plan = sample_randomization(req, SCAN_FIXTURE)
        self.assertEqual(plan.edits, [])
        self.assertTrue(any(s["kind"] == "light" for s in plan.skipped_prims))

    def test_camera_missing_from_scan_is_skipped(self):
        req = _request(cameras=[
            {"prim_path": "/World/MissingCam", "fov_deg": [55, 75]},
        ])
        plan = sample_randomization(req, SCAN_FIXTURE)
        self.assertEqual(plan.edits, [])
        self.assertTrue(any(s["kind"] == "camera" for s in plan.skipped_prims))
