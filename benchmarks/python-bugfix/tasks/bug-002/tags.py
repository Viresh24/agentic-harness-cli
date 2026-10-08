def add_tag(tag, tags=[]):
    """Return a new list of tags with `tag` added, without duplicates."""
    if tag not in tags:
        tags.append(tag)
    return tags
