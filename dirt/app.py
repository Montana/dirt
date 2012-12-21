import os
import time
import signal
import logging
import inspect
import functools

from gevent import Timeout
from gevent.lock import BoundedSemaphore, DummySemaphore
from gevent import GreenletExit

from dirt import rpc
from dirt.rpc.common import Call
from dirt.misc.iter import isiter
from dirt.misc.gevent_ import AlarmInterrupt

log = logging.getLogger(__name__)


class DebugAPI(object):
    """ Service debugging API. """

    TIME_STARTED = time.time()

    def __init__(self, edge, call):
        self.edge = edge
        self.call = call
        self.app = edge.app

    def _list_methods(self, obj):
        """ Lists the methods available on ``obj``. """
        return [
            name for name in dir(obj)
            if not name.startswith("_") and callable(getattr(obj, name))
        ]

    def _call_to_dict(self, call):
        """ Converts an instance of ``Call`` to a dict which will be returned
            from ``active_calls``. """
        call_dict = dict(call.__dict__)
        call_dict["meta"] = dict(call.meta)
        call_dict["meta"]["age"] = time.time() - call.meta["time_received"]
        return call_dict

    def getdoc(self):
        """ Returns the docstring for ``self``. For iPython compatibility. """
        return inspect.getdoc(self)

    def ping(self, raise_error=False):
        """ Returns ``time.time()``, unless ``raise_error`` is ``True``, in
            which case an exception is raised. """
        result = "pong: %s" %(time.time(), )
        if raise_error:
            raise Exception(result)
        return result

    def list_methods(self, prefix=""):
        """ Returns a list of the methods available on the API. """
        handlers = [
            handler_prefix + "." for handler_prefix in self.app.api_handlers
            if (
                handler_prefix and
                handler_prefix.startswith(prefix) and
                handler_prefix != prefix
            )
        ]
        dummy_call = Call(prefix + "._list_methods_dummy_method")
        handler, _ = self.edge.get_call_handler(dummy_call)
        methods = self._list_methods(handler)
        return handlers + methods

    def active_calls(self): # XXX re-write this
        """ Returns a description of all the currently active RPC calls. """
        return [
            ("%s:%s" %address, self._call_to_dict(call))
            for (address, call) in self.meta.active_calls
        ]

    def status(self):
        """ Returns some general status information. """
        api_calls = dict(self.edge.call_stats)
        num_pending = len([
            call for call in self.edge.active_calls
            if not call.meta.get("time_in_queue")
        ])
        api_calls.update({
            "pending": num_pending,
            "active": len(self.edge.active_calls) - num_pending,
        })
        return {
            "uptime": str(time.time() - self.TIME_STARTED),
            "api_calls": api_calls,
        }

    def connection_status(self):
        """ Returns a description of all the active connection pools. """
        return rpc.status() # XXX: ``rpc`` not defined


