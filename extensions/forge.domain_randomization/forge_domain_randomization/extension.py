"""Omniverse extension lifecycle wrapper."""

from __future__ import annotations

import gc
import asyncio
import weakref


try:  # pragma: no cover - only available inside Omniverse.
    import omni.ext
    import omni.kit.app
    import omni.ui as ui
    import omni.usd
    from isaacsim.gui.components.element_wrappers import ScrollingWindow
    from isaacsim.gui.components.menu import make_menu_item_description
    from omni.kit.menu.utils import MenuItemDescription, add_menu_items, remove_menu_items

    _BaseExtension = omni.ext.IExt
except Exception:  # pragma: no cover - lets normal Python import the module.
    class _BaseExtension:  # type: ignore[no-redef]
        pass


EXTENSION_TITLE = "FORGE Domain Randomization"


class ForgeDomainRandomizationExtension(_BaseExtension):
    """Isaac-style UI extension shell.

    Actual randomization work is exposed through `commands.run_domain_randomization()`
    so the same implementation can be reused by pipe host, standalone app, and UI.
    """

    def on_startup(self, ext_id):
        self.ext_id = ext_id
        self._window = None
        self._menu_items = []
        self._stage_event_sub = None
        self._usd_context = None
        self.ui_builder = None

        try:
            from .ui_builder import UIBuilder

            self._usd_context = omni.usd.get_context()
            self._window = ScrollingWindow(
                title=EXTENSION_TITLE,
                width=620,
                height=720,
                visible=False,
                dockPreference=ui.DockPreference.LEFT_BOTTOM,
            )
            self._window.set_visibility_changed_fn(self._on_window)

            self.ui_builder = UIBuilder()
            menu_items = [
                make_menu_item_description(
                    ext_id,
                    EXTENSION_TITLE,
                    lambda a=weakref.proxy(self): a._menu_callback(),
                )
            ]
            self._menu_items = [MenuItemDescription(name="FORGE", sub_menu=menu_items)]
            add_menu_items(self._menu_items, "Tools")
            print(f"FORGE domain randomization extension started: {ext_id}")
        except Exception as exc:  # pragma: no cover - runtime safety for Isaac startup.
            print(f"FORGE domain randomization UI startup failed: {type(exc).__name__}: {exc}")

    def on_shutdown(self):
        try:
            if self._menu_items:
                remove_menu_items(self._menu_items, "Tools")
            self._stage_event_sub = None
            self._usd_context = None
            if self.ui_builder:
                self.ui_builder.cleanup()
            self.ui_builder = None
            self._window = None
        finally:
            gc.collect()
        print("FORGE domain randomization extension stopped")

    def _menu_callback(self):
        if self._window:
            self._window.visible = not self._window.visible
        if self.ui_builder:
            self.ui_builder.on_menu_callback()

    def _on_window(self, visible):
        if not self._window or not self.ui_builder:
            return
        if self._window.visible:
            self._usd_context = omni.usd.get_context()
            events = self._usd_context.get_stage_event_stream()
            self._stage_event_sub = events.create_subscription_to_pop(self._on_stage_event)
            self._build_ui()
        else:
            self._stage_event_sub = None
            self._usd_context = None
            self.ui_builder.cleanup()

    def _on_stage_event(self, event):
        if self.ui_builder:
            self.ui_builder.on_stage_event(event)

    def _build_ui(self):
        if not self._window or not self.ui_builder:
            return
        with self._window.frame:
            with ui.VStack(spacing=5, height=0):
                self.ui_builder.build_ui()

        async def dock_window():
            await omni.kit.app.get_app().next_update_async()
            target = ui.Workspace.get_window("Viewport")
            window = ui.Workspace.get_window(EXTENSION_TITLE)
            if target and window:
                window.dock_in(target, ui.DockPosition.LEFT, 0.33)

        self._task = asyncio.ensure_future(dock_window())
