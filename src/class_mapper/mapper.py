from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.contracts import (
    BdnsTaggedAssets,
    BrickEquipment,
    BrickEquipmentSet,
)

logger = logging.getLogger(__name__)

# 未マップ時のフォールバック Brick クラス
DEFAULT_FALLBACK_BRICK_CLASS = "brick:Equipment"

# 固定スキーマの列名
COL_CODE = "bdns_abbriviation"  # 提示 CSV の綴りに厳密一致
COL_LABEL = "bdns_tag"
COL_IFC = "raw_ifc_class"
COL_BRICK = "brick_class_candidate"

# ------------------------------
# 既定マッピングのパス解決
# ------------------------------

def _default_mapping_csv_path() -> Path:
    """
    プロジェクトルートから BDNS → Brick マッピング CSV のデフォルトパスを返す.
    期待パス:
      resources/bdns/bdns_assets_to_brick_map.csv
    """
    here = Path(__file__).resolve()
    project_root = here.parents[2]
    return project_root / "resources" / "bdns" / "bdns_assets_to_brick_map.csv"


# ------------------------------
# 文字列正規化ユーティリティ
# ------------------------------
def _as_code_key(s: Optional[str]) -> str:
    if not s:
        return ""
    return s.strip().upper()


def _norm_label(s: Optional[str]) -> str:
    if not s:
        return ""
    t = s.lower()
    t = t.replace("-", " ")
    t = t.replace("_", " ")
    t = " ".join(t.split())
    return t.strip()


def _extract_prefix_from_name(name: Optional[str]) -> Optional[str]:
    """
    Asset Name から英字連続の先頭プレフィックスを抽出する.
    例: AHU-01 -> AHU. DSSO-00001 -> DSSO.
    """
    if not name:
        return None
    m = re.match(r"^([A-Za-z]+)", name.strip())
    if not m:
        return None
    return m.group(1).upper()


def _derive_label(name: Optional[str], code: Optional[str], guid: str) -> Optional[str]:
    if name and name.strip():
        return name.strip()
    if code:
        short = guid[:6] if guid else "XXXXXX"
        return f"{code}-{short}"
    return None


# ------------------------------
# マッピングインデックス
# ------------------------------
class _MappingIndex:
    """
    検索インデックスを二系統で保持する.
      by_code: BDNS 略号コード -> Brick クラス.
      by_label_ifc: (正規化ラベル, Ifc クラス) -> Brick クラス.
      by_label_only: 正規化ラベル -> Brick クラス.
    crosswalk は安全側で by_code と by_label_only の両方に適用する.
    """
    def __init__(self) -> None:
        self.by_code: Dict[str, str] = {}
        self.by_label_ifc: Dict[Tuple[str, str], str] = {}
        self.by_label_only: Dict[str, str] = {}

    def merge_crosswalk(self, override: Optional[dict]) -> None:
        if not override:
            return
        for k, v in override.items():
            if not isinstance(k, str) or not isinstance(v, str):
                continue
            brick = v.strip()
            if not brick:
                continue
            # コード想定
            code_key = _as_code_key(k)
            if code_key:
                self.by_code[code_key] = brick
            # ラベル想定
            label_key = _norm_label(k)
            if label_key:
                self.by_label_only[label_key] = brick


def _load_mapping(csv_path: Path) -> _MappingIndex:
    """
    固定スキーマ 4 列 CSV をロードする.
    ヘッダは厳密に
      bdns_abbriviation,bdns_tag,raw_ifc_class,brick_class_candidate
    を要求するが, BOM や余分な空白を正規化して受容する.
    """
    index = _MappingIndex()

    if not csv_path.is_file():
        logger.error("Mapping CSV not found. path=%s", csv_path)
        return index

    # utf-8-sig を用いて BOM を自動除去
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        # ヘッダ正規化: 前後空白除去, 小文字化, BOM 残滓除去
        def _norm_header(h: str | None) -> str:
            if not h:
                return ""
            return h.replace("\ufeff", "").strip().lower()

        raw_headers = list(reader.fieldnames or [])
        headers = [_norm_header(h) for h in raw_headers]

        # 正規化後のインデックスを DictReader に反映させるため, フィールド名を差し替え
        reader.fieldnames = headers

        required = {"bdns_abbriviation", "bdns_tag", "raw_ifc_class", "brick_class_candidate"}
        if not required.issubset(set(headers)):
            logger.error(
                "Invalid mapping CSV header. required=%s, found=%s",
                sorted(required),
                raw_headers,  # デバッグのため入力そのものを表示
            )
            return index

        for row in reader:
            # row のキーは正規化後の headers になる
            code = _as_code_key(row.get("bdns_abbriviation"))
            label = _norm_label(row.get("bdns_tag"))
            ifc = (row.get("raw_ifc_class") or "").strip()
            brick = (row.get("brick_class_candidate") or "").strip()
            if not brick:
                continue
            if code:
                index.by_code[code] = brick
            if label and ifc:
                index.by_label_ifc[(label, ifc)] = brick
            if label:
                index.by_label_only[label] = brick

    logger.info(
        "Loaded mapping. by_code=%d, by_label_ifc=%d, by_label_only=%d, path=%s",
        len(index.by_code),
        len(index.by_label_ifc),
        len(index.by_label_only),
        csv_path,
    )
    return index


