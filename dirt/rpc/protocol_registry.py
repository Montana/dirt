from dirt.misc.imp_ import import_

__all__ = [
    "ProtocolRegistry", "protocol_registry", "get_server_cls",
    "get_client_cls",
]

class ProtocolRegistry(object):
    def __init__(self):
        self.protocols = {}

    def register(self, proto, module=None):
        """ Register protocol handlers.

            >>> registry.register("foo", "some.module")
            >>> registry.register("bar", another_module)
            >>> registry.register({
            ...     "baz+a": "some.module",
            ...     "baz+b": "some.module",
            ... })
            >>>
            """
        if module is None:
            self.protocols.update(proto)
        else:
            self.protocols[proto] = module

    def _get(self, url, cls_name):
        proto, _, _ = url.partition(":")
        if proto not in self.protocols:
            raise ValueError("unrecognized protocol: %r in %r" %(proto, url))
        handler = self.protocols[proto]
        if isinstance(handler, basestring):
            handler = import_(handler)
            self.protocols[proto] = handler
        try:
            return getattr(handler, cls_name)
        except AttributeError:
            raise ValueError("%r class not found in %r (handler for %r)"
                             %(cls_name, handler, url))

    def get_server_cls(self, url):
        return self._get(url, "Server")

    def get_client_cls(self, url):
        return self._get(url, "Client")


protocol_registry = ProtocolRegistry()
get_server_cls = protocol_registry.get_server_cls
get_client_cls = protocol_registry.get_client_cls
