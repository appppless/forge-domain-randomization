"""Tests for the compose utility and the compose_layer_stack command."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from forge_domain_randomization.commands import compose_layer_stack
from forge_domain_randomization.compose import (
    ComposeResult,
    compose_stage,
    compose_stage_from_manifest,
)


def _write_fake_layer(path: Path, text: str = "#usda 1.0\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestComposeStage(unittest.TestCase):
    def test_writes_stub_with_strongest_first_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            base = tmp / "base_scene.usd"
            dr1 = tmp / "layers" / "dr_seed_0001.usda"
            dr2 = tmp / "layers" / "dr_seed_0001_distractors.usda"
            _write_fake_layer(base)
            _write_fake_layer(dr1)
            _write_fake_layer(dr2)

            result = compose_stage(
                base_scene_usd=str(base),
                sub_layers=[str(dr1), str(dr2)],
                output_path=tmp / "composed_scene.usda",
                variant_id="var_test",
                verify=True,
            )
            self.assertIsInstance(result, ComposeResult)
            self.assertTrue(Path(result.composed_scene_usd).exists())

            text = Path(result.composed_scene_usd).read_text()
            self.assertIn("#usda 1.0", text)
            self.assertIn("subLayers", text)
            # Restrict ordering check to the subLayers list (skip metadata block).
            sl_start = text.index("subLayers")
            sl_end = text.index("]", sl_start)
            sl_block = text[sl_start:sl_end]
            idx_dr1 = sl_block.find(str(dr1.resolve()))
            idx_dr2 = sl_block.find(str(dr2.resolve()))
            idx_base = sl_block.find(str(base.resolve()))
            self.assertGreaterEqual(idx_dr1, 0)
            self.assertGreaterEqual(idx_dr2, 0)
            self.assertGreaterEqual(idx_base, 0)
            self.assertLess(idx_dr1, idx_dr2)
            self.assertLess(idx_dr2, idx_base)

            self.assertEqual(result.sub_layers[-1], str(base.resolve()))
            self.assertEqual(result.sub_layers[0], str(dr1.resolve()))

    def test_missing_sublayer_reported_as_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            base = tmp / "base_scene.usd"
            _write_fake_layer(base)
            result = compose_stage(
                base_scene_usd=str(base),
                sub_layers=[str(tmp / "ghost.usda")],
                output_path=tmp / "composed_scene.usda",
                verify=True,
            )
            errors = [i for i in result.issues if i.get("severity") == "error"]
            self.assertTrue(errors)
            self.assertEqual(errors[0]["type"], "missing_sublayer")

    def test_verify_false_skips_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            result = compose_stage(
                base_scene_usd=str(tmp / "no_such.usd"),
                sub_layers=[str(tmp / "no_such.usda")],
                output_path=tmp / "composed_scene.usda",
                verify=False,
            )
            self.assertEqual(result.issues, [])
            self.assertTrue(Path(result.composed_scene_usd).exists())


class TestComposeFromManifest(unittest.TestCase):
    def test_reads_layer_stack_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            base = tmp / "base.usd"
            dr = tmp / "rl" / "dr.usda"
            _write_fake_layer(base)
            _write_fake_layer(dr)
            manifest = tmp / "layer_stack.json"
            manifest.write_text(json.dumps({
                "schema_version": "0.2",
                "variant_id": "var_x",
                "base_scene_usd": str(base),
                "sub_layers": [str(dr)],
                "composed_scene_usd": None,
            }))
            result = compose_stage_from_manifest(manifest, verify=True)
            self.assertEqual(
                Path(result.composed_scene_usd).name, "composed_scene.usda"
            )
            self.assertEqual(Path(result.composed_scene_usd).parent, tmp)

    def test_missing_manifest_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                compose_stage_from_manifest(Path(tmp) / "missing.json")


class TestComposeLayerStackCommand(unittest.TestCase):
    def test_from_manifest_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            base = tmp / "base.usd"
            dr = tmp / "dr.usda"
            _write_fake_layer(base)
            _write_fake_layer(dr)
            manifest = tmp / "layer_stack.json"
            manifest.write_text(json.dumps({
                "schema_version": "0.2",
                "variant_id": "var_y",
                "base_scene_usd": str(base),
                "sub_layers": [str(dr)],
            }))
            result = compose_layer_stack({"layer_stack_path": str(manifest)})
            self.assertTrue(result["success"])
            self.assertTrue(Path(result["composed_scene_usd"]).exists())
            self.assertEqual(result["base_scene_usd"], str(base.resolve()))

    def test_explicit_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            base = tmp / "base.usd"
            dr = tmp / "dr.usda"
            _write_fake_layer(base)
            _write_fake_layer(dr)
            out = tmp / "composed.usda"
            result = compose_layer_stack({
                "base_scene_usd": str(base),
                "sub_layers": [str(dr)],
                "output_path": str(out),
            })
            self.assertTrue(result["success"])
            self.assertTrue(out.exists())

    def test_missing_sublayer_marks_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            out = tmp / "composed.usda"
            result = compose_layer_stack({
                "base_scene_usd": str(tmp / "ghost_base.usd"),
                "sub_layers": [str(tmp / "ghost.usda")],
                "output_path": str(out),
            })
            self.assertFalse(result["success"])
            self.assertTrue(any(
                i["type"] == "missing_sublayer" for i in result.get("issues", [])
            ))

    def test_invalid_payload_returns_failure(self):
        result = compose_layer_stack({})
        self.assertFalse(result["success"])
        self.assertIn("message", result)


class TestRunComposesByDefault(unittest.TestCase):
    """`run_domain_randomization` must always emit a composed_scene.usda when
    the base scene exists on disk, in addition to the sublayer USDA(s)."""

    def _payload(self, output_dir: str, base_scene: str, extra: dict | None = None):
        payload = {
            "request_id": "req_t",
            "variant_id": "var_t",
            "base_scene_usd": base_scene,
            "output_dir": output_dir,
            "seed": 1,
            "layer_policy": {"mode": "single", "writer": "text"},
            "objects": [
                {"prim_path": "/World/red_mug", "material": {"color_jitter": 0.05}}
            ],
            "_injected_scan": {
                "base_scene_usd": base_scene,
                "base_scene_hash": "sha256:base",
                "prims": [{
                    "prim_path": "/World/red_mug",
                    "type_name": "Xform",
                    "world_transform": {"translation": [0.0, 0.0, 0.5]},
                    "physics": {"has_rigid_body": True, "has_collision": True, "mass": 0.25},
                    "material_bindings": [{
                        "material_path": "/World/Looks/m",
                        "base_color": [0.5, 0.5, 0.5],
                        "roughness": 0.5,
                    }],
                }],
                "lights": [],
                "cameras": [],
            },
        }
        if extra:
            payload.update(extra)
        return payload

    def test_composed_scene_written_alongside_sublayer(self):
        from forge_domain_randomization.commands import run_domain_randomization
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            base = tmp / "base_scene.usd"
            _write_fake_layer(base)
            out_dir = tmp / "out"
            result = run_domain_randomization(self._payload(str(out_dir), str(base)))
            self.assertTrue(result["success"])
            self.assertIsNotNone(result.get("composed_scene_usd"))
            composed = Path(result["composed_scene_usd"])
            self.assertTrue(composed.exists())
            self.assertEqual(composed.name, "composed_scene.usda")
            # Sublayer USDA still present.
            layer_files = list((out_dir / "randomization_layers").glob("*.usda"))
            self.assertTrue(layer_files)
            # Composed file references at least one DR layer + the base scene.
            text = composed.read_text()
            self.assertIn(str(layer_files[0].resolve()), text)
            self.assertIn(str(base.resolve()), text)
            # Manifest records composed_scene_usd.
            manifest = json.loads(Path(result["layer_stack_path"]).read_text())
            self.assertEqual(manifest["composed_scene_usd"], str(composed))

    def test_compose_skipped_when_base_scene_missing(self):
        from forge_domain_randomization.commands import run_domain_randomization
        with tempfile.TemporaryDirectory() as tmp:
            result = run_domain_randomization(
                self._payload(tmp, "/nope/base_scene.usd")
            )
            self.assertTrue(result["success"])
            self.assertIsNone(result.get("composed_scene_usd"))
            self.assertFalse((Path(tmp) / "composed_scene.usda").exists())
            report = json.loads(Path(result["result_path"]).read_text())
            issues = report["validation"]["issues"]
            self.assertTrue(any(i.get("type") == "compose_skipped" for i in issues))


class TestLayerStackManifestComposition(unittest.TestCase):
    def test_emits_composition_metadata(self):
        from forge_domain_randomization.commands import run_domain_randomization
        with tempfile.TemporaryDirectory() as tmp:
            payload = {
                "request_id": "req_t",
                "variant_id": "var_t",
                "base_scene_usd": "/tmp/test.usd",
                "output_dir": tmp,
                "seed": 1,
                "layer_policy": {"mode": "single", "writer": "text"},
                "objects": [
                    {"prim_path": "/World/red_mug", "material": {"color_jitter": 0.05}}
                ],
                "_injected_scan": {
                    "base_scene_usd": "/tmp/test.usd",
                    "base_scene_hash": "sha256:base",
                    "prims": [{
                        "prim_path": "/World/red_mug",
                        "type_name": "Xform",
                        "world_transform": {"translation": [0.0, 0.0, 0.5]},
                        "physics": {"has_rigid_body": True, "has_collision": True, "mass": 0.25},
                        "material_bindings": [{
                            "material_path": "/World/Looks/m",
                            "base_color": [0.5, 0.5, 0.5],
                            "roughness": 0.5,
                        }],
                    }],
                    "lights": [],
                    "cameras": [],
                },
            }
            result = run_domain_randomization(payload)
            self.assertTrue(result["success"])
            manifest = json.loads(Path(result["layer_stack_path"]).read_text())
            self.assertIn("composition", manifest)
            self.assertEqual(
                manifest["composition"]["order"], "subLayers_first_is_strongest"
            )
            self.assertEqual(manifest["composition"]["base_role"], "weakest_sublayer")


if __name__ == "__main__":
    unittest.main()
