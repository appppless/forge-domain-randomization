"""Layout-aware pose / camera applier + xform_layout math tests."""

from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from forge_domain_randomization import xform_layout as xl
from forge_domain_randomization.appliers import camera as cam_applier
from forge_domain_randomization.appliers import pose as pose_applier
from forge_domain_randomization.layer_writer import _format_attribute
from forge_domain_randomization.sampler import LayerEdit


def _identity_xform(layout: str = "trs", op_order=None, translate_op_name="xformOp:translate",
                    precision="double", local_translation=(0.0, 0.0, 0.0)) -> dict:
    return {
        "layout": layout,
        "op_order": list(op_order or [translate_op_name]),
        "translate_op_name": translate_op_name,
        "translate_op_precision": precision,
        "local_translation": list(local_translation),
        "local_transform_4x4": xl.identity_4x4(),
        "parent_world_transform_4x4": xl.identity_4x4(),
        "translate": {
            "present": translate_op_name is not None,
            "op_name": translate_op_name,
            "precision": precision,
            "base_value": list(local_translation),
        },
        "rotate": {
            "present": False,
            "op_name": None,
            "precision": None,
            "base_value": None,
            "op_type": None,
        },
        "scale": {
            "present": False,
            "op_name": None,
            "precision": None,
            "base_value": None,
        },
    }


class TestXformLayoutMath(unittest.TestCase):
    def test_identity_inverse_is_identity(self):
        inv = xl.matrix4d_inverse(xl.identity_4x4())
        self.assertEqual(inv, xl.identity_4x4())

    def test_mat_vec_mul_translates_point(self):
        m = xl.identity_4x4()
        # USD row-major: translation lives in row 3 (indices 12..14).
        m[12], m[13], m[14] = 1.0, 2.0, 3.0
        out = xl.mat_vec_mul_point(m, [0.0, 0.0, 0.0])
        self.assertEqual(out, [1.0, 2.0, 3.0])

    def test_world_to_local_with_translated_parent(self):
        parent = xl.identity_4x4()
        parent[12], parent[13], parent[14] = 1.0, 2.0, 3.0
        local = xl.world_to_local_translation([5.0, 5.0, 5.0], parent)
        self.assertEqual(local, [4.0, 3.0, 2.0])

    def test_replace_translation(self):
        m = xl.identity_4x4()
        out = xl.replace_translation(m, [7.0, 8.0, 9.0])
        self.assertEqual(out[12], 7.0)
        self.assertEqual(out[13], 8.0)
        self.assertEqual(out[14], 9.0)
        self.assertEqual(out[15], 1.0)
        # rotation rows untouched
        self.assertEqual(out[0], 1.0)
        self.assertEqual(out[5], 1.0)
        self.assertEqual(out[10], 1.0)


