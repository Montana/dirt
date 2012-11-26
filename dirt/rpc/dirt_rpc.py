import logging

from gevent.server import StreamServer
from .dirtrpc.server import ConnectionHandler
from .dirtrpc.connection import SocketError
from dirt.rpc.common import is_expected

log = logging.getLogger(__name__)

class DirtRPCServer(object):

    def __init__(self, edge, settings):

        self.edge = edge
        self.server = StreamServer(settings.bind, self.accept_connection)
        self.server.serve_forever()

    def accept_connection(self, socket, address):
        log_prefix = "connection from %s:%s: " %address
        log.debug(log_prefix + "accepting")

        handler = ConnectionHandler(self)
        try:
            handler.accept(socket, address)
        except Exception, e:
            if isinstance(e, SocketError) or is_expected(e):
                log.info(log_prefix + "ignoring expected exception %r", e)
            else:
                log.exception(log_prefix + "unexpected exception:")


    def execute(self, call):
        return self.edge.execute(call)
    
