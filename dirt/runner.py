import os
import sys
import signal
import logging
import itertools
from types import ModuleType

from gevent import Timeout
from setproctitle import setproctitle

from .rpc.client import SimpleClient
from .gevent_ import fork
from .log import setup_logging, ColoredFormatter


log = logging.getLogger(__name__)

class SettingsWrapper(object):
    def __init__(self, *args):
        self.chain = args

    def __getattr__(self, name):
        for link in self.chain:
            if hasattr(link, name):
                return getattr(link, name)

        raise AttributeError("Cannot find {0!r} in settings chain".format(name))


def import_class(to_import):
    if isinstance(to_import, type):
        return to_import
    if "." not in to_import:
        return __import__(to_import)
    mod_name, cls_name = to_import.rsplit(".", 1)
    mod = __import__(mod_name, fromlist=[cls_name])
    return getattr(mod, cls_name)

def list_apps(global_settings):
    for name in dir(global_settings):
        value = getattr(global_settings, name)
        if hasattr(value, 'app_class'):
            yield name.lower()

def app_settings(global_settings, app_name):
    app_settings = getattr(global_settings, app_name.upper(), None)
    if app_settings is None:
        raise ValueError("No settings found for app {0!r}".format(app_name))
    return SettingsWrapper(app_settings, global_settings)

def run_rpc_shell(global_settings, app_name):
    settings = app_settings(global_settings, app_name)
    api = get_api(global_settings.__dict__, app_name, use_bind=True)

    # Make PyFlakes ignore the 'unused' variables
    settings, api = settings, api

    logfile_root = os.path.expanduser("~/.dirt_api_logs/")
    if not os.path.exists(logfile_root):
        print "%r doesn't exist - not logging API calls" %(logfile_root, )
    else:
        logfile = os.path.join(logfile_root, app_name)
        from .rpc import connection
        connection.full_message_log_enable(logfile)
        print "Logging API calls to %r", logfile

    print "access the api using the `api` variable"
    print

    try:
        from IPython.frontend.terminal.embed import embed
        embed()
    except ImportError:
        # compat with older ipython
        from IPython.Shell import IPShellEmbed
        IPShellEmbed(argv='')()

def run(global_settings, argv=None):
    if argv is None:
        argv = sys.argv
    if len(argv) > 2:
        print "error: only one app can be specified"
        return 1
    run_many(global_settings, argv)

def usage(global_settings, argv):
    print (
        "usage: %s [-h|--help] [--shell] [--stop] "
        "{APP_NAME [APP_NAME ...]|./PATH/TO/SCRIPT}"
    ) %(argv[0], )
    print "available apps:"
    print "    " + "\n    ".join(list_apps(global_settings))

def run_many(global_settings, argv=None):
    if argv is None:
        argv = sys.argv

    if "-h" in argv or "--help" in argv:
        usage(global_settings, argv)
        return 0

    if "--list-apps" in argv:
        print "\n".join(list_apps(global_settings))
        return 0

    if "--shell" in argv:
        if len(argv) != 3:
            usage(global_settings, argv)
            return 1
        return run_rpc_shell(global_settings, argv[2])

    global_settings.stop_app = "--stop" in argv
    if global_settings.stop_app:
        global_settings.log_to_hub = False
        argv.remove("--stop")

    if len(argv) < 2:
        usage(global_settings, argv)
        return 1

    class RUN_SETTINGS:
        log_to_hub = False
    logging_settings = SettingsWrapper(RUN_SETTINGS, global_settings)
    setup_logging("run", logging_settings)

    # Check to see if we're running a script
    if "/" in argv[1]:
        argv[0] = "%s %s" %(argv[0], argv[1])
        script_path = argv.pop(1)
        return run_script(global_settings, script_path)

    app_names_settings = [
        (app_name, app_settings(global_settings, app_name))
        for app_name in argv[1:]
    ]

    _get_api_force_no_mock.update(argv[1:])

    app_colors = iter(itertools.cycle(
        ["blue", "magenta", "cyan", "green", "grey", "white"]
    ))

    pid = -1
    try:
        app_pids = {}
        for app_name, settings in app_names_settings:
            app_color = next(app_colors)
            pid = fork()
            if pid > 0:
                app_pids[pid] = app_name
            else:
                os.setsid()
                ColoredFormatter.app_color = app_color
                return run_app(app_name, settings)

        while app_pids:
            try:
                child, status_sig = os.waitpid(-1, 0)
                status = status_sig >> 8
            except KeyboardInterrupt:
                status = 4

            if status == 99:
                app_pids.pop(child, None)
                status = 0
                continue

            if status != 4:
                log_message = (status == 0) and log.info or log.warning
                log_message("app %s exited with status %s",
                            app_pids.get(child, child), status)

            break

    finally:
        pids_to_kill = (pid > 0) and app_pids.keys() or []
        for pid_to_kill in pids_to_kill:
            try:
                os.killpg(pid_to_kill, signal.SIGTERM)
            except OSError as e:
                # errno 3 == "ESRCH" (not found), and we expect to get at least
                #     one of those when we exit as a result of one of the
                #     apps exiting.
                # errno 1 == "EPERM" (permision denied), and this seems
                #     to be related to a specific "issue" related to killing
                #     process groups which contain zombies on Darwin/BSD. It
                #     doesn't seem to come up on Linux, though, and so should
                #     be safe to ignore.
                #     See discussion: http://stackoverflow.com/q/12521705/71522
                if e.errno not in [1, 3]:
                    log.error("killing %r: %s", pid_to_kill, e)
    return status

