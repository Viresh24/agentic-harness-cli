import pytest

from stats import median


def test_odd_length():
    assert median([3, 1, 2]) == 2


def test_even_length_averages_middle_two():
    assert median([4, 1, 3, 2]) == 2.5


def test_single_value():
    assert median([5]) == 5


def test_does_not_modify_input():
    data = [3, 1, 2]
    median(data)
    assert data == [3, 1, 2]


def test_empty_raises_value_error():
    with pytest.raises(ValueError):
        median([])
