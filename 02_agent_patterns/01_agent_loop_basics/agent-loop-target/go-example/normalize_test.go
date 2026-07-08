package agentloop

import (
	"reflect"
	"testing"
)

func TestNormalizeBasic(t *testing.T) {
	got := Normalize([]float64{2, 4})
	want := []float64{0.5, 1.0}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v want %v", got, want)
	}
}

func TestNormalizeEmptyReturnsEmpty(t *testing.T) {
	got := Normalize([]float64{})
	if len(got) != 0 {
		t.Fatalf("got %v want empty", got)
	}
}

func TestNormalizeAllZero(t *testing.T) {
	got := Normalize([]float64{0, 0, 0})
	want := []float64{0, 0, 0}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v want %v", got, want)
	}
}
