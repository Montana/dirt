import sys
import signal
import logging
import traceback

import gevent
from gevent.hub import get_hub

log = logging.getLogger(__name__)

arm_alarm = None
if hasattr(signal, "setitimer"):
    def alarm_itimer(seconds):
        return signal.setitimer(signal.ITIMER_REAL, seconds)[0]
    arm_alarm = alarm_itimer
else:
    try:
        import itimer
        arm_alarm = itimer.alarm
    except ImportError:
        import math
        def alarm_signal(seconds):
            return signal.alarm(math.ceil(seconds))
        arm_alarm = alarm_signal


class AlarmInterrupt(BaseException):
    """ Default exception raised by the ``BlockingDetector`` when it detects
        blocking.

        **NOTE**: This is a subclass of ``BaseException``, so it *will not* be
        caught by ``except Exception:`` (although it will be caught by
        ``dirt.runloop``). """
    pass


def fork():
    """ A workaround for gevent issue 154[0], until that is fixed.

        [0]: http://code.google.com/p/gevent/issues/detail?id=154 """
    tp = get_hub().threadpool
    if len(tp):
        sys.stderr.write("WARNING: calling fork() while threads are active; "
                         "they will be killed.\n")
    tp.kill()
    tp.join()
    result = gevent.fork()
    gevent.sleep(0)
    return result


def getany_and_join(greenlets):
    """ Waits for the first greenlet in ``greenlets`` to finish, kills all
    other greenlets, and returns the value returned by the finished greenlet
    (or raises an exception, if it raised an exception).

    Mostly useful for testing::

        server = SomeSever()
        def test_server():
            assert_equal(server.get_stuff(), "stuff")
        gevent_.getany_and_join([
            gevent.spawn(server.serve_forever),
            gevent.spawn(test_server),
        ])
    """

    current = gevent.getcurrent()
    _finished = []
    def switch(greenlet):
        _finished.append(greenlet)
        current.switch()

    try:
        for greenlet in greenlets:
            greenlet.link(switch)
        gevent.get_hub().switch()
    finally:
        for greenlet in greenlets:
            greenlet.unlink(switch)

    finished = _finished[0]
    for g in greenlets:
        if g is not finished:
            g.kill(block=True)
    if finished.exception:
        raise finished.exception
    return finished.value


class BlockingDetector(object):
    """ Use operating system signals to detect blocking threads.

    ``timeout=1`` is the number of seconds to wait before considering the
    thread blocked (note: if ``signal.setitimer`` or the ``itimer`` package is
    available, this can be a real number; otherwise it will be rounded up to
    the nearest integer).

    ``raise_exc=AlarmInterrupt`` controls which exception will be raised
    in the blocking thread. If ``raise_exc`` is False-ish, no exception will be
    raised (a ``log.warning`` message, including stack trace, will always be
    issued). **NOTE**: the default value, ``AlarmInterrupt``, is a subclass of
    ``BaseException``, so it *will not* be caught by ``except Exception:`` (it
    will be caught by ``dirt.runloop``). For example::

        # Don't raise an exception, only log a warning message and stack trace:
        BlockingDetector(raise_exc=False)

        # Raise ``MyException()`` and lot a warning message:
        BlockingDetector(raise_exc=MyException())

        # Raise ``MyException("blocking detected after timeout=...")`` and log
        # a warning message:
        BlockingDetector(raise_exc=MyException)

    ``aggressive=True`` determines whether the blocking detector will reset
    as soon as it is triggered, or whether it will wait until the blocking
    thread yields before it resets. For example, if ``aggressive=True``,
    ``raise_exc=False``, and ``timeout=1``, a log message will be written for
    every second that a thread blocks. However, if ``aggressive=False``, only
    one log message will be written until the blocking thread yields, at which
    point the alarm will be reset.

    Note: ``BlockingDetector`` overwrites the ``signal.SIGALRM`` handler, and
    does not attempt to save the previous value.

    For example::

        >>> def spinblock():
        ...     while True:
        ...         pass
        >>> gevent.spawn(BlockingDetector())
        >>> gevent.sleep()
        >>> spinblock()
        Traceback (most recent call last):
          File "<stdin>", line 1, in <module>
          File "<stdin>", line 3, in spinblock
          File ".../dirt/misc/gevent_.py", line 167, in alarm_handler
            raise exc
        dirt.misc.gevent_.AlarmInterrupt: blocking detected after timeout=1

    """
    def __init__(self, timeout=1, raise_exc=AlarmInterrupt, aggressive=True):
        self.timeout = timeout
        self.raise_exc = raise_exc
        self.aggressive = aggressive

    def __call__(self):
        """
        Loop for 95% of our detection time and attempt to clear the signal.
        """
        try:
            while True:
                self.reset_signal()
                gevent.sleep(self.timeout * 0.95)
        finally:
            self.clear_signal()

    def alarm_handler(self, signum, frame):
        log.warning("blocking detected after timeout=%r; stack:\n%s",
                    self.timeout, "".join(traceback.format_stack(frame)))
        if self.aggressive:
            self.reset_signal()
        if self.raise_exc:
            exc = self.raise_exc
            if issubclass(exc, type):
                exc = exc("blocking detected after timeout=%r"
                          %(self.timeout, ))
            raise exc

    def reset_signal(self):
        signal.signal(signal.SIGALRM, self.alarm_handler)
        arm_alarm(self.timeout)

    def clear_signal(self):
        arm_alarm(0)
