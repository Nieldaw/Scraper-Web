import importlib.util
import zipfile
from pathlib import Path

import yaml

_spec = importlib.util.spec_from_file_location(
    "build_package", Path(__file__).resolve().parents[1] / "scripts" / "build_package.py"
)
build_package = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_package)

ROOT = build_package.ROOT


def test_compose_app_is_valid_and_not_exposed_on_the_network():
    compose = yaml.safe_load((ROOT / "docker-compose.app.yml").read_text(encoding="utf-8"))
    assert set(compose["services"]) == {"db", "app"}
    assert compose["services"]["app"]["ports"] == ["127.0.0.1:8000:8000"]
    assert "ports" not in compose["services"]["db"]  # la base n'est pas publiée
    assert compose["services"]["app"]["depends_on"]["db"]["condition"] == "service_healthy"


def test_dockerfile_copies_everything_the_app_needs():
    text = (ROOT / "Dockerfile.app").read_text(encoding="utf-8")
    for needed in (
        "pyproject.toml",
        "alembic.ini",
        "src",
        "scripts",
        "migrations",
        "alembic upgrade head",
    ):
        assert needed in text
    for path in ("pyproject.toml", "alembic.ini", "src", "scripts", "migrations"):
        assert (ROOT / path).exists()


def test_package_contents_and_line_endings(tmp_path):
    archive = build_package.build(tmp_path / "pkg.zip")
    with zipfile.ZipFile(archive) as z:
        names = set(z.namelist())
        for needed in (
            "demarrer.bat",
            "arreter.bat",
            "start.sh",
            "docker-compose.app.yml",
            "Dockerfile.app",
            "alembic.ini",
            "migrations/env.py",
            "scripts/collect_sale_by_canton.py",
            "src/immo_ne_collector/main.py",
            "src/immo_ne_collector/web/static/tour.js",
            "src/immo_ne_collector/web/templates/base.html",
            "GUIDE_UTILISATION.md",
        ):
            assert f"immo-collector/{needed}" in names, needed
        assert not [n for n in names if "__pycache__" in n or "egg-info" in n or "seed_demo" in n]
        bat = z.read("immo-collector/demarrer.bat")
        assert b"\r\n" in bat and b"\n" not in bat.replace(b"\r\n", b"")  # CRLF partout
        assert b"\r" not in z.read("immo-collector/start.sh")


def test_windows_launcher_checks_docker_then_builds_then_opens_browser():
    bat = (ROOT / "demarrer.bat").read_text(encoding="utf-8")
    assert (
        bat.index("docker info")
        < bat.index("up -d --build")
        < bat.index('start "" http://localhost:8000')
    )
    assert "/health" in bat  # n'ouvre le navigateur qu'une fois l'application prête
    assert all(ord(c) < 128 for c in bat)  # ASCII : pas de caractères mal rendus par cmd.exe
