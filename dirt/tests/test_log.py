import logging

from mock import Mock

from .. import log

class TestSetupLogging(object):
    def setup(self):
        self.old_logging_root = logging.root

    def teardown(self):
        logging.root = self.old_logging_root

    def test_setup_logging_no_hub(self):
        class SETTINGS:
            get_api = Mock()
            log_to_hub = False
            LOGGING = log.logging_default("/dev/null")
        log.setup_logging("mock_app", SETTINGS)
        assert not SETTINGS.get_api.called

    def test_setup_logging_hub(self):
        class SETTINGS:
            # log_to_hub should default to 'True'
            get_api = Mock()
            LOGGING = log.logging_default("/dev/null")
        log.setup_logging("mock_app", SETTINGS)
        assert SETTINGS.get_api.called
