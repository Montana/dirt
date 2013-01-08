import sys
import cgi
import time
import urllib
import logging
import functools
from itertools import chain

import bson
from gevent import socket

from dirt.rpc.common import expected
from dirt.misc.strutil import truncate

log = logging.getLogger(__name__)

full_message_log = logging.getLogger(__name__ + ".full_message_log")
full_message_log.propagate = False
full_message_log.setLevel(logging.ERROR)

def full_message_log_enable(filename):
    full_message_log.level = logging.DEBUG
    full_message_log.setLevel(logging.DEBUG)
    handler = logging.FileHandler(filename)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s %(message)s')
    handler.setFormatter(formatter)
    full_message_log.addHandler(handler)


class LogWrapper(object):
    def __init__(self, log, prefix):
        self._log = log
        self.prefix = prefix

    def __getattr__(self, attr):
        return functools.partial(self.log, attr)

    def isEnabledFor(self, lvl):
        return self._log.isEnabledFor(lvl)

    def log(self, level, msg, *args):
        getattr(log, level)(self.prefix + msg, *args)


class ConnectionError(Exception):
    """ Raised when there is an error at the connection level.

        The ``ConnectionError`` class will be used for protocol-level errors,
        and the subclass ``SocketError`` will be used for socket-level
        errors.
        """

    def __init__(self, msg="<none>", peer=None):
        self.msg = msg
        self.peer = peer

    def _str_suffix(self):
        try:
            peer = "%s:%s" %self.peer
        except:
            peer = "!" + repr(self.peer)
        return "peer: " + peer

    def __str__(self):
        return "%s (%s)" %(self.msg, self._str_suffix())

    def __repr__(self):
        return "<%s %r (%s)>" %(type(self).__name__, self.msg, self._str_suffix())


class SocketError(ConnectionError):
    pass


@expected
class EmptyRead(SocketError):
    """ Raised when there is an unexpected empty read from a peer. This happens
        when the peer closes the connection, and doesn't normally need to be
        treated like an unexpected error. """

    def __init__(self):
        ConnectionError.__init__(self, "empty read")


class MessageError(Exception):
    @classmethod
    def bad_type(cls, type):
        return cls("unexpected message type: %r" %(type, ))

    @classmethod
    def bad_magic(cls, message_str):
        return cls("invalid magic number on message: %r"
                   %(truncate(message_str), ))

    @classmethod
    def invalid(cls, message, why):
        return cls("invalid message: %r (%s)" %(message, why))


def handle_error(f):
    @functools.wraps(f)
    def handle_error_helper(self, *args, **kwargs):
        try:
            return f(self, *args, **kwargs)
        except:
            return self._handle_error(*sys.exc_info())
    return handle_error_helper


def _socket_error_message(address, exception):
    # args for socket.error can either be (errno, "message")
    # or just "message"
    if len(exception.args) == 1:
        return "error with connection to %s: %s." % \
            (address, exception.args[0])
    else:
        return "error %s with connection to %s: %s." % \
            (exception.args[0], address, exception.args[1])



