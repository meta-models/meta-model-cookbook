package agentloop

import "testing"

func TestLetterGradeLowerBoundsInclusive(t *testing.T) {
	cases := map[int]string{90: "A", 80: "B", 70: "C", 60: "D"}
	for score, want := range cases {
		got, err := LetterGrade(score)
		if err != nil {
			t.Fatalf("score %d: unexpected error %v", score, err)
		}
		if got != want {
			t.Fatalf("score %d: got %q want %q", score, got, want)
		}
	}
}

func TestLetterGradeInterior(t *testing.T) {
	for score, want := range map[int]string{95: "A", 85: "B", 59: "F", 100: "A", 0: "F"} {
		got, _ := LetterGrade(score)
		if got != want {
			t.Fatalf("score %d: got %q want %q", score, got, want)
		}
	}
}

func TestLetterGradeOutOfRange(t *testing.T) {
	if _, err := LetterGrade(101); err == nil {
		t.Fatal("expected error for 101")
	}
	if _, err := LetterGrade(-1); err == nil {
		t.Fatal("expected error for -1")
	}
}
