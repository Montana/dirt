import os
import sys
import signal
import logging
import itertools
from types import ModuleType

import gevent
from setproctitle import setproctitle

from dirt import rpc
from dirt.misc.gevent_ import fork
from dirt.rpc.common import ClientWrapper
from dirt.reloader import run_with_reloader
from dirt.misc.imp_ import instance_or_import
from dirt.misc.gevent_ import BlockingDetector
from dirt.log import AppNameInjector, ColoredFormatter
from dirt.misc.dictconfig import dictConfig as loggingDictConfig

log = logging.getLogger(__name__)

class SettingsWrapper(object):
    def __init__(self, *args):
        self.chain = args

    def __getattr__(self, name):
        for link in self.chain:
            if hasattr(link, name):
                return getattr(link, name)
        raise AttributeError("Cannot find {0!r} in settings chain".format(name))


class DirtRunner(object):
    def __init__(self, settings):
        self.settings = settings
        self.app_colors = iter(itertools.cycle(
            ["blue", "magenta", "cyan", "green", "grey", "white"]
        ))

    def list_apps(self):
        apps = []
        for name in dir(self.settings):
            value = getattr(self.settings, name)
            if hasattr(value, "app_class"):
                apps.append(name.lower())
        return apps

    def get_app_settings(self, app_name):
        app_settings = getattr(self.settings, app_name.upper(), None)
        if app_settings is None:
            raise ValueError("No settings found for app {0!r}".format(app_name))
        return SettingsWrapper(app_settings, self.settings)

    def run_rpc_shell(self, app_name):
        settings = self.get_app_settings(app_name)
        api = self.get_api(self.settings.__dict__, app_name, use_bind=True)

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

    def usage(self, argv):
        print (
            "usage: %s [-h|--help] [--shell] [--stop] "
            "{APP_NAME [APP_NAME ...]|./PATH/TO/SCRIPT}"
        ) %(argv[0], )
        print "available apps:"
        print "    " + "\n    ".join(self.list_apps())

    def parse_argv(self, argv):
        if not argv:
            raise ValueError('No args passed in')

        class CountApps(object):
            counter = 0
            def __call__(self, arg):
                if not arg.startswith('-'):
                    self.counter += 1
                return self.counter

        argv_groups = [
            list(group[1])
            for group in itertools.groupby(argv, CountApps())]

        if argv_groups:
            return argv_groups[0], argv_groups[1:]
        else:
            return [], []

    def handle_argv(self, argv):
        if "-h" in argv or "--help" in argv:
            self.usage(argv)
            return 0

        if "--list-apps" in argv:
            print "\n".join(self.list_apps())
            return 0

        if "--shell" in argv:
            if len(argv) != 3:
                self.usage(argv)
                return 1
            return self.run_rpc_shell(argv[2])

        self.settings.stop_app = "--stop" in argv
        if self.settings.stop_app:
            self.settings.log_to_hub = False
            argv.remove("--stop")

        return None

    def run_many(self, *a, **kw):
        import warnings
        warnings.warn("'runner.run_many' is deprectated; "
                      "'runner.run' should be used instead")
        return self.run(*a, **kw)

    def run(self, argv=None):
        if argv is None:
            argv = sys.argv

        run_argv, app_argvs = self.parse_argv(argv)
        ret = self.handle_argv(run_argv)
        if ret is not None:
            return ret

        if not app_argvs:
            self.usage(argv)
            return 1

        class RUN_SETTINGS:
            log_to_hub = False
        logging_settings = SettingsWrapper(RUN_SETTINGS, self.settings)
        self.setup_logging("run", logging_settings)

        self._get_api_force_no_mock.update(argv[1:])

        try:
            parent_proc = False
            app_pids = self.fork_and_run_many(run_argv, app_argvs)

            # Because the child processes started by 'fork_and_run_many' will
            # raise a 'SystemExit' when they exit, they will hit the 'finally'
            # block below, but 'parent_proc' will be False at that point, so no
            # cleanup will be attempted.
            parent_proc = True

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
                    log_message("%r exited with status %s",
                                app_pids.get(child, child), status)

                break

        finally:
            pids_to_kill = parent_proc and app_pids.keys() or []
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

    def fork_and_run_many(self, run_argv, app_argvs):
        app_pids = {}
        for app_argv in app_argvs:
            app_name, app_argv = app_argv[0], app_argv[1:]
            pid = self.fork_and_run_one(run_argv, app_name, app_argv)
            app_pids[pid] = app_name
        return app_pids

    def fork_and_run_one(self, run_argv, app_name, app_argv):
        app_color = next(self.app_colors)
        pid = fork()
        if pid > 0:
            return pid

        os.setsid()
        ColoredFormatter.app_color = app_color
        result = self.run_one(run_argv, app_name, app_argv)
        sys.exit(result)

    def run_one(self, run_argv, app_name, app_argv):
        if "/" in app_name:
            fake_argv = [run_argv[0], app_name] + app_argv
            result = self.run_script(app_name, fake_argv=fake_argv)
        else:
            app_settings = self.get_app_settings(app_name)
            result = self.run_app(app_name, app_settings, app_argv)
        return result

    def run_script(self, script_path, fake_argv=None):
        if fake_argv:
            sys.argv[:] = fake_argv
        dirtscript = ModuleType("dirtscript")
        dirtscript.__dict__.update({
            "settings": self.settings,
        })
        sys.modules["dirtscript"] = dirtscript
        self.setup_logging(script_path, self.settings)
        execfile(script_path, {})
        return 0

    def run_app(self, app_name, app_settings, app_argv):
        app_settings.get_api = self.get_api_factory()
        self.setup_logging(app_name, app_settings)
        use_reloader = getattr(app_settings, "USE_RELOADER", False)
        if use_reloader and not app_settings.stop_app:
            setproctitle("%s-reloader" %(app_name, ))
            return run_with_reloader(
                lambda: self._run(app_name, app_settings, app_argv)
            )
        else:
            return self._run(app_name, app_settings, app_argv)

    def setup_logging(self, app_name, app_settings):
        AppNameInjector.app_name = app_name
        if not hasattr(app_settings, "LOGGING"):
            logging.basicConfig()
            log.warning("'LOGGING' not found in settings; using failsafe defaults.")
            return
        loggingDictConfig(app_settings.LOGGING)

    def setup_blocking_detector(self, app_settings):
        timeout = getattr(app_settings, "BLOCKING_DETECTOR_TIMEOUT", None)
        if not timeout:
            return
        raise_exc = getattr(app_settings, "BLOCKING_DETECTOR_RAISE_EXC", False)
        if raise_exc:
            log_suffix = "an AlarmInterrupt exception will be raised in"
        else:
            log_suffix = "a log.warning will be issued if"
        log.info("Using blocking detector; %s any thread that blocks for more "
                 "than %s seconds", log_suffix, timeout)
        gevent.spawn(BlockingDetector(timeout=timeout, raise_exc=raise_exc))
        gevent.sleep(0)

    def _run(self, app_name, app_settings, app_argv):
        setproctitle(app_name)
        self.setup_blocking_detector(app_settings)
        app_class = instance_or_import(app_settings.app_class)
        app = app_class(app_name, app_settings, app_argv)
        return app.run()

    # If we are running multiple apis at once, we will know that some will
    # exist, even if they aren't running *right now*. This set contains
    # the names of those apis.
    _get_api_force_no_mock = set()

    def get_api(self, settings_dict, api_name, mock_cls=None, use_bind=False):
        api_settings = settings_dict.get(api_name.upper())
        if not api_settings:
            raise ValueError("unknown or undefined API: %r" %(api_name, ))

        allow_mock = settings_dict.get("ALLOW_MOCK_API")
        if allow_mock:
            allow_mock = not ("NO_MOCK_" + api_name.upper()) in os.environ

        remote_url = getattr(api_settings, "remote_url", None)
        if remote_url is None and use_bind:
            remote_url = api_settings.bind_url
        if not remote_url:
            raise Exception("No 'remote_url' specified for %r" %(api_name, ))

        ClientCls = rpc.get_client_cls(remote_url)
        client = ClientCls(remote_url)
        should_check_mock = (
            allow_mock and
            api_name not in self._get_api_force_no_mock
        )
        if should_check_mock and not client.server_is_alive():
            mock_cls = mock_cls or getattr(api_settings, "mock_cls", None)
            if mock_cls:
                mock_cls = instance_or_import(mock_cls)
                log.warning("%s is not up; using mock API %r for %r",
                            remote_url, mock_cls, api_name)
                return mock_cls()

        WrapperClass = getattr(api_settings, "rpc_wrapper", ClientWrapper)
        return WrapperClass(client)

    def get_api_factory(self):
        def get_api_factory_helper(*args):
            return self.get_api(self.settings.__dict__, *args)
        return get_api_factory_helper

def run(settings, argv=None, runner_cls=DirtRunner):
    runner = runner_cls(settings)
    return runner.run(argv=argv)

def run_many(*a, **kw):
    import warnings
    warnings.warn("'run_many' is deprectated; 'run' should be used instead")
    return run(*a, **kw)
