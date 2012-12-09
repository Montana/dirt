``dirt``: a comprehensive framework for building Python applications which are part of a service oriented architecture
======================================================================================================================

``dirt`` provides all the tools required to build long-running Python
applications ("services") which can communicate over RPC.

Specifically, it provides:

* An RPC framework with pluggable protocols (currently a custom protocol,
  ``drpc``, and ZeroRPC).
* A framework for creating long-running applications which can expose methods
  over RPC.
* Tools for running multiple applications in one terminal, either for
  development or in production.
* A simple syntax for defining applications, which is largely configuration
  file format independent (currently only Django-style ``settings.py`` files
  are best supported, but ``.ini`` could easily be supported too).

An application can be as simple as::

    $ cat app.py
    import gevent
    import logging

    from dirt import DirtApp, runloop

    log = logging.getLogger(__name__)

    class PingAPI(object):
        def ping(self):
            return "pong"

    class PingApp(DirtApp):
        def get_api(self, edge, call):
            return PingAPI()

    class LongRunningApp(DirtApp):
        @runloop(log)
        def serve(self):
            ping_app = self.settings.get_api("ping")
            while True:
                result = ping_app.ping()
                log.info("ping: %r", result)
                gevent.sleep(1)

    $ cat settings.py
    from dirt import logging_default
    USE_RELOADER = False
    DIRT_APP_PIDFILE = "/tmp/dirt-example-{app_name}.pid"
    LOGGING = logging_default("/tmp/dirt-example-log", root_level="INFO")

    class PING:
        app_class = "app.PingApp"
        bind_url = "zrpc+tcp://127.0.0.1:9990"
        remote_url = bind_url

    class LONG_RUNNING:
        app_class = "app.LongRunningApp"

    $ ./run ping long_running
    23:20:21.289 ping INFO dirt.app: binding to zrpc+tcp://127.0.0.1:9990...
    23:20:21.477 long_running INFO app: ping: 'pong'
    23:20:22.380 long_running INFO app: ping: 'pong'


Some notes:

* ``dirt`` plays well with others, integrating easily into existing projects.
  See the ``example_project/`` directory for a Django project which uses
  ``dirt``.
* ``dirt`` depends on ``gevent==1.0``. In theory it should be possible for
  applications to use operating system threads, but this hasn't been tested.


Development Status
------------------

``dirt`` is used by Luminautics in a production environment, and has been
incredibly stable for the last six months.

That said, there will likely be some undocumented assumptions which could
affect other users, so some amount of testing should be done before trusting it
in your production environment.
