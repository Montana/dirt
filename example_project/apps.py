import logging

import gevent
from dirt import DirtApp, runloop

log = logging.getLogger(__name__)

class PingMock(object):
    def ping(self):
        log.info("mock got ping...")
        return "mock pong"


class PingAPI(object):
    def ping(self):
        log.info("got ping...")
        return "pong"


class PingApp(DirtApp):
    def get_api(self, edge, call):
        return PingAPI()

    def start(self):
        log.info("starting...")

def PongAPI(object):
    def __init__(self, app):
        self.app = app

    def get_count(self):
        return self.app.count

class PongApp(DirtApp):
    def setup(self):
        self.count = 0

    def get_api(self, edge, call):
        return PongAPI(self)

    @runloop(log)
    def serve(self):
        log.info("Trying to ping...")
        api_zrpc = self.settings.get_api("ping_zrpc")
        api_drpc = self.settings.get_api("ping_drpc")
        while True:
            log.info("ping zrpc: %r", api_zrpc.ping())
            log.info("ping drpc: %r", api_drpc.ping())
            self.count += 1
            gevent.sleep(1)
