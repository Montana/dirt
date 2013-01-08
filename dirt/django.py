from __future__ import absolute_import

import logging

from django.core.handlers.wsgi import WSGIHandler as DjangoWSGIApp
from django.conf import settings
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
        settings.get_api = self.settings.get_api
        self.server = WSGIServer(self.settings.http_bind, self.application, log=None)

    def serve_dirt_rpc(self):
        """ Calls ``DirtApp.serve`` to start the RPC server, which lets callers
            use the debug API. """
        if getattr(self.settings, "bind_url", None) is None:
            self.log.info("no `bind_url` specified; RPC server not starting.")
            return
        DirtApp.serve(self)

    def serve(self):
        self.api_thread = gevent.spawn(self.serve_dirt_rpc)
        self.log.info("Starting server on http://%s:%s...", *self.settings.http_bind)
        self.server.serve_forever()

    def get_api(self, *args, **kwargs):
        """ The DjangoApp returns an empty API object by default so that tab
            completion of the API will work. Feel free to override this method.
            """
        return object()
