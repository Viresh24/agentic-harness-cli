from tags import add_tag


def test_each_call_starts_fresh():
    assert add_tag("a") == ["a"]
    assert add_tag("b") == ["b"]


def test_no_duplicates():
    assert add_tag("x", ["x"]) == ["x"]


def test_appends_to_given_tags():
    assert add_tag("b", ["a"]) == ["a", "b"]


def test_does_not_modify_the_argument():
    original = ["a"]
    assert add_tag("b", original) == ["a", "b"]
    assert original == ["a"]
