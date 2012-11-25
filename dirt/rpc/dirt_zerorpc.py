import zerorpc
from zerorpc.channel import BufferedChannel
from zerorpc.heartbeat import HeartBeatOnChannel
from dirt.rpc.common import Call

class DirtZeroRPCServer(zerorpc.Server):

    def __init__(self, edge, settings):
        self.edge = edge
        zerorpc.Server.__init__(self, methods=edge.get_api(None)) #FIXME
        binding = "tcp://%s:%s" % settings.bind
        self.bind(binding)
        self.run()

    def _async_task(self, initial_event):
        ### TODO: Use ZeroRPC middleware functionality

        protocol_v1 = initial_event.header.get('v', 1) < 2
        channel = self._multiplexer.channel(initial_event)
        hbchan = HeartBeatOnChannel(channel, freq=self._heartbeat_freq,
                passive=protocol_v1)
        bufchan = BufferedChannel(hbchan)
        event = bufchan.recv()
        try:
            self._context.middleware_load_task_context(event.header)

            # TODO: support non Req/Rep patterns, such as pubsub, pushpull
            call = Call(event.name, event.args, {}, [])
            self.edge.execute(call)

        except LostRemote:
            self._print_traceback(protocol_v1)
        except Exception:
            exception_info = self._print_traceback(protocol_v1)
            bufchan.emit('ERR', exception_info,
                    self._context.middleware_get_task_context())
        finally:
            bufchan.close()

class DirtZeroRPCClient(zerorpc.Client):

    def __init__(self, address=None, client=None, prefix=""):
        if address:
            assert not client, "can't supply both a client and an address"
            zerorpc.Client.__init__(self, connect_to=("tcp://%s:%s" % address))
            self._client = self
        else:
            assert client, "must supply either a client or an address"
            self._client = client
        self._prefix = prefix
    
    # TODO: refactor SimpleClient into common to eliminate copy-paste

    def _disconnect(self):
        self._client.disconnect()

    def trait_names(self):
        """ For tab completion with iPyhton. """
        return []

    def _getAttributeNames(self):
        """ For tab completion with iPyhton. """
        from ..app import APIMeta
        if self._prefix == "":
            return self.debug.api_methods()
        elif self._prefix == APIMeta.DEBUG_CALL_PREFIX:
            return self.debug_methods()
        return []

    def __call__(self, *args, **kwargs):
        assert self._prefix, "can't call before a prefix has been set"
        return zerorpc.Client.__call__(self._client, self._prefix, *args, **kwargs)

    def __getattr__(self, suffix):
        new_prefix = self._prefix and self._prefix + "." + suffix or suffix
        bound = self.__class__(client=self._client, prefix=new_prefix)
        setattr(self, suffix, bound)
        return bound

        

    
    
