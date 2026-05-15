from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent.parent
DOCS_DATA = ROOT / "docs" / "data"

SOURCES = [
    (ROOT / "data" / "dat_damage_lines.geojson", DOCS_DATA / "dat_damage_lines.geojson"),
    (ROOT / "output" / "tornado_crossing_times.csv", DOCS_DATA / "tornado_crossing_times.csv"),
]


def main():
    DOCS_DATA.mkdir(parents=True, exist_ok=True)

    for src, dst in SOURCES:
        if not src.exists():
            raise FileNotFoundError(f"Missing required file: {src}")
        if src.stat().st_size == 0:
            raise ValueError(f"File is empty: {src}")
        shutil.copyfile(src, dst)
        print(f"Copied {src} to {dst}")


if __name__ == "__main__":
    main()
