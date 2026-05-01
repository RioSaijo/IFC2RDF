from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# ---------- Stage 0: IFC bundle ----------

@dataclass(frozen=True)
class IfcBundle:
    """
    IFC 取り込み後に、下流モジュールへ渡す最小限の IFC 情報。
    - schema: "IFC2X3", "IFC4" など
    - source_path: 元 IFC ファイルパス
    - model: ifcopenshell.model など、実体（ライブラリ非依存とするなら Any）
    """
    schema: str
    source_path: str
    model: Any  # 具体型（ifcopenshell.file など）は ingestor 内部でのみ知っていればOK

# ---------- Stage 1: BDNS tagged assets ----------


@dataclass(frozen=True)
class BdnsTaggedAsset:
    """
    IFC 内で BDNS タグが付与された 1 つの設備を表す最小単位。
    """
    ifc_guid: str                  # IFC の GUID
    name: Optional[str]            # 設備名（あれば）
    bdns_tag: str                  # 抽出した BDNS タグ（例: "AHU", "FCU" 等）
    raw_ifc_class: Optional[str]   # Ifc配管要素などのクラス名（任意）


@dataclass(frozen=True)
class BdnsTaggedAssets:
    """
    BDNS タグ付き設備の集合。
    """
    items: List[BdnsTaggedAsset]


# ---------- Stage 2: Brick equipment ----------

@dataclass(frozen=True)
class BrickEquipment:
    """
    BDNS タグから Brick クラスにマッピングされた 1 つの設備。
    """
    ifc_guid: str                  # 対応する IFC 要素 GUID
    brick_class: str               # 例: "brick:Air_Handler_Unit"
    label: Optional[str]           # ヒューマンリーダブルなラベル
    bdns_tag: Optional[str]        # 元になった BDNS タグ（デバッグ用にも有用）
    extra_props: Dict[str, Any]    # 必要に応じて拡張用（任意のメタ情報）


@dataclass(frozen=True)
class BrickEquipmentSet:
    """
    Brick 設備の集合。
    """
    items: List[BrickEquipment]



# ---------- Stage 3: Points table (CSV) ----------

@dataclass(frozen=True)
class PointRow:
    """
    CSV 1行分を表す最小限のポイント情報。
    想定例:
    - point_name: "AHU-01-SA-T"
    - equipment_ref: "AHU-01"（設備識別子）
    - kind: "sensor" / "setpoint" など
    - unit: "degC", "kW", ...
    - raw: 元の行全体を dict として保持（列仕様の揺れに対応）
    """
    point_name: str
    equipment_ref: Optional[str]
    kind: Optional[str]
    unit: Optional[str]
    raw: Dict[str, Any]


@dataclass(frozen=True)
class PointTable:
    """
    CSV から読み込んだポイント一覧。
    """
    rows: List[PointRow]



# ---------- Stage 4: Brick points & linking ----------

@dataclass(frozen=True)
class BrickPoint:
    """
    Brick のポイント個別表現。
    """
    brick_point_iri: str           # 例: "http://example.com/brick#AHU_01_SA_T"
    point_name: str
    linked_equipment_guid: Optional[str]  # brick:hasPoint でつながる設備の IFC GUID
    kind: Optional[str]
    unit: Optional[str]
    extra_props: Dict[str, Any]


@dataclass(frozen=True)
class BrickPointsSet:
    """
    Brick 化されたポイント集合。
    """
    items: List[BrickPoint]



 #---------- Stage 5: Brick graph (RDF) ----------

@dataclass(frozen=True)
class BrickGraph:
    """
    rdflib.Graph などをラップした RDF グラフ。
    実際の型は rdf_writer / topology_reasoner 内でのみ知っていればよいので Any とする。
    """
    graph_obj: Any  # 実態: rdflib.Graph を想定

