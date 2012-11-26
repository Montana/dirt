from nose.tools import assert_equal
from mock import Mock

from dirt.app import APIEdge
from dirt.testing import parameterized

from ..server import ConnectionHandler


class MockApp(object):
    api_handlers = {
        "": "get_api",
    }

    def __init__(self, api):
        self.api = api

    def get_api(self, socket, address):
        return self.api


class TestConnectionHandler(object):
    def setup(self):
        self.api = Mock()
        self.cxn = Mock()
        self.edge = APIEdge(MockApp(self.api), None)
        self.handler = ConnectionHandler(self.edge.execute)
        self.handler.client = ("mock_peer", 1234)
        self.handler.cxn = self.cxn

    def set_next_message(self, type, data):
        self.cxn.recv_message.return_value = (type, data)

    def test_call_normal(self):
        self.set_next_message("call", ("foo", [], {}))
        self.handler._handle_one_message()
        assert_equal(self.cxn.send_message.call_args,
                     ((("return", self.api.foo()),), {}))

    def test_call_normal_no_response(self):
       self.set_next_message("call_ignore", ("foo", [], {}))
       self.handler._handle_one_message()
       assert_equal(self.cxn.send_message.call_count, 0)

    test_iterables = [
        ([1, 2], [("return", [1, 2])]),
        ("foo", [("return", "foo")]),
        ({"a": 1}, [("return", {"a": 1})]),
        (iter([]), [("stop", )]),
        (iter([1]), [("yield", 1), ("stop", )]),
    ]

    @parameterized(test_iterables)
    def test_call_returns_iterable(self, iterable, expected):
        self.api.foo.return_value = iterable
        self.set_next_message("call", ("foo", [], {}))
        self.handler._handle_one_message()
        actual = [args[0] for (args, kwargs)
                  in self.cxn.send_message.call_args_list]
        assert_equal(actual, expected)

    def _run_exception_test(self, call):
        self.api.foo.side_effect = Exception("ohai")
        self.set_next_message(call, ("foo", [], {}))
        try:
            self.handler._handle_one_message()
            raise AssertionError("Exception not raised")
        except Exception, e:
            if str(e) != "ohai":
                raise

    def test_call_exception(self):
        self._run_exception_test("call")
        assert_equal(self.cxn.send_message.call_args,
                     ((("raise", repr(self.api.foo.side_effect)),), {}))

    def test_call_exception_no_response(self):
        self._run_exception_test("call_ignore")
        assert_equal(self.cxn.send_message.call_count, 0)

    def test_shutdown_called(self):
        self.handler._handle_one_message = Mock(side_effect=Exception("ohai"))
        self.handler._shutdown = Mock()
        try:
            self.handler.accept(Mock(), ("dummy", 1234))
            raise AssertionError("Exception not raised")
        except Exception, e:
            if str(e) != "ohai":
                raise
        assert self.handler._shutdown.called
