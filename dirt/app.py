import os
import time
import signal
import logging
import inspect
import functools

from gevent import Timeout
from gevent.lock import BoundedSemaphore, DummySemaphore
from gevent import GreenletExit

from dirt import dt
from dirt.iter import isiter

log = logging.getLogger(__name__)

class DebugAPI(object):
    """ Service debugging API. """

    TIME_STARTED = dt.utcnow()

    def __init__(self, meta):
        self.meta = meta

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

    def api_methods(self):
        """ Returns a list of the methods available on the API. """
        api_methods = self._list_methods(self.meta.get_api())
        return api_methods + [APIMeta.DEBUG_CALL_PREFIX]

    def debug_methods(self):
        """ Returns a list of the methods available on the debug API. """
        methods = self._list_methods(self)
        methods.remove("getdoc")
        return methods

    def active_calls(self):
        """ Returns a description of all the currently active RPC calls. """
        return [
            ("%s:%s" %address, self._call_to_dict(call))
            for (address, call) in self.meta.active_calls
        ]

    def status(self):
        """ Returns some general status information. """
        api_calls = dict(self.meta.call_stats)
        num_pending = len([
            call for call in self.meta.active_calls
            if not call.meta.get("time_in_queue")
        ])
        api_calls.update({
            "pending": num_pending,
            "active": len(self.meta.active_calls) - num_pending,
        })
        return {
            "uptime": str(dt.utcnow() - self.TIME_STARTED),
            "api_calls": api_calls,
        }

    def connection_status(self):
        """ Returns a description of all the active connection pools. """
        return rpc.status() # XXX: ``rpc`` not defined


class APIMeta(object):
    """ The ``APIMeta`` class handles the "meta" aspects of an API;
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
            class Meta(APIMeta):
                call_timeout = 30
                max_concurrent_calls = 5

                def call_method(self, call, method):
                    try:
                        return APIMeta.call_method(self, call, method)
                    catch MyException as e:
                        return (False, str(e))

            class MyAPI(object):
                # The timeout will not be applied when calling ``slow_method``.
                @Meta.no_timeout
                def slow_method(self):
                    gevent.sleep(100)
                    return 42

            class MyApp(DirtApp):
                api_meta = Meta

                def get_api(self, socket, address):
                    return MyAPI()
        """
    DEBUG_CALL_PREFIX = "debug"

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
        if self.call_is_debug(call):
            return DummySemaphore()

        try:
            semaphore = self.app._call_semaphore
        except AttributeError:
            if self.max_concurrent_calls is None:
                semaphore = DummySemaphore()
            else:
                semaphore = BoundedSemaphore(self.max_concurrent_calls)
            self.app._call_semaphore = semaphore
        return semaphore

    def call_is_debug(self, call):
        return call.name.startswith(self.DEBUG_CALL_PREFIX + ".")

    def get_debug_api(self):
        return self.app.get_debug_api(self)

    def get_api(self, call_info):
        return  self.app.get_api(call_info)

    def execute(self, call):
        method = self.lookup_method(call)
        if method is None:
            raise expected(ValueError("invalid method: %r" %(call.name, ))) # XXX: expected undefined
        return self.call_method(call, method)

    def lookup_method(self, call):
        """ Looks up a method for an RPC call (part of ``ConnectionHandler``'s
            ``call_handler`` interface). Returns either the method (which will be
            passed to ``call_method`` or ``None``.
            """

        name = call.name
        if self.call_is_debug(call):
            name = name.split(".", 1)[1]
            api = self.get_debug_api()
        else:
            api = self.get_api(call)

        if name.startswith("_"):
            return None

        suffix = None
        if "." in name:
            name, suffix = name.split(".", 1)

        result = getattr(api, name, None)
        if suffix is not None:
            result = self.lookup_method_with_suffix(call, result, suffix)
        return result

    def lookup_method_with_suffix(self, call, method, suffix):
        if suffix != "getdoc":
            return None
        return lambda: inspect.getdoc(method)

    def call_method(self, call, method):
        """ Calls a method for an RPC call (part of ``ConnectionHandler``'s
            ``call_handler`` interface).
            """
        timeout = None
        if self.call_timeout is not None:
            timeout = Timeout(getattr(method, "_timeout", self.call_timeout))

        call_semaphore = self._get_call_semaphore(call)
        if call_semaphore.locked():
            log.warning("too many concurrent callers (%r); "
                        "call from %r to %r will block",
                        self.max_concurrent_calls, self.address, call.name)

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
            result = method(*call.args, **call.kwargs)
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
        """ Decorates a function function, telling ``APIMeta`` that a timeout
            should not be used for calls to this method (for example, because
            it returns a generator). """
        f._timeout = None
        return f

    def serve(self):
        self.settings.rpc_class(self, self.settings)

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
    edge_class = APIMeta
    debug_api_class = DebugAPI

    def __init__(self, app_name, settings):
        self.app_name = app_name
        self.settings = settings
        self.edge = self.edge_class(self, self.settings)

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
        log.info("binding to %s:%s" %self.settings.bind)
        self.edge.serve()

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

    def get_api(self, call_info):
        raise Exception("Subclasses must implement the 'get_api' method.")

    def get_debug_api(self, meta):
        return self.debug_api_class(meta)


def runloop(log, sleep=time.sleep):
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

    """

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
            except GreenletExit:
                log.debug("%r stopping due to GreenletExit", func)
                raise
            except Exception:
                sleep_time = get_sleep_time(start_time)
                log_suffix = "restarting in %s..." %(sleep_time, )

                log.exception("%r raised unexpected exception; %s",
                              func, log_suffix)
            sleep(sleep_time)

    def runloop_return(f):
        runloop_wrapper.wrapped_func = f
        return functools.wraps(f)(runloop_wrapper)


    return runloop_return

runloop.done = object()

