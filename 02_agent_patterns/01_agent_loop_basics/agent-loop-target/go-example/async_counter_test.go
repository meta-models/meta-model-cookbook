package agentloop

import "testing"

// Run with the race detector to catch the unsynchronized access reliably:
//
//	go test -race ./...
func TestCountsEveryEvent(t *testing.T) {
	if got := CountEvents(100); got != 100 {
		t.Fatalf("got %d want 100", got)
	}
}

func TestCountsSmall(t *testing.T) {
	if got := CountEvents(5); got != 5 {
		t.Fatalf("got %d want 5", got)
	}
}

func TestCountsZero(t *testing.T) {
	if got := CountEvents(0); got != 0 {
		t.Fatalf("got %d want 0", got)
	}
}
