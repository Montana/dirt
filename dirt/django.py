from __future__ import absolute_import

import logging

from django.core.handlers.wsgi import WSGIHandler as DjangoWSGIApp
from gevent.wsgi import WSGIServer
import gevent

from .app import DirtApp


class DjangoApp(DirtApp):
    log = logging.getLogger(__name__)

    def setup(self):
        self.application = DjangoWSGIApp()
        if self.settings.DEBUG:
            from werkzeug import DebuggedApplication
            self.application = DebuggedApplication(self.application, evalex=True)
        self.server = WSGIServer(self.settings.http_bind, self.application, log=None)

    def dirt_app_serve_forever(self):
        """ Calls ``DirtApp.serve_forever`` to start the RPC server, which
            lets callers use the debug API. """
        DirtApp.serve_forever(self)

    def serve_forever(self):
        self.api_thread = gevent.spawn(self.dirt_app_serve_forever)
        self.log.info("Starting server on http://%s:%s...", *self.settings.http_bind)
        self.server.serve_forever()
