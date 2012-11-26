from nose.tools import assert_equal
from dirt.testing import assert_contains

from .. import ProtocolRegistry

class Server(object):
    pass

class Client(object):
    pass


class TestProtocolRegistry(object):
    def setup(self):
        self.registry = ProtocolRegistry()
        self.registry.register("good", __name__)

    def test_bad_proto(self):
        try:
            self.registry.get_server_cls("foo://")
            raise AssertionError
        except ValueError as e:
            assert_contains(str(e), "unrecognized protocol")

    def test_bad_class(self):
        try:
            self.registry._get("good://", "bad_cls")
            raise AssertionError
        except ValueError as e:
            assert_contains(str(e), "class not found in")

    def test_good_server(self):
        # nb: run assertion twice to ensure that caching works
        assert_equal(self.registry.get_server_cls("good://"), Server)
        assert_equal(self.registry.get_server_cls("good://"), Server)

    def test_good_client(self):
        # nb: run assertion twice to ensure that caching works
        assert_equal(self.registry.get_client_cls("good://"), Client)
        assert_equal(self.registry.get_client_cls("good://"), Client)

    def test_register_from_dict(self):
        self.registry.register({
            "foo+bar": __name__,
        })
        assert_equal(self.registry.get_client_cls("foo+bar://"), Client)
