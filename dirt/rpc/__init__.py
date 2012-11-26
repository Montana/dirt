from .protocol_registry import *

protocol_registry.register({
    "drpc": __name__ + ".proto_drpc",
    "zrpc+tcp": __name__ + ".proto_zrpc",
})
