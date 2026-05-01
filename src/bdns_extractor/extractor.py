from __future__ import annotations
from typing import List, Optional, Dict
from dataclasses import dataclass
from app.contracts import IfcBundle, BdnsTaggedAsset, BdnsTaggedAssets

@dataclass
class SpatialElement:
    ifc_guid: str
    name: Optional[str]
    raw_ifc_class: str                  # "IfcSite" | "IfcBuilding" | "IfcBuildingStorey" | "IfcSpace"
    composition_type: Optional[str]     # IfcElementCompositionEnum 相当
    elevation: Optional[float]          # Storey 基準高さがあれば保持
    parent_guid: Optional[str]          # IfcRelAggregates での親の GUID
    path: str   

@dataclass
class SpatialElements:
    items: List[SpatialElement]

# ==================================
# 既存: BDNS 抽出の実装は変更なし
# ==================================

def extract_bdns_tags(bundle: IfcBundle) -> BdnsTaggedAssets:
    model = getattr(bundle, "model", None)
    if model is None:
        raise ValueError("IfcBundle.model is None; ifc_ingestor で IFC モデルをセットしてください.")
    bdns_class = _find_bdns_classification(model)
    if bdns_class is None:
        return BdnsTaggedAssets(items=[])
    ref_to_code = _collect_bdns_references(model, bdns_class)
    if not ref_to_code:
        return BdnsTaggedAssets(items=[])
    assets: List[BdnsTaggedAsset] = []
    for rel in model.by_type("IfcRelAssociatesClassification"):
        ref = getattr(rel, "RelatingClassification", None)
        if ref is None:
            continue
        bdns_code = ref_to_code.get(ref)
        if not bdns_code:
            continue
        related_objs = getattr(rel, "RelatedObjects", []) or []
        for obj in related_objs:
            guid = getattr(obj, "GlobalId", None)
            if guid is None:
                continue
            name = getattr(obj, "Name", None)
            ifc_class = obj.is_a() if hasattr(obj, "is_a") else None
            asset = BdnsTaggedAsset(
                ifc_guid=str(guid),
                name=str(name) if name is not None else None,
                bdns_tag=bdns_code,
                raw_ifc_class=str(ifc_class) if ifc_class is not None else None,
            )
            assets.append(asset)
    return BdnsTaggedAssets(items=assets)




def _find_bdns_classification(model) -> Optional[object]:
    for c in model.by_type("IfcClassification"):
        name = getattr(c, "Name", None)
        if isinstance(name, str) and name.strip().upper() == "BDNS":
            return c
    return None


def _collect_bdns_references(model, bdns_class) -> Dict[object, str]:
    ref_to_code: Dict[object, str] = {}
    for ref in model.by_type("IfcClassificationReference"):
        if ref.ReferencedSource != bdns_class:
            continue
        ident = getattr(ref, "Identification", None)
        if isinstance(ident, str) and ident.strip():
            code = ident.strip()
        else:
            name = getattr(ref, "Name", None)
            if isinstance(name, str) and name.strip():
                code = name.strip()
            else:
                continue
        ref_to_code[ref] = code
    return ref_to_code

# ==============================
# 追加: 空間要素の抽出ロジック
# ==============================

_WANTED_SPATIAL = ("IfcSite", "IfcBuilding", "IfcBuildingStorey", "IfcSpace")


def extract_spatial_elements(bundle: IfcBundle) -> SpatialElements:
    """
    IfcSite, IfcBuilding, IfcBuildingStorey, IfcSpace を抽出し, 親参照と論理パスを付加して返す.
    空間階層は IfcRelAggregates により連結されるため, 逆参照 Decomposes を辿って親を特定する [1](https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcSpatialStructureElement.htm)[2](https://iaiweb.lbl.gov/Resources/IFC_Releases/R2x3_final/ifcproductextension/lexical/ifcspatialstructureelement.htm)
    """
    model = getattr(bundle, "model", None)
    if model is None:
        raise ValueError("IfcBundle.model is None; ifc_ingestor で IFC モデルをセットしてください.")
    items: List[SpatialElement] = []
    for cls in _WANTED_SPATIAL:
        for obj in model.by_type(cls):
            guid = _guid(obj)
            if guid is None:
                continue
            parent = _parent_of(obj)
            el = SpatialElement(
                ifc_guid=guid,
                name=_name(obj),
                raw_ifc_class=cls,
                composition_type=_composition_type(obj),
                elevation=_elevation_if_storey(obj),
                parent_guid=_guid(parent) if parent is not None else None,
                path=_build_path(obj),
            )
            items.append(el)
    return SpatialElements(items=items)

def _parent_of(obj) -> Optional[object]:
    """
    IfcRelAggregates の逆参照 Decomposes から親要素を取得.
    見つからなければ None.
    仕様上, 空間構造の親子は IfcRelAggregates で構成される [1](https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcSpatialStructureElement.htm)[2](https://iaiweb.lbl.gov/Resources/IFC_Releases/R2x3_final/ifcproductextension/lexical/ifcspatialstructureelement.htm)
    """
    decomposes = getattr(obj, "Decomposes", None)
    if not decomposes:
        return None
    for rel in decomposes:
        if rel.is_a("IfcRelAggregates"):
            return getattr(rel, "RelatingObject", None)
    return None

def _guid(obj) -> Optional[str]:
    g = getattr(obj, "GlobalId", None)
    return str(g) if g is not None else None

def _name(obj) -> Optional[str]:
    n = getattr(obj, "Name", None)
    return str(n) if n is not None else None

def _composition_type(obj) -> Optional[str]:
    c = getattr(obj, "CompositionType", None)
    # Ifc2x3 では定義あり. 無い場合は None とする [2](https://iaiweb.lbl.gov/Resources/IFC_Releases/R2x3_final/ifcproductextension/lexical/ifcspatialstructureelement.htm)
    return str(c) if c is not None else None

def _build_path(obj) -> str:
    """
    親を辿って Site → Building → Storey → Space の順にラベル化したパスを生成.
    各要素は ClassName[Name or GUID] とする.
    """
    chain: List[object] = []
    cur = obj
    while cur is not None:
        chain.append(cur)
        cur = _parent_of(cur)
    chain.reverse()
    labels: List[str] = []
    for x in chain:
        cls = x.is_a() if hasattr(x, "is_a") else type(x).__name__
        nm = _name(x) or _guid(x) or "unknown"
        labels.append(f"{cls}[{nm}]")
    return "/".join(labels)

def _elevation_if_storey(obj) -> Optional[float]:
    """
    IfcBuildingStorey の場合のみ Elevation を抽出.
    無ければ None.
    """
    try:
        if obj.is_a("IfcBuildingStorey"):
            ev = getattr(obj, "Elevation", None)
            return float(ev) if ev is not None else None
    except Exception:
        pass
    return None