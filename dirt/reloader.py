# This file is copied from werkzeug.serving
import os
import sys
import time
import logging
from itertools import chain

import gevent
from gevent.queue import Queue
from dirt.misc.gevent_ import fork

log = logging.getLogger(__name__)

def reloader_loop(extra_files=None, interval=1):
    """ When this function is run from the main thread, it will force other
        threads to exit when any modules currently loaded change. """
    def iter_module_files():
        for module in sys.modules.values():
            filename = getattr(module, '__file__', None)
            if filename:
                old = None
                while not os.path.isfile(filename):
                    old = filename
                    filename = os.path.dirname(filename)
                    if filename == old:
                        break
                else:
                    if filename[-4:] in ('.pyc', '.pyo'):
                        filename = filename[:-1]
                    yield filename

    mtimes = {}
    while 1:
        for filename in chain(iter_module_files(), extra_files or ()):
            try:
                mtime = os.stat(filename).st_mtime
            except OSError:
                continue

            old_time = mtimes.get(filename)
            if old_time is None:
                mtimes[filename] = mtime
                continue
            elif mtime > old_time:
                log.info('detected change in %r, reloading...', filename)
                return 3
        gevent.sleep(interval)

def run_and_push_result(queue, func, args):
    try:
        result = func(*args)
    except KeyboardInterrupt:
        result = 1
    except:
        log.exception("%r with args %r failed with exception:", func, args)
        result = 2
    queue.put(result)


def run_with_reloader(main_func, extra_files=None, interval=1):
    """ Run the given function in an independent python interpreter. """
    log.info('running with reloader...')
    while 1:
        pid = fork()
        if pid == 0:
            ready_queue = Queue()
            gevent.spawn(run_and_push_result,
                         ready_queue, main_func, ())
            gevent.spawn(run_and_push_result,
                         ready_queue, reloader_loop, (extra_files, interval))
            sys.exit(ready_queue.get())
        try:
            pid, code_sig = os.waitpid(pid, 0)
            exit_code = code_sig >> 8
        except KeyboardInterrupt:
            exit_code = 4
        if exit_code != 3:
            return exit_code
