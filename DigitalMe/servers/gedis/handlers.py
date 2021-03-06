from Jumpscale import j
from redis.exceptions import ConnectionError
import nacl

from .protocol import RedisCommandParser, RedisResponseWriter

JSBASE = j.application.JSBaseClass


class Session:
    def __init__(self):
        self.dmid = None  # is the digital me id e.g. kristof.ibiza
        self.admin = False


def _command_split(cmd, namespace="system"):
    """
    :param cmd: command is in form x.x.x split in parts
    :param namespace: is the default namespace
    :return: (namespace, actor, cmd)
    """
    cmd_parts = cmd.split(".")
    if len(cmd_parts) == 3:
        namespace = cmd_parts[0]
        actor = cmd_parts[1]
        if "__" in actor:
            actor = actor.split("__", 1)[1]
        cmd = cmd_parts[2]

    elif len(cmd_parts) == 2:
        actor = cmd_parts[0]
        if "__" in actor:
            actor = actor.split("__", 1)[1]
        cmd = cmd_parts[1]
        if actor == "system":
            namespace = "system"
    elif len(cmd_parts) == 1:
        namespace = "system"
        actor = "system"
        cmd = cmd_parts[0]
    else:
        raise RuntimeError("cmd not properly formatted")

    return namespace, actor, cmd


class Command:
    """
    command is an object representing a string gedis command
    it has 3 part
    - namespace
    - actor
    - command name
    """

    def __init__(self, command):
        self._namespace, self._actor, self._command = _command_split(command)

    @property
    def namespace(self):
        return self._namespace

    @property
    def actor(self):
        return self._actor

    @property
    def command(self):
        return self._command

    def __str__(self):
        return self.command

    def __repr__(self):
        return self.command


class Request:
    """
    Request is an helper object that
    encapsulate a raw gedis command and expose some property
    for easy access of the different part of the request
    """

    def __init__(self, request):
        self._request_ = request

    @property
    def _request(self):
        return self._request_

    @property
    def command(self):
        """
        return a Command object
        """
        return Command(self._request[0].decode().lower())

    @property
    def arguments(self):
        """
        :return: the list of arguments of any or an emtpy list
        :rtype: list
        """
        if len(self._request) > 1:
            return self._request[1:]
        return []

    @property
    def headers(self):
        """
        :return: return the headers of the request or an emtpy dict
        :rtype: dict
        """
        if len(self._request) > 2:
            return j.data.serializers.json.loads(self._request[2])
        return {}

    @property
    def content_type(self):
        """
        :return: read the content type of the request form the headers
        :rtype: string
        """
        return self.headers.get("content_type", "auto").casefold()

    @property
    def response_type(self):
        """
        :return: read the response type from the headers
        :rtype: string
        """
        return self.headers.get("response_type", "auto").casefold()


class ResponseWriter:
    """
    ResponseWriter is an object that expose methods
    to write data back to the client
    """

    def __init__(self, socket):
        self._socket = socket
        self._writer = RedisResponseWriter(socket)

    def write(self, value):
        self._writer.encode(value)

    def error(self, value):
        self._writer.error(value)


class GedisSocket:
    """
    GedisSocket encapsulate the raw tcp socket
    when you want to read the next request on the socket,
    call the `read` method, it will return a Request object
    when you want to write back to the client
    call get_writer to get ReponseWriter
    """

    def __init__(self, socket):
        self._socket = socket
        self._parser = RedisCommandParser(socket)
        self._writer = ResponseWriter(self._socket)

    def read(self):
        """
        call this method when you want to process the next request

        :return: return a Request
        :rtype: tuple
        """
        raw_request = self._parser.read_request()
        if not raw_request:
            raise ValueError("malformatted request")
        return Request(raw_request)

    @property
    def writer(self):
        return self._writer

    def on_disconnect(self):
        """
        make sur to always call this method before closing the socket
        """
        if self._parser:
            self._parser.on_disconnect()

    @property
    def closed(self):
        return self._socket.closed


