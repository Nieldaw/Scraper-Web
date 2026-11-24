"""Fabrique `dist/immo-collector.zip` : le dossier à envoyer à un utilisateur non développeur.

Le ZIP ne contient que ce qui sert à lancer l'application avec Docker (pas de tests, de docs
internes, de données ni d'outils de développement). Les scripts Windows sont écrits en CRLF.

    python scripts/build_package.py            # -> dist/immo-collector.zip
"""

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP = "immo-collector"

FILES = [
    "Dockerfile.app",
    "docker-compose.app.yml",
    ".dockerignore",
    "pyproject.toml",
    "alembic.ini",
    "demarrer.bat",
    "arreter.bat",
    "start.sh",
    "stop.sh",
    "LISEZMOI.txt",
    "GUIDE_UTILISATION.md",
]
DIRS = ["src", "scripts", "migrations"]
EXCLUDE_NAMES = {"__pycache__", "seed_demo.py", "build_package.py"}
EXCLUDE_SUFFIXES = (".pyc", ".pyo")
EXECUTABLE = {"start.sh", "stop.sh"}
CRLF = (".bat",)


def _skip(path: Path) -> bool:
    return (
        any(part in EXCLUDE_NAMES or part.endswith(".egg-info") for part in path.parts)
        or path.suffix in EXCLUDE_SUFFIXES
    )


def collect_files() -> list[Path]:
    found: list[Path] = []
    for name in FILES:
        path = ROOT / name
        if not path.is_file():
            raise FileNotFoundError(f"Fichier manquant pour le paquet : {name}")
        found.append(path)
    for directory in DIRS:
        for path in sorted((ROOT / directory).rglob("*")):
            if path.is_file() and not _skip(path.relative_to(ROOT)):
                found.append(path)
    return found


def _payload(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix in CRLF:  # cmd.exe est fragile avec des fins de ligne LF (étiquettes goto)
        data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    return data


def build(output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in collect_files():
            relative = path.relative_to(ROOT)
            info = zipfile.ZipInfo(f"{TOP}/{relative.as_posix()}", date_time=(2026, 1, 1, 0, 0, 0))
            mode = 0o755 if relative.name in EXECUTABLE else 0o644
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, _payload(path))
        # Dossier de données vide (exports CSV, cache, journaux), monté par Docker.
        for sub in ("data/exports", "data/cache/html", "data/logs"):
            archive.writestr(f"{TOP}/{sub}/.gitkeep", b"")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / f"{TOP}.zip")
    args = parser.parse_args()
    target = build(args.output)
    print(f"{target} ({target.stat().st_size / 1024:.0f} Ko)")
