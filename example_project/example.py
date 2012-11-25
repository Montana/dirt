import time
import logging

from dirt import DirtApp, runloop

log = logging.getLogger(__name__)

class FirstAPI(object):
    def ping(self):
        return "pong"

class FirstApp(DirtApp):
    def get_api(self, call_info):
        return FirstAPI()

    def start(self):
        log.info("starting...")


class SecondApp(DirtApp):
    @runloop(log)
    def serve(self):
        log.info("Trying to ping FirstApp...")
        api = self.settings.get_api("first")
        while True:
            time.sleep(1)
            log.info("ping: %r", api.ping())