class TestPoseLayoutApplier(unittest.TestCase):
    def test_trs_emits_single_translate(self):
        edits, warns = pose_applier.translation_edits(
            "/World/mug", [1.0, 2.0, 3.0],
            _identity_xform(layout="trs"),
        )
        self.assertEqual(warns, [])
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0].attribute, "xformOp:translate")
        self.assertEqual(edits[0].value_type, "double3")
        self.assertEqual(edits[0].value, [1.0, 2.0, 3.0])

    def test_trs_respects_op_name_and_precision(self):
        xform = _identity_xform(
            layout="trs", translate_op_name="xformOp:translate:pivot", precision="float",
        )
        edits, _ = pose_applier.translation_edits("/World/mug", [0.1, 0.2, 0.3], xform)
        self.assertEqual(edits[0].attribute, "xformOp:translate:pivot")
        self.assertEqual(edits[0].value_type, "float3")

    def test_matrix_rewrites_full_transform(self):
        xform = _identity_xform(layout="matrix", op_order=["xformOp:transform"],
                                translate_op_name="xformOp:transform")
        # Bake a rotation into the local matrix so we can verify it's preserved.
        local = xl.identity_4x4()
        local[0], local[1] = 0.0, 1.0
        local[4], local[5] = -1.0, 0.0
        xform["local_transform_4x4"] = local
        edits, warns = pose_applier.translation_edits(
            "/World/cam", [10.0, 20.0, 30.0], xform,
        )
        self.assertEqual(warns, [])
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0].attribute, "xformOp:transform")
        self.assertEqual(edits[0].value_type, "matrix4d")
        self.assertEqual(len(edits[0].value), 16)
        # Translation row replaced.
        self.assertEqual(edits[0].value[12], 10.0)
        self.assertEqual(edits[0].value[13], 20.0)
        self.assertEqual(edits[0].value[14], 30.0)
        # Rotation row 0 preserved.
        self.assertEqual(edits[0].value[0], 0.0)
        self.assertEqual(edits[0].value[1], 1.0)

    def test_empty_layout_emits_translate_and_order(self):
        xform = _identity_xform(layout="empty", op_order=[], translate_op_name=None)
        edits, warns = pose_applier.translation_edits("/World/x", [1.0, 0.0, 0.0], xform)
        self.assertEqual(warns, [])
        kinds = sorted((e.attribute, e.value_type) for e in edits)
        self.assertIn(("xformOp:translate", "double3"), kinds)
        self.assertIn(("xformOpOrder", "token[]"), kinds)

    def test_unknown_layout_warns_and_skips(self):
        xform = _identity_xform(layout="unknown", op_order=["xformOp:rotateXYZ"],
                                translate_op_name=None)
        edits, warns = pose_applier.translation_edits("/World/y", [0.0, 0.0, 0.0], xform)
        self.assertEqual(edits, [])
        self.assertEqual(len(warns), 1)
        self.assertEqual(warns[0]["type"], "unknown_xform_layout")

    def test_singular_parent_warns(self):
        xform = _identity_xform(layout="trs")
        # Zero matrix is singular.
        xform["parent_world_transform_4x4"] = [0.0] * 16
        edits, warns = pose_applier.translation_edits("/World/y", [1.0, 1.0, 1.0], xform)
        self.assertEqual(edits, [])
        self.assertEqual(warns[0]["type"], "parent_transform_singular")

    def test_none_xform_falls_back_to_legacy(self):
        edits, warns = pose_applier.translation_edits("/World/z", [4.0, 5.0, 6.0], None)
        self.assertEqual(warns, [])
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0].attribute, "xformOp:translate")
        self.assertEqual(edits[0].value, [4.0, 5.0, 6.0])

    def test_trs_rotation_updates_existing_rotate_op(self):
        xform = _identity_xform(layout="trs", op_order=["xformOp:rotateXYZ"])
        xform["rotate"] = {
            "present": True,
            "op_name": "xformOp:rotateXYZ",
            "precision": "float",
            "op_type": "rotateXYZ",
            "base_value": [0.0, 5.0, 10.0],
        }
        edits, warns = pose_applier.rotation_edits("/World/mug", [1.0, 2.0, 3.0], xform)
        self.assertEqual(warns, [])
        self.assertEqual(edits[0].attribute, "xformOp:rotateXYZ")
        self.assertEqual(edits[0].value_type, "float3")
        self.assertEqual(edits[0].value, [1.0, 7.0, 13.0])

    def test_trs_orient_rotation_updates_existing_quaternion_op(self):
        xform = _identity_xform(layout="trs", op_order=["xformOp:orient"])
        xform["rotate"] = {
            "present": True,
            "op_name": "xformOp:orient",
            "precision": "float",
            "op_type": "orient",
            # Scanner stores quaternions as [x, y, z, w].
            "base_value": [0.0, 0.0, 0.0, 1.0],
        }
        edits, warns = pose_applier.rotation_edits("/World/mug", [0.0, 0.0, 90.0], xform)
        self.assertEqual(warns, [])
        self.assertEqual(edits[0].attribute, "xformOp:orient")
        self.assertEqual(edits[0].value_type, "quatf")
        self.assertAlmostEqual(edits[0].value[0], 0.0)
        self.assertAlmostEqual(edits[0].value[1], 0.0)
        self.assertAlmostEqual(edits[0].value[2], 0.70710678)
        self.assertAlmostEqual(edits[0].value[3], 0.70710678)

    def test_trs_scale_updates_existing_scale_op(self):
        xform = _identity_xform(layout="trs", op_order=["xformOp:scale"])
        xform["scale"] = {
            "present": True,
            "op_name": "xformOp:scale",
            "precision": "double",
            "base_value": [2.0, 3.0, 4.0],
        }
        edits, warns = pose_applier.scale_edits("/World/mug", [0.5, 1.0, 1.5], xform)
        self.assertEqual(warns, [])
        self.assertEqual(edits[0].attribute, "xformOp:scale")
        self.assertEqual(edits[0].value, [1.0, 3.0, 6.0])

    def test_trs_missing_rotate_warns(self):
        xform = _identity_xform(layout="trs", op_order=["xformOp:translate"])
        edits, warns = pose_applier.rotation_edits("/World/mug", [0.0, 0.0, 5.0], xform)
        self.assertEqual(edits, [])
        self.assertEqual(warns[0]["type"], "missing_rotate_op")

    def test_matrix_combines_translation_rotation_and_scale(self):
        xform = _identity_xform(layout="matrix", op_order=["xformOp:transform"],
                                translate_op_name="xformOp:transform")
        xform["local_transform_4x4"] = xl.compose_trs(
            [1.0, 2.0, 3.0],
            [0.0, 0.0, 10.0],
            [2.0, 2.0, 2.0],
        )
        edits, warns, applied = pose_applier.transform_edits(
            "/World/mug",
            xform,
            world_translation=[4.0, 5.0, 6.0],
            rotation_delta_deg=[0.0, 0.0, 15.0],
            scale_factors=[0.5, 1.0, 1.5],
        )
        self.assertEqual(warns, [])
        self.assertEqual(applied, {"translation", "rotation", "scale"})
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0].attribute, "xformOp:transform")
        t, r, s = xl.decompose_trs(edits[0].value)
        self.assertEqual(t, [4.0, 5.0, 6.0])
        self.assertAlmostEqual(r[2], 25.0)
        self.assertAlmostEqual(s[0], 1.0)
        self.assertAlmostEqual(s[1], 2.0)
        self.assertAlmostEqual(s[2], 3.0)


