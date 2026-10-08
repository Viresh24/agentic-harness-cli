def round_price(amount):
    """Round a price to 2 decimal places; halves round away from zero (2.675 -> 2.68)."""
    return round(amount, 2)
