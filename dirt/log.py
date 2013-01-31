import os
import time
import logging
import logging.handlers

from gevent.lock import RLock

from dirt.misc.imp_ import instance_or_import

ANSI_COLORS = dict(zip(
    ["grey", "red", "green", "yellow", "blue", "magenta", "cyan", "white"],
    ["\033[%dm" %x for x in range(30, 38)],
))
ANSI_COLORS["reset"] = '\033[0m'

log = logging.getLogger(__name__)


class AppNameInjector(logging.Filter):
    """ Ensures that all log records have an 'app_name' field.

        ``app_name`` will be set by ``setup_logging``. """

    app_name = "__no_app__"

    def filter(self, record):
        record.app_name = self.app_name
        return True


class EnvVarLogFilter(logging.Filter):
    """ Filters out any log messages which match any of the space-delimited
        values in ``env_var``. Eg, if ``env_var`` is set to ``"LOG_IGNORE``::

            $ ./foo.py
            INFO foo: one
            INFO bar.baz: two
            INFO bar: three
            $ LOG_IGNORE="foo two" python foo.py
            INFO bar: three """

    def __init__(self, env_var):
        self.env_var = env_var
        env_val = os.environ.get(env_var, "")
        self.filters = filter(None, env_val.split())
        self.issued_warning = False

    def filter(self, record):
        if not self.issued_warning:
            self.issued_warning = True
            if self.filters:
                my_log = logging.getLogger(log.name + ".EnvVarLogFilter")
                my_log.warning("ignoring messages containing %s", self.filters)
        if record.name.endswith("EnvVarLogFilter"):
            return True
        msg = " ".join([
            getattr(record, "app_name", "<no-app>"), record.name,
            record.levelname, record.getMessage()
        ])
        return not any(filter in msg for filter in self.filters)

class DirtFileHandler(logging.Handler):
    """ A log handler which expands ``{app_name}`` in the provided ``filename``
        so that each app will log to its own file using the provided
        ``handler_cls``.

        For example::

            DirtFileHandler(filename="/var/logs/dirt-{app_name}/log",
                            handler_cls="logging.RotatingFileHandler",
                            max_bytes=1024*1024)

        Note: the ``DirtFileHandler`` will appear to work if ``{app_name}`` is
        not included in the ``filename``, but it will likely result in mangled
        logs, as the apps -- running in separate OS processes -- will be
        writing to the same logfile.

        Hint: Use ``sort --merge`` to merge multiple log files::

            $ sort --merge logs/dirt-{first_app,second_app}/log
            19:01:41,042Z first_app INFO log msg 1
            19:01:42,042Z second_app INFO log msg 2
            19:01:43,042Z first_app INFO log msg 3
            19:01:44,042Z second_app INFO log msg 4
        """

    def __init__(self, filename, handler_cls, *handler_args, **handler_kwargs):
        handler_level = handler_kwargs.get("level", logging.NOTSET)
        logging.Handler.__init__(self, level=handler_level)
        self.filename = filename
        self.handlers = {}
        self.handlers_lock = RLock()
        self.handler_cls = instance_or_import(handler_cls)
        self.handler_args = handler_args
        self.handler_kwargs = handler_kwargs

    def _create_handler(self, app_name):
        # nb: it's possible that ``app_fmt`` will be the empty string if
        # "{app_name}" does not occur in the filename!
        base, app_fmt, suffix = self.filename.partition("{app_name}")
        filename = base + app_fmt.format(app_name=app_name) + suffix
        for path in [base, filename]:
            dir = os.path.dirname(path)
            if not os.path.exists(dir):
                try:
                    os.mkdir(dir)
                except OSError as e:
                    if e.errno != 17: # file exists
                        raise
                    pass
        handler = self.handler_cls(filename, *self.handler_args,
                                   **self.handler_kwargs)
        handler.formatter = self.formatter
        return handler

    def handle(self, record):
        rv = self.filter(record)
        if not rv:
            return rv
        try:
            handler = self.handlers[record.app_name]
        except KeyError:
            with self.handlers_lock:
                app_name = record.app_name
                if app_name not in self.handlers:
                    handler = self._create_handler(app_name)
                    self.handlers[app_name] = handler
            handler = self.handlers[record.app_name]
        try:
            handler.acquire()
            handler.emit(record)
        finally:
            handler.release()
        return rv

    def close(self):
        with self.handlers_lock:
            old_handlers = self.handlers
            self.handlers = {}
            for handler in old_handlers.values():
                handler.close()


class UTCFormatter(logging.Formatter):
    converter = time.gmtime


class ColoredFormatter(logging.Formatter):
    COLORS = [
        (logging.ERROR, "red"),
        (logging.WARNING, "yellow"),
        (logging.INFO, "green"),
        (logging.DEBUG, "white"),
    ]
    COLORS.sort(reverse=True)

    # Will be set in `run`
    app_color = "white"

    def __init__(self, *args, **kwargs):
        logging.Formatter.__init__(self, *args, **kwargs)

    def format(self, record):
        for level, color in self.COLORS:
            if level <= record.levelno:
                break

        record.app_color = ANSI_COLORS[self.app_color]
        record.c_reset = ANSI_COLORS["reset"]
        record.c_level = ANSI_COLORS[color]
        record.c_grey = ANSI_COLORS["grey"]
        return logging.Formatter.format(self, record)


logging_default = lambda log_filename, root_level="DEBUG": {
    "version": 1,
    "disable_existing_loggers": False,

    "formatters": {
        "colored_debug_fmt": {
            "()": __name__ + ".ColoredFormatter",
            "datefmt": "%H:%M:%S",
            "format": (
                "%(asctime)s.%(msecs)03d "
                "%(app_color)s%(app_name)s%(c_reset)s "
                "%(c_level)s%(levelname)s%(c_reset)s "
                "%(c_grey)s%(name)s%(c_reset)s: "
                "%(message)s"
            ),
        },
        "production_fmt": {
            "()": __name__ + ".UTCFormatter",
            "datefmt": "%Y-%m-%d %H:%M:%S",
            "format": (
                "%(asctime)s.%(msecs)03dZ "
                "%(app_name)s %(levelname)s %(name)s: %(message)s"
            ),
        },
    },

    "filters": {
        "app_name_injector": {
            "()": __name__ + ".AppNameInjector",
        },
        "env_var_filter": {
            "()": __name__ + ".EnvVarLogFilter",
            "env_var": "LOG_IGNORE",
        },
    },

    "handlers": {
        "debug_handler": {
            "class": "logging.StreamHandler",
            "level": "DEBUG",
            "filters": ["app_name_injector", "env_var_filter"],
            "formatter": "colored_debug_fmt",
            "stream": "ext://sys.stdout",
        },
        "rotating_file_handler": {
            "class": __name__ + ".DirtFileHandler",
            "level": "DEBUG",
            "filters": ["app_name_injector"],
            "formatter": "production_fmt",
            "filename": log_filename,
            "handler_cls": "logging.handlers.RotatingFileHandler",
            "maxBytes": 1024*1024,
        },
    },

    "loggers": {
        "": {
            "handlers": ["debug_handler", "rotating_file_handler"],
            "level": root_level,
            "propagate": True,
        },
    },
}

