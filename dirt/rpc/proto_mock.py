import logging

from dirt.rpc.common import ServerBase, ClientBase

log = logging.getLogger(__name__)

class Server(ServerBase):
    def serve_forever(self):
        raise Exception("Mock server can't serve forever")


class Client(ClientBase):
    def call(self, call):
        raise Exception("Mock client can't call()")

    def server_is_alive(self):
        return True

    def disconnect(self):
        pass

