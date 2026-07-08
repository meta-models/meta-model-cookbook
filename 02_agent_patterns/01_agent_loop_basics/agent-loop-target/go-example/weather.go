package agentloop

// ParseCurrentTemperature returns the current temperature in Celsius from a
// decoded weather API response shaped like:
//
//	map[string]any{
//	    "location": map[string]any{"name": "San Francisco", "region": "CA"},
//	    "current": map[string]any{
//	        "temperature_c": 21.5,
//	        "humidity":      60,
//	        "condition":     "Partly cloudy",
//	    },
//	}
func ParseCurrentTemperature(resp map[string]any) float64 {
	return resp["temperature_c"].(float64)
}

// ParseCondition returns the human-readable condition string from the same
// response. It already works — use it to cross-reference the correct nesting.
func ParseCondition(resp map[string]any) string {
	current := resp["current"].(map[string]any)
	return current["condition"].(string)
}
