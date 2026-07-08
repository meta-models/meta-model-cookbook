"""Bug 4 (incorrect API response parsing): pull fields out of a weather payload."""


def parse_current_temperature(response):
    """Return the current temperature in Celsius from a weather API response.

    The API returns a nested JSON object shaped like::

        {
            "location": {"name": "San Francisco", "region": "CA"},
            "current": {
                "temperature_c": 21.5,
                "humidity": 60,
                "condition": "Partly cloudy"
            }
        }

    Args:
        response: the decoded JSON response (a dict) with the structure above.

    Returns:
        The current temperature in Celsius as a number.
    """
    return response["temperature_c"]


def parse_condition(response):
    """Return the human-readable ``condition`` string from the same response.

    See :func:`parse_current_temperature` for the response structure.
    """
    return response["current"]["condition"]