class TestCameraLayoutApplier(unittest.TestCase):
    def test_camera_translation_uses_simulator_domain(self):
        edits, _ = cam_applier.translation_edits(
            "/OmniverseKit_Persp", [1.0, 2.0, 3.0],
            _identity_xform(layout="trs"),
        )
        self.assertTrue(all(e.domain == "simulator" for e in edits))

    def test_camera_matrix_layout_preserves_rotation(self):
        xform = _identity_xform(layout="matrix", op_order=["xformOp:transform"],
                                translate_op_name="xformOp:transform")
        local = xl.identity_4x4()
        # 90-degree rotation about Z.
        local[0], local[1] = 0.0, 1.0
        local[4], local[5] = -1.0, 0.0
        xform["local_transform_4x4"] = local
        edits, _ = cam_applier.translation_edits(
            "/OmniverseKit_Persp", [5.0, 0.0, 2.0], xform,
        )
        self.assertEqual(edits[0].value_type, "matrix4d")
        self.assertEqual(edits[0].value[0], 0.0)
        self.assertEqual(edits[0].value[1], 1.0)
        self.assertEqual(edits[0].value[12], 5.0)


class TestLayerWriterValueTypes(unittest.TestCase):
    def test_matrix4d_format(self):
        edit = LayerEdit(
            domain="placement", prim_path="/p",
            attribute="xformOp:transform",
            value=list(range(16)), value_type="matrix4d",
        )
        line = _format_attribute(edit)
        self.assertTrue(line.startswith("matrix4d xformOp:transform = ( ("))
        self.assertIn("(0, 1, 2, 3)", line)
        self.assertIn("(12, 13, 14, 15)", line)

    def test_token_array_format(self):
        edit = LayerEdit(
            domain="placement", prim_path="/p",
            attribute="xformOpOrder", value=["xformOp:translate", "xformOp:rotateXYZ"],
            value_type="token[]",
        )
        line = _format_attribute(edit)
        self.assertEqual(
            line,
            'uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:rotateXYZ"]',
        )

    def test_float3_value(self):
        edit = LayerEdit(
            domain="placement", prim_path="/p",
            attribute="xformOp:translate", value=[0.5, 1.5, 2.5], value_type="float3",
        )
        line = _format_attribute(edit)
        self.assertEqual(line, "float3 xformOp:translate = (0.5, 1.5, 2.5)")

    def test_asset_value(self):
        edit = LayerEdit(
            domain="asset", prim_path="/p",
            attribute="inputs:diffuse_texture", value="/textures/steel.png", value_type="asset",
        )
        line = _format_attribute(edit)
        self.assertEqual(line, "asset inputs:diffuse_texture = @/textures/steel.png@")

    def test_quat_value(self):
        edit = LayerEdit(
            domain="placement", prim_path="/p",
            attribute="xformOp:orient", value=[0.0, 0.0, 0.70710678, 0.70710678], value_type="quatf",
        )
        line = _format_attribute(edit)
        self.assertEqual(line, "quatf xformOp:orient = (0.70710678, 0, 0, 0.70710678)")


class TestLayoutDescriptorSymmetry(unittest.TestCase):
    """The descriptor returned by extract_layout exposes T / R / S as peers."""

    def test_empty_layout_has_all_three_components(self):
        layout = xl.empty_layout()
        for key in ("translate", "rotate", "scale"):
            self.assertIn(key, layout)
            self.assertFalse(layout[key]["present"])
            self.assertIsNone(layout[key]["op_name"])
            self.assertIsNone(layout[key]["base_value"])
        # rotate carries an additional op_type discriminant
        self.assertIn("op_type", layout["rotate"])
        self.assertIsNone(layout["rotate"]["op_type"])

    def test_empty_layout_keeps_legacy_mirrors(self):
        # Existing pose applier / tests read these keys; do not drop them.
        layout = xl.empty_layout()
        self.assertIn("translate_op_name", layout)
        self.assertIn("translate_op_precision", layout)
        self.assertIn("local_translation", layout)

    def test_safe_op_type_returns_specific_rotate_kind_from_name(self):
        # No pxr available: name-based fallback must still discriminate.
        class _StubOp:
            def __init__(self, name): self._n = name
            def GetName(self): return self._n
            def GetOpType(self): raise RuntimeError("no pxr")
        self.assertEqual(xl._safe_op_type(_StubOp("xformOp:rotateXYZ"), object()), "rotateXYZ")
        self.assertEqual(xl._safe_op_type(_StubOp("xformOp:rotateZYX"), object()), "rotateZYX")
        self.assertEqual(xl._safe_op_type(_StubOp("xformOp:rotateX"), object()), "rotateX")
        self.assertEqual(xl._safe_op_type(_StubOp("xformOp:orient"), object()), "orient")
        self.assertEqual(xl._safe_op_type(_StubOp("xformOp:scale"), object()), "scale")
        self.assertEqual(xl._safe_op_type(_StubOp("xformOp:translate"), object()), "translate")


if __name__ == "__main__":
    unittest.main()
