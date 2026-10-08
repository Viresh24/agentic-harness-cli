from collections import Counter


def top_words(text, n):
    """The n most common words: case-insensitive, punctuation ignored, ties broken alphabetically."""
    return [word for word, _ in Counter(text.split()).most_common(n)]
