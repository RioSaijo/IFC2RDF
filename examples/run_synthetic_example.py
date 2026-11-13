from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from app.pipeline import run_pipeline
from bms_points import run_points_stage
from create_synthetic_inputs import create_synthetic_inputs
from match import run_match_stage

RESOURCES = PROJECT_ROOT / "data" / "resources"
BASE_NS = "https://example.org/synthetic-building#"


def main() -> None:
    generated = Path(__file__).resolve().parent / "generated"
    inputs = create_synthetic_inputs(generated / "input")
    output = generated / "output"
    ifc = run_pipeline(
        mep_ifc_paths=inputs["mep_ifc"],
        arc_ifc_paths=inputs["arc_ifc"],
        mapping_csv_path=RESOURCES / "BDNS mapping partial.csv",
        output_dir=output / "1_ifc",
        base_ns=BASE_NS,
    )
    points = run_points_stage(inputs["points_csv"], RESOURCES / "brick_classes.json", output / "2_points", BASE_NS)
    match = run_match_stage(output / "1_ifc" / "building_brick.ttl", output / "2_points" / "points_brick.ttl",
                            output / "3_match", BASE_NS)
    print(json.dumps({"1_ifc": ifc, "2_points": points, "3_match": match}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
