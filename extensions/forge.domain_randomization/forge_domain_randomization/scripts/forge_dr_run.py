"""Standalone headless runner for FORGE domain randomization.

This script intentionally launches Isaac Sim before importing the command module.
That keeps Omniverse runtime imports aligned with IsaacLab extension guidance.
"""

from __future__ import annotations

import argparse
import json
import sys


def _launch_isaac(headless: bool):
    try:
        from isaaclab.app import AppLauncher

        launcher = AppLauncher(headless=headless)
        return launcher.app
    except Exception:
        from isaacsim import SimulationApp

        return SimulationApp({"headless": headless})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run FORGE domain randomization for one request.")
    parser.add_argument("--request", required=True, help="Path to domain_randomization_request.json")
    parser.add_argument("--headless", action="store_true", default=True, help="Run Isaac Sim headless")
    args = parser.parse_args(argv)

    simulation_app = _launch_isaac(args.headless)
    try:
        from forge_domain_randomization.commands import run_domain_randomization
        from forge_domain_randomization.reports import read_json

        result = run_domain_randomization(read_json(args.request))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("success") else 1
    finally:
        simulation_app.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
