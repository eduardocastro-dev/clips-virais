"""Smoke test: import every registered API route before deploying the runtime image."""
from backend.api import app


def test_api_startup_has_health_and_live_clip_routes():
    routes = [(getattr(route, "path", ""), set(getattr(route, "methods", set()) or ()))
              for route in app.routes]
    assert ("/health", {"GET"}) in routes
    assert any(path == "/api/live-clips/{id}/decision" and "POST" in methods
               for path, methods in routes)
    assert sum(path == "/api/live-clips/{id}/file" for path, methods in routes) == 1
    assert sum(path == "/api/live-clips/{id}/metadata" for path, methods in routes) == 1
    assert any(path == "/api/operations/live" and "GET" in methods for path, methods in routes)
    assert any(path == "/api/live-clips/from-url" and "POST" in methods
               for path, methods in routes)

