"""pxr-backed USD override layer writer for sampled randomization edits.

This writer is intended for Isaac / USD-capable runtimes. It keeps the same
LayerEdit contract as the offline text writer, but authors values through USD
APIs so typed values such as matrices, token arrays, and future quaternion /
relationship edits can be handled without hand-formatting USDA.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .sampler import LayerEdit, RandomizationPlan
from .schemas import DomainRandomizationRequest


class PxrLayerWriterUnavailable(RuntimeError):
    """Raised when the pxr-backed writer is requested outside a USD runtime."""


def write_randomization_layers_pxr(
    request: DomainRandomizationRequest,
    plan: RandomizationPlan,
) -> list[str]:
    layer_dir = Path(request.output_dir) / "randomization_layers"
    layer_dir.mkdir(parents=True, exist_ok=True)

    mode = request.layer_policy.get("mode", "single")
    grouped = plan.by_domain()
    paths: list[str] = []
    if mode == "separate_by_domain":
        for domain in ("asset", "placement", "simulator"):
            edits = grouped.get(domain) or []
            if not edits:
                continue
            path = layer_dir / f"dr_seed_{request.seed:04d}_{domain}.usda"
            _write_usd_layer(path, request, edits)
            paths.append(str(path))
    else:
        path = layer_dir / f"dr_seed_{request.seed:04d}.usda"
        _write_usd_layer(path, request, plan.edits)
        paths.append(str(path))
    return paths


def _write_usd_layer(
    path: Path,
    request: DomainRandomizationRequest,
    edits: list[LayerEdit],
) -> None:
    try:
        from pxr import Gf, Sdf, Usd, Vt
    except Exception as exc:
        raise PxrLayerWriterUnavailable("pxr modules are required for the pxr layer writer") from exc

    if path.exists():
        path.unlink()
    layer = Sdf.Layer.CreateNew(str(path))
    layer.customLayerData = {
        "request_id": request.request_id,
        "variant_id": request.variant_id,
        "base_scene_hash": request.base_scene_hash or "",
        "config_hash": request.config_hash or "",
        "seed": request.seed,
        "writer": "pxr",
    }
    stage = Usd.Stage.Open(layer)
    if stage is None:
        raise RuntimeError(f"failed to open newly created USD layer: {path}")
    stage.SetEditTarget(layer)

    for edit in edits:
        prim = stage.OverridePrim(str(edit.prim_path))
        if _apply_composition_edit(prim, edit, Sdf):
            continue
        value_type = _sdf_value_type(edit.value_type, edit.value, Sdf)
        attr = prim.CreateAttribute(str(edit.attribute), value_type, custom=False)
        attr.Set(_usd_value(edit.value, edit.value_type, Gf, Sdf, Vt))

    layer.Save()


def _apply_composition_edit(prim: Any, edit: LayerEdit, Sdf: Any) -> bool:
    value_type = edit.value_type or ""
    if value_type == "relationship":
        rel = prim.CreateRelationship(str(edit.attribute), custom=False)
        rel.SetTargets([Sdf.Path(str(target)) for target in _relationship_targets(edit.value)])
        return True
    if value_type == "references":
        refs = [_sdf_reference(item, Sdf) for item in _composition_items(edit.value)]
        op = _composition_op(edit.value)
        if op == "add":
            for ref in refs:
                prim.GetReferences().AddReference(ref)
        else:
            prim.GetReferences().SetReferences(refs)
        return True
    if value_type == "payloads":
        payloads = [_sdf_payload(item, Sdf) for item in _composition_items(edit.value)]
        op = _composition_op(edit.value)
        if op == "add":
            for payload in payloads:
                prim.GetPayloads().AddPayload(payload)
        else:
            prim.GetPayloads().SetPayloads(payloads)
        return True
    return False


def _sdf_value_type(value_type: str | None, value: Any, Sdf: Any) -> Any:
    vt = value_type or _infer_value_type(value)
    mapping = {
        "bool": Sdf.ValueTypeNames.Bool,
        "int": Sdf.ValueTypeNames.Int,
        "float": Sdf.ValueTypeNames.Float,
        "double": Sdf.ValueTypeNames.Double,
        "half": Sdf.ValueTypeNames.Half,
        "float3": Sdf.ValueTypeNames.Float3,
        "double3": Sdf.ValueTypeNames.Double3,
        "half3": Sdf.ValueTypeNames.Half3,
        "color3f": Sdf.ValueTypeNames.Color3f,
        "quath": Sdf.ValueTypeNames.Quath,
        "quatf": Sdf.ValueTypeNames.Quatf,
        "quatd": Sdf.ValueTypeNames.Quatd,
        "matrix4d": Sdf.ValueTypeNames.Matrix4d,
        "asset": Sdf.ValueTypeNames.Asset,
        "token": Sdf.ValueTypeNames.Token,
        "token[]": Sdf.ValueTypeNames.TokenArray,
        "string": Sdf.ValueTypeNames.String,
    }
    return mapping.get(vt, Sdf.ValueTypeNames.String)


def _usd_value(value: Any, value_type: str | None, Gf: Any, Sdf: Any, Vt: Any) -> Any:
    vt = value_type or _infer_value_type(value)
    if vt in {"float3", "color3f"}:
        return Gf.Vec3f(*_vec3(value))
    if vt == "half3":
        return Gf.Vec3h(*_vec3(value))
    if vt == "double3":
        return Gf.Vec3d(*_vec3(value))
    if vt == "matrix4d":
        flat = [float(v) for v in (value or [])]
        if len(flat) != 16:
            flat = [
                1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                0.0, 0.0, 0.0, 1.0,
            ]
        return Gf.Matrix4d(*flat)
    if vt in {"quath", "quatf", "quatd"}:
        x, y, z, w = _quat_xyzw(value)
        if vt == "quath":
            return Gf.Quath(w, Gf.Vec3h(x, y, z))
        if vt == "quatf":
            return Gf.Quatf(w, Gf.Vec3f(x, y, z))
        return Gf.Quatd(w, Gf.Vec3d(x, y, z))
    if vt == "token[]":
        return Vt.TokenArray([str(item) for item in (value or [])])
    if vt == "asset":
        return Sdf.AssetPath(str(value))
    if vt == "token":
        return str(value)
    if vt == "bool":
        return bool(value)
    if vt == "int":
        return int(value)
    if vt in {"float", "double", "half"}:
        return float(value)
    return str(value)


def _infer_value_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "double"
    if isinstance(value, (list, tuple)) and len(value) == 16:
        return "matrix4d"
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return "double3"
    if isinstance(value, str):
        return "string"
    return "string"


def _quat_xyzw(value: Any) -> tuple[float, float, float, float]:
    if isinstance(value, (list, tuple)) and len(value) == 4:
        return float(value[0]), float(value[1]), float(value[2]), float(value[3])
    return 0.0, 0.0, 0.0, 1.0


def _composition_op(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("op") or "set").lower()
    return "set"


def _composition_items(value: Any) -> list[dict[str, str]]:
    raw = value.get("items") if isinstance(value, dict) else value
    if not isinstance(raw, list):
        raw = [raw]
    out: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, str):
            out.append({"asset_path": item})
        elif isinstance(item, dict):
            out.append({
                "asset_path": str(item.get("asset_path") or item.get("asset") or item.get("path") or ""),
                "prim_path": str(item.get("prim_path") or item.get("target_prim") or ""),
            })
    return out


def _sdf_reference(item: dict[str, str], Sdf: Any) -> Any:
    asset_path = str(item.get("asset_path") or "")
    prim_path = str(item.get("prim_path") or "")
    if prim_path:
        return Sdf.Reference(asset_path, prim_path)
    return Sdf.Reference(asset_path)


def _sdf_payload(item: dict[str, str], Sdf: Any) -> Any:
    asset_path = str(item.get("asset_path") or "")
    prim_path = str(item.get("prim_path") or "")
    if prim_path:
        return Sdf.Payload(asset_path, prim_path)
    return Sdf.Payload(asset_path)


def _relationship_targets(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _vec3(value: Any) -> tuple[float, float, float]:
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return float(value[0]), float(value[1]), float(value[2])
    return 0.0, 0.0, 0.0
