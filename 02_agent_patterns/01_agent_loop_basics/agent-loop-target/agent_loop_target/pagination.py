"""Bug 1 (off-by-one): split a sequence into fixed-size pages."""


def paginate(items, page_size):
    """Split ``items`` into consecutive pages of at most ``page_size`` elements.

    The final page holds the remainder when ``len(items)`` is not an exact
    multiple of ``page_size``. For example, 10 items with ``page_size=3`` yields
    four pages: ``[[0,1,2], [3,4,5], [6,7,8], [9]]``.

    Args:
        items: a sequence (list) of elements.
        page_size: maximum number of elements per page; must be positive.

    Returns:
        A list of pages (each a list). An empty input yields ``[]``.
    """
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    pages = []
    num_pages = len(items) // page_size
    for p in range(num_pages):
        pages.append(items[p * page_size:(p + 1) * page_size])
    return pages
