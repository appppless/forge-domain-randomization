"""Sparse USDA override layer writer for sampled randomization edits."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .sampler import LayerEdit, RandomizationPlan
from .schemas import DomainRandomizationRequest, LayerStackManifest
from .reports import write_json


def write_randomization_layers(request: DomainRandomizationRequest, plan: RandomizationPlan) -> list[str]:
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
            _write_usda(path, request, edits)
            paths.append(str(path))
    else:
        path = layer_dir / f"dr_seed_{request.seed:04d}.usda"
        _write_usda(path, request, plan.edits)
        paths.append(str(path))
    return paths


def write_layer_stack_manifest(
    request: DomainRandomizationRequest,
    layer_paths: list[str],
    composed_scene_usd: str | None = None,
) -> str:
    manifest = LayerStackManifest(
        variant_id=request.variant_id,
        base_scene_usd=request.base_scene_usd,
        sub_layers=layer_paths,
        composed_scene_usd=composed_scene_usd,
    )
    return write_json(Path(request.output_dir) / "layer_stack.json", manifest.to_dict())


def _write_usda(path: Path, request: DomainRandomizationRequest, edits: list[LayerEdit]) -> None:
    grouped: dict[str, list[LayerEdit]] = {}
    for edit in edits:
        grouped.setdefault(edit.prim_path, []).append(edit)

    lines = [
        "#usda 1.0",
        "(",
        "    customLayerData = {",
        f'        string request_id = "{_escape(request.request_id)}"',
        f'        string variant_id = "{_escape(request.variant_id)}"',
        f'        string base_scene_hash = "{_escape(request.base_scene_hash or "")}"',
        f'        string config_hash = "{_escape(request.config_hash or "")}"',
        f"        int seed = {request.seed}",
        "    }",
        ")",
        "",
    ]
    tree = _build_tree(grouped)
    _render_tree(lines, tree, indent=0)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _build_tree(grouped: dict[str, list[LayerEdit]]) -> dict[str, Any]:
    root: dict[str, Any] = {"children": {}, "edits": []}
    for prim_path, edits in grouped.items():
        parts = [part for part in prim_path.split("/") if part]
        node = root
        for part in parts:
            node = node["children"].setdefault(part, {"children": {}, "edits": []})
        node["edits"].extend(edits)
    return root


def _render_tree(lines: list[str], node: dict[str, Any], indent: int) -> None:
    for name in sorted(node["children"]):
        child = node["children"][name]
        pad = "    " * indent
        metadata_edits = [e for e in child["edits"] if _is_metadata_edit(e)]
        body_edits = [e for e in child["edits"] if not _is_metadata_edit(e)]
        lines.append(f'{pad}over "{_escape(name)}"')
        if metadata_edits:
            lines.append(f"{pad}(")
            for edit in metadata_edits:
                lines.append(f"{pad}    {_format_metadata(edit)}")
            lines.append(f"{pad})")
        lines.append(f"{pad}{{")
        for edit in body_edits:
            lines.append(f"{pad}    {_format_attribute(edit)}")
        _render_tree(lines, child, indent + 1)
        lines.append(f"{pad}}}")


def _format_attribute(edit: LayerEdit) -> str:
    value_type = edit.value_type or _infer_usd_type(edit.value)
    if value_type == "relationship":
        return f"rel {edit.attribute} = {_format_relationship_targets(edit.value)}"
    if value_type == "token[]":
        items = ", ".join(f'"{_escape(str(item))}"' for item in (edit.value or []))
        return f"uniform token[] {edit.attribute} = [{items}]"
    if value_type == "matrix4d":
        return f"matrix4d {edit.attribute} = {_format_matrix4d(edit.value)}"
    if value_type == "asset":
        return f"asset {edit.attribute} = @{_escape_asset(str(edit.value))}@"
    if value_type in {"quath", "quatf", "quatd"}:
        return f"{value_type} {edit.attribute} = {_format_quat(edit.value)}"
    return f"{value_type} {edit.attribute} = {_format_value(edit.value, value_type)}"


def _is_metadata_edit(edit: LayerEdit) -> bool:
    return (edit.value_type or "") in {"references", "payloads"}


def _format_metadata(edit: LayerEdit) -> str:
    value_type = edit.value_type or ""
    keyword = "references" if value_type == "references" else "payload"
    items = _composition_items(edit.value)
    formatted = [_format_composition_item(item) for item in items]
    if len(formatted) == 1:
        return f"{keyword} = {formatted[0]}"
    return f"{keyword} = [{', '.join(formatted)}]"


def _infer_usd_type(value: Any) -> str:
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


def _format_value(value: Any, value_type: str) -> str:
    if value_type in {"double3", "float3", "half3", "color3f"}:
        items = ", ".join(_format_scalar(float(item)) for item in value)
        return f"({items})"
    if value_type == "matrix4d":
        return _format_matrix4d(value)
    if value_type in {"quath", "quatf", "quatd"}:
        return _format_quat(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _format_scalar(value)
    return f'"{_escape(str(value))}"'


def _format_matrix4d(value: Any) -> str:
    flat = [float(v) for v in (value or [])]
    if len(flat) != 16:
        flat = [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ]
    rows = []
    for r in range(4):
        items = ", ".join(_format_scalar(flat[r * 4 + c]) for c in range(4))
        rows.append(f"({items})")
    return "( " + ", ".join(rows) + " )"


def _format_quat(value: Any) -> str:
    if isinstance(value, (list, tuple)) and len(value) == 4:
        x, y, z, w = (float(value[0]), float(value[1]), float(value[2]), float(value[3]))
    else:
        x, y, z, w = 0.0, 0.0, 0.0, 1.0
    return "(" + ", ".join(_format_scalar(item) for item in (w, x, y, z)) + ")"


def _format_relationship_targets(value: Any) -> str:
    if isinstance(value, str):
        return f"<{value}>"
    targets = [str(item) for item in (value or [])]
    if len(targets) == 1:
        return f"<{targets[0]}>"
    return "[" + ", ".join(f"<{target}>" for target in targets) + "]"


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


def _format_composition_item(item: dict[str, str]) -> str:
    asset = str(item.get("asset_path") or "")
    prim = str(item.get("prim_path") or "")
    out = f"@{_escape_asset(asset)}@"
    if prim:
        out += f"<{prim}>"
    return out


def _format_scalar(value: int | float) -> str:
    if isinstance(value, int):
        return str(value)
    return f"{value:.8g}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _escape_asset(value: str) -> str:
    return value.replace("\\", "\\\\").replace("@", "@@")
