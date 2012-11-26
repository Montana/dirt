
from nose.tools import assert_equal
from mock import Mock

from dirt.rpc.common import Call
from ..client import ResultGenerator, RemoteException, Client

class ClientTestBase(object):
    def setup(self):
        self.release_called = False

    def _release(self, cxn):
        assert not self.release_called
        self.release_called = True
        assert_equal(cxn, self.cxn)
        self.cxn.recv_message.side_effect = Exception("cxn released")

    def set_messages(self, messages):
        messages = [ (m[0], m[1:] and m[1] or None)
                     for m in reversed(messages) ]
        self.cxn.recv_message.side_effect = messages.pop


class TestResultGenerator(ClientTestBase):
    def setup(self):
        super(TestResultGenerator, self).setup()
        self.cxn = None

    def get_gen(self, type, data=None):
        self.cxn = Mock()
        return ResultGenerator(self.cxn, self._release, (type, data))

    def test_zero_length(self):
        gen = self.get_gen("stop")
        try:
            next(gen)
            raise AssertionError("StopIteration not raised")
        except StopIteration:
            pass
        # On a clean close, the connection should be left open
        assert not self.cxn.disconnect.called
        assert self.release_called

    def test_remote_exception(self):
        gen = self.get_gen("raise", 42)
        try:
            next(gen)
            raise AssertionError("RemoteException not raised")
        except RemoteException:
            pass
        # A remote error, however, should cause the connection to be reset
        assert self.cxn.disconnect.called
        assert self.release_called

    def test_unexpected_exception(self):
        gen = self.get_gen("yield", "foo")
        self.cxn.recv_message.side_effect = Exception("ohno")
        assert_equal(next(gen), "foo")
        try:
            next(gen)
            raise AssertionError("Exception not raised")
        except Exception as e:
            assert_equal(str(e), "ohno")
        assert self.cxn.disconnect.called
        assert self.release_called

    def test_normal(self):
        gen = self.get_gen("yield", 1)
        self.set_messages([("yield", 2), ("stop", )])

        assert_equal(list(gen), [1, 2])
        assert not self.cxn.disconnect.called
        assert self.release_called


class TestClient(ClientTestBase):
    def setup(self):
        super(TestClient, self).setup()
        self.client = Client("dirtrpc://mock_server:1234")
        self.client.pool = Mock()
        self.client.pool.release = self._release
        self.released = False
        self.cxn = self.client.pool.get_connection()

    def test_simple_call(self):
        self.set_messages([("return", 42)])
        result = self.client.call(Call("foo", (1,), {"bar": 2}))
        assert_equal(result, 42)
        assert_equal(self.cxn.send_message.call_args_list,
                     [((("call", ("foo", (1, ), {"bar": 2})),), {})])
        assert not self.cxn.disconnect.called
        assert self.release_called

    def test_returns_stop(self):
        self.set_messages([("stop",)])
        result = self.client.call(Call("foo"))
        assert_equal(list(result), [])
        assert not self.cxn.disconnect.called
        assert self.release_called

    def test_returns_yields(self):
        self.set_messages([("yield", 1), ("yield", 2), ("stop", )])
        result = self.client.call(Call("foo"))
        assert_equal(list(result), [1, 2])
        assert not self.cxn.disconnect.called
        assert self.release_called

    def test_raise(self):
        self.set_messages([("raise", "42")])
        try:
            self.client.call(Call("foo"))
            raise AssertionError("RemoteException not raised")
        except RemoteException, e:
            pass
        assert "42" in str(e)
        # note: Because a remote exception puts the server in an unknown state,
        # it will disconnect the connection. It should be disconnected here
        # to speed up the next call.
        assert self.cxn.disconnect.called
        assert self.release_called

    def test_no_want_response(self):
        self.client.call(Call("foo", flags={"want_response": False}))
        assert_equal(self.cxn.recv_message.call_count, 0)
        assert not self.cxn.disconnect.called
        assert self.release_called
    
    def test_repr(self):
        assert_equal(
            repr(self.client),
            "dirt.rpc.proto_drpc.client.Client(remote_url='dirtrpc://mock_server:1234')",
        )
