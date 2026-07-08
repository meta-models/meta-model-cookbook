package agentloop

import "fmt"

// LetterGrade returns the letter grade for a 0-100 score.
//
// Cutoffs are inclusive at the lower bound:
// 90-100 -> "A", 80-89 -> "B", 70-79 -> "C", 60-69 -> "D", below 60 -> "F".
// So exactly 90 is an "A" and exactly 80 is a "B". It returns an error if
// score is outside 0-100.
func LetterGrade(score int) (string, error) {
	if score < 0 || score > 100 {
		return "", fmt.Errorf("score out of range: %d", score)
	}
	if score > 90 {
		return "A", nil
	}
	if score >= 80 {
		return "B", nil
	}
	if score >= 70 {
		return "C", nil
	}
	if score >= 60 {
		return "D", nil
	}
	return "F", nil
}