class MessageSocket(object):
    """ A wrapper around ``socket.socket`` to provide a message-based
        interface.

        See: ``send_message``, ``recv_message``. """

    VERSION = "1.zlib"
    MSG_HEADER_SIZE = 8
    MSG_MAX_SIZE = 16 ** 6
    MSG_HEADER_FORMAT = "{size:06x}{magic}{type}"

    TYPE_NORMAL = ":"
    TYPE_CONTROL = "!"
    TYPES = [TYPE_NORMAL, TYPE_CONTROL]

    MAGIC_ZLIB = "Z"
    MAGIC_NONE = "N"

    def __init__(self, address, get_socket, version_info, use_zlib=False):
        self.id = self._next_id()
        self.address = address
        self.version_info = dict(version_info)
        self.version_info["message_socket"] = self.VERSION
        self._check_version_info()
        self._socket = None
        self._get_socket = get_socket
        self.use_zlib = use_zlib

        # 'self.log.prefix' is expected to be set by code using this
        self.log = LogWrapper(log, "MessageSocket")

    def __del__(self):
        try:
            self.log.warning("connection leak!")
            self.disconnect()
        except:
            pass

    _last_id = 0

    @classmethod
    def _next_id(cls):
        # Note: in real threaded environments this will not be safe
        cls._last_id += 1
        return cls._last_id

    def send_version(self):
        """ Sends this socket's ``version_info`` to the peer and waits for
            a response (either ``OK`` or ``VERSION MISMATCH: ...``). """
        version_info_str = self._serialize_version_info()
        self.send_message("VERSION %s" %(version_info_str, ),
                          type=self.TYPE_CONTROL)

    def _handle_control_message(self, message):
        if message.startswith("VERSION_MISMATCH "):
            self.disconnect()
            raise ConnectionError(message)

        if message.startswith("VERSION "):
            peer_version_info_str = message.split(" ", 1)[1]
            my_version_info_str = self._serialize_version_info()
            if peer_version_info_str != my_version_info_str:
                self.send_message("VERSION_MISMATCH my_reported=%r != peer=%r"
                                  %(peer_version_info_str, my_version_info_str),
                                  type=self.TYPE_CONTROL)
                self.disconnect()
                raise ConnectionError("VERSION_MISMATCH my %r != peer %r"
                                      %(my_version_info_str, peer_version_info_str))
            self.peer_version_info = self._load_version_info(peer_version_info_str)
            return

        raise ConnectionError("unexpected control message: %r" %(message, ))

    def _check_version_info(self):
        try:
            for (key, val) in self.version_info.items():
                assert type(key) == str, "invalid key: %r" %(key, )
                assert type(val) == str, "invalid val: %r" %(val, )
        except AssertionError, e:
            raise ValueError("invalid version_info: %s (version_info: %r)"
                             %(e, self.version_info))

    def _serialize_version_info(self):
        items = self.version_info.items()
        items.sort()
        return urllib.urlencode(items)

    def _load_version_info(self, version_info_str):
        try:
            return dict(cgi.parse_qsl(version_info_str))
        except Exception, e:
            raise ValueError("poorly formatted version info: %r (error: %r)"
                             %(version_info_str,e))

    # These hooks can be set by code which uses this class
    on_disconnect = lambda self: None
    on_connect = lambda self: None

    def disconnect(self):
        if self._socket is None:
            return

        self.log.debug("disconnecting")
        try:
            self._socket.close()
        except socket.error:
            pass
        self._socket = None
        self.peer_version_info = None
        self.on_disconnect()

    def connect(self):
        if self._socket is not None:
            self.log.warning("trying to connect but already connected!")
            return

        self.log.debug("connecting")
        self.peer_version_info = None
        self._socket = self._get_socket()
        self.on_connect()

    def connected(self):
        return self._socket is not None

    def _handle_error(self, exc_type, exc_value, exc_traceback):
        self.disconnect()

        if isinstance(exc_value, socket.error):
            message = _socket_error_message(self.address, exc_value)
            exc_value = SocketError(message)

        if isinstance(exc_value, ConnectionError):
            exc_value.peer = self.address

        if not isinstance(exc_value, EmptyRead):
            # Only log non-empty-read errors, as will be logged when they are
            # raised.
            self.log.debug("error during send/recv: %r", exc_value)

        raise exc_value, None, exc_traceback

    def _socket_recv(self, size):
        if self._socket is None:
            self.connect()
        result = ""
        read = 0
        while read < size:
            data = self._socket.recv(size - read)
            if data == "":
                self.log.debug("empty read")
                raise EmptyRead()
            read += len(data)
            result += data
        return result

    def _socket_send(self, data):
        if self._socket is None:
            self.connect()
        self._socket.sendall(data)

    @handle_error
    def recv_message(self):
        while True:
            type, message = self._recv_one_message()
            full_message_log.info("recv %s %r", type, message)
            if type == self.TYPE_NORMAL:
                break
            elif type == self.TYPE_CONTROL:
                self._handle_control_message(message)
            else:
                raise ConnectionError("unexpected message type: %r" %(type, ))
        return message

    def _recv_one_message(self):
        header = self._socket_recv(self.MSG_HEADER_SIZE)
        size_str, magic, type = header[:6], header[6], header[7]
        try:
            size = int(size_str, 16)
        except ValueError:
            raise ConnectionError("invalid message size: %r" %(size_str, ))
        message = self._socket_recv(size)
        if magic == self.MAGIC_NONE:
            pass
        elif magic == self.MAGIC_ZLIB:
            message = message.decode("zlib")
        else:
            raise ConnectionError("bad magic number: %r (header: %r, msg: %r)"
                                  %(magic, header, truncate(message)))
        return type, message

    @handle_error
    def send_message(self, message, type=TYPE_NORMAL):
        assert type in self.TYPES, "unexpected message type: %r" %(type, )
        full_message_log.info("send %s %r", type, message)
        if self.use_zlib:
            magic = self.MAGIC_ZLIB
            message = message.encode("zlib")
        else:
            magic = self.MAGIC_NONE

        assert len(message) < self.MSG_MAX_SIZE, "message too large"
        size = len(message)
        header = self.MSG_HEADER_FORMAT.format(size=size, magic=magic, type=type)
        self._socket_send(header + message)

    def __repr__(self):
        state = self._socket and "connected" or "not connected"
        return "<%s %s %s to %s>" %(
            self.__class__.__name__, self.id, state,
            "%s:%s" %self.address,
        )


