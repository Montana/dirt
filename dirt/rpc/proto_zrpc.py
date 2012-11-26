import logging

import zerorpc
from zerorpc.channel import BufferedChannel
from zerorpc.heartbeat import HeartBeatOnChannel
from zerorpc.exceptions import LostRemote
from zmq.core.error import ZMQError

from dirt.rpc.common import Call, ServerBase, ClientBase

log = logging.getLogger(__name__)

class CustomZRPCServer(zerorpc.Server):
    def __init__(self, execute_call, *args, **kwargs):
        self.execute_call = execute_call
        zerorpc.Server.__init__(self, *args, **kwargs)

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
            call = Call(event.name, event.args) # TODO: Adam: add ``peer=...`` here
            result = self.execute_call(call)
            bufchan.emit('OK', (result,), self._context.middleware_get_task_context())
        except LostRemote:
            self._print_traceback(protocol_v1)
        except Exception:
            exception_info = self._print_traceback(protocol_v1)
            bufchan.emit('ERR', exception_info,
                    self._context.middleware_get_task_context())
        finally:
            bufchan.close()


class Server(ServerBase):
    def init(self):
        self.zrpc_server = CustomZRPCServer(self.execute_call)

    def serve_forever(self):
        _, _, zmq_url = self.bind_url.partition("+")
        try:
            self.zrpc_server.bind(zmq_url)
        except ZMQError as e:
            if "Operation not supported by device" in str(e):
                log.warning("*" * 80)
                log.warning(
                    "HINT: zmq can't bind to hostnames (ex, 'localhost'); "
                    "it must bind either to '*', an IPv4 address, or a "
                    "network interface name. "
                    "See also: http://stackoverflow.com/a/8958414/71522"
                )
                log.warning("*" * 80)
            raise

        self.zrpc_server.run()


class Client(ClientBase):
    def init(self):
        self.zrpc_client = None
        _, _, self.zmq_url = self.remote_url.partition("+")

    def call(self, call):
        if self.zrpc_client is None:
            self.zrpc_client = zerorpc.Client(connect_to=self.zmq_url)
        if call.kwargs:
            raise ValueError("zerorpc doesn't support kwargs, but %r has kwargs" %(call, ))
        return self.zrpc_client(call.name, *call.args)

    def server_is_alive(self):
        return False # TODO: Adam: implement this

    def disconnect(self):
        if self.zrpc_client is not None:
            self.zrpc_client.close()