class Handler(JSBASE):
    def __init__(self, gedis_server):
        JSBASE.__init__(self)
        self.gedis_server = gedis_server
        self.cmds = {}  # caching of commands
        self.actors = self.gedis_server.actors
        self.cmds_meta = self.gedis_server.cmds_meta
        self.session = Session()

    def handle_redis(self, socket, address):

        # BUG: if we start a server with kosmos --debug it should get in the debugger but it does not if errors trigger, maybe something in redis?
        # w=self.t
        # raise RuntimeError("d")
        gedis_socket = GedisSocket(socket)

        try:
            self._handle_redis_session(gedis_socket, address)
        finally:
            gedis_socket.on_disconnect()
            self._log_info("connection closed", context="%s:%s" % address)

    def _handle_redis_session(self, gedis_socket, address):
        """
        deal with 1 specific session
        :param socket:
        :param address:
        :param parser:
        :param response:
        :return:
        """
        self._log_info("new incoming connection", context="%s:%s" % address)

        while True:
            try:
                request = gedis_socket.read()
                self._log_info("request received: %s" % request.command)
                result = self._handle_request(request, address)
                gedis_socket.writer.write(result)
            except ConnectionError as err:
                self._log_info("connection error: %s" % str(err), context="%s:%s" % address)
                return
            except Exception as e:
                self._log_error(str(e), context="%s:%s" % address)
                if not gedis_socket.closed:
                    gedis_socket.writer.error(str(e))

    def _handle_request(self, request, address):
        """
        deal with 1 specific request
        :param request:
        :return:
        """
        # process the predefined commands
        if request.command == "command":
            return "OK"
        elif request.command == "ping":
            return "PONG"
        elif request.command == "auth":
            dm_id, epoch, signed_message = request[1:]
            if self.dm_verify(dm_id, epoch, signed_message):
                self.session.dmid = dm_id
                self.session.admin = True
                return True

        self._log_debug(
            "command received %s %s %s" % (request.command.namespace, request.command.actor, request.command.command),
            context="%s:%s" % address,
        )

        # cmd is cmd metadata + cmd.method is what needs to be executed
        cmd = self._cmd_obj_get(
            cmd=request.command.command, namespace=request.command.namespace, actor=request.command.actor
        )

        params_list = []
        params_dict = {}
        if cmd.schema_in:
            params_dict = self._read_input_args_schema(request, cmd)
        else:
            params_list = request.arguments

        # the params are binary values now, no conversion happened
        # at this stage the input is in params as a dict

        # makes sure we understand which schema to use to return result from method
        if cmd.schema_out:
            params_dict["schema_out"] = cmd.schema_out

        # now execute the method() of the cmd
        result = None

        self._log_debug("params cmd %s %s" % (params_list, params_dict))
        result = cmd.method(*params_list, **params_dict)
        if isinstance(result, list):
            result = [_result_encode(cmd, request.response_type, r) for r in result]
        else:
            result = _result_encode(cmd, request.response_type, result)

        return result

    def _read_input_args_schema(self, request, command):
        """
        get the arguments from an input which is a schema
        :param content_type:
        :param request:
        :param cmd:
        :return:
        """

        def capnp_decode(request, command, die=True):
            try:
                # Try capnp which is combination of msgpack of a list of id/capnpdata
                id, data = j.data.serializers.msgpack.loads(request.arguments[0])
                args = command.schema_in.get(data=data)
                if id:
                    args.id = id
                return args
            except Exception as e:
                if die:
                    raise ValueError(
                        "the content is not valid capnp while you provided content_type=capnp\n%s\n%s"
                        % (e, request.arguments[0])
                    )
                return None

        def json_decode(request, command, die=True):
            try:
                args = command.schema_in.get(data=j.data.serializers.json.loads(request.arguments[0]))
                return args
            except Exception as e:
                if die:
                    raise ValueError(
                        "the content is not valid json while you provided content_type=json\n%s\n%s"
                        % (str, request.arguments[0])
                    )
                return None

        if request.content_type == "auto":
            args = capnp_decode(request=request, command=command, die=False)
            if args is None:
                args = json_decode(request=request, command=command)
        elif request.content_type == "json":
            args = json_decode(request=request, command=command)
        elif request.content_type == "capnp":
            args = capnp_decode(request=request, command=command)
        else:
            raise ValueError("invalid content type was provided the valid types are ['json', 'capnp', 'auto']")

        method_arguments = command.cmdobj.args
        if "schema_out" in method_arguments:
            raise RuntimeError("schema_out should not be in arguments of method")

        params = {}

        for key in command.schema_in.propertynames:
            params[key] = getattr(args, key)

        return params

    def _cmd_obj_get(self, namespace, actor, cmd):
        """
        arguments come from self._command_split()
        will do caching of the populated command
        :param namespace:
        :param actor:
        :param cmd:
        :return: the cmd object, cmd.method is the method to be executed
        """
        key = "%s__%s" % (namespace, actor)
        key_cmd = "%s__%s" % (key, cmd)

        # caching so we don't have to eval every time
        if key_cmd in self.cmds:
            return self.cmds[key_cmd]

        self._log_debug("command cache miss:%s %s %s" % (namespace, actor, cmd))
        if namespace == "system" and key not in self.actors:
            # we will now check if the info is in default namespace
            key = "default__%s" % actor
        if namespace == "default" and key not in self.actors:
            # we will now check if the info is in system namespace
            key = "system__%s" % actor

        if key not in self.actors:
            raise j.exceptions.Input("Cannot find cmd with key:%s in actors" % key)

        if key not in self.cmds_meta:
            raise j.exceptions.Input("Cannot find cmd with key:%s in cmds_meta" % key)

        meta = self.cmds_meta[key]

        # check cmd exists in the metadata
        if cmd not in meta.cmds:
            raise j.exceptions.Input("Cannot find method with name:%s in namespace:%s" % (cmd, namespace))

        cmd_obj = meta.cmds[cmd]

        try:
            cl = self.actors[key]
            cmd_method = getattr(cl, cmd)
        except Exception as e:
            raise j.exceptions.Input(
                "Could not execute code of method '%s' in namespace '%s'\n%s" % (key, namespace, e)
            )

        cmd_obj.method = cmd_method
        self.cmds[key_cmd] = cmd_obj

        return self.cmds[key_cmd]