class APIEdge(object):
    """ The ``APIEdge`` class handles the "meta" aspects of an API;
        specificailly, looking up and calling methods.

        The default implementation also includes the option to set a call
        timeout, and limit the number of concurrent API calls.

        The ``timeout = None`` attribute can be used to limit the amount of
        time (in seconds) that will be spent in method calls. Note that this
        timeout does *not* apply to time spent waiting to acquire the call
        semaphore. A value of ``None`` (default) means that calls will not time
        out.

        The ``max_concurrent_calls = 32`` attribute limits the total number of
        concurrent calls that will be allowed to access the API. A value of
        ``None`` disables concurrent call limiting. Note that the semiphore is
        a class attribute, not an instance attribute.

        For example::

            # Limit calls to 30 seconds with a maximum of 5 concurrent calls.
            # Additionally, catch instances of ``MyException``, and instead
            # return a tuple of ``(False, str(e))``
            class APIEdge(dirt.APIEdge):
                call_timeout = 30
                max_concurrent_calls = 5

                def execute(self, call):
                    try:
                        return APIEdge.execute(self, call)
                    catch MyException as e:
                        return (False, str(e))

            class MyAPI(object):
                # The timeout will not be applied when calling ``slow_method``.
                @APIEdge.no_timeout
                def slow_method(self):
                    gevent.sleep(100)
                    return 42

            class MyApp(DirtApp):
                edge_class = APIEdge

                def get_api(self, edge, call):
                    return MyAPI()
        """

    call_timeout = None
    max_concurrent_calls = 64

    active_calls = []
    call_stats = {
        "completed": 0,
        "errors": 0,
    }

    _call_semaphore = None

    def __init__(self, app, settings):
        self.app = app
        self.settings = settings

    def _get_call_semaphore(self, call):
        if call.name.startswith("debug."): # XXX A bit of a hack
            return DummySemaphore()
        if self._call_semaphore is None:
            if self.max_concurrent_calls is None:
                semaphore = DummySemaphore()
            else:
                semaphore = BoundedSemaphore(self.max_concurrent_calls)
            self._call_semaphore = semaphore
        return self._call_semaphore

    def get_call_callable(self, call):
        handler, method_name = self.get_call_handler(call)
        return self.get_call_handler_method(call, handler, method_name)

    def get_call_handler(self, call):
        """ Returns a tuple of ``(handler, method_name)``, where ``handler``
            is an object (probably an instance of an API class) which may
            have a method ``method_name``. Mapping the ``method_name`` to
            a concrete method is done by ``get_call_handler_method``. """
        prefix, _, method_name = call.name.rpartition(".")
        handler_callable = self.app.api_handlers.get(prefix, None)
        if not handler_callable:
            raise ValueError("no handlers registered on %r for %r"
                             %(self.app, prefix))
        if isinstance(handler_callable, basestring):
            handler_callable = getattr(self.app, handler_callable)
        return (handler_callable(self, call), method_name)

    def get_call_handler_method(self, call, handler, method_name):
        """ Returns the callable method of ``handler``, looked up using
            ``method_name``, which should be used to handle ``call``. """
        method = None
        if not method_name.startswith("_"):
            method = getattr(handler, method_name, None)
        if method is None:
            raise ValueError("no method %r on handler %r"
                             %(method_name, handler))
        return method

    def execute(self, call):
        """ Calls a method for an RPC call (part of ``ConnectionHandler``'s
            ``call_handler`` interface).
            """
        callable = self.get_call_callable(call)
        timeout = None
        if self.call_timeout is not None:
            timeout = Timeout(getattr(callable, "_timeout", self.call_timeout))

        call_semaphore = self._get_call_semaphore(call)
        if call_semaphore.locked():
            log.warning("too many concurrent callers (%r); call %r will block",
                        self.max_concurrent_calls, call)

        call_semaphore.acquire()
        def finished_callback(is_error):
            self.active_calls.remove(call)
            self.call_stats["completed"] += 1
            if is_error:
                self.call_stats["errors"] += 1
            call_semaphore.release()
            if timeout is not None:
                timeout.cancel()

        got_err = True
        result_is_generator = False
        try:
            if timeout is not None:
                timeout.start()
            time_in_queue = time.time() - call.meta.get("time_received", 0)
            call.meta["time_in_queue"] = time_in_queue
            self.active_calls.append(call)
            result = callable(*call.args, **call.kwargs)
            if isiter(result):
                result = self.wrap_generator_result(call, result,
                                                    finished_callback)
                result_is_generator = True
            got_err = False
        finally:
            if not result_is_generator:
                finished_callback(is_error=got_err)

        return result

    def wrap_generator_result(self, call, result, finished_callback):
        got_err = True
        try:
            call.meta["yielded_items"] = 0
            for item in result:
                call.meta["yielded_items"] += 1
                yield item
            got_err = False
        finally:
            finished_callback(is_error=got_err)

    @classmethod
    def no_timeout(cls, f):
        """ Decorates a function function, telling ``APIEdge`` that a timeout
            should not be used for calls to this method (for example, because
            it returns a generator). """
        f._timeout = None
        return f

    def serve_forever(self):
        ServerCls = rpc.get_server_cls(self.settings.bind_url)
        server = ServerCls(self.settings.bind_url, self.execute)
        server.serve_forever()


