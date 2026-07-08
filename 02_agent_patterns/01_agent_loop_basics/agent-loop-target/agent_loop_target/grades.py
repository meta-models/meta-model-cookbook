"""Bug 2 (wrong comparison operator): map a numeric score to a letter grade."""


def letter_grade(score):
    """Return the letter grade for a 0-100 ``score``.

    Cutoffs are inclusive at the lower bound:
        90-100 -> "A", 80-89 -> "B", 70-79 -> "C", 60-69 -> "D", below 60 -> "F".
    So exactly 90 is an "A", exactly 80 is a "B", and so on.

    Args:
        score: a number between 0 and 100 inclusive.

    Returns:
        A single-character grade string.

    Raises:
        ValueError: if ``score`` is outside 0-100.
    """
    if score < 0 or score > 100:
        raise ValueError("score out of range")
    if score > 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"
