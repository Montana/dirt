import time
from urlparse import urlparse

from ..strutil import to_str

def expected(exception):
    """ Mark an exception as being "expected". Expected exceptions will not
        have a stack trace logged. """
    exception._is_expected = True
    return exception

def is_expected(exception):
    return getattr(exception, "_is_expected", False)


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
        self.kwargs = dict((to_str(key), val) for (key, val) in kwargs.items())
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


class ServerBase(object):
    def __init__(self, bind_url, execute_call):
        self.bind_url = bind_url
        self.bind = urlparse(bind_url)
        self.execute_call = execute_call
        self.init()

    def init(self):
        pass

    def serve_forever(self):
        raise NotImplementedError


class ClientBase(object):
    def __init__(self, remote_url):
        self.remote_url = remote_url
        self.remote = urlparse(remote_url)
        self.init()
    
    def init(self):
        pass

    def call(self, call):
        raise NotImplementedError

    def server_is_alive(self):
        """ Returns ``True`` if the server is alive and reachable.

            Used by ``DirtRunner`` to determine whether this connection should
            be mocked. """
        return False

    def disconnect(self):
        pass

    def __repr__(self):
        cls = type(self)
        return "%s.%s(remote_url=%r)" %(
            cls.__module__, cls.__name__, self.remote_url,
        )


class RPCClientProxy(object):
    def __init__(self, client, prefix=""):
        self._client = client
        self._prefix = prefix

    def _disconnect(self):
        self._client.disconnect()

    def trait_names(self):
        """ For tab completion with iPyhton. """
        return self._client.call("debug.list_methods", self._prefix)

    def _getAttributeNames(self):
        """ For tab completion with iPyhton. """
        return []

    def __call__(self, *args, **kwargs):
        assert self._prefix, "can't call before a prefix has been set"
        call = Call(self._prefix, args, kwargs)
        return self._client.call(call)

    def __getattr__(self, suffix):
        new_prefix = self._prefix and self._prefix + "." + suffix or suffix
        bound = self.__class__(client=self._client, prefix=new_prefix)
        setattr(self, suffix, bound)
        return bound

    def __repr__(self):
        return "<%s client=%r prefix=%r>" %(
            type(self).__name__, self._client, self._prefix,
        )
