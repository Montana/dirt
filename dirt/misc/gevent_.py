import gevent
from gevent.hub import get_hub

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
    """
    Utility class to detect thread blocking. Intended for debugging only.
    
    ``timeout`` is the number of seconds to wait before considering the thread
    blocked.

    ``raise_exc`` controls whether or not an exception is raised
    (default: ``True``). If ``raise_exc`` is ``False`` only a log message
    will be written.
    
    Operates by setting and attempt to clear an alarm signal. The alarm signal
    cannot be cleared then the thread is considered blocked and
    ``BlockingDetector.alarm_handler`` is invoked with the signal and current
    frame. An ``AlarmInterrupt`` exception will be raised if the signal
    actually gets raised.
    
    Invoke via: gevent.spawn(BlockingDetector())
    """
    def __init__(self, timeout=1, raise_exc=True):
        self.timeout = timeout
        self.raise_exc = raise_exc

    def __call__(self):
        """
        Loop for 95% of our detection time and attempt to clear the signal.
        """
        while True:
            self.set_signal()
            gevent.sleep(self.timeout * 0.95)
            self.clear_signal()
            # sleep the rest of the time
            gevent.sleep(self.timeout * 0.05)

    def alarm_handler(self, signum, frame):
        log.warning("blocking detected after timeout=%r; stack:\n%s",
                    self.timeout, "".join(traceback.format_stack(frame)))
        if self.raise_exc:
            raise AlarmInterrupt("blocking detected")

    def set_signal(self):
        tmp = signal.signal(signal.SIGALRM, self.alarm_handler)
        if tmp != self.alarm_handler:
            self._old_signal_handler = tmp
        arm_alarm(self.timeout)

    def clear_signal(self):
        if (hasattr(self, "_old_signal_handler") and self._old_signal_handler):
            signal.signal(signal.SIGALRM, self._old_signal_handler)
        signal.alarm(0)

