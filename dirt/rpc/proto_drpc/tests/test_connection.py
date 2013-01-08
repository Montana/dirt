import gevent
from gevent.event import AsyncResult
from gevent.queue import Queue
from gevent import socket
from nose.tools import assert_equal

from mock import Mock

from ..connection import (
    ServerConnection, ClientConnection, ConnectionError, MessageSocket,
    ConnectionPool,
)
from dirt.testing import assert_contains, parameterized


class TestConnection(object):
    def setup(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(("127.0.0.1", 0))
        self.server_socket.listen(1)
        self.bind_address = self.server_socket.getsockname()

        self.client_cxn = ClientConnection(self.bind_address)
        self.threads = []

    def teardown(self):
        self.server_socket.close()
        for thread in self.threads:
            thread.kill(timeout=1)

    def spawn(self, *args, **kwargs):
        thread = gevent.spawn(*args, **kwargs)
        self.threads.append(thread)
        return thread

    def test_repr(self):
        expected = "<ClientConnection msg_socket=<MessageSocket %s%%s connected to %s>>" %(
            self.client_cxn.id, "%s:%s" %self.bind_address
        )

        assert_equal(repr(self.client_cxn),
                     expected %" not")

        self.client_cxn.connect()
        assert_equal(repr(self.client_cxn),
                     expected %"")

    def test_simple_message(self):
        server_messages = Queue()
        def server_thread():
            socket, addr = self.server_socket.accept()
            server = ServerConnection(socket, addr)
            server_messages.put(server.recv_message())
            server.send_message(("hello", "client"))
            socket.close()
        self.spawn(server_thread)

        client = self.client_cxn
        client.send_message(("hello", "server"))
        assert_equal(server_messages.get(timeout=1), ("hello", "server"))
        assert_equal(client.recv_message(), ("hello", "client"))

    def test_client_disconnect(self):
        def server_thread():
            for num in xrange(2):
                socket, addr = self.server_socket.accept()
                server = ServerConnection(socket, addr)
                server.send_message(("num", num))
        self.spawn(server_thread)

        client = self.client_cxn
        assert_equal(client.recv_message(), ("num", 0))

        client.disconnect()
        assert_equal(client.recv_message(), ("num", 1))

    def test_client_empty_read(self):
        def server_thread():
            for num in xrange(2):
                socket, addr = self.server_socket.accept()
                if num == 1:
                    server = ServerConnection(socket, addr)
                    server.send_message(("second", ))
                socket.close()
        self.spawn(server_thread)

        client = self.client_cxn
        try:
            client.recv_message()
            raise AssertionError("no exception raised")
        except ConnectionError, e:
            assert_contains(str(e), str(self.bind_address[1]))
            assert_equal(client.connected(), False)

        assert_equal(client.recv_message(), ("second", None))

    def test_client_bad_write_server_not_available(self):
        self.server_socket.close()
        client = self.client_cxn
        try:
            client.send_message(("msg", ))
            raise AssertionError("no exception raised")
        except ConnectionError, e:
            assert_contains(str(e), str(self.bind_address[1]))
            assert_equal(client.connected(), False)

    def test_sends_version_info_on_connect(self):
        client = self.client_cxn
        server_version = AsyncResult()
        def server_thread():
            socket, addr = self.server_socket.accept()
            server = ServerConnection(socket, addr)
            assert_equal(server.recv_message(), ("hello", "world"))
            server_version.set(server.msg_socket.peer_version_info)
            server.disconnect()
        self.spawn(server_thread)

        client.send_message(("hello", "world"))
        assert_equal(server_version.get(timeout=0.01),
                     client.msg_socket.version_info)

    def test_server_rejects_bad_version_info(self):
        server_done = AsyncResult()
        client = self.client_cxn
        def server_thread():
            socket, addr = self.server_socket.accept()
            server = ServerConnection(socket, addr)
            try:
                server.recv_message()
                raise AssertionError("expected exception not raised")
            except ConnectionError, e:
                assert_contains(str(e), "VERSION_MISMATCH")
            assert not server.connected()
            server_done.set(True)
        self.spawn(server_thread)

        client.msg_socket.version_info["foo"] = 42
        client.send_message(("hello", "world"))
        try:
            client.recv_message()
            raise AssertionError("expected exception not raised")
        except ConnectionError, e:
            assert_contains(str(e), "VERSION_MISMATCH")
        assert not client.connected()
        server_done.get(timeout=0.01)


class TestMessageSocket(object):
    def test_zlib(self):
        socket = Mock()
        msg_socket = MessageSocket(("127.0.0.1", 0), lambda: socket, {}, use_zlib=True)
        msg_socket.send_message("hello, world!")
        assert_equal(socket.sendall.call_args[0],
                     ("000015Z:" + "hello, world!".encode("zlib"), ))

    def test_send_version(self):
        socket = Mock()
        msg_socket = MessageSocket(("127.0.0.1", 0), lambda: socket, {
            "foo": "42",
        })
        msg_socket.send_version()
        assert_equal(socket.sendall.call_args[0],
                     ("000024N!VERSION foo=42&message_socket=1.zlib", ))

    def test_recv_good_version(self):
        msg_socket = MessageSocket(("127.0.0.1", 0), lambda: Mock(), {})
        msg_socket.disconnect = Mock()
        messages = [
            (MessageSocket.TYPE_CONTROL, "VERSION %s" %(msg_socket._serialize_version_info(), )),
            (MessageSocket.TYPE_NORMAL, "OK"),
        ]
        msg_socket._recv_one_message = lambda: messages.pop(0)
        result = msg_socket.recv_message()
        assert_equal(result, "OK")
        assert_equal(msg_socket.peer_version_info, msg_socket.version_info)
        assert not msg_socket.disconnect.called

    @parameterized([
        ("VERSION bad=42", ),
        ("VERSION_MISMATCH blah blah", ),
    ])
    def test_recv_version_error(self, version_msg):
        msg_socket = MessageSocket(("127.0.0.1", 0), lambda: Mock(), {})
        msg_socket.disconnect = Mock()
        messages = [
            (MessageSocket.TYPE_CONTROL, version_msg),
        ]
        msg_socket._recv_one_message = lambda: messages.pop(0)
        try:
            msg_socket.recv_message()
            raise AssertionError("expected exception not raised")
        except ConnectionError, e:
            expected = version_msg.split(" ", 1)[1]
            assert_contains(str(e), expected)
        assert msg_socket.disconnect.called

    @parameterized([
        ({42: "numeric key"}, ),
        ({"numeric value": 42}, ),
    ])
    def test_invalid_version_info(self, version_info):
        try:
            MessageSocket(("127.0.0.1", 0), lambda: None, version_info)
            raise AssertionError("expected exception not raised")
        except ValueError, e:
            assert_contains(str(e), "42")


class TestConnectionPool(object):
    def test_repr(self):
        pool = ConnectionPool(("1.2.3.4", 5678))
        assert_equal(repr(pool), "<ConnectionPool '1.2.3.4:5678' active=0 available=0 created=0 max=32>")