def delegate(field_name, target_name):
    @property
    def delegate_helper(self):
        target = getattr(self, target_name)
        value = getattr(target, field_name)
        self.__dict__[field_name] = value
        return value
    return delegate_helper


class RPCConnectionBase(object):
    """ Uses a ``MessageSocket`` to send and receive RPC messages. """

    VERSION = "2"
    serializer = bson

    def __init__(self, address, use_zlib=None):
        if use_zlib is None:
            use_zlib = address[0] not in ["127.0.0.1", "localhost"]
        self.msg_socket = MessageSocket(address, self._get_socket, {
            "rpc": self.VERSION,
        }, use_zlib=use_zlib)
        self.msg_socket.on_connect = self._on_connect
        self.msg_socket.on_disconnect = self._on_disconnect
        self._last_txrx_time = 0

    def _dumps(self, message):
        # Because BSON will only serialize objects at the top level, wrap
        # the message in an object.
        return self.serializer.dumps({"m": message})

    def _loads(self, message):
        return self.serializer.loads(message)["m"]

    def recv_message(self):
        """ Returns a (rpc_command, data) message tuple. """
        message = self._loads(self.msg_socket.recv_message())
        if self.log.isEnabledFor(logging.DEBUG):
            last_activity = self._last_txrx_time
            self.log.debug("recv since_last=%0.04f %s",
                           last_activity and time.time() - last_activity,
                           truncate(repr(message), max_len=256))
        self._last_txrx_time = time.time()
        if len(message) == 1:
            message = (message[0], None)
        if len(message) > 2:
            raise MessageError.invalid(message, "too big")
        return (message[0], message[1])

    def send_message(self, message):
        if self.log.isEnabledFor(logging.DEBUG):
            last_activity = self._last_txrx_time
            self.log.debug("send since_last=%0.04f %s",
                           last_activity and time.time() - last_activity,
                           truncate(repr(message), max_len=256))
        self._last_txrx_time = time.time()
        if len(message) > 2:
            raise MessageError.invalid(message, "too big")
        self.msg_socket.send_message(self._dumps(message))

    def _get_socket(self):
        raise Exception("_get_socket should be implemented by subclasses")

    def _on_disconnect(self):
        pass

    def _on_connect(self):
        pass

    connect = delegate("connect", "msg_socket")
    disconnect = delegate("disconnect", "msg_socket")
    connected = delegate("connected", "msg_socket")
    address = delegate("address", "msg_socket")
    id = delegate("id", "msg_socket")
    log = delegate("log", "msg_socket")

    def __repr__(self):
        return "<%s msg_socket=%r>" %(self.__class__.__name__, self.msg_socket)


