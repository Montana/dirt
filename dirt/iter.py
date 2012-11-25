from itertools import islice

def hunkify(iterable, hunk_size):
    """ Returns hunks of size ``hunk_size`` from ``iterable.

        >>> list(hunkify(range(5), 3))
        [[0, 1, 2], [3, 4]]
        >>>
    """

    i = iter(iterable)
    while True:
        result = list(islice(i, hunk_size))
        if not result:
            return
        yield result

def isiter(obj):
    """ Returns ``True`` iff ``obj`` is a non-indexable iterable.

        >>> isiter([42])
        False
        >>> isiter({"hello": "world"})
        False
        >>> isiter(iter("foo"))
        True
        >>> def my_generator():
        ...     yield 1
        >>> isiter(my_generator())
        True
        """
    return hasattr(obj, "__iter__") and not hasattr(obj, "__getitem__")

if __name__ == "__main__":
    import doctest
    doctest.testmod()