class PIDFile(object):
    def __init__(self, path):
        self.path = path

    def check(self):
        """ Returns either the PID from ``self.path`` if the process is
            running, otherwise ``None``. """
        piddir = os.path.dirname(self.path)
        if not os.path.exists(piddir):
            try:
                os.mkdir(piddir)
            except OSError as e:
                if e.errno not in [17, 21]:
                    raise
                # Ignore errors:
                # [Errno 17] File exists: '/tmp'
                # [Errno 21] Is a directory: '/'

        cur_pid = None
        try:
            with open(self.path) as f:
                cur_pid_str = f.read().strip()
            try:
                cur_pid = int(cur_pid_str)
            except ValueError:
                log.info("invalid pid found in %r: %r; ignoring",
                         self.path, cur_pid_str)
        except IOError as e:
            if e.errno != 2:
                raise

        if cur_pid is not None:
            if not self.is_pid_active(cur_pid):
                cur_pid = None
        return cur_pid

    def is_pid_active(self, pid):
        try:
            os.kill(pid, signal.SIGWINCH)
            return True
        except OSError as e:
            if e.errno != 3:
                raise
            return False

    def kill(self, pid, timeout=5.0, aggressive=False):
        """ Tries to kill ``pid`` gracefully. If ``aggressive`` is ``True``
            and graceful attempts to stop the process fail, a ``SIGKILL``
            (``kill -9``) will be sent. """
        for signame in ["SIGTERM", "SIGKILL"]:
            start_time = time.time()
            os.kill(pid, getattr(signal, signame))
            while time.time() < (start_time + timeout):
                time.sleep(0.01)
                if not self.is_pid_active(pid):
                    log.info("%s killed with %s after %0.02f seconds",
                             pid, signame, time.time() - start_time)
                    return True
            if not aggressive:
                break
            log.warning("%s failed to kill %s after %s seconds",
                        signame, pid, timeout)
        return False

    def write(self):
        """ Writes the current PID to ``self.path``. """
        with open(self.path, "w") as f:
            f.write("%s\n" %(os.getpid(), ))


class DirtApp(object):
    edge_class = APIEdge

    api_handlers_defaults = {
        "": "get_api",
        "debug": DebugAPI,
    }
    api_handlers = {}

    def __init__(self, app_name, settings, app_argv=None):
        self.app_name = app_name
        self.settings = settings
        self.app_argv = app_argv or []
        self.api_handlers = self._get_api_handlers()
        self.edge = self.edge_class(self, self.settings)

    def _get_api_handlers(self):
        """ Returns a dictionary of API handlers, created by merging
            ``cls.api_handlers`` into ``cls.api_handlers_defaults``.
            Should probably only be called from ``__init__``. """
        cls = type(self)
        handlers = dict(cls.api_handlers_defaults)
        handlers.update(cls.api_handlers)
        return handlers

    def run(self):
        try:
            result = self.pre_setup()
            if result is not None:
                return result
            self.setup()
            self.start()
            self.serve()
        except:
            log.exception("error encountered while trying to run %r:",
                          self.app_name)
            return 1

    def serve(self):
        log.info("binding to %s..." %(self.settings.bind_url, ))
        self.edge.serve_forever()

    def pidfile_path(self):
        pidfile_path_tmpl = getattr(self.settings, "DIRT_APP_PIDFILE", None)
        if pidfile_path_tmpl is None:
            return None
        return pidfile_path_tmpl.format(app_name=self.app_name)

    def pidfile_check(self):
        pidfile_path = self.pidfile_path()
        if pidfile_path is None:
            return

        pidfile = PIDFile(pidfile_path)
        cur_pid = pidfile.check()
        if self.settings.stop_app:
            if cur_pid:
                pidfile.kill(cur_pid, aggressive=True)
            else:
                log.info("doesn't appear to be running; not stopping.")
            return 99
        if cur_pid:
            log.error("%r suggests another instance is running at %r" %(
                pidfile_path, cur_pid
            ))
            return 1
        pidfile.write()

    def pre_setup(self):
        result = self.pidfile_check()
        if self.settings.stop_app:
            result = result or 0
        return result

    def setup(self):
        """ Sets up the application but doesn't "start" anything.

            Especially useful when writing unit tests.

            Subclasses can implement this method without calling super(). """

    def start(self):
        """ Starts any background threads needed for this app.

            Assumes that ``.setup()`` has already been called.

            This distinction is useful when writing unit tests.

            Subclasses can implement this method without calling super(). """

    def get_api(self, edge, call):
        raise Exception("Subclasses must implement the 'get_api' method.")


