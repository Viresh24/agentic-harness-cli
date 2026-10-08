from money import round_price


def test_half_rounds_up():
    assert round_price(2.675) == 2.68


def test_half_rounds_up_small():
    assert round_price(1.005) == 1.01


def test_exact_half():
    assert round_price(0.125) == 0.13


def test_negative_half_rounds_away_from_zero():
    assert round_price(-2.675) == -2.68


def test_whole_number():
    assert round_price(10) == 10.0
