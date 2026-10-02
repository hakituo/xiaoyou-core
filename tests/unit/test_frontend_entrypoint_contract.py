from fastapi import FastAPI

from config.settings_server import ServerSettings
from core.utils import static_files


def _route_names(app: FastAPI) -> set[str]:
    return {str(getattr(route, "name", "")) for route in app.routes}


def test_server_defaults_keep_frontend_separate() -> None:
    settings = ServerSettings()

    assert settings.port == 8000
    assert settings.serve_frontend is False
    assert "localhost:3000" in settings.allowed_origins
    assert "5173" not in settings.allowed_origins


def test_split_mode_does_not_mount_frontend_catch_all() -> None:
    app = FastAPI()

    static_files.mount_static_files(app, serve_frontend=False)

    names = _route_names(app)
    assert "backend_static" in names
    assert "output_static" in names
    assert "backend_root" in names
    assert "frontend" not in names


def test_single_port_mode_mounts_frontend_when_explicitly_enabled(
    tmp_path, monkeypatch
) -> None:
    frontend_dir = tmp_path / "dist"
    frontend_dir.mkdir()
    (frontend_dir / "index.html").write_text("<html>ok</html>", encoding="utf-8")

    monkeypatch.setattr(
        static_files,
        "_resolve_dev_frontend_dir",
        lambda _project_root: str(frontend_dir),
    )

    app = FastAPI()
    static_files.mount_static_files(app, serve_frontend=True)

    names = _route_names(app)
    assert "frontend" in names
    assert "read_root" in names
    assert "backend_root" not in names
