from pathlib import Path
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = PROJECT_ROOT / "extensions" / "forge.domain_randomization"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PACKAGE_ROOT))

from forge_domain_randomization.commands import run_domain_randomization
from forge_domain_randomization.schemas import DomainScanReport


class SceneCraftCouplingTest(unittest.TestCase):
    def test_bridge_adds_extension_path_and_runs_offline_payload(self):
        from SceneCraft.domain_randomization_bridge import (
            extension_package_root,
            run_domain_randomization_payload,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base_scene.usd"
            base.write_text("#usda 1.0\n", encoding="utf-8")
            result = run_domain_randomization_payload(
                {
                    "request_id": "bridge_seed_0001",
                    "variant_id": "bridge_seed_0001",
                    "base_scene_usd": str(base),
                    "output_dir": str(root / "dr"),
                    "seed": 1,
                    "layer_policy": {"mode": "single", "writer": "text"},
                    "_injected_scan": {
                        "base_scene_usd": str(base),
                        "base_scene_hash": "sha256:base",
                        "prims": [],
                        "lights": [],
                        "cameras": [],
                    },
                }
            )
            self.assertTrue(result["success"])
            self.assertEqual(extension_package_root(), PACKAGE_ROOT)
            self.assertIn(str(PACKAGE_ROOT), sys.path)

    def test_command_can_use_active_stage_supplied_by_scene_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base_scene.usd"
            base.write_text("#usda 1.0\n", encoding="utf-8")
            scan_report = DomainScanReport(
                base_scene_usd=str(base),
                base_scene_hash="sha256:base",
                prims=[],
                lights=[],
                cameras=[],
            )
            with patch("forge_domain_randomization.commands.scan_stage", return_value=scan_report) as mocked_scan:
                result = run_domain_randomization(
                    {
                        "request_id": "active_stage_seed_0001",
                        "variant_id": "active_stage_seed_0001",
                        "base_scene_usd": str(base),
                        "output_dir": str(root / "dr"),
                        "seed": 1,
                        "layer_policy": {"mode": "single", "writer": "text"},
                        "_stage": object(),
                    }
                )
            self.assertTrue(result["success"])
            self.assertTrue(mocked_scan.called)
            self.assertTrue(Path(result["scan_path"]).exists())

    def test_python_side_wrapper_serializes_pipe_command_and_parses_response(self):
        from SceneCraft.Tools import domain_randomization_tool

        response = {
            "success": True,
            "variant_id": "task_001_seed_0001",
            "result_path": "/tmp/achieved_domain_report.json",
        }
        captured = {}

        def fake_request(command, timeout=300):
            captured["command"] = command
            captured["timeout"] = timeout
            return json.dumps(response)

        with patch.object(domain_randomization_tool, "_request_isaac", side_effect=fake_request):
            result = domain_randomization_tool.run_domain_randomization(
                {
                    "request_id": "task_001_dr_seed_0001",
                    "variant_id": "task_001_seed_0001",
                    "base_scene_usd": "/tmp/base_scene.usd",
                    "output_dir": "/tmp/dr",
                    "seed": 1,
                },
                timeout=123,
            )

        self.assertEqual(result, response)
        self.assertEqual(captured["timeout"], 123)
        self.assertTrue(captured["command"].startswith("domain_randomization_run,"))
        payload = json.loads(captured["command"].split(",", 1)[1])
        self.assertEqual(payload["variant_id"], "task_001_seed_0001")

    def test_persistent_isaac_host_pipe_smoke(self):
        if os.environ.get("FORGE_DR_PIPE_SMOKE") != "1":
            self.skipTest("set FORGE_DR_PIPE_SMOKE=1 to run against a live SceneCraft Isaac host")

        from SceneCraft.Tools.domain_randomization_tool import run_domain_randomization

        base_scene_usd = os.environ.get("FORGE_DR_PIPE_BASE_USD")
        if base_scene_usd and not Path(base_scene_usd).exists():
            self.fail(f"FORGE_DR_PIPE_BASE_USD does not exist: {base_scene_usd}")

        timeout = int(os.environ.get("FORGE_DR_PIPE_TIMEOUT", "300"))
        output_root = os.environ.get("FORGE_DR_PIPE_OUTPUT_DIR")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(output_root or tmp)
            output_dir = root / "dr_pipe_smoke_seed_0001"
            request = {
                "request_id": "dr_pipe_smoke_seed_0001",
                "variant_id": "dr_pipe_smoke_seed_0001",
                "output_dir": str(output_dir),
                "seed": 1,
                "layer_policy": {"mode": "separate_by_domain"},
                "lights": [
                    {
                        "prim_path": "/World/DomeLight",
                        "intensity_scale": [0.8, 1.2],
                        "color_temperature": [3000, 6500],
                    }
                ],
                "cameras": [
                    {
                        "prim_path": "/World/Camera",
                        "pose_jitter_m": [-0.02, 0.02],
                        "fov_deg": [55, 75],
                    }
                ],
            }
            if base_scene_usd:
                request["base_scene_usd"] = base_scene_usd

            result = run_domain_randomization(request, timeout=timeout)
            self.assertTrue(result.get("success"), result)
            self.assertEqual(result.get("variant_id"), "dr_pipe_smoke_seed_0001")

            scan_path = Path(result["scan_path"])
            layer_stack_path = Path(result["layer_stack_path"])
            report_path = Path(result["result_path"])
            self.assertTrue(scan_path.exists(), result)
            self.assertTrue(layer_stack_path.exists(), result)
            self.assertTrue(report_path.exists(), result)

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["variant_id"], "dr_pipe_smoke_seed_0001")
            self.assertTrue(report["randomization_layers"], report)
            self.assertTrue(report["achieved_parameters"], report)


if __name__ == "__main__":
    unittest.main()
