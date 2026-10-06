from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from app.pipeline import run_pipeline
from create_synthetic_inputs import create_synthetic_inputs


def main() -> None:
    generated = Path(__file__).resolve().parent / "generated"
    inputs = create_synthetic_inputs(generated / "input")
    result = run_pipeline(
        ifc_path=inputs["ifc"],
        points_csv=inputs["points_csv"],
        mapping_csv_path=PROJECT_ROOT / "data" / "resources" / "BDNS mapping partial.csv",
        output_dir=generated / "output",
        base_ns="https://example.org/synthetic-building#",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
