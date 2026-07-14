"""Authenticated local operations dashboard for the Ainekio gateway."""

from .server import DashboardHttpServer, start_dashboard_server

__all__ = ["DashboardHttpServer", "start_dashboard_server"]
