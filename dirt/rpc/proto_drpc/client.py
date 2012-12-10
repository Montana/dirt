import logging

from gevent import socket
from gevent.timeout import Timeout

from dirt.rpc.common import ClientBase

from .connection import ConnectionError, MessageError, ConnectionPool

log = logging.getLogger(__name__)


class Client(ClientBase):
    def init(self):
        remote_addr = (self.remote.hostname, self.remote.port)
        self.pool = ConnectionPool.get_pool(remote_addr)

    def call(self, call):
        """ Calls ``name(*args, **kwargs)``. See ``default_flags`` for values
            of ``custom_flags``. """
        result = None
        cxn = self.pool.get_connection()
        try:
            result = self._call_with_cxn_with_retry(cxn, call)
        except:
            cxn.disconnect()
            raise
        finally:
            if not (result and result.holds_cxn):
                self.pool.release(cxn)

        assert result, "result somehow managed to stay undefined"
        return result.result

    def _call_with_cxn_with_retry(self, cxn, call):
        can_retry = call.flags.get("can_retry")
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

    def server_is_alive(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with Timeout(1.0):
                s.connect((self.remote.hostname, self.remote.port))
        except (socket.error, Timeout):
            return False
        finally:
            s.close()
        return True


    def disconnect(self):
        self.pool.disconnect()


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
