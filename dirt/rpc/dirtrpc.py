
from gevent import StreamServer
from .dirtrpc import ConnectionHandler

class DirtRPCServer(object):

    def __init__(binding, edge):

        self.edge = edge
        self.server = StreamServer(self.settings.bind, self.accept_connection)
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
        method = self.edge.lookup_method(call)
        if method is None:
            raise expected(ValueError("invalid method: %r" %(call.name, )))
        result = self.edge.call_method(call, method)
    
