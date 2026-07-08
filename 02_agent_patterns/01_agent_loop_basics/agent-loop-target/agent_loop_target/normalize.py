"""Bug 3 (missing edge case): scale a list of numbers to the 0..1 range."""


def normalize(values):
    """Scale ``values`` into the range [0, 1] by dividing by the maximum value.

    Edge cases the caller relies on:
      * An empty list returns ``[]``.
      * If the maximum is 0 (e.g. all values are 0), every result is ``0.0``
        rather than raising a division error.

    Args:
        values: a list of non-negative numbers.

    Returns:
        A new list of floats in [0, 1], the same length as ``values``.
    """
    largest = max(values)
    return [v / largest for v in values]
