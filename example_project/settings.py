from dirt import logging_default
from dirt.rpc.dirt_zerorpc import DirtZeroRPCClient as RPCClient

DEBUG = True
USE_RELOADER = DEBUG
ALLOW_MOCK_API = DEBUG
LOGGING = logging_default("/tmp/dirt-example-log", root_level="INFO")
DIRT_APP_PIDFILE = "/tmp/dirt-example-{app_name}.pid"

class FIRST:
    app_class = "example.FirstApp"
    rpc_proxy = RPCClient
    bind = ("localhost", 9990)
    remote = ("localhost", 9990)

class SECOND:
    app_class = "example.SecondApp"
    rpc_proxy = RPCClient

