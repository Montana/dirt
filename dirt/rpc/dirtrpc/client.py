import logging

from .common import Call
from .connection import ConnectionError, MessageError, ConnectionPool

log = logging.getLogger(__name__)


class RemoteException(Exception):
    """ Raised by the Client when the server returns an error.
        Currently has no useful content apart from a `repr` of the remote
        error. """
    pass


class ResultGenerator(object):
    def __init__(self, cxn, release_cxn, first_message):
        self.cxn = cxn
        self.release_cxn = release_cxn
        self._first_call = [True, first_message]

    def __del__(self):
        try:
            self.close()
        except:
            pass

    def __iter__(self):
        return self

    def close(self):
        self.cxn.disconnect()
        self.release_cxn(self.cxn)

    def next(self):
        try:
            return self._next()
        except Exception, e:
            if not isinstance(e, StopIteration):
                self.cxn.disconnect()
            self.release_cxn(self.cxn)
            raise

    def _next(self):
        if self._first_call[0]:
            type, data = self._first_call[1]
            self._first_call = [False]
        else:
            type, data = self.cxn.recv_message()

        if type == "yield":
            return data
        if type == "raise":
            raise RemoteException(data)
        if type == "stop":
            raise StopIteration()
        raise MessageError.bad_type(type)


class CallResult(object):
    def __init__(self, result, holds_cxn=False):
        self.holds_cxn = holds_cxn
        self.result = result


class Client(object):
    def __init__(self, server_address):
        self.server_address = server_address
        self.pool = ConnectionPool.get_pool(server_address)

    def _call(self, call, retry_on_error=True):
        """ Calls ``name(*args, **kwargs)``. See ``default_flags`` for values
            of ``custom_flags``. """
        result = None
        cxn = self.pool.get_connection()
        try:
            result = self._call_with_cxn_with_retry(cxn, call, retry_on_error)
        except:
            cxn.disconnect()
            raise
        finally:
            if not (result and result.holds_cxn):
                self.pool.release(cxn)

        assert result, "result somehow managed to stay undefined"
        return result.result

    def _call_with_cxn_with_retry(self, cxn, call, can_retry):
        try:
            return self._call_with_cxn(cxn, call)
        except ConnectionError:
            if not (can_retry and call.can_retry):
                raise
            return self._call_with_cxn(cxn, call)

    def _call_with_cxn(self, cxn, call):
        type = call.want_response and "call" or "call_ignore"
        message = (type, (call.name, call.args, call.kwargs))
        cxn.send_message(message)
        if not call.want_response:
            return CallResult(None)

        type, data = cxn.recv_message()
        if type == "return":
            return CallResult(data)
        if type == "raise":
            raise RemoteException(data)
        if type in ["yield", "stop"]:
            return CallResult(ResultGenerator(cxn, self.pool.release,
                                              (type, data)),
                              holds_cxn=True)
        raise MessageError.bad_type(type)

    def call(self, name, *call_args, **kwargs):
        call_kwargs = {}
        flags = {}
        for key, val in kwargs.items():
            if key.startswith("_") and key[1:] in Call.default_flags:
                flags[key[1:]] = val
            else:
                call_kwargs[key] = val

        call = Call(name, call_args, call_kwargs, flags)
        return self._call(call)

    def disconnect(self):
        self.pool.disconnect()

    def __repr__(self):
        return "<Client server='{0}:{1}'>".format(*self.server_address)


class SimpleClient(object):
    def __init__(self, address=None, client=None, prefix=""):
        if address:
            assert not client, "can't supply both a client and an address"
            self._client = Client(address)
        else:
            assert client, "must supply either a client or an address"
            self._client = client
        self._prefix = prefix

    def _disconnect(self):
        self._client.disconnect()

    def trait_names(self):
        """ For tab completion with iPyhton. """
        return []

    def _getAttributeNames(self):
        """ For tab completion with iPyhton. """
        return self._client.call("debug.list_methods", self._prefix)

    def __call__(self, *args, **kwargs):
        assert self._prefix, "can't call before a prefix has been set"
        return self._client.call(self._prefix, *args, **kwargs)

    def __getattr__(self, suffix):
        new_prefix = self._prefix and self._prefix + "." + suffix or suffix
        bound = self.__class__(client=self._client, prefix=new_prefix)
        setattr(self, suffix, bound)
        return bound

    def __repr__(self):
        return "<SimpleClient client={0!r} prefix={1!r}>".format(
            self._client, self._prefix)
