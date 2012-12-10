from .protocol_registry import *

protocol_registry.register({
    "drpc": __name__ + ".proto_drpc",
    "zrpc+tcp": __name__ + ".proto_zrpc",
    "mock": __name__ + ".proto_mock",
})

from .common import ClientWrapper

def connect_simple(url, wrapper_cls=None):
    """ A helper method for doing a "simple" connect, where the client and
        wrapper classes are looked up directly.

        Note: this function ignores app-specific settings (ex, the wrapper), so
        it should be used with some amount of care.

        ::

            >>> ping_api = connect_simple("drpc://127.0.0.1:1234")
            >>> ping_api
            <ClientWrapper client=dirt.rpc.proto_drpc.client.Client('drpc://127.0.0.1:1234') prefix='prefix'>
            >>> ping_api.ping()
            'pong!'

        """
    client_cls = protocol_registry.get_client_cls(url)
    client = client_cls(url)
    wrapper_cls = wrapper_cls or ClientWrapper
    return wrapper_cls(client)
