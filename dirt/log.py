import os
import time
import logging
import logging.handlers

from dirt.misc.dictconfig import dictConfig

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

_TimedRotatingFileHandler = logging.handlers.TimedRotatingFileHandler

class TimedRotatingFileHandler(_TimedRotatingFileHandler):
    def __init__(self, filename, *args, **kwargs):
        if not os.path.exists(os.path.dirname(filename)):
            os.mkdir(os.path.dirname(filename))
        _TimedRotatingFileHandler.__init__(self, filename, *args, **kwargs)

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

    # Will be set in `run_many`
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


logging_default = lambda log_file_base, root_level="DEBUG": {
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
            "class": __name__ + ".TimedRotatingFileHandler",
            "level": "DEBUG",
            "filters": ["app_name_injector"],
            "formatter": "production_fmt",
            "filename": log_file_base,
            "when": "midnight",
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


def setup_logging(app_name, app_settings):
    AppNameInjector.app_name = app_name

    if not hasattr(app_settings, "LOGGING"):
        logging.basicConfig()
        log.warning("'LOGGING' not found in settings; using failsafe defaults.")
        return
    dictConfig(app_settings.LOGGING)

    # XXX: have a pluggable log_to_hub like this:
    # if getattr(app_settings, "log_to_hub", True):
    #     from ensi_common.msg_hub.logger import HubLogHandler
    #     hub_handler = HubLogHandler()
    #     hub_handler.addFilter(AppNameInjector())
    #     hub_handler.set_hub(app_settings.get_api("msg_hub"))
    #     logging.root.addHandler(hub_handler)