RUNLOOP_DEFAULT_RE_RAISE_EXCEPTIONS = [
    SystemExit, KeyboardInterrupt, GreenletExit, AlarmInterrupt,
]

def runloop(log, sleep=time.sleep,
            re_raise_exc=None, re_raise_exc_use_defaults=True):
    """ A decorator which makes a function run forever, logging any errors::

            log = logging.getLogger("example")

            @runloop(log)
            def run_echo_server(socket):
                while 1:
                    line = socket.readline().strip()
                    if line == "quit":
                        return 0
                    socket.write(line)

        The ``runloop.done`` sentinal can be returned to break out of the
        runloop::

            @runloop(log)
            def exiting_runloop():
                return runloop.done

        By default, ``runloop`` will catch all subclasses of ``BaseException``,
        except for ``SystemExit``, ``KeyboardInterrupt``, and ``GreenletExit``
        (see ``RUNLOOP_DEFAULT_RE_RAISE_EXCEPTIONS``). The ``re_raise_exc``
        argument can be supplied, and exception types listed there will also be
        re-raised::

            @runloop(log, re_raise_exc=(MyException, ))
            def my_exception_not_caught():
                # The runloop will not catch ``MyException``
                ...

         Additionally, the ``re_raise_exc_use_defaults`` flag can be set to
         ``False`` to ignore the default list of exceptions::

            @runloop(log, re_raise_exc_use_defaults=False)
            def all_exceptions_caught():
                # All exceptions (including ``KeyboardInterrupt`` and
                # ``SystemExit``) will be caught; this function will never
                # exit.
                ...
    """

    re_raise_exc = tuple(
        list(re_raise_exc or []) +
        list(re_raise_exc_use_defaults and RUNLOOP_DEFAULT_RE_RAISE_EXCEPTIONS or [])
    )

    if not all(callable(getattr(log, x, None)) for x in ["info", "exception"]):
        raise ValueError((
            "The `runloop` decorator must be passed a logger (and %r "
            "doesn't appear to be a logger). Did you use `@runloop` instead "
            "of `@runloop(log)`?"
        ) %(log, ))

    def get_sleep_time(start_time):
        end_time = time.time()
        delta = end_time - start_time
        # If the function returned quickly, sleep for a little while before
        # letting it start again.
        if delta < 5:
            return 15
        # Otherwise let it go again fairly quickly.
        return 1

    def runloop_wrapper(*args, **kwargs):
        func = runloop_wrapper.wrapped_func
        while 1:
            # This *should* be set below... But set it here to make absolutely
            # sure we don't hit a bug because it isn't defined.
            sleep_time = 10

            try:
                start_time = time.time()
                result = func(*args, **kwargs)
                if result is runloop.done:
                    return
                sleep_time = get_sleep_time(start_time)
                log.info("%r returned %r; restarting in %s...",
                         func, result, sleep_time)
            except re_raise_exc as e:
                log.debug("%r stopping due to %r", func, e)
                raise
            except BaseException as e:
                sleep_time = get_sleep_time(start_time)
                log.exception("%r raised unexpected exception; "
                              "restarting in %s...", func, sleep_time)
            sleep(sleep_time)

    def runloop_return(f):
        runloop_wrapper.wrapped_func = f
        return functools.wraps(f)(runloop_wrapper)


    return runloop_return

runloop.done = object()

