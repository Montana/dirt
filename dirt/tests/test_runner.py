from mock import Mock
from nose.tools import eq_

from ..runner import DirtRunner


class TestDirtRunner(object):
    def setup(self):
        self.runner = DirtRunner(Mock())

    def test_handle_argv_with_h_calls_usage_and_returns_0(self):
        self.runner.usage = Mock()
        argv = ['-h']
        ret = self.runner.handle_argv(argv)
        self.runner.usage.assert_called_once_with(argv)
        eq_(0, ret)

    def test_handle_argv_with_help_calls_usage_and_returns_0(self):
        self.runner.usage = Mock()
        argv = ['--help']
        ret = self.runner.handle_argv(argv)
        self.runner.usage.assert_called_once_with(argv)
        eq_(0, ret)

    def test_handle_argv_with_list_apps_calls_list_apps_and_returns_0(self):
        self.runner.list_apps= Mock()
        self.runner.list_apps.return_value = []
        argv = ['--list-apps']
        ret = self.runner.handle_argv(argv)
        self.runner.list_apps.assert_called_once_with()
        eq_(0, ret)

    def test_handle_argv_with_shell_calls_run_rpc_shell_with_third_arg(self):
        self.runner.run_rpc_shell= Mock()
        ret = self.runner.handle_argv(['', '--shell', 'app'])
        self.runner.run_rpc_shell.assert_called_once_with('app')

    def test_handle_argv_with_stop_sets_settings_stop_app(self):
        ret = self.runner.handle_argv(['', '--stop'])
        eq_(True, self.runner.settings.stop_app)

    def test_handle_argv_with_stop_sets_settings_log_to_hub_to_false(self):
        ret = self.runner.handle_argv(['', '--stop'])
        eq_(False, self.runner.settings.log_to_hub)

    def test_handle_argv_with_stop_removes_stop_from_argv(self):
        argv = ['', '--stop']
        ret = self.runner.handle_argv(argv)
        eq_([''], argv)

    def test_handle_argv_with_1_arg_calls_usage_and_returns_1(self):
        self.runner.usage = Mock()
        argv = ['']
        ret = self.runner.handle_argv(argv)
        self.runner.usage.assert_called_once_with(argv)
        eq_(1, ret)

    def test_handle_argv_with_2_args_returns_none(self):
        ret = self.runner.handle_argv(['', ''])
        eq_(None, ret)