# ------------------------------
# 公開関数
# ------------------------------
def map_bdns_to_brick_equipment(
    tagged_assets: BdnsTaggedAssets,
    base_ns: str,
    crosswalk_equip: dict | None = None,
    mapping_csv_path: str | Path | None = None,
) -> BrickEquipmentSet:
    """
    固定スキーマ 4 列 CSV を用いて BDNS タグ付き設備集合を Brick 設備集合へマッピングする.
    優先順位:
      1. Name 先頭の略号コード一致
      2. (bdns_tag 正規化, raw_ifc_class) 一致
      3. bdns_tag 正規化のみ一致
      4. 未マップは通過し brick:Equipment を付与し unmapped=True を設定
    crosswalk_equip はコードキーおよびラベルキーの仮説の両方で上書きに適用する.
    base_ns は本段では未使用.
    """
    csv_path = Path(mapping_csv_path) if mapping_csv_path is not None else _default_mapping_csv_path()
    index = _load_mapping(csv_path)
    index.merge_crosswalk(crosswalk_equip)

    equipments: List[BrickEquipment] = []

    for asset in tagged_assets.items:
        code = _extract_prefix_from_name(asset.name)
        brick_class: Optional[str] = None
        mapping_source: Optional[str] = None

        # 1. コード一致
        if code:
            brick_class = index.by_code.get(code)
            if brick_class:
                mapping_source = "code"

        # 2. ラベル+IFC 一致
        if not brick_class:
            lbl = _norm_label(asset.bdns_tag)
            ifc = (asset.raw_ifc_class or "").strip()
            if lbl and ifc:
                brick_class = index.by_label_ifc.get((lbl, ifc))
                if brick_class:
                    mapping_source = "label_ifc"

        # 3. ラベルのみ一致
        if not brick_class:
            lbl = _norm_label(asset.bdns_tag)
            if lbl:
                brick_class = index.by_label_only.get(lbl)
                if brick_class:
                    mapping_source = "label_only"

        # 4. 構築
        if not brick_class:
            label = _derive_label(asset.name, code, asset.ifc_guid)
            equipments.append(
                BrickEquipment(
                    ifc_guid=asset.ifc_guid,
                    brick_class=DEFAULT_FALLBACK_BRICK_CLASS,
                    label=label,
                    bdns_tag=code or asset.bdns_tag,
                    extra_props={
                        "raw_ifc_class": asset.raw_ifc_class,
                        "bdns_label": asset.bdns_tag,
                        "unmapped": True,
                    },
                )
            )
            logger.info(
                "Unmapped asset passed. guid=%s, name=%s, bdns=%s, ifc=%s",
                asset.ifc_guid,
                asset.name,
                asset.bdns_tag,
                asset.raw_ifc_class,
            )
            continue

        label = _derive_label(asset.name, code, asset.ifc_guid)
        equipments.append(
            BrickEquipment(
                ifc_guid=asset.ifc_guid,
                brick_class=brick_class,
                label=label,
                bdns_tag=code or asset.bdns_tag,
                extra_props={
                    "raw_ifc_class": asset.raw_ifc_class,
                    "bdns_label": asset.bdns_tag,
                    "mapping_source": mapping_source,
                },
            )
        )

    return BrickEquipmentSet(items=equipments)


# 後方互換用の薄いラッパー
def map_bdns_to_brick(
    bdns_assets: BdnsTaggedAssets,
    mapping_csv_path: str | Path | None = None,
) -> BrickEquipmentSet:
    return map_bdns_to_brick_equipment(
        tagged_assets=bdns_assets,
        base_ns="",
        crosswalk_equip=None,
        mapping_csv_path=mapping_csv_path,
    )