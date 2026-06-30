from pathlib import Path
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


class ActiveStageCommandTest(unittest.TestCase):
    def test_command_can_use_supplied_active_stage(self):
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


if __name__ == "__main__":
    unittest.main()
