from __future__ import annotations

#環境非依存処理
from ifc_ingestor.ingestor import load_ifc_bundle
from bdns_extractor.extractor import extract_bdns_tags


from typing import Dict, Any
from app.contracts import BrickGraph
from ifc_ingestor.ingestor import load_ifc_bundle
from bdns_extractor.extractor import extract_bdns_tags
from class_mapper.mapper import map_bdns_to_brick_equipment
from points_csv_ingestor.loader import load_points_csv
from points_linker.linker import link_points_to_equipment
from topology_reasoner.reasoner import build_graph
from rdf_writer.writer import write_turtle

def run_pipeline(
    ifc_path: str,


    
    points_csv: str,
    base_ns: str,
    out_ttl: str,
    csvw_metadata_path: str | None = None,
    crosswalk_equip: dict | None = None,
    crosswalk_points: dict | None = None,
) -> Dict[str, Any]:
    crosswalk_equip = crosswalk_equip or {}
    crosswalk_points = crosswalk_points or {}

# Path to the input IFC file.
    bundle = load_ifc_bundle(str(ifc_path))

    print("\n=== IFC Loaded ===")
    print("schema:", bundle.schema)
    print("model type:", type(bundle.model))

# --- BDNS タグ抽出 ---
    bdns_assets = extract_bdns_tags(bundle)
    print("\n=== BDNS Extraction Result ===")
    print("BDNS-tagged assets:", len(bdns_assets.items))

# 最初の数件を表示
for asset in bdns_assets.items[:10]:
    print(
        "GUID:", asset.ifc_guid,
        "| BDNS:", asset.bdns_tag,
        "| Name:", asset.name,
        "| Class:", asset.raw_ifc_class
    )
#ここで実装中断
