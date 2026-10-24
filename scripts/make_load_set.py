"""Build a 250-label batch for load testing the batch UI and worker pool.

Copies the samples expected to pass under unique names until there are 250, and writes a
matching manifest. Output goes to samples/load/, which is gitignored.

Run from the repo root:  backend/.venv/bin/python scripts/make_load_set.py
"""

import csv
import json
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SAMPLES = REPO / "samples"
LOAD = SAMPLES / "load"
COUNT = 250


def main() -> None:
    expected = json.loads((SAMPLES / "expected.json").read_text())
    with (SAMPLES / "applications.csv").open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        rows = {row["filename"]: row for row in reader}
    passing = [name for name, e in expected.items() if e["overall"] == "pass"]

    if LOAD.exists():
        shutil.rmtree(LOAD)
    LOAD.mkdir(parents=True)
    with (LOAD / "applications.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, columns, lineterminator="\n")
        writer.writeheader()
        for i in range(COUNT):
            source = passing[i % len(passing)]
            name = f"load_{i:03d}_{source}"
            shutil.copyfile(SAMPLES / "labels" / source, LOAD / name)
            writer.writerow(rows[source] | {"filename": name})
    print(f"Wrote {COUNT} labels and applications.csv to {LOAD.relative_to(REPO)}/")


if __name__ == "__main__":
    main()
