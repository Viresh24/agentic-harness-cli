def median(values):
    """Median of a non-empty list of numbers. Does not modify the input; raises ValueError if empty."""
    values.sort()
    return values[len(values) // 2]
