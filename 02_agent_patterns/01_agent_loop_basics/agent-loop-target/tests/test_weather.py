"""Bug 4 — incorrect API response parsing: the field is nested under "current"."""

from agent_loop_target.weather import parse_condition, parse_current_temperature

SAMPLE_RESPONSE = {
    "location": {"name": "San Francisco", "region": "CA"},
    "current": {
        "temperature_c": 21.5,
        "humidity": 60,
        "condition": "Partly cloudy",
    },
}


def test_parse_current_temperature():
    assert parse_current_temperature(SAMPLE_RESPONSE) == 21.5


def test_parse_condition():
    # This one already works — it shows the correct nesting to cross-reference.
    assert parse_condition(SAMPLE_RESPONSE) == "Partly cloudy"