def _result_encode(cmd, response_type, item):

    if cmd.schema_out is not None:
        if response_type == "msgpack":
            return item._msgpack
        elif response_type == "capnp" or response_type == "auto":
            return item._data
        else:
            return item._json
    else:

        if isinstance(item, j.data.schema.DataObjBase):
            if response_type == "json":
                return item._json
            else:
                return item._data
        return item


def dm_verify(dm_id, epoch, signed_message):
    """
    retrieve the verify key of the threebot identified by bot_id
    from tfchain

    :param dm_id: threebot identification, can be one of the name or the unique integer
                    of a threebot
    :type dm_id: string
    :param epoch: the epoch param that is signed
    :type epoch: str
    :param signed_message: the epoch param signed by the private key
    :type signed_message: str
    :return: True if the verification succeeded
    :rtype: bool
    :raises: PermissionError in case of wrong message
    """
    tfchain = j.clients.tfchain.new("3bot", network_type="TEST")
    record = tfchain.threebot.record_get(dm_id)
    verify_key = nacl.signing.VerifyKey(str(record.public_key.hash), encoder=nacl.encoding.HexEncoder)
    if verify_key.verify(signed_message) != epoch:
        raise PermissionError("You couldn't authenticate your 3bot: {}".format(dm_id))

    return True
