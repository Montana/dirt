import logging

from gevent.server import StreamServer

from dirt.rpc.common import Call, is_expected, ServerBase
from dirt.misc.iter import isiter

from .connection import (
    ConnectionError, MessageError, ServerConnection, SocketError,
)

log = logging.getLogger(__name__)

class Server(ServerBase):
    def init(self):
        bind = (self.bind.hostname, self.bind.port)
        self.server = StreamServer(bind, self.accept_connection)

    def serve_forever(self):
        self.server.serve_forever()

    def accept_connection(self, socket, address):
        log_prefix = "connection from %s:%s: " %address
        log.debug(log_prefix + "accepting")

        handler = ConnectionHandler(self.execute_call)
        try:
            handler.accept(socket, address)
        except Exception, e:
            if isinstance(e, SocketError) or is_expected(e):
                log.info(log_prefix + "ignoring expected exception %r", e)
            else:
                log.exception(log_prefix + "unexpected exception:")


class ConnectionHandler(object):
    """ Accepts and handles one client socket.

        RPC calls (``call`` types) will be looked up using the
        ``_lookup_method`` method (which must be overridden by subclasses), the
        resulting function will be called and the result will returned.

        Note that one socket may receive multiple calls, and be used by
        multiple threads. """

    def __init__(self, execute_call):
        self.execute_call = execute_call

    def accept(self, socket, address):
        """ Accepts a socket, wraps it in a ``ServerConnection``, which is
            passed to ``handle_connection``. """
        self.client = address
        self.cxn = ServerConnection(socket, address)
        self.log = self.cxn.log
        try:
            self.handle_connection()
        finally:
            self.cxn.disconnect()
            self._shutdown()

    def handle_connection(self):
        try:
            while 1:
                self._handle_one_message()
        except Exception, e:
            if not is_expected(e):
                raise
            self.log.debug("got expected exception: %r", e)

    def _handle_one_message(self):
        """ Handles one stateless message from a client.

            Stateful messages should be handled by other sub-functions (eg,
            ``_handle_call``). """

        type, data = self.cxn.recv_message()

        if type.startswith("call"):
            if len(data) != 3:
                message = (type, data)
                raise MessageError.invalid(message, "incorrect number of args")
            flags = {
                "want_response": type == "call",
            }
            call = Call(data[0], data[1], data[2], flags, self.client)
            self._handle_call(call)
            return False

        raise MessageError.bad_type(type)

    def _handle_call(self, call):
        """ Handles one ``call`` message. """
        try:
            result = self.execute_call(call)
            if not call.want_response:
                return
            if isiter(result):
                for to_yield in result:
                    self.cxn.send_message(("yield", to_yield))
                self.cxn.send_message(("stop", ))
            else:
                self.cxn.send_message(("return", result))
        except ConnectionError:
            raise
        except Exception, e:
            if call.want_response:
                self.cxn.send_message(("raise", self._serialize_exception(e)))
            raise

    def _serialize_exception(self, exception):
        # Note: this is really simple for now, but it could easily be made
        # better if that would be useful.
        return repr(exception)

    def _lookup_method(self, call):
        """ Looks up the method which ``call`` should call (probably using
            ``call.name``), returning a callable.

            If None is returned, a helpful error will be returned to the
            client. """
        raise Exception("_lookup_method must be implemented by subclasses.")

    def _call_method(self, call, method):
        """ Calls the method returned by ``_lookup_method``. """
        raise Exception("_call_method must be implemented by subclasses.")

    def _shutdown(self):
        """ Called after this connection's socket has been closed, before
            ``accept`` returns.

            Subclasses can override this method to do cleanup. """
