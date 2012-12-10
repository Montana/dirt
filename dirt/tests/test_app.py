import os
import logging

from mock import Mock
from nose.tools import assert_equal, assert_raises
import gevent
from gevent.event import Event
from gevent import GreenletExit


from dirt.rpc.common import expected, Call
from dirt.testing import (
    assert_contains, parameterized, assert_logged,
    setup_logging, teardown_logging,
)

from ..app import runloop, APIEdge, PIDFile, DirtApp

log = logging.getLogger(__name__)


class XXXTestBase(object):
    # NOTE: This should probably be moved around or something!

    # Subclasses can specify a ``settings`` dict, which will be merged with the
    # "SETTINGS" object returned by ``get_settings``
    settings = {}

    def setup(self):
        self._settings = None
        setup_logging()

    def setUp(self):
        super(XXXTestBase, self).setUp()
        self.setup()

    def teardown(self):
        teardown_logging()

    def tearDown(self):
        super(XXXTestBase, self).tearDown()
        self.teardown()

    @classmethod
    def build_settings(self):
        class MOCK_SETTINGS:
            get_api = Mock()
            engine = None
        MOCK_SETTINGS.__dict__.update(self.settings)
        return MOCK_SETTINGS

    def get_settings(self):
        if self._settings is None:
            self._settings = self.build_settings()
        return self._settings


class MockApp(object):
    api_handlers = {
        "": "get_api",
        "debug": "mock_debug_api",
    }

    def __init__(self, api=None, debug_api=None):
        self.api = api or Mock()
        self.debug_api = debug_api or Mock()

    def get_api(self, edge, call):
        return self.api

    def mock_debug_api(self, edge, call):
        return self.debug_api


class GotSleep(Exception):
    @classmethod
    def mock(cls):
        sleep = Mock()
        sleep.side_effect = cls()
        return sleep


class TestRunloop(object):
    def test_bad_use(self):
        try:
            runloop(42)
        except ValueError, e:
            assert_contains(str(e), "@runloop(log)")
        else:
            raise AssertionError("ValueError not raised")

    def test_loops(self):
        results = [3, 2, 1]
        sleep = Mock()
        @runloop(log, sleep=sleep)
        def run():
            if not results:
                sleep.side_effect = GotSleep()
            return results.pop()

        assert_raises(GotSleep, run)
        assert_equal(results, [])

    def test_normal_return(self):
        @runloop(log, sleep=GotSleep.mock())
        def run(input):
            return input
        assert_raises(GotSleep, run)

    @parameterized([
        ("keyboard interrupt", KeyboardInterrupt()),
        ("system exit", SystemExit()),
        ("greenlet exit", GreenletExit()),
    ])
    def test_expected_errors(self, name, exception):
        @runloop(log)
        def run():
            raise exception
        assert_raises(type(exception), run)

    @parameterized([
        ("expected exc", expected(Exception("expected exception"))),
        ("unexpected exc", Exception("unexpected exception")),
        ("gevent.Timeout", gevent.Timeout()),
    ])
    def test_restart_on_exception(self, name, exception):
        @runloop(log, sleep=GotSleep.mock())
        def run():
            raise exception
        assert_raises(GotSleep, run)


class TestAPIEdge(XXXTestBase):
    def assert_edge_clean(self, edge):
        assert_equal(edge._call_semaphore.counter,
                     edge.max_concurrent_calls)

    def test_normal_call(self):
        edge = APIEdge(MockApp(), self.get_settings())
        api = edge.app.api
        call = Call("foo")

        assert_equal(edge.get_call_handler(call), (api, "foo"))
        assert_equal(edge.get_call_handler_method(call, api, "foo"), api.foo)

        edge.execute(call)
        assert_equal(api.foo.call_count, 1)
        self.assert_edge_clean(edge)

    def test_debug_call(self):
        edge = APIEdge(MockApp(), self.get_settings())
        debug_api = edge.app.debug_api
        call = Call("debug.foo")

        edge.execute(call)
        assert_equal(debug_api.foo.call_count, 1)
        assert_equal(edge._call_semaphore, None)

    def test_timeout(self):
        edge = APIEdge(MockApp(), self.get_settings())
        edge.call_timeout = 0.0
        edge.app.api.foo = lambda: gevent.sleep(0.1)

        try:
            edge.execute(Call("foo"))
            raise AssertionError("timeout not raised!")
        except gevent.Timeout:
            pass
        self.assert_edge_clean(edge)

    def test_no_timeout_decorator(self):
        app = MockApp()
        edge = APIEdge(app, self.get_settings())
        app.api.foo = edge.no_timeout(Mock())
        edge.execute(Call("foo"))
        assert_equal(app.api.foo.call_count, 1)
        self.assert_edge_clean(edge)

    def test_semaphore(self):
        edge = APIEdge(MockApp(), self.get_settings())
        api = edge.app.api
        edge.max_concurrent_calls = 1

        in_first_method = Event()
        finish_first_method = Event()
        def first_method():
            in_first_method.set()
            finish_first_method.wait()
        api.first_method = first_method

        in_second_method = Event()
        def second_method():
            in_second_method.set()
        api.second_method = second_method

        gevent.spawn(edge.execute, Call("first_method"))
        in_first_method.wait()

        gevent.spawn(edge.execute, Call("second_method"))
        gevent.sleep(0)

        assert_logged("too many concurrent callers")
        assert not in_second_method.is_set()

        finish_first_method.set()
        in_second_method.wait()
        self.assert_edge_clean(edge)


class TestDebugAPI(XXXTestBase):
    def test_normal_call(self):
        app = DirtApp("test_normal_call", self.get_settings(), [])
        edge = APIEdge(app, app.settings)
        call = Call("debug.status", (), {}, {})
        result = edge.execute(call)
        assert_contains(result, "uptime")

    def test_error_call(self):
        app = DirtApp("test_normal_call", self.get_settings(), [])
        edge = APIEdge(app, app.settings)
        call = Call("debug.ping", (), {"raise_error": True}, {})
        try:
            edge.execute(call)
            raise AssertionError("exception not raised")
        except Exception as e:
            if not str(e).startswith("pong:"):
                raise


class TestPIDFILE(object):
    def setup(self):
        self.filename = "/tmp/%s-test-pidfile" %(__name__, )

    def teardown(self):
        if os.path.exists(self.filename):
            os.unlink(self.filename)

    def test_invalid_file(self):
        open(self.filename, "w").write("foo")
        pf = PIDFile(self.filename)
        assert_equal(pf.check(), None)
        pf.write()

    def test_write_pid(self):
        pf = PIDFile(self.filename)
        pf.write()
        assert_equal(os.getpid(), pf.check())

    def test_pid_does_not_exist(self):
        open(self.filename, "w").write("2")
        pf = PIDFile(self.filename)
        assert_equal(None, pf.check())
