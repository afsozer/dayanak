"""emsal-mcp artik Dayanak.  ``emsal_mcp.x`` importlari ``dayanak.x``e yonlenir."""
from __future__ import annotations

import importlib
import importlib.abc
import importlib.util
import sys
import warnings

import dayanak

warnings.warn(
    "emsal_mcp paketi Dayanak olarak yeniden adlandirildi; 'import dayanak' kullanin.",
    DeprecationWarning,
    stacklevel=2,
)


class _DayanakAlias(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """``emsal_mcp.<alt>`` istegini ayni ``dayanak.<alt>`` modul nesnesiyle karsilar."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("emsal_mcp."):
            return importlib.util.spec_from_loader(fullname, self)
        return None

    def create_module(self, spec):
        return importlib.import_module("dayanak" + spec.name[len("emsal_mcp"):])

    def exec_module(self, module):
        pass


sys.meta_path.insert(0, _DayanakAlias())

__version__ = dayanak.__version__
__path__: list[str] = []
