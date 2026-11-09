"""Assign Brick Sensor / Setpoint classes to BMS points without project rules.

Brick class names are built from words (Supply_Air_Temperature_Sensor =
Supply + Air + Temperature + Sensor). A point's words are collected from:

- its name and description, normalised with a general HVAC vocabulary
  (temp -> Temperature, rh -> Humidity, room -> Zone, sat -> Supply Air
  Temperature, ...);
- its BACnet object type, which gives the point kind:
  AI -> Sensor; AV -> Setpoint only when a setpoint word is present;
  BI -> Sensor only when a binary-sensor word is present (occupancy,
  motion, ...). Everything else is outside the Sensor/Setpoint scope;
- its unit, which gives the measured quantity (degC -> Temperature, ...);
- its equipment (BDNS abbreviation -> project crosswalk -> Brick class),
  which gives the medium (Air for air handling units, VAV boxes, ...), or
  Zone + Air for a point that belongs to a space.

The chosen class is the most specific Brick class whose words are all in the
point's words and that contains its quantity. No match, or several equally
specific matches, leaves the point unclassified; it is never guessed. The
procedure is deterministic and runs locally; no model or service is involved.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

# Word (lower case) -> Brick words. General HVAC spellings, not project rules.
VOCABULARY: Dict[str, Tuple[str, ...]] = {
    "temp": ("Temperature",), "temperature": ("Temperature",), "tmp": ("Temperature",),
    "humidity": ("Humidity",), "hum": ("Humidity",), "rh": ("Humidity",),
    "co2": ("CO2",), "co": ("CO",), "no2": ("NO2",),
    "flow": ("Flow",), "airflow": ("Air", "Flow"), "volume": ("Flow",),
    "pressure": ("Pressure",), "press": ("Pressure",), "static": ("Static",),
    "differential": ("Differential",), "dp": ("Differential", "Pressure"),
    "speed": ("Speed",), "spd": ("Speed",),
    "occupancy": ("Occupancy",), "occ": ("Occupancy",), "presence": ("Occupancy",),
    "motion": ("Motion",),
    "supply": ("Supply",), "sup": ("Supply",), "sa": ("Supply", "Air"),
    "return": ("Return",), "ret": ("Return",), "ra": ("Return", "Air"),
    "mixed": ("Mixed",), "mix": ("Mixed",), "ma": ("Mixed", "Air"),
    "outside": ("Outside",), "outdoor": ("Outside",), "oa": ("Outside", "Air"),
    "exhaust": ("Exhaust",), "ea": ("Exhaust", "Air"),
    "discharge": ("Discharge",), "da": ("Discharge", "Air"),
    "zone": ("Zone",), "zn": ("Zone",), "room": ("Zone",), "rm": ("Zone",), "space": ("Zone",),
    "air": ("Air",), "water": ("Water",), "chw": ("Chilled", "Water"), "hw": ("Hot", "Water"),
    "setpoint": ("Setpoint",), "stpt": ("Setpoint",), "spt": ("Setpoint",), "setp": ("Setpoint",),
    "sat": ("Supply", "Air", "Temperature"), "rat": ("Return", "Air", "Temperature"),
    "mat": ("Mixed", "Air", "Temperature"), "oat": ("Outside", "Air", "Temperature"),
    "dat": ("Discharge", "Air", "Temperature"), "zat": ("Zone", "Air", "Temperature"),
    "znt": ("Zone", "Air", "Temperature"),
}
# "sp" is setpoint on a value object, static pressure on a pressure input.
AMBIGUOUS_SP = "sp"

CONCENTRATIONS = frozenset({"CO2", "CO", "NO2"})  # Brick names these "<gas>_Level"

# Unit -> the quantity words it allows. A single word is also added to the
# point's words; ppm allows any gas but does not say which.
UNIT_QUANTITIES: Dict[str, FrozenSet[str]] = {
    "degc": frozenset({"Temperature"}), "°c": frozenset({"Temperature"}),
    "degf": frozenset({"Temperature"}), "k": frozenset({"Temperature"}),
    "pa": frozenset({"Pressure"}), "kpa": frozenset({"Pressure"}), "inh2o": frozenset({"Pressure"}),
    "m3/s": frozenset({"Flow"}), "m3/h": frozenset({"Flow"}), "l/s": frozenset({"Flow"}), "cfm": frozenset({"Flow"}),
    "ppm": CONCENTRATIONS, "%rh": frozenset({"Humidity"}), "rpm": frozenset({"Speed"}),
}
QUANTITIES = {"Temperature", "Pressure", "Flow", "Humidity", "Speed", "Occupancy", "Motion"} | CONCENTRATIONS
BINARY_SENSOR_WORDS = {"Occupancy", "Motion"}

# Brick equipment class words that say which medium a point measures.
AIR_EQUIPMENT_WORDS = ("Air_Handling_Unit", "AHU", "Air_Volume_Box", "VAV", "CAV", "Fan_Coil_Unit", "Terminal_Unit",
                       "Air_Diffuser", "Fan", "Damper", "Rooftop_Unit", "Makeup_Air_Unit", "Dedicated_Outdoor_Air")
WATER_EQUIPMENT_WORDS = ("Pump", "Chiller", "Boiler", "Water", "Heat_Exchanger", "Cooling_Tower")


@dataclass(frozen=True)
class PointClassification:
    status: str  # classified | unclassified | out_of_scope
    kind: str = ""  # Sensor | Setpoint
    brick_class: str = ""
    words: Tuple[str, ...] = ()
    candidates: Tuple[str, ...] = ()
    reason: str = ""


def _split(text: str) -> List[str]:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text or "")
    return [w for w in re.split(r"[^A-Za-z0-9%/°]+", text.lower()) if w]


def _class_words(name: str) -> FrozenSet[str]:
    return frozenset(name.split("_"))


def medium_words(equipment_class: Optional[str], is_space: bool) -> Set[str]:
    if is_space:
        return {"Zone", "Air"}
    name = (equipment_class or "").removeprefix("brick:")
    if any(word in name for word in AIR_EQUIPMENT_WORDS):
        return {"Air"}
    if any(word in name for word in WATER_EQUIPMENT_WORDS):
        return {"Water"}
    return set()


def classify_point(
    name: str,
    description: str,
    object_type: str,
    units: str,
    context_words: Set[str],
    sensor_classes: Iterable[str],
    setpoint_classes: Iterable[str],
) -> PointClassification:
    tokens = _split(name) + _split(description)
    words: Set[str] = set()
    for token in tokens:
        words.update(VOCABULARY.get(token, ()))
    object_type = object_type.upper()
    allowed = UNIT_QUANTITIES.get((units or "").strip().lower(), frozenset())

    if AMBIGUOUS_SP in tokens:
        words.add("Setpoint" if object_type == "AV" else "Static")
        if object_type != "AV" and "Pressure" in allowed:
            words.add("Pressure")

    if object_type == "AI":
        kind = "Sensor"
    elif object_type == "AV" and "Setpoint" in words:
        kind = "Setpoint"
    elif object_type == "BI" and words & BINARY_SENSOR_WORDS:
        kind = "Sensor"
    else:
        return PointClassification("out_of_scope", words=tuple(sorted(words)),
                                   reason=f"{object_type} point is not a Sensor or Setpoint")

    named = words & QUANTITIES
    if len(named) > 1:
        return PointClassification("unclassified", kind, words=tuple(sorted(words)),
                                   reason=f"name states several quantities {sorted(named)}")
    if named and allowed and not named <= allowed:
        return PointClassification("unclassified", kind, words=tuple(sorted(words)),
                                   reason=f"unit {units!r} contradicts the name ({sorted(named)[0]})")
    if len(allowed) == 1:
        words |= allowed
    measured = words & QUANTITIES
    if not measured:
        return PointClassification("unclassified", kind, words=tuple(sorted(words)),
                                   reason="no measured quantity in name, description or unit")
    if measured & CONCENTRATIONS:
        words.add("Level")
    words |= context_words
    words.add(kind)

    pool = sensor_classes if kind == "Sensor" else setpoint_classes
    fitting = [c for c in pool if _class_words(c) <= words and _class_words(c) & measured and c.endswith(kind)]
    if not fitting:
        return PointClassification("unclassified", kind, words=tuple(sorted(words)),
                                   reason="no Brick class is made only of the point's words")
    best = max(len(_class_words(c)) for c in fitting)
    top = sorted(c for c in fitting if len(_class_words(c)) == best)
    if len(top) > 1:
        return PointClassification("unclassified", kind, words=tuple(sorted(words)), candidates=tuple(top),
                                   reason=f"{len(top)} equally specific classes fit")
    return PointClassification("classified", kind, top[0], tuple(sorted(words)), tuple(sorted(fitting)))