class ClientConnection(RPCConnectionBase):
    """ Wraps a client-side socket, re-establishing a connection to the server
        as necessary (eg, if the connection is disconnected due to an error). """

    def __init__(self, address, socket_timeout=None):
        self.socket_timeout = socket_timeout
        super(ClientConnection, self).__init__(address)
        self.log.prefix = "%s-%s to %s:%s: " %(
            self.__class__.__name__, self.id, address[0], address[1]
        )

    def _get_socket(self):
        self.log.debug("connecting")
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.socket_timeout)
            sock.connect(self.address)
            return sock
        except socket.error, e:
            raise expected(SocketError(_socket_error_message(self.address, e)))

    def _on_connect(self):
        self.msg_socket.send_version()


class ServerConnection(RPCConnectionBase):
    """ Wraps a server-side socket (eg, won't reconnect on error). """

    def __init__(self, socket, address):
        self._socket = socket
        super(ServerConnection, self).__init__(address)
        self.log.prefix = "%s %s to %s: " %(
            self.__class__.__name__, self.id, "%s:%s" %address,
        )
        self.log.debug("connect")

    def _get_socket(self):
        return self._socket


class ConnectionPool(object):
    """ A simple pool for managing client connections.

        Currently has a fairly small maximum size (128 connections), and will
        raise an exception if too many connections are requested.
    
        I expect this behaviour will be OK, as we should never *need* that many
        connections, so if that limit is ever hit it means we're leaking
        connections... So explicitly erroring will just hasten the inevitable.
        """

    active_pools = {}
    _instance_count = 0

    def __init__(self, address, connection_class=ClientConnection,
                 max_connections=None, keep_connections=None):
        num = type(self)._instance_count
        type(self)._instance_count += 1
        self.log = logging.getLogger(__name__ + ".ConnectionPool-%02d" %(num, ))
        self.connection_class = connection_class
        self.connection_kwargs = {
            "address": address,
        }
        self.max_connections = max_connections or 32
        self._created_connections = 0
        self._available_connections = []
        self._in_use_connections = set()

    @classmethod
    def get_pool(cls, address, **kwargs):
        if address not in cls.active_pools:
            cls.active_pools[address] = cls(address, **kwargs)
        return cls.active_pools[address]

    def _log_change(self, change, cxn):
        self.log.debug("%s %r (active: %r; available: %r)", change, cxn,
                       len(self._in_use_connections),
                       len(self._available_connections))

    def get_connection(self):
        try:
            connection = self._available_connections.pop()
        except IndexError:
            connection = self._make_connection()
        self._in_use_connections.add(connection)
        self._log_change("allocating", connection)
        return connection

    def _make_connection(self):
        if self._created_connections >= self.max_connections:
            raise AssertionError("too many connections (%s created, %s active)"
                                 %(self._created_connections,
                                   len(self._in_use_connections)))
        if self._created_connections >= self.max_connections * 0.7:
            self.log.warning("%r has %r active connections (70%% of maximum)",
                             self, self._created_connections)
        self._created_connections += 1
        return self.connection_class(**self.connection_kwargs)

    def release(self, connection):
        self._in_use_connections.remove(connection)
        self._available_connections.append(connection)
        self._log_change("releasing", connection)

    def disconnect(self):
        all_conns = chain(self._available_connections, self._in_use_connections)
        for connection in all_conns:
            connection.disconnect()

    def summarize(self):
        """ Returns a summary of this connection pool which can be used for
            diagnostics and debugging. """

        try:
            peer = "%s:%s" %self.connection_kwargs["address"]
        except Exception:
            # ``except Exception`` here to ensure that summarize never crashes
            peer = "<invalid:%s>" %(self.connection_kwargs.get("address"), )
        return {
            "peer": peer,
            "num_active": len(self._in_use_connections),
            "num_inactive": len(self._available_connections),
            "num_created": self._created_connections,
            "num_max": self.max_connections,
        }

    def __repr__(self):
        summary = self.summarize()
        summary["type_name"] = type(self).__name__
        return (
            "<%(type_name)s %(peer)r "
            "active=%(num_active)r available=%(num_inactive)r "
            "created=%(num_created)r max=%(num_max)r>"
        ) %summary
