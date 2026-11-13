"""Brick Sensor / Setpoint assignment from point names (src/point_classes.py)."""
from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from bms_points import load_point_classes
from point_classes import classify_point, medium_words

SENSORS, SETPOINTS = load_point_classes(PROJECT_ROOT / "data" / "resources" / "brick_classes.json")
AIR = medium_words("brick:Air_Handling_Unit", is_space=False)
ROOM = medium_words(None, is_space=True)


def _classify(name, object_type="AI", units="", context=AIR, description=""):
    return classify_point(name, description, object_type, units, set(context), SENSORS, SETPOINTS)


@pytest.mark.parametrize(
    "name, object_type, units, context, expected",
    [
        ("AHU-1 Supply Air Temperature", "AI", "degC", AIR, "Supply_Air_Temperature_Sensor"),
        ("AHU-1 SAT", "AI", "degC", AIR, "Supply_Air_Temperature_Sensor"),
        ("ahu_supply_sp", "AI", "Pa", AIR, "Supply_Air_Static_Pressure_Sensor"),
        ("AHU-1 Return Air Temperature", "AI", "degC", AIR, "Return_Air_Temperature_Sensor"),
        ("AHU-1 OAT", "AI", "degC", AIR, "Outside_Air_Temperature_Sensor"),
        ("VAV-1 Zone Air Temperature", "AI", "degC", AIR, "Zone_Air_Temperature_Sensor"),
        ("VAV-1 Zone CO2", "AI", "ppm", AIR, "Zone_CO2_Level_Sensor"),
        ("Room 1 Temperature", "AI", "degC", ROOM, "Zone_Air_Temperature_Sensor"),
        ("Room 1 RH", "AI", "%RH", ROOM, "Zone_Air_Humidity_Sensor"),
        ("Room 1 Occupancy", "BI", "", ROOM, "Occupancy_Sensor"),
        ("CP-1 Water Temperature", "AI", "degC", medium_words("brick:Circulator_Pump", False), "Water_Temperature_Sensor"),
        ("AHU-1 Fan Speed", "AI", "rpm", AIR, "Speed_Sensor"),  # no "motor" word -> no Motor_Speed_Sensor
        ("VAV-1 Zone Air Flow", "AI", "m3/s", AIR, "Air_Flow_Sensor"),  # no "supply" word -> broader class
        # Zone_Air_Temperature_Setpoint is deprecated in Brick 1.3.0 and the name has no "target" word
        ("Zone Temp SP", "AV", "degC", ROOM, "Air_Temperature_Setpoint"),
        # Supply_Water_Temperature_Sensor is deprecated; "leaving" is not in the name, so no Leaving_* class
        ("CP-1 Supply Water Temperature", "AI", "degC", medium_words("brick:Circulator_Pump", False), "Water_Temperature_Sensor"),
        ("AHU-1 Supply Air Temperature Setpoint", "AV", "degC", AIR, "Supply_Air_Temperature_Setpoint"),
    ],
)
def test_classes_come_from_words_unit_type_and_equipment(name, object_type, units, context, expected):
    result = _classify(name, object_type, units, context)

    assert (result.status, result.brick_class) == ("classified", expected)


def test_sp_means_static_pressure_on_inputs_and_setpoint_on_values():
    assert _classify("Supply SP", "AI", "Pa").brick_class == "Supply_Air_Static_Pressure_Sensor"
    assert _classify("Supply Temp SP", "AV", "degC").kind == "Setpoint"


@pytest.mark.parametrize(
    "name, object_type, units",
    [
        ("FCU-1 Fan Status", "BI", ""),  # status, not a sensor
        ("AHU-1 Fan Command", "BO", ""),  # output
        ("AHU-1 Damper Position", "AO", "%"),  # output
        ("AHU-1 Mode", "MV", ""),  # multi-state value
        ("AHU-1 Supply Air Temperature", "AV", "degC"),  # value without a setpoint word
    ],
)
def test_points_outside_sensor_and_setpoint_are_out_of_scope(name, object_type, units):
    assert _classify(name, object_type, units).status == "out_of_scope"


@pytest.mark.parametrize(
    "name, units, reason",
    [
        ("AHU-1 Supply Air Temperature", "ppm", "contradicts"),
        ("AHU-1 Temperature Humidity", "degC", "several quantities"),
        ("AHU-1 Analog Input 7", "", "no measured quantity"),
    ],
)
def test_unclear_points_are_unclassified_not_guessed(name, units, reason):
    result = _classify(name, "AI", units)

    assert result.status == "unclassified"
    assert reason in result.reason
    assert result.brick_class == ""


def test_unit_alone_gives_a_broad_class():
    result = _classify("AHU-1 Analog Input 7", "AI", "degC", context=set())

    assert result.brick_class == "Temperature_Sensor"


def test_class_list_is_brick_144_without_deprecated_classes():
    import json

    data = json.loads((PROJECT_ROOT / "data" / "resources" / "brick_classes.json").read_text(encoding="utf-8"))

    assert data["brick_version"] == "1.4.4"
    assert {"Sensor", "Motor_Speed_Sensor", "Supply_Air_Flow_Sensor"} <= set(SENSORS)
    assert {"Setpoint", "Target_Zone_Air_Temperature_Setpoint"} <= set(SETPOINTS)
    # a sample of classes deprecated in Brick 1.3.0 / 1.4.0
    assert not {"Supply_Water_Temperature_Sensor", "Return_Water_Temperature_Sensor", "Heat_Sensor"} & set(SENSORS)
    assert not {"Zone_Air_Temperature_Setpoint", "Supply_Hot_Water_Temperature_Setpoint"} & set(SETPOINTS)
