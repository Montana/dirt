import time

from ...strutil import to_str

class Call(object):
    """ Stores the data and options for one RPC call. """

    default_flags = {
        # Should we wait for a result from the server? If ``False``, ``_call``
        # will return immediately.
        "want_response": True,
        # Is this call safe to retry if it fails?
        "can_retry": True,
    }

    def __init__(self, name, args=None, kwargs=None, flags=None):
        args = args or ()
        kwargs = kwargs or {}
        flags = flags or {}

        for flag in flags:
            if flag not in self.default_flags:
                raise ValueError("invalid flag: %r" %(flag, ))
        self.__dict__.update(self.default_flags)
        self.__dict__.update(flags)
        self.flags = flags
        self.name = name
        self.args = args
        self.kwargs = dict((to_str(k), v) for (k, v) in kwargs.items())
        # Some debug-related information about this call
        self.meta = {
            # The time the call was first received.
            "time_received": time.time(),
            # The time between when the call was received and the time the call
            # was started.
            "time_in_queue": None,
            # The number of items which have been yielded, if this call
            # returned an iterator.
            "yielded_items": None,
        }


def expected(exception):
    """ Mark an exception as being "expected". Expected exceptions will not
        have a stack trace logged. """
    exception._is_expected = True
    return exception

def is_expected(exception):
    return getattr(exception, "_is_expected", False)
