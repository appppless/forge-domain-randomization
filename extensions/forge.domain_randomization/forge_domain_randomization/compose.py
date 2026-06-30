"""Composition utility for v0.2 domain randomization.

Reads a `layer_stack.json` manifest and writes a *stub* USDA whose only
content is a `subLayers` list pointing at:

    [randomization layers..., base_scene_usd]

USD LIVRPS composition rule: in a sublayer stack, the **first entry is the
strongest**, and the root layer of any opened stage is strictly stronger
than its own sublayers.  Our stub is empty, so the strongest opinion is
always the first DR layer, while the base scene provides the underlying
def/reference structure.

This module is intentionally not invoked by `run_domain_randomization` —
composing the stage is a *host* policy decision, not part of producing
randomization artifacts.  The function is exposed both as a Python API and
as a pipe command (`domain_randomization_compose`) so an Isaac runtime
host, a FORGE planner, or a user can opt into it.

The stub is plain text and does not require pxr at write time.  The
optional `verify=True` flag will try to import pxr and open the resulting
stub to catch missing sublayer files; if pxr is unavailable we fall back
to filesystem existence checks.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ComposeResult:
    composed_scene_usd: str
    sub_layers: list[str]
    base_scene_usd: str
    issues: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "composed_scene_usd": self.composed_scene_usd,
            "sub_layers": list(self.sub_layers),
            "base_scene_usd": self.base_scene_usd,
            "issues": list(self.issues),
        }


def compose_stage_from_manifest(
    layer_stack_path: str | os.PathLike,
    output_path: str | os.PathLike | None = None,
    *,
    verify: bool = True,
) -> ComposeResult:
    """Read a layer_stack.json manifest and write a composed scene stub.

    Parameters
    ----------
    layer_stack_path:
        Path to a `layer_stack.json` produced by `run_domain_randomization`.
    output_path:
        Where to write the composed stub.  Defaults to
        `<manifest_dir>/composed_scene.usda`.
    verify:
        If True, check that every referenced layer exists on the filesystem
        and (if pxr is importable) open the resulting stage to confirm it
        composes without raising.  Issues are returned, not raised.
    """
    manifest_path = Path(layer_stack_path).resolve()
    if not manifest_path.exists():
        raise FileNotFoundError(f"layer stack manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    return compose_stage(
        base_scene_usd=str(manifest["base_scene_usd"]),
        sub_layers=list(manifest.get("sub_layers") or []),
        output_path=output_path or (manifest_path.parent / "composed_scene.usda"),
        variant_id=str(manifest.get("variant_id", "")),
        verify=verify,
    )


def compose_stage(
    *,
    base_scene_usd: str,
    sub_layers: list[str],
    output_path: str | os.PathLike,
    variant_id: str = "",
    verify: bool = True,
) -> ComposeResult:
    """Write a stub USDA composing `sub_layers` on top of `base_scene_usd`.

    The stub itself contains no prim opinions.  Layer strength order:

        stub root                 (empty, so contributes nothing)
        > sub_layers[0]           (strongest DR override)
        > sub_layers[1]
        > ...
        > base_scene_usd          (weakest; provides the actual scene)
    """
    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    base_abs = Path(base_scene_usd).resolve()
    sublayer_abs = [str(Path(p).resolve()) for p in sub_layers]
    # Sublayers go strongest-first; append base last.
    full_sublayers = [*sublayer_abs, str(base_abs)]

    text = _render_stub(full_sublayers, variant_id=variant_id, base_scene_usd=str(base_abs))
    out.write_text(text, encoding="utf-8")

    issues: list[dict[str, Any]] = []
    if verify:
        issues.extend(_verify_paths_exist(full_sublayers))
        issues.extend(_verify_pxr_compose(out))

    return ComposeResult(
        composed_scene_usd=str(out),
        sub_layers=full_sublayers,
        base_scene_usd=str(base_abs),
        issues=issues,
    )


def _render_stub(sublayer_paths: list[str], *, variant_id: str, base_scene_usd: str) -> str:
    sublayer_block = ",\n".join(
        f"        @{_escape(p)}@" for p in sublayer_paths
    )
    return (
        "#usda 1.0\n"
        "(\n"
        "    customLayerData = {\n"
        f'        string forge_compose_variant_id = "{_escape(variant_id)}"\n'
        f'        string forge_compose_base_scene = "{_escape(base_scene_usd)}"\n'
        '        string forge_compose_role = "composition_stub"\n'
        "    }\n"
        "    subLayers = [\n"
        f"{sublayer_block}\n"
        "    ]\n"
        ")\n"
    )


def _verify_paths_exist(paths: list[str]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for p in paths:
        if not Path(p).exists():
            issues.append({
                "type": "missing_sublayer",
                "severity": "error",
                "path": p,
                "message": f"sublayer path does not exist: {p}",
            })
    return issues


def _verify_pxr_compose(stub_path: Path) -> list[dict[str, Any]]:
    try:
        from pxr import Usd
    except Exception:
        return [{
            "type": "pxr_unavailable",
            "severity": "info",
            "message": "pxr not importable; skipped USD composition check",
        }]
    issues: list[dict[str, Any]] = []
    try:
        stage = Usd.Stage.Open(str(stub_path))
        if stage is None:
            issues.append({
                "type": "stage_open_failed",
                "severity": "error",
                "message": f"Usd.Stage.Open returned None for {stub_path}",
            })
            return issues
        # Report any sublayer that failed to load.
        for sublayer in stage.GetLayerStack(includeSessionLayers=False):
            try:
                if sublayer is None:
                    continue
                if not sublayer.realPath:
                    issues.append({
                        "type": "sublayer_unresolved",
                        "severity": "warning",
                        "message": f"sublayer has no realPath: {sublayer.identifier}",
                    })
            except Exception:
                continue
    except Exception as exc:
        issues.append({
            "type": "compose_exception",
            "severity": "error",
            "message": f"{type(exc).__name__}: {exc}",
        })
    return issues


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
