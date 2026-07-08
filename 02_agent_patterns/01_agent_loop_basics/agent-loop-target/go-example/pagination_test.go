package agentloop

import (
	"reflect"
	"testing"
)

func TestPaginateExactMultiple(t *testing.T) {
	got := Paginate([]int{1, 2, 3, 4}, 2)
	want := [][]int{{1, 2}, {3, 4}}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v want %v", got, want)
	}
}

func TestPaginatePartialFinalPageIsKept(t *testing.T) {
	got := Paginate([]int{0, 1, 2, 3, 4, 5, 6, 7, 8, 9}, 3)
	want := [][]int{{0, 1, 2}, {3, 4, 5}, {6, 7, 8}, {9}}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v want %v", got, want)
	}
}

func TestPaginateSinglePartialPage(t *testing.T) {
	got := Paginate([]int{1, 2}, 5)
	want := [][]int{{1, 2}}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v want %v", got, want)
	}
}

func TestPaginateEmpty(t *testing.T) {
	got := Paginate([]int{}, 3)
	if len(got) != 0 {
		t.Fatalf("got %v want empty", got)
	}
}