def run_script(global_settings, script_path):
    dirtscript = ModuleType("dirtscript")
    dirtscript.__dict__.update({
        "settings": global_settings,
    })
    sys.modules["dirtscript"] = dirtscript
    setup_logging(script_path, global_settings)
    execfile(script_path)
    return 0

def run_app(app_name, settings):
    setup_logging(app_name, settings)
    use_reloader = getattr(settings, "USE_RELOADER", False)
    if use_reloader and not settings.stop_app:
        from .reloader import run_with_reloader
        setproctitle("%s-reloader" %(app_name, ))
        return run_with_reloader(lambda: _run(app_name, settings))
    else:
        return _run(app_name, settings)

def setup_blocking_detector(settings):
    timeout = getattr(settings, "BLOCKING_DETECTOR_TIMEOUT", None)
    if not timeout:
        return
    import gevent
    from .gevent_ import BlockingDetector
    raise_exc = getattr(settings, "BLOCKING_DETECTOR_RAISE_EXC", False)
    gevent.spawn(BlockingDetector(timeout=timeout, raise_exc=raise_exc))

def _run(app_name, settings):
    setproctitle(app_name)
    setup_blocking_detector(settings)
    app_class = import_class(settings.app_class)
    app = app_class(app_name, settings)
    return app.run()

def api_is_alive(address):
    # note: defer import of socket in case it's being monkey patched.
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with Timeout(1.0):
            s.connect(address)
    except (socket.error, Timeout):
        return False
    finally:
        s.close()
    return True

# If we are running multiple apis at once, we will know that some will
# exist, even if they aren't running *right now*. This set contains
# the names of those apis.
_get_api_force_no_mock = set()

def get_api(settings_dict, api_name, mock_cls=None, use_bind=False):
    api_settings = settings_dict.get(api_name.upper())
    if not api_settings:
        raise ValueError("unknown or undefined API: %r" %(api_name, ))

    allow_mock = settings_dict.get("ALLOW_MOCK_API")
    if allow_mock:
        allow_mock = not ("NO_MOCK_" + api_name.upper()) in os.environ

    remote = getattr(api_settings, "remote", None)
    if remote is None and use_bind:
        bind = api_settings.bind
        remote = (bind[0] or "localhost", bind[1])

    if allow_mock and api_name not in _get_api_force_no_mock:
        if not mock_cls:
            mock_cls = getattr(api_settings, "mock_cls", None)
        elif remote is None:
            raise Exception("No 'remote' specified for %r" %(api_name, ))
        if mock_cls and not api_is_alive(remote):
            log.warning("%s is not up; using mock API %r for %r",
                        remote, mock_cls, api_name)
            return mock_cls()

    ProxyClass = getattr(api_settings, "rpc_proxy", SimpleClient)
    proxy_args = getattr(api_settings, "rpc_proxy_args", {})
    proxy_args.setdefault("address", remote)
    return ProxyClass(**proxy_args)


def get_api_factory(settings_globals):
    def get_api_factory_helper(*args):
        return get_api(settings_globals(), *args)
    return get_api_factory_helper
