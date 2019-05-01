import os
import gevent
from Jumpscale import j

JSConfigClient = j.application.JSBaseConfigClass
MASTER_BRANCH = "master"
DEV_BRANCH = "development"
DEV_SUFFIX = "_dev"
WIKI_CONFIG_TEMPLATE = "WIKI_CONF_TEMPLATE"
WEBSITE_CONFIG_TEMPLATE = "WEBSITE_CONF_TEMPLATE"
OPEN_PUBLISH_REPO = "https://github.com/threefoldtech/OpenPublish"


class OpenPublish(JSConfigClient):
    _SCHEMATEXT = """
        @url = jumpscale.open_publish.1
        name* = "" (S)
        websites = (LO) !jumpscale.open_publish.website.1
        wikis = (LO) !jumpscale.open_publish.wiki.1
        gedis = (O) !jumpscale.open_publish.gedis.1
        zdb = (O) !jumpscale.open_publish.zdb.1
        
        @url = jumpscale.open_publish.zdb.1
        name = "main"
        host = "127.0.0.1" (ipaddr)
        port = 9900 (I)
        mode = "seq" (S)
        adminsecret_ = "password"
        
        @url = jumpscale.open_publish.gedis.1
        name = "main"
        host = "0.0.0.0" (ipaddr)
        port = 8888 (I),
        ssl = False
        password_ = ""
            
        @url = jumpscale.open_publish.website.1
        name = "" (S)
        repo_url = "" (S)
        domain = "" (S)
        ip = "" (ipaddr)
        
        @url = jumpscale.open_publish.wiki.1
        name = "" (S)
        repo_url = "" (S)
        domain = "" (S)
        ip = "" (ipaddr)
    """

    def _init(self):
        self.open_publish_path = j.clients.git.getGitRepoArgs(OPEN_PUBLISH_REPO)[-3]
        self.gedis_server = None
        self.dns_server = None

    def auto_update(self):
        def update(objects):
            for obj in objects:
                self._log_info("Updating: {}".format(obj.name))
                self.load_site(obj, MASTER_BRANCH)
                self.load_site(obj, DEV_BRANCH, DEV_SUFFIX)
        while True:
            update(self.wikis)
            update(self.websites)
            self._log_info("Reload for docsites done")
            gevent.sleep(300)

    def bcdb_get(self, name, secret="", use_zdb=False):
        zdb_std_client = None
        if use_zdb:
            zdb_admin_client = j.clients.zdb.client_admin_get(addr=self.zdb.host, port=self.zdb.port,
                                                              secret=self.zdb.adminsecret_, mode=self.zdb.mode)
            zdb_std_client = zdb_admin_client.namespace_new(name, secret)
        bcdb = j.data.bcdb.new(name, zdb_std_client)
        return bcdb

    def servers_start(self):
        # TODO Move lapis to a seperate server and just call it from here
        j.clients.git.getContentPathFromURLorPath(OPEN_PUBLISH_REPO, pull=True)
        url = "https://github.com/threefoldtech/jumpscale_weblibs"
        weblibs_path = j.clients.git.getContentPathFromURLorPath(url, pull=True)
        j.sal.fs.symlink("{}/static".format(weblibs_path), "{}/static/weblibs".format(self.open_publish_path),
                         overwriteTarget=False)

        # Start Lapis Server
        self._log_info("Starting Lapis Server")
        cmd = "moonc . && lapis server".format(self.open_publish_path)
        lapis = j.tools.startupcmd.get(name="Lapis", cmd=cmd, path=self.open_publish_path)
        if lapis.running:
            self.reload_server()
        else:
            lapis.start()

        # Start ZDB Server and create dns namespace
        self._log_info("Starting ZDB Server")
        j.servers.zdb.configure(name=self.zdb.name, addr=self.zdb.host, port=self.zdb.port,
                                mode=self.zdb.mode, adminsecret=self.zdb.adminsecret_)
        j.servers.zdb.start()

        # Start bcdb server and create corresponding dns namespace
        bcdb = self.bcdb_get(name="dns", use_zdb=True)
        # Start DNS Server
        self.dns_server = j.servers.dns.get(bcdb=bcdb)
        gevent.spawn(self.dns_server.serve_forever)

        # Start Gedis Server
        self._log_info("Starting Gedis Server")
        self.gedis_server = j.servers.gedis.configure(name=self.gedis.name, port=self.gedis.port, host=self.gedis.host,
                                                      ssl=self.gedis.ssl, password=self.gedis.password_)
        actors_path = j.sal.fs.joinPaths(j.sal.fs.getDirName(os.path.abspath(__file__)), "base_actors")
        self.gedis_server.actors_add(actors_path)
        chatflows_path = j.sal.fs.joinPaths(j.sal.fs.getDirName(os.path.abspath(__file__)), "base_chatflows")
        self.gedis_server.chatbot.chatflows_load(chatflows_path)
        self.gedis_server.start()

    def load_site(self, obj, branch, suffix=""):
        try:
            dest = j.clients.git.getGitRepoArgs(obj.repo_url)[-3] + suffix
            j.clients.git.pullGitRepo(obj.repo_url, branch=branch, dest=dest)
            docs_path = "{}/docs".format(dest)
            doc_site = j.tools.markdowndocs.load(docs_path, name=obj.name + suffix)
            doc_site.write()
        except Exception as e:
            self._log_warning(e)

    def reload_server(self):
        cmd = "cd {0} && moonc . && lapis build".format(self.open_publish_path)
        j.tools.executorLocal.execute(cmd)

    def generate_nginx_conf(self, obj):
        conf_base_path = j.sal.fs.getDirName(os.path.abspath(__file__))
        if "website" in obj._schema.key:
            path = j.sal.fs.joinPaths(conf_base_path, WEBSITE_CONFIG_TEMPLATE)
        else:
            path = j.sal.fs.joinPaths(conf_base_path, WIKI_CONFIG_TEMPLATE)
        dest = j.sal.fs.joinPaths(self.open_publish_path, 'vhosts', '{}.conf'.format(obj.domain))
        args = {
            'name': obj.name,
            'domain': obj.domain,
        }
        j.tools.jinja2.file_render(path=path, dest=dest, **args)
        # handle if the tool used without using dns server
        if self.dns_server:
            self.dns_server.resolver.create_record(domain="wiki." + obj.domain, value=obj.ip)
            self.dns_server.resolver.create_record(domain="wiki2." + obj.domain, value=obj.ip)
        self.reload_server()

    def add_wiki(self, name, repo_url, domain, ip):
        wiki = self.wikis.new(data=dict(name=name, repo_url=repo_url, domain=domain, ip=ip))

        # Generate md files for master and dev branches
        for branch in [DEV_BRANCH and MASTER_BRANCH]:
            suffix = DEV_SUFFIX if branch == DEV_BRANCH else ""
            self.load_site(wiki, branch, suffix)

        # Generate nginx config file for wiki
        self.generate_nginx_conf(wiki)
        self.save()

    def add_website(self, name, repo_url, domain, ip):
        website = self.websites.new(data=dict(name=name, repo_url=repo_url, domain=domain, ip=ip))

        # Generate md files for master and dev branches
        for branch in [DEV_BRANCH and MASTER_BRANCH]:
            suffix = DEV_SUFFIX if branch == DEV_BRANCH else ""
            self.load_site(website, branch, suffix)

        # link website files into open publish dir
        repo_path = j.sal.fs.joinPaths(j.clients.git.getGitRepoArgs(repo_url)[-3])
        lapis_path = j.sal.fs.joinPaths(repo_path, "lapis")

        static_path = j.sal.fs.joinPaths(lapis_path, 'static', name)
        if j.sal.fs.exists(static_path):
            dest_path = j.sal.fs.joinPaths(self.open_publish_path, 'static', name)
            j.sal.fs.symlink(static_path, dest_path, overwriteTarget=False)

        views_path = j.sal.fs.joinPaths(lapis_path, 'views', name)
        if j.sal.fs.exists(views_path):
            dest_path = j.sal.fs.joinPaths(self.open_publish_path, 'views', name)
            j.sal.fs.symlink(views_path, dest_path, overwriteTarget=False)

        moon_files_path = j.sal.fs.joinPaths(lapis_path, 'applications', name + ".moon")
        if j.sal.fs.exists(moon_files_path):
            dest_path = j.sal.fs.joinPaths(self.open_publish_path, 'applications', name + ".moon")
            j.sal.fs.symlink(moon_files_path, dest_path, overwriteTarget=False)

        # Load actors and chatflows if exists
        if self.gedis_server:
            actors_path = j.sal.fs.joinPaths(repo_path, "actors")
            if j.sal.fs.exists(actors_path):
                self.gedis_server.actors_add(actors_path, namespace=name)

            chatflows_path = j.sal.fs.joinPaths(repo_path, "chatflows")
            if j.sal.fs.exists(chatflows_path):
                self.gedis_server.chatbot.chatflows_load(chatflows_path)

        if website.domain:
            # Generate nginx config file for website
            self.generate_nginx_conf(website)

        self.save()

    def remove_wiki(self, name):
        for wiki in self.wikis:
            if name == wiki.name:
                dest = j.clients.git.getGitRepoArgs(wiki.repo_url)[-3]
                j.sal.fs.remove(dest)
                j.sal.fs.remove(dest + DEV_SUFFIX)
                j.sal.fs.remove(j.sal.fs.joinPaths(j.dirs.VARDIR, "docsites", wiki.name))
                j.sal.fs.remove(j.sal.fs.joinPaths(j.dirs.VARDIR, "docsites", wiki.name + DEV_SUFFIX))
                j.sal.fs.remove(j.sal.fs.joinPaths(self.open_publish_path, 'vhosts', '{}.conf'.format(wiki.domain)))
                self.wikis.remove(wiki)
                self.save()
                self.reload_server()
                break
        else:
            raise ValueError("No wiki found with this name: {}".format(name))

    def remove_website(self, name):
        for website in self.websites:
            if name == website.name:
                dest = j.clients.git.getGitRepoArgs(website.repo_url)[-3]
                j.sal.fs.remove(dest)
                j.sal.fs.remove(dest + DEV_SUFFIX)
                try:
                    j.sal.fs.remove(j.sal.fs.joinPaths(j.dirs.VARDIR, "docsites", website.name))
                    j.sal.fs.remove(j.sal.fs.joinPaths(j.dirs.VARDIR, "docsites", website.name + DEV_SUFFIX))
                except ValueError:
                    self._log_info("This website doesn't contain docsite to remove")
                j.sal.fs.remove(j.sal.fs.joinPaths(self.open_publish_path, 'vhosts', '{}.conf'.format(website.domain)))
                j.sal.fs.remove(j.sal.fs.joinPaths(self.open_publish_path, 'static', name))
                j.sal.fs.remove(j.sal.fs.joinPaths(self.open_publish_path, 'views', name))
                j.sal.fs.remove(j.sal.fs.joinPaths(self.open_publish_path, 'applications', name + ".moon"))
                self.websites.remove(website)
                self.save()
                self.reload_server()
                break
        else:
            raise ValueError("No website found with this name: {}".format(name))
