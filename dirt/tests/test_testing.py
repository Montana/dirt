import logging
from unittest import TestCase

from nose.tools import assert_equal

from ..testing import (
    parameterized, assert_contains, setup_logging, teardown_logging,
    logged_messages, assert_raises, assert_no_errors_logged,
)

log = logging.getLogger(__name__)

missing_tests = set([
    "test_parameterized_naked_function",
    "test_parameterized_instance_method",
    "test_parameterized_on_TestCase",
])

@parameterized([(42, )])
def test_parameterized_naked_function(foo):
    missing_tests.remove("test_parameterized_naked_function")

class TestParameterized(object):
    @parameterized([(42, )])
    def test_parameterized_instance_method(self, foo):
        missing_tests.remove("test_parameterized_instance_method")


def test_warns_on_bad_use_of_parameterized():
    try:
        class TestTestCaseWarnsOnBadUseOfParameterized(TestCase):
            @parameterized([42])
            def test_should_throw_error(self, param):
                pass
    except Exception, e:
        assert_contains(str(e), "parameterized.expand")
    else:
        raise AssertionError("Expected exception not raised")


class TestParamerizedOnTestCase(TestCase):
    @parameterized.expand([("stuff", )])
    def test_parameterized_on_TestCase(self, input):
        assert_equal(input, "stuff")
        missing_tests.remove("test_parameterized_on_TestCase")


class TestLogging(object):
    def teardown(self):
        teardown_logging()

    def test_logged_messages(self):
        setup_logging()
        log.info("foo")
        log.warning("bar")
        log_messages = [ msg for (msg, _) in logged_messages() ]
        assert_contains(log_messages[0], "foo")
        assert_contains(log_messages[1], "bar")

    def test_not_setup(self):
        assert_raises(logged_messages, AssertionError, "setup_logging")

    def test_assert_no_errors(self):
        setup_logging()
        log.info("foo")
        assert_no_errors_logged()
        log.warning("bar")
        assert_raises(assert_no_errors_logged, AssertionError)


def teardown_module():
    assert len(missing_tests) == 0, "tests not executed: %r" %(missing_tests, )
