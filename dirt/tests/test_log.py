import os
import glob
import shutil
import logging
import textwrap
import tempfile
from logging import FileHandler, LogRecord

from nose.tools import assert_equal

from ..log import DirtFileHandler

class TestDirtFileHandler(object):
    def setup(self):
        self.record_count = 0
        self.tempdir = tempfile.mkdtemp(prefix="DirtFileHandlerTest")
        filename = os.path.join(self.tempdir, "{app_name}", "log")
        self.handler = DirtFileHandler(filename=filename,
                                       handler_cls=FileHandler)
        self.handler.formatter = logging.Formatter(
            "%(asctime)s - %(app_name)s - %(levelname)s - %(message)s"
        )

    def teardown(self):
        self.handler.close()
        shutil.rmtree(self.tempdir)

    def record(self, app_name):
        self.record_count += 1
        msg =  "log msg %r" %(self.record_count, )
        record = LogRecord("name", logging.INFO, "x.py", 42, msg, None, None)
        record.app_name = app_name
        record.created = 100 + self.record_count
        record.msecs = 42
        return record

    def assert_logged(self, text):
        expected = textwrap.dedent(text.strip("\n")).strip()
        lines = []
        for file in glob.glob(self.tempdir + "/*/log"):
            lines.extend(open(file))
        actual = "".join(sorted(lines)).strip()
        if expected != actual:
            print "Expected:"
            print expected
            print
            print "Actual:"
            print actual
            raise AssertionError("logged messages don't match")

    def test_multiple_apps(self):
        handler = self.handler
        handler.handle(self.record("app1"))
        handler.handle(self.record("app1"))
        handler.handle(self.record("app2"))
        handler.handle(self.record("app2"))
        self.assert_logged("""
            1969-12-31 19:01:41,042 - app1 - INFO - log msg 1
            1969-12-31 19:01:42,042 - app1 - INFO - log msg 2
            1969-12-31 19:01:43,042 - app2 - INFO - log msg 3
            1969-12-31 19:01:44,042 - app2 - INFO - log msg 4
        """)

    def test_close(self):
        handler = self.handler
        handler.handle(self.record("app1"))
        handler.handle(self.record("app2"))
        handler.close()
        handler.handle(self.record("app1"))
        handler.handle(self.record("app2"))
        handler.close()
        self.assert_logged("""
            1969-12-31 19:01:41,042 - app1 - INFO - log msg 1
            1969-12-31 19:01:42,042 - app2 - INFO - log msg 2
            1969-12-31 19:01:43,042 - app1 - INFO - log msg 3
            1969-12-31 19:01:44,042 - app2 - INFO - log msg 4
        """)
