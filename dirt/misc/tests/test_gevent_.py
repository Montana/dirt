import time
import gevent

from nose.tools import raises, assert_equal

from ..gevent_ import BlockingDetector, AlarmInterrupt, arm_alarm


class TestBlockingDetector(object):
    def setup(self):
        self.detector = BlockingDetector(timeout=0.05)
        self.detector_thread = gevent.spawn(self.detector)
        gevent.sleep()

    def teardown(self):
        self.detector_thread.kill(block=True)
        assert_equal(arm_alarm(0), 0)

    def block_and_assert_raised(self):
        try:
            target = time.time() + 2
            while time.time() < target:
                pass
            raise AssertionError("AlarmInterrupt not raised!")
        except AlarmInterrupt:
            pass

    def test_alarm_interrupt_raised_when_thread_blocks(self):
        self.block_and_assert_raised()

    def test_with_multiple_alarms(self):
        self.block_and_assert_raised()
        self.block_and_assert_raised()

    def test_no_alarm_interrupt_on_non_blocking_thread(self):
        gevent.sleep(0.1)

