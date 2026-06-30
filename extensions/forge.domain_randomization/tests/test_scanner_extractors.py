"""Unit tests for scanner pure-python extractors.

These inject fake pxr-shaped objects so they do not require Isaac Sim. They
verify that the scanner correctly walks the subtree of a whitelisted prim and
aggregates physics / material info from descendants, even when the APIs live
on referenced children (the BEHAVIOR-1K layout).
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from forge_domain_randomization import scanner


class _FakePath:
    def __init__(self, p):
        self._p = p
    def __str__(self):
        return self._p


class _FakeAttr:
    def __init__(self, value, exists=True, name=None):
        self._value = value
        self._exists = exists
        self._name = name
    def __bool__(self):
        return self._exists
    def Get(self):
        return self._value
    def GetName(self):
        return self._name or ""


class _FakeRel:
    def __init__(self, targets):
        self._t = targets
    def GetTargets(self):
        return self._t


class FakePrim:
    def __init__(self, path, type_name="Xform", applied_apis=None,
                 attributes=None, material_binding_target=None,
                 physics_material_target=None, children=None,
                 valid=True, active=True):
        self._path = path
        self._type_name = type_name
        self._apis = applied_apis or set()
        self._attrs = attributes or {}
        self._material_binding = material_binding_target
        self._physics_material = physics_material_target
        self._children = list(children or [])
        self._valid = valid
        self._active = active

    def IsValid(self): return self._valid
    def IsActive(self): return self._active
    def IsInstanceProxy(self): return False
    def IsA(self, typ): return getattr(typ, "_name", None) == self._type_name
    def HasAPI(self, api_cls): return getattr(api_cls, "_name", None) in self._apis
    def GetTypeName(self): return self._type_name
    def GetName(self): return self._path.rsplit("/", 1)[-1]
    def GetPath(self): return _FakePath(self._path)
    def GetChildren(self): return list(self._children)

    def GetAttribute(self, name):
        if name in self._attrs:
            return _FakeAttr(self._attrs[name], name=name)
        return _FakeAttr(None, exists=False, name=name)

    def GetRelationship(self, name):
        if name == "material:binding" and self._material_binding is not None:
            return _FakeRel([self._material_binding])
        return _FakeRel([])


class _FakeAPI:
    def __init__(self, name):
        self._name = name


class _FakeMaterial:
    def __init__(self, prim):
        self._prim = prim
    def GetPrim(self):
        return self._prim
    def __bool__(self):
        return self._prim is not None


class _FakeMaterialBindingAPI:
    _name = "MaterialBindingAPI"
    def __init__(self, prim):
        self._prim = prim
    def ComputeBoundMaterial(self, purpose=None):
        if purpose == "physics":
            mat = getattr(self._prim, "_physics_material", None)
        else:
            mat = getattr(self._prim, "_material_binding", None)
        return (_FakeMaterial(mat), None)


class _FakeShaderInput:
    def __init__(self, prim, name):
        self._prim = prim
        self._name = name
    def GetAttr(self):
        return self._prim.GetAttribute(self._name)
    def GetFullName(self):
        return self._name
    def GetBaseName(self):
        return self._name.split("inputs:", 1)[-1]
    def Get(self):
        return self.GetAttr().Get()


class _FakeShader:
    def __init__(self, prim):
        self._prim = prim
    def GetInputs(self):
        return [
            _FakeShaderInput(self._prim, name)
            for name in self._prim._attrs
            if name.startswith("inputs:")
        ]
    def GetPrim(self):
        return self._prim


class _FakeMaterialSchema:
    def __init__(self, prim):
        self._prim = prim
    def ComputeSurfaceSource(self):
        for child in self._prim.GetChildren():
            if str(child.GetTypeName()) == "Shader":
                return (_FakeShader(child), "", "")
        return (None, "", "")


class _FakePhysicsMatAPI:
    _name = "MaterialAPI"
    def __init__(self, prim):
        self._prim = prim
    def GetDynamicFrictionAttr(self):
        return self._prim.GetAttribute("physics:dynamicFriction")
    def GetRestitutionAttr(self):
        return self._prim.GetAttribute("physics:restitution")


class _FakeMassAPI:
    _name = "MassAPI"
    def __init__(self, prim):
        self._prim = prim
    def GetMassAttr(self):
        return self._prim.GetAttribute("physics:mass")


def _modules():
    UsdPhysics = types.SimpleNamespace(
        RigidBodyAPI=_FakeAPI("RigidBodyAPI"),
        CollisionAPI=_FakeAPI("CollisionAPI"),
        MassAPI=_FakeMassAPI,
        MaterialAPI=_FakePhysicsMatAPI,
    )
    UsdShade = types.SimpleNamespace(
        MaterialBindingAPI=_FakeMaterialBindingAPI,
        Shader=_FakeShader,
        Material=_FakeMaterialSchema,
    )
    return UsdPhysics, UsdShade


class TestManualDescendants(unittest.TestCase):
    def test_walks_all_active_prims(self):
        leaf = FakePrim("/A/B/C")
        b = FakePrim("/A/B", children=[leaf])
        root = FakePrim("/A", children=[b])
        out = scanner._manual_descendants(root)
        self.assertEqual([str(p.GetPath()) for p in out], ["/A", "/A/B", "/A/B/C"])

    def test_skips_inactive(self):
        leaf = FakePrim("/A/inactive", active=False)
        root = FakePrim("/A", children=[leaf])
        out = scanner._manual_descendants(root)
        self.assertEqual([str(p.GetPath()) for p in out], ["/A"])


class TestExtractPhysics(unittest.TestCase):
    def test_rigid_body_mass_on_descendant(self):
        UsdPhysics, UsdShade = _modules()
        base_link = FakePrim(
            "/Knife/base_link",
            applied_apis={"RigidBodyAPI", "MassAPI", "CollisionAPI"},
            attributes={"physics:mass": 0.42},
        )
        root = FakePrim("/Knife", children=[base_link])
        descendants = scanner._manual_descendants(root)
        physics = scanner._extract_physics(descendants, UsdPhysics, UsdShade)
        self.assertTrue(physics["has_rigid_body"])
        self.assertEqual(physics["rigid_body_prim_path"], "/Knife/base_link")
        self.assertTrue(physics["has_collision"])
        self.assertEqual(physics["collision_prim_paths"], ["/Knife/base_link"])
        self.assertAlmostEqual(physics["mass"], 0.42)
        self.assertEqual(physics["mass_prim_path"], "/Knife/base_link")

    def test_root_without_apis_empty(self):
        UsdPhysics, UsdShade = _modules()
        root = FakePrim("/Plain")
        descendants = scanner._manual_descendants(root)
        physics = scanner._extract_physics(descendants, UsdPhysics, UsdShade)
        self.assertFalse(physics["has_rigid_body"])
        self.assertFalse(physics["has_collision"])
        self.assertIsNone(physics["mass"])
        self.assertIsNone(physics["mass_prim_path"])

    def test_physics_material_friction_restitution(self):
        UsdPhysics, UsdShade = _modules()
        phys_mat = FakePrim(
            "/Knife/PhysMat",
            type_name="Material",
            attributes={"physics:dynamicFriction": 0.55, "physics:restitution": 0.1},
        )
        base_link = FakePrim(
            "/Knife/base_link",
            applied_apis={"RigidBodyAPI"},
            physics_material_target=phys_mat,
        )
        root = FakePrim("/Knife", children=[base_link])
        descendants = scanner._manual_descendants(root)
        physics = scanner._extract_physics(descendants, UsdPhysics, UsdShade)
        self.assertEqual(physics["physics_material_prim_path"], "/Knife/PhysMat")
        self.assertAlmostEqual(physics["friction"], 0.55)
        self.assertAlmostEqual(physics["restitution"], 0.1)

    def test_first_rigid_body_wins(self):
        UsdPhysics, UsdShade = _modules()
        link_a = FakePrim("/Robot/link_a", applied_apis={"RigidBodyAPI"})
        link_b = FakePrim("/Robot/link_b", applied_apis={"RigidBodyAPI"})
        root = FakePrim("/Robot", children=[link_a, link_b])
        descendants = scanner._manual_descendants(root)
        physics = scanner._extract_physics(descendants, UsdPhysics, UsdShade)
        self.assertEqual(physics["rigid_body_prim_path"], "/Robot/link_a")


class TestExtractMaterialBindings(unittest.TestCase):
    def test_binding_on_descendant(self):
        UsdPhysics, UsdShade = _modules()
        shader = FakePrim(
            "/Knife/Looks/KnifeMat/Shader",
            type_name="Shader",
            attributes={"inputs:diffuseColor": (0.8, 0.1, 0.1), "inputs:roughness": 0.5},
        )
        material = FakePrim("/Knife/Looks/KnifeMat", type_name="Material", children=[shader])
        visuals = FakePrim(
            "/Knife/base_link/visuals",
            applied_apis={"MaterialBindingAPI"},
            material_binding_target=material,
        )
        base_link = FakePrim("/Knife/base_link", children=[visuals])
        root = FakePrim("/Knife", children=[base_link])
        descendants = scanner._manual_descendants(root)
        bindings = scanner._extract_material_bindings(descendants, UsdShade)
        self.assertEqual(len(bindings), 1)
        b = bindings[0]
        self.assertEqual(b["binding_prim_path"], "/Knife/base_link/visuals")
        self.assertEqual(b["material_path"], "/Knife/Looks/KnifeMat/Shader")
        self.assertEqual(b["material_model"], "usd_preview_surface")
        self.assertAlmostEqual(b["roughness"], 0.5)
        self.assertEqual([round(c, 3) for c in b["base_color"]], [0.8, 0.1, 0.1])
        self.assertEqual(b["base_color_attr"], "inputs:diffuseColor")
        self.assertEqual(b["roughness_attr"], "inputs:roughness")
        self.assertEqual(b["shader_inputs"], ["inputs:diffuseColor", "inputs:roughness"])

    def test_omnipbr_binding_records_mdl_input_names(self):
        UsdPhysics, UsdShade = _modules()
        shader = FakePrim(
            "/Knife/Looks/KnifeMat/Shader",
            type_name="Shader",
            attributes={
                "inputs:diffuse_color_constant": (0.8, 0.1, 0.1),
                "inputs:diffuse_tint": (1.0, 0.9, 0.8),
                "inputs:reflection_roughness_constant": 0.5,
                "inputs:diffuse_texture": "/textures/steel.png",
            },
        )
        material = FakePrim("/Knife/Looks/KnifeMat", type_name="Material", children=[shader])
        visuals = FakePrim(
            "/Knife/base_link/visuals",
            applied_apis={"MaterialBindingAPI"},
            material_binding_target=material,
        )
        root = FakePrim("/Knife", children=[visuals])
        descendants = scanner._manual_descendants(root)
        bindings = scanner._extract_material_bindings(descendants, UsdShade)
        self.assertEqual(len(bindings), 1)
        b = bindings[0]
        self.assertEqual(b["material_model"], "omni_pbr")
        self.assertEqual(b["base_color_attr"], "inputs:diffuse_color_constant")
        self.assertEqual(b["diffuse_tint_attr"], "inputs:diffuse_tint")
        self.assertEqual([round(c, 3) for c in b["diffuse_tint"]], [1.0, 0.9, 0.8])
        self.assertEqual(b["roughness_attr"], "inputs:reflection_roughness_constant")
        self.assertEqual(b["diffuse_texture_attr"], "inputs:diffuse_texture")
        self.assertEqual(b["diffuse_texture"], "/textures/steel.png")
        self.assertEqual(
            b["shader_inputs"],
            [
                "inputs:diffuse_color_constant",
                "inputs:diffuse_texture",
                "inputs:diffuse_tint",
                "inputs:reflection_roughness_constant",
            ],
        )

    def test_omnipbr_identity_wins_over_stale_preview_inputs(self):
        UsdPhysics, UsdShade = _modules()
        shader = FakePrim(
            "/Knife/Looks/KnifeMat/Shader",
            type_name="Shader",
            attributes={
                "info:mdl:sourceAsset": "/home/znr/isaacsim/kit/mdl/core/Base/OmniPBR.mdl",
                "info:mdl:sourceAsset:subIdentifier": "OmniPBR",
                # Stale attrs from older DR layers must not classify this as
                # USD PreviewSurface.
                "inputs:diffuseColor": (0.1, 0.2, 0.3),
                "inputs:roughness": 0.9,
                "inputs:diffuse_color_constant": (0.8, 0.1, 0.1),
                "inputs:reflection_roughness_constant": 0.5,
            },
        )
        material = FakePrim("/Knife/Looks/KnifeMat", type_name="Material", children=[shader])
        visuals = FakePrim(
            "/Knife/base_link/visuals",
            applied_apis={"MaterialBindingAPI"},
            material_binding_target=material,
        )
        descendants = scanner._manual_descendants(FakePrim("/Knife", children=[visuals]))
        bindings = scanner._extract_material_bindings(descendants, UsdShade)
        self.assertEqual(len(bindings), 1)
        b = bindings[0]
        self.assertEqual(b["material_model"], "omni_pbr")
        self.assertEqual(b["base_color_attr"], "inputs:diffuse_color_constant")
        self.assertEqual(b["roughness_attr"], "inputs:reflection_roughness_constant")

    def test_no_bindings(self):
        UsdPhysics, UsdShade = _modules()
        root = FakePrim("/Knife", children=[FakePrim("/Knife/empty")])
        descendants = scanner._manual_descendants(root)
        bindings = scanner._extract_material_bindings(descendants, UsdShade)
        self.assertEqual(bindings, [])

    def test_multiple_descendants_with_bindings(self):
        UsdPhysics, UsdShade = _modules()
        mat_a = FakePrim("/Looks/A", type_name="Material")
        mat_b = FakePrim("/Looks/B", type_name="Material")
        v1 = FakePrim("/Asset/v1", applied_apis={"MaterialBindingAPI"}, material_binding_target=mat_a)
        v2 = FakePrim("/Asset/v2", applied_apis={"MaterialBindingAPI"}, material_binding_target=mat_b)
        root = FakePrim("/Asset", children=[v1, v2])
        descendants = scanner._manual_descendants(root)
        bindings = scanner._extract_material_bindings(descendants, UsdShade)
        self.assertEqual(len(bindings), 2)
        paths = {b["material_path"] for b in bindings}
        self.assertEqual(paths, {"/Looks/A", "/Looks/B"})


class TestEulerConversion(unittest.TestCase):
    def test_identity_quaternion(self):
        class Q:
            def GetReal(self): return 1.0
            def GetImaginary(self): return (0.0, 0.0, 0.0)
        out = scanner._quat_to_euler_xyz_deg(Q())
        self.assertEqual(out, [0.0, 0.0, 0.0])

    def test_zero_quaternion_handled(self):
        class Q:
            def GetReal(self): return 0.0
            def GetImaginary(self): return (0.0, 0.0, 0.0)
        out = scanner._quat_to_euler_xyz_deg(Q())
        self.assertEqual(out, [0.0, 0.0, 0.0])


class TestSamplerCarrierPathIntegration(unittest.TestCase):
    """End-to-end: scan dict with carrier paths produces edits targeting the
    descendant prim, not the whitelist root path."""

    def test_mass_edit_targets_carrier(self):
        from forge_domain_randomization.sampler import sample_randomization
        from forge_domain_randomization.schemas import DomainRandomizationRequest

        scan = {
            "base_scene_usd": "/tmp/test.usd",
            "base_scene_hash": "sha256:base",
            "prims": [{
                "prim_path": "/World/Knife",
                "type_name": "Xform",
                "world_transform": {"translation": [0.0, 0.0, 0.0]},
                "physics": {
                    "has_rigid_body": True,
                    "rigid_body_prim_path": "/World/Knife/base_link",
                    "has_collision": True,
                    "collision_prim_paths": ["/World/Knife/base_link"],
                    "mass": 0.4,
                    "mass_prim_path": "/World/Knife/base_link",
                    "friction": None,
                    "restitution": None,
                    "physics_material_prim_path": "/World/Knife/PhysMat",
                },
                "material_bindings": [],
            }],
            "lights": [],
            "cameras": [],
        }
        req = DomainRandomizationRequest.from_dict({
            "request_id": "req_t",
            "variant_id": "var_t",
            "base_scene_usd": "/tmp/test.usd",
            "output_dir": "/tmp/out",
            "seed": 1,
            "base_scene_hash": "sha256:base",
            "config_hash": "sha256:config",
            "objects": [{
                "prim_path": "/World/Knife",
                "physics": {"mass_scale": [0.8, 1.2], "friction": [0.4, 0.6]},
            }],
            "lights": [], "cameras": [], "visibility_pools": [],
        })
        plan = sample_randomization(req, scan)
        mass_edits = [e for e in plan.edits if e.attribute == "physics:mass"]
        friction_edits = [e for e in plan.edits if e.attribute == "physics:dynamicFriction"]
        self.assertEqual(len(mass_edits), 1)
        self.assertEqual(mass_edits[0].prim_path, "/World/Knife/base_link")
        self.assertEqual(len(friction_edits), 1)
        self.assertEqual(friction_edits[0].prim_path, "/World/Knife/PhysMat")


if __name__ == "__main__":
    unittest.main()
