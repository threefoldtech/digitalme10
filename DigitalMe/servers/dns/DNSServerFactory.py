from pprint import pprint

from Jumpscale import j

from .DNSServer import DNSServer
import os

JSBASE = j.application.JSBaseClass
from gevent import socket

# http://mirror1.malwaredomains.com/files/justdomains  domains we should not query, lets download & put in redis core
# https://blog.cryptoaustralia.org.au/2017/12/05/build-your-private-dns-server/


class DNSServerFactory(JSBASE):
    def __init__(self):
        self.__jslocation__ = "j.servers.dns"
        JSBASE.__init__(self)
        self._extensions = {}

    def get(self, port=53, bcdb=None):
        return DNSServer(port=port, bcdb=bcdb)

    def start(self, port=53, background=False):
        """
        js_shell 'j.servers.dns.start()'
        """
        if background:
            if j.core.platformtype.myplatform.platform_is_osx and port < 1025:
                pprint("PLEASE GO TO TMUX SESSION, GIVE IN PASSWD FOR SUDO, do tmux a")
                cmd = "sudo js_shell 'j.servers.dns.start(background=False,port=%s)'" % port
            else:
                cmd = "js_shell 'j.servers.dns.start(background=False,port=%s)'" % port
            j.tools.tmux.execute(cmd, window="dnsserver", pane="main", reset=False)
            self._log_info("waiting for uidserver to start on port %s" % port)
            res = j.sal.nettools.waitConnectionTest("localhost", port)
        else:
            s = self.get(port=port)
            s.serve_forever()

    @property
    def dns_extensions(self):
        """
        all known extensions on http://data.iana.org/TLD/tlds-alpha-by-domain.txt
        """
        if self._extensions == {}:
            path = os.path.join(os.path.dirname(__file__), "knownextensions.txt")
            for line in j.sal.fs.readFile(path).split("\n"):
                if line.strip() == "" or line[0] == "#":
                    continue
                self._extensions[line] = True
        return self._extensions

    def ping(self, addr="localhost", port=53):
        """
        js_shell 'print(j.servers.dns.ping(port=53))'
        """

        address = (addr, port)
        message = b"PING"
        sock = socket.socket(type=socket.SOCK_DGRAM)
        sock.connect(address)
        pprint("Sending %s bytes to %s:%s" % ((len(message),) + address))
        sock.send(message)
        try:
            data, address = sock.recvfrom(8192)
        except Exception as e:
            if "refused" in str(e):
                return False
            raise RuntimeError("unexpected result")
        return True

    def test(self, start=False, port=5354):
        """
        js_shell 'j.servers.dns.test()'
        """

        if start or not self.ping(port=port):
            self.start(background=True, port=port)

        def ping():
            from gevent import socket

            address = ("localhost", port)
            message = b"PING"
            sock = socket.socket(type=socket.SOCK_DGRAM)
            sock.connect(address)
            pprint("Sending %s bytes to %s:%s" % ((len(message),) + address))
            sock.send(message)
            data, address = sock.recvfrom(8192)
            pprint("%s:%s: got %r" % (address + (data,)))
            assert data == b"PONG"

        ping()

        ns = j.tools.dnstools.get(["localhost"], port=port)

        pprint(ns.namerecords_get("google.com"))
        pprint(ns.namerecords_get("info.despiegk"))
