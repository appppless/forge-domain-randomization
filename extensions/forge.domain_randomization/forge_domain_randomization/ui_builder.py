"""Omniverse UI builder for the FORGE domain randomization extension."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import carb
import omni.ui as ui
import omni.usd
from isaacsim.gui.components.element_wrappers import (
    CheckBox,
    CollapsableFrame,
    DropDown,
    FloatField,
    IntField,
    StringField,
    TextBlock,
)
from isaacsim.gui.components.ui_utils import btn_builder, get_style

from .commands import compose_layer_stack, run_domain_randomization
from .ui_models import (
    UIFactorSelection,
    UIPrimRandomization,
    UIRunSettings,
    UITargetSelection,
    build_request_payload,
    default_output_dir,
    format_current_values,
    is_object_candidate_path,
    prim_config_from_metadata,
    prune_nested_candidates,
    summarize_result,
    summarize_targets,
)


class UIBuilder:
    """Builds and owns the FORGE DR tool panel."""

    def __init__(self):
        self._wrapped_ui_elements: list[Any] = []
        self._targets = UITargetSelection()
        self._last_result: dict[str, Any] = {}
        self._last_request: dict[str, Any] = {}
        self._target_summary: TextBlock | None = None
        self._object_dropdown: DropDown | None = None
        self._light_dropdown: DropDown | None = None
        self._camera_dropdown: DropDown | None = None
        self._custom_prim_path: StringField | None = None
        self._target_rows_frame: ui.Frame | None = None
        self._target_row_models: dict[str, dict[str, Any]] = {}
        self._expanded_value_rows: set[str] = set()
        self._result_summary: TextBlock | None = None
        self._request_preview: TextBlock | None = None

    def on_menu_callback(self):
        self._refresh_stage_fields()

    def on_stage_event(self, event):
        self._refresh_stage_fields()

    def cleanup(self):
        for elem in self._wrapped_ui_elements:
            try:
                elem.cleanup()
            except Exception:
                pass
        self._wrapped_ui_elements = []

    def build_ui(self):
        self.cleanup()
        self._models: dict[str, Any] = {}

        self._make_run_setup_frame()
        self._make_factors_frame()
        self._make_targets_frame()
        self._make_actions_frame()
        self._make_results_frame()

    def _make_run_setup_frame(self):
        current_stage = _current_stage_path()
        output_dir = default_output_dir(current_stage)

        frame = CollapsableFrame("Run Setup", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                self._models["base_scene_usd"] = StringField(
                    "Base Scene USD",
                    default_value=current_stage,
                    tooltip="Base USD scene to randomize. Defaults to the current open stage.",
                )
                self._models["scene_manifest"] = StringField(
                    "Scene Manifest",
                    default_value="",
                    tooltip="Optional scene_manifest.json path.",
                )
                self._models["output_dir"] = StringField(
                    "Output Dir",
                    default_value=output_dir,
                    tooltip="Directory where DR artifacts will be written.",
                )
                btn_builder(
                    label="Output Dir",
                    text="Browse",
                    tooltip="Select the output artifact directory.",
                    on_clicked_fn=self._browse_output_dir,
                )
                self._models["request_id"] = StringField(
                    "Request ID",
                    default_value="forge_dr_ui_request",
                    tooltip="Request identifier recorded in achieved_domain_report.json.",
                )
                self._models["variant_id"] = StringField(
                    "Variant ID",
                    default_value="forge_dr_ui_variant",
                    tooltip="Variant identifier recorded in layer and result artifacts.",
                )
                self._models["seed"] = IntField("Seed", default_value=1, tooltip="Deterministic randomization seed.")
                self._models["variants"] = IntField(
                    "Variants",
                    default_value=1,
                    tooltip="Number of deterministic variants to generate.",
                )
                self._models["writer"] = StringField(
                    "Writer",
                    default_value="pxr",
                    tooltip="Use pxr inside Isaac. Use text for offline debug.",
                )
                btn_builder(
                    label="Stage",
                    text="Refresh",
                    tooltip="Refresh the base scene field from the current open stage.",
                    on_clicked_fn=self._refresh_stage_fields,
                )

    def _make_factors_frame(self):
        frame = CollapsableFrame("Factors", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                self._models["object_material"] = CheckBox(
                    "Object Material",
                    default_value=True,
                    tooltip="Apply conservative material perturbations to discovered object prims.",
                )
                self._models["object_pose"] = CheckBox(
                    "Object Pose",
                    default_value=True,
                    tooltip="Apply small translation and yaw perturbations to discovered object prims.",
                )
                self._models["light"] = CheckBox(
                    "Lighting",
                    default_value=True,
                    tooltip="Apply intensity and color temperature perturbations to discovered lights.",
                )
                self._models["camera"] = CheckBox(
                    "Camera",
                    default_value=True,
                    tooltip="Apply pose and FOV perturbations to discovered cameras.",
                )

    def _make_targets_frame(self):
        frame = CollapsableFrame("Targets", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                btn_builder(
                    label="Stage",
                    text="Scan",
                    tooltip="Discover candidate object, light, and camera prims from the current stage.",
                    on_clicked_fn=self._scan_stage,
                )
                self._target_summary = TextBlock(
                    "Discovered Targets",
                    summarize_targets(self._targets),
                    tooltip="Scanned candidate prims and current enabled count.",
                    num_lines=5,
                    include_copy_button=True,
                )
                self._build_target_selectors()
                self._target_rows_frame = ui.Frame()
                self._target_rows_frame.set_build_fn(self._build_target_rows)
                self._target_rows_frame.rebuild()

    def _make_actions_frame(self):
        frame = CollapsableFrame("Actions", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                btn_builder(
                    label="Request",
                    text="Build",
                    tooltip="Build a request payload from the current UI state.",
                    on_clicked_fn=self._build_request,
                )
                btn_builder(
                    label="Run",
                    text="Randomize",
                    tooltip="Run domain randomization with the current UI request.",
                    on_clicked_fn=self._run_randomization,
                )
                btn_builder(
                    label="Compose",
                    text="Layer Stack",
                    tooltip="Compose the latest layer_stack.json into composed_scene.usda.",
                    on_clicked_fn=self._compose_latest,
                )
                self._request_preview = TextBlock(
                    "Request Preview",
                    "No request built yet.",
                    tooltip="JSON request generated from the UI.",
                    num_lines=8,
                    include_copy_button=True,
                )

    def _make_results_frame(self):
        frame = CollapsableFrame("Results", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                self._result_summary = TextBlock(
                    "Last Result",
                    summarize_result(self._last_result),
                    tooltip="Last run or composition result.",
                    num_lines=10,
                    include_copy_button=True,
                )

    def _refresh_stage_fields(self):
        path = _current_stage_path()
        if not path:
            return
        try:
            self._models["base_scene_usd"].set_value(path)
            current_output = self._models["output_dir"].get_value()
            if not current_output:
                self._models["output_dir"].set_value(default_output_dir(path))
        except Exception:
            pass

    def _browse_output_dir(self):
        try:
            from omni.kit.window.filepicker import FilePickerDialog
        except Exception as exc:
            carb.log_error(f"FORGE DR file picker unavailable: {exc}")
            return

        def _folder_only(item):
            return not item or getattr(item, "is_folder", False)

        def _selected(filename: str, dirname: str):
            chosen = dirname if not filename else str(Path(dirname) / filename)
            if chosen:
                self._models["output_dir"].set_value(chosen)
            dialog.hide()

        def _cancelled(filename: str, dirname: str):
            dialog.hide()

        current_dir = self._models["output_dir"].get_value() or default_output_dir(_current_stage_path())
        dialog = FilePickerDialog(
            "Select FORGE DR Output Directory",
            allow_multi_selection=False,
            apply_button_label="Select",
            current_directory=current_dir,
            click_apply_handler=_selected,
            click_cancel_handler=_cancelled,
            item_filter_fn=_folder_only,
            enable_versioning_pane=True,
        )

    def _scan_stage(self):
        try:
            stage = omni.usd.get_context().get_stage()
            self._targets = _discover_targets(stage, self._factors_from_ui())
            if self._target_summary:
                self._target_summary.set_text(summarize_targets(self._targets))
            self._refresh_target_dropdowns()
            if self._target_rows_frame:
                self._target_rows_frame.rebuild()
            carb.log_info("FORGE DR stage scan completed.")
        except Exception as exc:
            carb.log_error(f"FORGE DR stage scan failed: {exc}")
            if self._target_summary:
                self._target_summary.set_text(f"Scan failed: {type(exc).__name__}: {exc}")

    def _build_request(self) -> dict[str, Any]:
        self._sync_target_rows()
        settings = self._settings_from_ui()
        factors = self._factors_from_ui()
        self._last_request = build_request_payload(settings, self._targets, factors)
        if self._request_preview:
            self._request_preview.set_text(json.dumps(self._last_request, indent=2, sort_keys=True))
        return self._last_request

    def _run_randomization(self):
        try:
            request = self._build_request()
            stage = omni.usd.get_context().get_stage()
            if stage is not None:
                request["_stage"] = stage
            self._last_result = run_domain_randomization(request)
            if self._result_summary:
                self._result_summary.set_text(summarize_result(self._last_result))
            carb.log_info("FORGE DR randomization completed.")
        except Exception as exc:
            carb.log_error(f"FORGE DR randomization failed: {exc}")
            self._last_result = {"success": False, "message": f"{type(exc).__name__}: {exc}"}
            if self._result_summary:
                self._result_summary.set_text(summarize_result(self._last_result))

    def _compose_latest(self):
        layer_stack_path = self._last_result.get("layer_stack_path")
        if not layer_stack_path:
            self._last_result = {"success": False, "message": "No layer_stack_path available."}
            if self._result_summary:
                self._result_summary.set_text(summarize_result(self._last_result))
            return
        output_path = str(Path(layer_stack_path).with_name("composed_scene.usda"))
        self._last_result = compose_layer_stack({
            "layer_stack_path": layer_stack_path,
            "output_path": output_path,
            "verify": True,
        })
        if self._result_summary:
            self._result_summary.set_text(summarize_result(self._last_result))

    def _settings_from_ui(self) -> UIRunSettings:
        return UIRunSettings(
            base_scene_usd=self._models["base_scene_usd"].get_value(),
            scene_manifest=self._models["scene_manifest"].get_value(),
            output_dir=self._models["output_dir"].get_value(),
            request_id=self._models["request_id"].get_value(),
            variant_id=self._models["variant_id"].get_value(),
            seed=self._models["seed"].get_value(),
            variants=max(1, self._models["variants"].get_value()),
            writer=self._models["writer"].get_value() or "pxr",
        )

    def _factors_from_ui(self) -> UIFactorSelection:
        return UIFactorSelection(
            object_material=self._models["object_material"].get_value(),
            object_pose=self._models["object_pose"].get_value(),
            light=self._models["light"].get_value(),
            camera=self._models["camera"].get_value(),
        )

    def _build_target_rows(self):
        self._target_row_models = {}
        if not self._targets.prims:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                ui.Label("Use a selector above to add prims to this configuration.", word_wrap=True)
            return

        with ui.VStack(style=get_style(), spacing=5, height=0):
            btn_builder(
                label="Selected",
                text="Clear",
                tooltip="Clear all selected prim randomization rows.",
                on_clicked_fn=self._clear_selected_prims,
            )
            self._build_prim_group("Selected Objects", [p for p in self._targets.prims if p.prim_kind == "object"])
            self._build_prim_group("Selected Lights", [p for p in self._targets.prims if p.prim_kind == "light"])
            self._build_prim_group("Selected Cameras", [p for p in self._targets.prims if p.prim_kind == "camera"])

    def _build_target_selectors(self):
        frame = CollapsableFrame("Add Prim", collapsed=False)
        with frame:
            with ui.VStack(style=get_style(), spacing=5, height=0):
                self._object_dropdown = DropDown(
                    "Object Prim",
                    tooltip="Candidate object prims discovered by Scan.",
                    populate_fn=lambda: self._targets.objects,
                    keep_old_selections=True,
                )
                btn_builder(
                    label="Object",
                    text="Add",
                    tooltip="Add the selected object prim to the randomization configuration.",
                    on_clicked_fn=lambda: self._add_selected_prim("object"),
                )
                self._light_dropdown = DropDown(
                    "Light Prim",
                    tooltip="Candidate light prims discovered by Scan.",
                    populate_fn=lambda: self._targets.lights,
                    keep_old_selections=True,
                )
                btn_builder(
                    label="Light",
                    text="Add",
                    tooltip="Add the selected light prim to the randomization configuration.",
                    on_clicked_fn=lambda: self._add_selected_prim("light"),
                )
                self._camera_dropdown = DropDown(
                    "Camera Prim",
                    tooltip="Candidate camera prims discovered by Scan.",
                    populate_fn=lambda: self._targets.cameras,
                    keep_old_selections=True,
                )
                btn_builder(
                    label="Camera",
                    text="Add",
                    tooltip="Add the selected camera prim to the randomization configuration.",
                    on_clicked_fn=lambda: self._add_selected_prim("camera"),
                )
                self._custom_prim_path = StringField(
                    "Custom Prim Path",
                    default_value="",
                    tooltip="Fallback prim path when Scan does not discover the target.",
                )
                with ui.HStack(spacing=5, height=0):
                    btn_builder(
                        label="Custom Object",
                        text="Add",
                        tooltip="Add the custom prim path as an object target.",
                        on_clicked_fn=lambda: self._add_custom_prim("object"),
                    )
                    btn_builder(
                        label="Custom Light",
                        text="Add",
                        tooltip="Add the custom prim path as a light target.",
                        on_clicked_fn=lambda: self._add_custom_prim("light"),
                    )
                    btn_builder(
                        label="Custom Camera",
                        text="Add",
                        tooltip="Add the custom prim path as a camera target.",
                        on_clicked_fn=lambda: self._add_custom_prim("camera"),
                    )
        self._refresh_target_dropdowns()

    def _refresh_target_dropdowns(self):
        for dropdown in (self._object_dropdown, self._light_dropdown, self._camera_dropdown):
            if dropdown:
                dropdown.repopulate()

    def _add_selected_prim(self, prim_kind: str):
        dropdown = {
            "object": self._object_dropdown,
            "light": self._light_dropdown,
            "camera": self._camera_dropdown,
        }.get(prim_kind)
        if dropdown is None:
            return
        prim_path = dropdown.get_selection()
        if not prim_path:
            return
        existing = next((p for p in self._targets.prims if p.prim_path == prim_path), None)
        if existing is None:
            self._targets.prims.append(self._default_prim_config(prim_path, prim_kind))
        if self._target_summary:
            self._target_summary.set_text(summarize_targets(self._targets))
        if self._target_rows_frame:
            self._target_rows_frame.rebuild()

    def _add_custom_prim(self, prim_kind: str):
        if self._custom_prim_path is None:
            return
        prim_path = self._custom_prim_path.get_value().strip()
        if not prim_path:
            return
        if not prim_path.startswith("/"):
            prim_path = "/" + prim_path
        if prim_path not in self._targets.metadata:
            metadata = _scan_custom_metadata(prim_path, prim_kind)
            if metadata:
                self._targets.metadata[prim_path] = metadata
            else:
                carb.log_warn(f"FORGE DR custom prim scan found no metadata for {prim_path}; using fallback UI defaults.")
        if prim_kind == "object" and prim_path not in self._targets.objects:
            self._targets.objects.append(prim_path)
        elif prim_kind == "light" and prim_path not in self._targets.lights:
            self._targets.lights.append(prim_path)
        elif prim_kind == "camera" and prim_path not in self._targets.cameras:
            self._targets.cameras.append(prim_path)
        existing = next((p for p in self._targets.prims if p.prim_path == prim_path), None)
        if existing is None:
            self._targets.prims.append(self._default_prim_config(prim_path, prim_kind))
        else:
            existing.prim_kind = prim_kind
            existing.enabled = True
        self._refresh_target_dropdowns()
        if self._target_summary:
            self._target_summary.set_text(summarize_targets(self._targets))
        if self._target_rows_frame:
            self._target_rows_frame.rebuild()

    def _clear_selected_prims(self):
        self._targets.prims = []
        self._target_row_models = {}
        self._expanded_value_rows = set()
        if self._target_summary:
            self._target_summary.set_text(summarize_targets(self._targets))
        if self._target_rows_frame:
            self._target_rows_frame.rebuild()

    def _default_prim_config(self, prim_path: str, prim_kind: str) -> UIPrimRandomization:
        metadata = self._targets.metadata.get(prim_path, {})
        return prim_config_from_metadata(prim_path, prim_kind, self._factors_from_ui(), metadata)

    def _build_prim_group(self, title: str, prims: list[UIPrimRandomization]):
        frame = CollapsableFrame(f"{title} ({len(prims)})", collapsed=title == "Objects")
        with frame:
            with ui.VStack(style=get_style(), spacing=3, height=0):
                if not prims:
                    ui.Label("No candidates found.")
                    return
                for prim in prims:
                    self._build_prim_row(prim)

    def _build_prim_row(self, prim: UIPrimRandomization):
        models: dict[str, Any] = {}
        self._target_row_models[prim.prim_path] = models
        with ui.VStack(style=get_style(), spacing=2, height=0):
            ui.Label(prim.prim_path, tooltip=prim.prim_path, word_wrap=True)
            with ui.HStack(spacing=8, height=0):
                models["enabled"] = _checkbox_model(
                    prim.enabled,
                    lambda value, p=prim: self._on_prim_bool_changed(p, "enabled", value),
                )
                ui.Label("Enable", width=70)
                if prim.prim_kind == "object":
                    if prim.available_material:
                        models["material"] = _checkbox_model(
                            prim.material,
                            lambda value, p=prim: self._on_prim_bool_changed(p, "material", value),
                        )
                        ui.Label("Material", width=75)
                    if prim.available_pose:
                        models["pose"] = _checkbox_model(
                            prim.pose,
                            lambda value, p=prim: self._on_prim_bool_changed(p, "pose", value),
                        )
                        ui.Label("Pose", width=55)
                    if prim.available_visibility:
                        models["visibility"] = _checkbox_model(
                            prim.visibility,
                            lambda value, p=prim: self._on_prim_bool_changed(p, "visibility", value),
                        )
                        ui.Label("Visibility", width=85)
                    if prim.available_asset:
                        models["asset"] = _checkbox_model(
                            prim.asset,
                            lambda value, p=prim: self._on_prim_bool_changed(p, "asset", value),
                        )
                        ui.Label("Copy", width=55)
                    if prim.available_physics:
                        models["physics"] = _checkbox_model(
                            prim.physics,
                            lambda value, p=prim: self._on_prim_bool_changed(p, "physics", value),
                        )
                        ui.Label("Physics", width=70)
                elif prim.prim_kind == "light":
                    if prim.available_light:
                        models["light"] = _checkbox_model(
                            prim.light,
                            lambda value, p=prim: self._on_prim_bool_changed(p, "light", value),
                        )
                        ui.Label("Lighting", width=75)
                elif prim.prim_kind == "camera":
                    if prim.available_camera_pose:
                        models["camera_pose"] = _checkbox_model(
                            prim.camera_pose,
                            lambda value, p=prim: self._on_prim_bool_changed(p, "camera_pose", value),
                        )
                        ui.Label("Pose", width=55)
                    if prim.available_camera_fov:
                        models["camera_fov"] = _checkbox_model(
                            prim.camera_fov,
                            lambda value, p=prim: self._on_prim_bool_changed(p, "camera_fov", value),
                        )
                        ui.Label("FOV", width=45)
            if prim.prim_kind == "object":
                self._build_object_value_fields(prim, models)
            elif prim.prim_kind == "light":
                self._build_light_value_fields(prim, models)
            elif prim.prim_kind == "camera":
                self._build_camera_value_fields(prim, models)

    def _build_object_value_fields(self, prim: UIPrimRandomization, models: dict[str, Any]):
        frame = CollapsableFrame("Object Values", collapsed=prim.prim_path not in self._expanded_value_rows)
        with frame:
            with ui.VStack(style=get_style(), spacing=3, height=0):
                ui.Label(_format_selected_current_values(prim), word_wrap=True)
                if prim.available_material and prim.material:
                    models["material_color_jitter"] = FloatField(
                        "Color Jitter",
                        default_value=prim.material_color_jitter,
                    )
                    models["roughness_min"] = FloatField("Roughness Min", default_value=prim.roughness_min)
                    models["roughness_max"] = FloatField("Roughness Max", default_value=prim.roughness_max)
                if prim.available_pose and prim.pose:
                    ui.Label("Translation Jitter m", word_wrap=True)
                    models["translation_x_min_m"] = FloatField("X Min", default_value=prim.translation_x_min_m)
                    models["translation_x_max_m"] = FloatField("X Max", default_value=prim.translation_x_max_m)
                    models["translation_y_min_m"] = FloatField("Y Min", default_value=prim.translation_y_min_m)
                    models["translation_y_max_m"] = FloatField("Y Max", default_value=prim.translation_y_max_m)
                    models["translation_z_min_m"] = FloatField("Z Min", default_value=prim.translation_z_min_m)
                    models["translation_z_max_m"] = FloatField("Z Max", default_value=prim.translation_z_max_m)
                    ui.Label("Rotation Jitter deg", word_wrap=True)
                    models["rotation_x_min_deg"] = FloatField("Roll/X Min", default_value=prim.rotation_x_min_deg)
                    models["rotation_x_max_deg"] = FloatField("Roll/X Max", default_value=prim.rotation_x_max_deg)
                    models["rotation_y_min_deg"] = FloatField("Pitch/Y Min", default_value=prim.rotation_y_min_deg)
                    models["rotation_y_max_deg"] = FloatField("Pitch/Y Max", default_value=prim.rotation_y_max_deg)
                    models["rotation_z_min_deg"] = FloatField("Yaw/Z Min", default_value=prim.rotation_z_min_deg)
                    models["rotation_z_max_deg"] = FloatField("Yaw/Z Max", default_value=prim.rotation_z_max_deg)
                    ui.Label("Scale Jitter", word_wrap=True)
                    models["scale_x_min"] = FloatField("Scale X Min", default_value=prim.scale_x_min)
                    models["scale_x_max"] = FloatField("Scale X Max", default_value=prim.scale_x_max)
                    models["scale_y_min"] = FloatField("Scale Y Min", default_value=prim.scale_y_min)
                    models["scale_y_max"] = FloatField("Scale Y Max", default_value=prim.scale_y_max)
                    models["scale_z_min"] = FloatField("Scale Z Min", default_value=prim.scale_z_min)
                    models["scale_z_max"] = FloatField("Scale Z Max", default_value=prim.scale_z_max)
                if prim.available_visibility and prim.visibility:
                    visibility_dropdown = DropDown(
                        "Visibility Mode",
                        tooltip="Visibility override mode for this prim.",
                        populate_fn=lambda: ["visible", "hidden", "random"],
                        keep_old_selections=True,
                    )
                    visibility_dropdown.repopulate()
                    visibility_dropdown.set_selection(_normalized_visibility_mode(prim.visibility_mode))
                    models["visibility_mode"] = visibility_dropdown
                if prim.available_asset and prim.asset:
                    models["copy_count"] = IntField("Copy Count", default_value=prim.copy_count)
                    models["copy_suffix"] = StringField("Copy Suffix", default_value=prim.copy_suffix)
                    models["copy_radius_min_m"] = FloatField("Copy Radius Min m", default_value=prim.copy_radius_min_m)
                    models["copy_radius_max_m"] = FloatField("Copy Radius Max m", default_value=prim.copy_radius_max_m)
                    models["copy_max_attempts"] = IntField("Copy Max Attempts", default_value=prim.copy_max_attempts)
                    with ui.HStack(spacing=8, height=0):
                        models["copy_collision_check"] = _checkbox_model(
                            prim.copy_collision_check,
                            lambda value, p=prim: self._on_prim_bool_changed(p, "copy_collision_check", value),
                        )
                        ui.Label("Copy Collision Check", width=170)
                if prim.available_physics and prim.physics:
                    models["mass_scale_min"] = FloatField("Mass Scale Min", default_value=prim.mass_scale_min)
                    models["mass_scale_max"] = FloatField("Mass Scale Max", default_value=prim.mass_scale_max)

    def _build_light_value_fields(self, prim: UIPrimRandomization, models: dict[str, Any]):
        frame = CollapsableFrame("Light Values", collapsed=prim.prim_path not in self._expanded_value_rows)
        with frame:
            with ui.VStack(style=get_style(), spacing=3, height=0):
                ui.Label(_format_selected_current_values(prim), word_wrap=True)
                if prim.available_light and prim.light:
                    models["intensity_min"] = FloatField("Intensity Scale Min", default_value=prim.intensity_min)
                    models["intensity_max"] = FloatField("Intensity Scale Max", default_value=prim.intensity_max)
                    models["color_temperature_min"] = FloatField(
                        "Temperature Min",
                        default_value=prim.color_temperature_min,
                    )
                    models["color_temperature_max"] = FloatField(
                        "Temperature Max",
                        default_value=prim.color_temperature_max,
                    )

    def _build_camera_value_fields(self, prim: UIPrimRandomization, models: dict[str, Any]):
        frame = CollapsableFrame("Camera Values", collapsed=prim.prim_path not in self._expanded_value_rows)
        with frame:
            with ui.VStack(style=get_style(), spacing=3, height=0):
                ui.Label(_format_selected_current_values(prim), word_wrap=True)
                if prim.available_camera_pose and prim.camera_pose:
                    models["camera_pose_min_m"] = FloatField("Pose Jitter Min m", default_value=prim.camera_pose_min_m)
                    models["camera_pose_max_m"] = FloatField("Pose Jitter Max m", default_value=prim.camera_pose_max_m)
                    models["camera_yaw_pitch_min_deg"] = FloatField(
                        "Yaw/Pitch Jitter Min deg",
                        default_value=prim.camera_yaw_pitch_min_deg,
                    )
                    models["camera_yaw_pitch_max_deg"] = FloatField(
                        "Yaw/Pitch Jitter Max deg",
                        default_value=prim.camera_yaw_pitch_max_deg,
                    )
                if prim.available_camera_fov and prim.camera_fov:
                    models["camera_fov_min_deg"] = FloatField("FOV Min deg", default_value=prim.camera_fov_min_deg)
                    models["camera_fov_max_deg"] = FloatField("FOV Max deg", default_value=prim.camera_fov_max_deg)

    def _sync_target_rows(self):
        for prim in self._targets.prims:
            models = self._target_row_models.get(prim.prim_path)
            if not models:
                continue
            for name, model in models.items():
                if hasattr(prim, name):
                    if hasattr(model, "get_selection"):
                        value = model.get_selection()
                    elif hasattr(model, "get_value_as_bool"):
                        value = model.get_value_as_bool()
                    elif hasattr(model, "get_value"):
                        value = model.get_value()
                    else:
                        continue
                    setattr(prim, name, value)
        if self._target_summary:
            self._target_summary.set_text(summarize_targets(self._targets))

    def _on_prim_bool_changed(self, prim: UIPrimRandomization, name: str, value: bool):
        self._sync_target_rows()
        setattr(prim, name, bool(value))
        if self._target_summary:
            self._target_summary.set_text(summarize_targets(self._targets))
        if name != "enabled" and self._target_rows_frame:
            self._expanded_value_rows.add(prim.prim_path)
            self._target_rows_frame.rebuild()


def _format_selected_current_values(prim: UIPrimRandomization) -> str:
    values: dict[str, Any] = {}
    if prim.prim_kind == "object":
        if prim.material:
            values.update(_select_keys(prim.current_values, ("material_path", "base_color", "roughness")))
        if prim.pose:
            values.update(_select_keys(prim.current_values, ("translation", "rotation_euler_deg", "scale")))
        if prim.physics:
            values.update(_select_keys(prim.current_values, ("mass", "rigid_body_prim_path", "has_collision")))
        if prim.visibility:
            values["visibility_mode"] = prim.visibility_mode
        if prim.asset:
            values["copy_source"] = prim.prim_path
    elif prim.prim_kind == "light":
        if prim.light:
            values.update(_select_keys(prim.current_values, ("intensity", "color")))
    elif prim.prim_kind == "camera":
        if prim.camera_pose:
            values.update(_select_keys(prim.current_values, ("translation", "rotation_euler_deg")))
        if prim.camera_fov:
            values.update(_select_keys(prim.current_values, ("fov_deg", "focal_length", "horizontal_aperture")))
    if not values:
        return "Select a domain to edit its values."
    return format_current_values(values)


def _select_keys(values: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: values[key] for key in keys if key in values}


def _normalized_visibility_mode(mode: str) -> str:
    normalized = str(mode or "random").strip().lower()
    if normalized in {"visible", "show", "shown", "keep_visible", "inherited", "on", "true"}:
        return "visible"
    if normalized in {"hidden", "hide", "invisible", "off", "false"}:
        return "hidden"
    return "random"


def _current_stage_path() -> str:
    try:
        context = omni.usd.get_context()
        if hasattr(context, "get_stage_url"):
            url = context.get_stage_url()
            if url:
                return str(url)
        stage = context.get_stage()
        if stage is None:
            return ""
        layer = stage.GetRootLayer()
        return str(getattr(layer, "realPath", None) or getattr(layer, "identifier", "") or "")
    except Exception:
        return ""


def _discover_targets(stage: Any, defaults: UIFactorSelection) -> UITargetSelection:
    if stage is None:
        return UITargetSelection()
    try:
        from pxr import Usd, UsdGeom, UsdLux
    except Exception as exc:
        raise RuntimeError("pxr modules are required to discover stage targets") from exc

    objects: list[str] = []
    lights: list[str] = []
    cameras: list[str] = []
    light_type_names = {
        "DomeLight", "SphereLight", "RectLight", "DiskLight", "DistantLight", "CylinderLight",
    }
    for prim in Usd.PrimRange(stage.GetPseudoRoot()):
        if not prim or not prim.IsValid() or not prim.IsActive():
            continue
        path = str(prim.GetPath())
        if path == "/":
            continue
        type_name = str(prim.GetTypeName())
        try:
            if type_name == "Camera" or prim.IsA(UsdGeom.Camera):
                cameras.append(path)
                continue
        except Exception:
            pass
        try:
            if type_name in light_type_names or prim.IsA(UsdLux.Light):
                lights.append(path)
                continue
        except Exception:
            if type_name in light_type_names:
                lights.append(path)
                continue
        if type_name in {"Xform", "Mesh", "Cube", "Sphere", "Capsule", "Cylinder", "Cone"}:
            if is_object_candidate_path(path):
                objects.append(path)
    objects = prune_nested_candidates(objects)[:200]
    lights = prune_nested_candidates(lights)[:100]
    cameras = prune_nested_candidates(cameras)[:100]
    metadata = _scan_target_metadata(stage, objects, lights, cameras)
    return UITargetSelection(
        objects=objects,
        lights=lights,
        cameras=cameras,
        metadata=metadata,
    )


def _scan_target_metadata(
    stage: Any,
    objects: list[str],
    lights: list[str],
    cameras: list[str],
) -> dict[str, dict[str, Any]]:
    try:
        from .schemas import DomainRandomizationRequest
        from .scanner import scan_stage
    except Exception:
        return {}
    request = DomainRandomizationRequest.from_dict({
        "request_id": "forge_dr_ui_scan",
        "variant_id": "forge_dr_ui_scan",
        "base_scene_usd": _current_stage_path() or "<live_stage>",
        "output_dir": str(Path.cwd()),
        "seed": 1,
        "objects": [{"prim_path": path} for path in objects],
        "lights": [{"prim_path": path, "intensity_scale": [1.0, 1.0]} for path in lights],
        "cameras": [{"prim_path": path, "fov_deg": [1.0, 1.0]} for path in cameras],
    })
    report = scan_stage(stage, request, "ui_scan")
    metadata: dict[str, dict[str, Any]] = {}
    for item in report.prims + report.lights + report.cameras:
        path = str(item.get("prim_path") or "")
        if path:
            metadata[path] = item
    return metadata


def _scan_custom_metadata(prim_path: str, prim_kind: str) -> dict[str, Any]:
    try:
        stage = omni.usd.get_context().get_stage()
    except Exception:
        stage = None
    if stage is None:
        return {}
    objects = [prim_path] if prim_kind == "object" else []
    lights = [prim_path] if prim_kind == "light" else []
    cameras = [prim_path] if prim_kind == "camera" else []
    try:
        return _scan_target_metadata(stage, objects, lights, cameras).get(prim_path, {})
    except Exception as exc:
        carb.log_warn(f"FORGE DR custom prim metadata scan failed for {prim_path}: {exc}")
        return {}


def _checkbox_model(default_value: bool, on_changed):
    model = ui.SimpleBoolModel()
    model.set_value(bool(default_value))

    def _on_changed(changed_model):
        on_changed(changed_model.get_value_as_bool())

    ui.CheckBox(model=model)
    model.add_value_changed_fn(_on_changed)
    return model
