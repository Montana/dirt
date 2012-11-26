import os
import logging

from mock import Mock
from nose.tools import assert_equal, assert_raises
import gevent
from gevent.event import Event
from gevent import GreenletExit


from dirt.rpc.common import expected, Call as _Call
from dirt.testing import (
    assert_contains, parameterized, assert_logged,
    setup_logging, teardown_logging,
)

from ..app import runloop, APIMeta, PIDFile, DirtApp

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
    def __init__(self, api=None, debug_api=None):
        self.api = api or Mock()
        self.debug_api = debug_api or Mock()

    def get_api(self, socket, address):
        return self.api

    def get_debug_api(self, meta):
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

    def test_greenlet_exit(self):
        @runloop(log)
        def run():
            raise GreenletExit()
        assert_raises(GreenletExit, run)

    @parameterized([
        expected(Exception("expected exception")),
        Exception("unexpected exception"),
    ])
    def test_restart_on_exception(self, exception):
        @runloop(log, sleep=GotSleep.mock())
        def run():
            raise exception
        assert_raises(GotSleep, run)


class Call(_Call):
    def __init__(self, name, args=None, kwargs=None, flags=None):
        super(Call, self).__init__(name, args or (), kwargs or {}, flags or [])


class TestAPIMeta(XXXTestBase):
    def Meta(self, **meta_dict):
        return type("Meta", (APIMeta, ), meta_dict)

    def assert_meta_clean(self, meta):
        assert_equal(meta.app._call_semaphore.counter,
                     meta.max_concurrent_calls)

    def test_normal_call(self):
        Meta = self.Meta()
        meta = Meta(MockApp(), self.get_settings())
        api = meta.app.api
        call = Call("foo")

        assert_equal(meta.lookup_method(call), api.foo)

        meta.call_method(call, api.foo)
        assert_equal(api.foo.call_count, 1)
        self.assert_meta_clean(meta)

    def test_debug_call(self):
        Meta = self.Meta()
        meta = Meta(MockApp(), self.get_settings())
        debug_api = meta.app.debug_api
        call = Call("debug.foo")

        assert_equal(meta.lookup_method(call), debug_api.foo)

        meta.call_method(call, debug_api.foo)
        assert_equal(debug_api.foo.call_count, 1)
        assert_equal(meta._call_semaphore, None)

    def test_timeout(self):
        Meta = self.Meta(call_timeout=0.0)
        meta = Meta(MockApp(), self.get_settings())

        foo = lambda: gevent.sleep(0.01)
        try:
            meta.call_method(Call("foo"), foo)
            raise AssertionError("timeout not raised!")
        except gevent.Timeout:
            pass
        self.assert_meta_clean(meta)

    def test_no_timeout_decorator(self):
        Meta = self.Meta(call_timeout=0.0)
        meta = Meta(MockApp(), self.get_settings())

        foo = meta.no_timeout(Mock())
        meta.call_method(Call("foo"), foo)
        assert_equal(foo.call_count, 1)
        self.assert_meta_clean(meta)

    def test_semaphore(self):
        Meta = self.Meta(max_concurrent_calls=1)

        in_first_method = Event()
        finish_first_method = Event()
        def first_method():
            in_first_method.set()
            finish_first_method.wait()

        in_second_method = Event()
        def second_method():
            in_second_method.set()

        app = MockApp()
        meta0 = Meta(app, self.get_settings())
        gevent.spawn(meta0.call_method, Call("first_method"), first_method)
        in_first_method.wait()

        meta1 = Meta(app, self.get_settings())
        gevent.spawn(meta1.call_method, Call("second_method"), second_method)
        gevent.sleep(0)

        assert_logged("too many concurrent callers")
        assert not in_second_method.is_set()

        finish_first_method.set()
        in_second_method.wait()
        self.assert_meta_clean(meta0)
        self.assert_meta_clean(meta1)


class TestDebugAPI(XXXTestBase):
    def test_normal_call(self):
        app = DirtApp("test_normal_call", [], self.get_settings())
        meta = APIMeta(app, app.settings)
        call = Call("debug.status", (), {}, {})
        method = meta.lookup_method(call)
        result = meta.call_method(call, method)
        assert_contains(result, "uptime")

    def test_error_call(self):
        app = DirtApp("test_normal_call", [], self.get_settings())
        meta = APIMeta(app, app.settings)
        call = Call("debug.ping", (), {"raise_error": True}, {})
        method = meta.lookup_method(call)
        try:
            meta.call_method(call, method)
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
