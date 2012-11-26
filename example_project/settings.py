from dirt import logging_default

DEBUG = True
USE_RELOADER = DEBUG
ALLOW_MOCK_API = DEBUG
LOGGING = logging_default("/tmp/dirt-example-log", root_level="INFO")
DIRT_APP_PIDFILE = "/tmp/dirt-example-{app_name}.pid"

class FIRST_ZRPC:
    app_class = "example.FirstApp"
    bind_url = "zrpc+tcp://127.0.0.1:9990"
    remote_url = bind_url
    mock_cls = "example.FirstMock"

class FIRST_DRPC:
    app_class = "example.FirstApp"
    bind_url = "drpc://127.0.0.1:9991"
    remote_url = bind_url
    mock_cls = "example.FirstMock"

class SECOND:
    app_class = "example.SecondApp"

