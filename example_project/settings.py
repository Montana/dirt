from ensi_common.dirt import get_api_factory, logging_default
from ensi_common.msg_hub.rpc import HubProxy, MockHub

DEBUG = True
USE_RELOADER = DEBUG
ALLOW_MOCK_API = DEBUG
LOGGING = logging_default("/tmp/dirt-example-log", root_level="INFO")
DIRT_APP_PIDFILE = "/tmp/dirt-example-{app_name}.pid"

get_api = get_api_factory(lambda: globals())

class FIRST:
    app_class = "example.FirstApp"

class SECOND:
    app_class = "example.SecondApp"

class MSG_HUB:
    app_class = "lumbo.msg_hub.app.App"
    bind = ("", 8753)
    log_to_hub = False

    remote = ("localhost", 8753)
    rpc_proxy = HubProxy
    mock_cls = MockHub
