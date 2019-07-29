

# Copyright (C) 2019 :  TF TECH NV in Belgium see https://www.threefold.tech/
# This file is part of jumpscale at <https://github.com/threefoldtech>.
# jumpscale is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# jumpscale is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License v3 for more details.
#
# You should have received a copy of the GNU General Public License
# along with jumpscale or jumpscale derived works.  If not, see <http://www.gnu.org/licenses/>.


# This file is part of Radicale Server - Calendar Server
# Copyright © 2014 Jean-Marc Martins
# Copyright © 2012-2017 Guillaume Ayoub
# Copyright © 2017-2019 Unrud <unrud@outlook.com>
#
# This library is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Radicale.  If not, see <http://www.gnu.org/licenses/>.

import contextlib
import logging
import os
import shlex
import subprocess

from radicale import pathutils
from radicale.log import logger


class CollectionLockMixin:
    @classmethod
    def static_init(cls):
        super().static_init()
        folder = cls.configuration.get("storage", "filesystem_folder")
        lock_path = os.path.join(folder, ".Radicale.lock")
        cls._lock = pathutils.RwLock(lock_path)

    def _acquire_cache_lock(self, ns=""):
        if self._lock.locked == "w":
            return contextlib.ExitStack()
        cache_folder = os.path.join(self._filesystem_path, ".Radicale.cache")
        self._makedirs_synced(cache_folder)
        lock_path = os.path.join(cache_folder, ".Radicale.lock" + (".%s" % ns if ns else ""))
        lock = pathutils.RwLock(lock_path)
        return lock.acquire("w")

    @classmethod
    @contextlib.contextmanager
    def acquire_lock(cls, mode, user=None):
        with cls._lock.acquire(mode):
            yield
            # execute hook
            hook = cls.configuration.get("storage", "hook")
            if mode == "w" and hook:
                folder = cls.configuration.get("storage", "filesystem_folder")
                logger.debug("Running hook")
                debug = logger.isEnabledFor(logging.DEBUG)
                p = subprocess.Popen(
                    hook % {"user": shlex.quote(user or "Anonymous")},
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE if debug else subprocess.DEVNULL,
                    stderr=subprocess.PIPE if debug else subprocess.DEVNULL,
                    shell=True,
                    universal_newlines=True,
                    cwd=folder,
                )
                stdout_data, stderr_data = p.communicate()
                if stdout_data:
                    logger.debug("Captured stdout hook:\n%s", stdout_data)
                if stderr_data:
                    logger.debug("Captured stderr hook:\n%s", stderr_data)
                if p.returncode != 0:
                    raise subprocess.CalledProcessError(p.returncode, p.args)
