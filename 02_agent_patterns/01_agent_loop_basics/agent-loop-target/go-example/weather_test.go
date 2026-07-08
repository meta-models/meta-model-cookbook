package agentloop

import "testing"

func sampleResponse() map[string]any {
	return map[string]any{
		"location": map[string]any{"name": "San Francisco", "region": "CA"},
		"current": map[string]any{
			"temperature_c": 21.5,
			"humidity":      60,
			"condition":     "Partly cloudy",
		},
	}
}

func TestParseCurrentTemperature(t *testing.T) {
	if got := ParseCurrentTemperature(sampleResponse()); got != 21.5 {
		t.Fatalf("got %v want 21.5", got)
	}
}

func TestParseCondition(t *testing.T) {
	if got := ParseCondition(sampleResponse()); got != "Partly cloudy" {
		t.Fatalf("got %q want %q", got, "Partly cloudy")
	}
}
