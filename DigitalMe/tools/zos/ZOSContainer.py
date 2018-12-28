from Jumpscale import j
from watchdog.observers import Observer
from .MyFileSystemEventHandler import MyFileSystemEventHandler
JSBASE = j.application.JSBaseClass
import time
class ZOSContainer(JSBASE):

    def __init__(self,zos,data):
        self.zos = zos
        self.__dict__.update(data)

        self._node = None

        if "address" not in data:
            self.address=self.zos.address

        self.port_ssh = None

        for p in self.ports.split(","):
            outside,inside = p.split(":")
            inside=int(inside)
            outside=int(outside)
            if inside==22:
                self.port_ssh = outside

        if self.port_ssh is None:
            raise RuntimeError("Cannot do zoscontainer: port_ssh is None:%s"%self.address)

    @property
    def node(self):
        if self._node==None:
            name="zos_%s_%s"%(self.zos.name,self.name)

            sshclient = j.clients.ssh.new(addr=self.address, port=self.port_ssh, instance=name, keyname="",
                                            timeout=5, allow_agent=True)
            node = j.tools.nodemgr.get(name=name,sshclient=name,active=True,selected=True)
            self._node=node
        return self._node

    def sync(self, monitor=False,paths=["{DIR_CODE}/github/threefoldtech/jumpscaleX",
                                        "{DIR_CODE}/github/threefoldtech/jumpscale_lib",
                                        "{DIR_CODE}/github/threefoldtech/jumpscale_prefab",
                                        "{DIR_CODE}/github/threefoldtech/digital_me"]):
        """
        sync all code to the remote destinations, uses config as set in jumpscale.toml

        """
        paths_return = self.node.sync(paths=paths,add_dont_pull=True)
        if monitor:
            self._monitor(paths=paths_return)

    def _monitor(self,paths):
        """
        look for changes in directories which are being pushed & if found push to remote nodes

        paths is [path1, path2,...] or [["/src",'/dest'],["/src2",'/dest2']]

        js_shell 'j.tools.develop.monitor()'

        """

        event_handler = MyFileSystemEventHandler(paths=paths,zoscontainer=self)
        observer = Observer()
        for source in paths:
            if j.data.types.list.check(source):
                source=source[0]
            self._logger.info("monitor:%s" % source)
            source2 = j.builder.tools.replace(source)
            observer.schedule(event_handler, source2, recursive=True)
        observer.start()
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
