from mock import Mock
from nose.tools import assert_equal

from ..common import RPCClientProxy

class TestRPCClientProxy(object):
    def test_calling(self):
        c = Mock()
        sc = RPCClientProxy(client=c)
        sc.foo(1, bar=2)
        call = c.call.call_args[0][0]
        assert_equal((call.args, call.kwargs), ((1, ), {"bar": 2}))

    def test_repr(self):
        c = Mock()
        sc = RPCClientProxy(client=c)
        assert_equal(
            repr(sc.prefix),
            "<RPCClientProxy client=%r prefix='prefix'>" %(c, )
        )

