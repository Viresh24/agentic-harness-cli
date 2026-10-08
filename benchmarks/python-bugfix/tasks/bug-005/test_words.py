from words import top_words


def test_most_common_first():
    assert top_words("a b b c c c", 2) == ["c", "b"]


def test_case_insensitive():
    assert top_words("Dog dog cat", 1) == ["dog"]


def test_ignores_punctuation():
    assert top_words("hi, hi! bye.", 1) == ["hi"]


def test_ties_broken_alphabetically():
    assert top_words("pear apple pear apple fig", 2) == ["apple", "pear"]


def test_n_larger_than_vocabulary():
    assert top_words("one", 5) == ["one"]
