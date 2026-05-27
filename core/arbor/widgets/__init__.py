"""
Widget registry.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from .alarms import AlarmsWidget
from .base import Widget
from .calendar import CalendarWidget
from .chromebox import ChromeboxWidget
from .notes import NotesWidget
from .reminders import ReminderWidget

logger = logging.getLogger("nervus.widgets")

_BUILTIN_WIDGETS: list[type[Widget]] = [
    ReminderWidget,
    CalendarWidget,
    NotesWidget,
    AlarmsWidget,
    ChromeboxWidget,
]


class WidgetRegistry:
    """Manage widget lifecycle, routing, and AI dispatch."""

    def __init__(self) -> None:
        self._widgets: dict[str, Widget] = {}

    def init_all(self) -> None:
        for cls in _BUILTIN_WIDGETS:
            widget = cls()
            widget.init_db()
            self._widgets[widget.id] = widget
            logger.info("Widget loaded: %s (%s %s)", widget.id, widget.icon, widget.name)

    def mount_all(self, app: FastAPI) -> None:
        for widget in self._widgets.values():
            app.include_router(widget.router)
            logger.info("Widget route mounted: %s", widget.id)

    def get(self, widget_id: str) -> Widget | None:
        return self._widgets.get(widget_id)

    def list(self) -> list[dict]:
        return [
            {"id": widget.id, "name": widget.name, "icon": widget.icon, "state": widget.get_state()}
            for widget in self._widgets.values()
        ]

    def dispatch_read(self, widget_id: str, intent: str, params: dict) -> dict:
        widget = self.get(widget_id)
        if not widget:
            return {"error": f"widget '{widget_id}' not found"}
        return widget.handle_read(intent, params)

    def dispatch_write(self, widget_id: str, intent: str, params: dict) -> dict:
        widget = self.get(widget_id)
        if not widget:
            return {"error": f"widget '{widget_id}' not found"}
        confirm = widget.prepare_write(intent, params)
        return {"type": "confirm", "data": confirm}

    def dispatch_execute(self, widget_id: str, intent: str, params: dict) -> dict:
        widget = self.get(widget_id)
        if not widget:
            return {"error": f"widget '{widget_id}' not found"}
        return widget.execute_write(intent, params)
