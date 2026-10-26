"""External extractor plugins.

A plugin is a Python file that defines one or more subclasses of
``gtnh_save_inspector.extractors.base.Extractor``. Loading it registers every extractor
class it defines (plus any ``EXTRACTORS = [...]`` list it exposes).

Load order: built-in extractors, then plugins in the order they were given. Registration
re-sorts by ``priority``, so a plugin can run before or after built-ins.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from typing import Iterable, List, Optional

from . import EXTRACTORS
from .base import Extractor


class PluginError(RuntimeError):
    """Raised when a plugin cannot be loaded."""


def _load_module(path: str, index: int):
    module_name = "gtnh_save_inspector_plugin_%d" % index
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise PluginError("cannot load plugin: %s" % path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - plugin authors see this
        raise PluginError("plugin %s failed to import: %s" % (path, exc)) from exc
    return module


def _extractors_from_module(module) -> List[Extractor]:
    found: List[Extractor] = []
    declared = getattr(module, "EXTRACTORS", None)
    if declared:
        for item in declared:
            if isinstance(item, Extractor):
                found.append(item)
    for value in vars(module).values():
        if not isinstance(value, type):
            continue
        if value is Extractor or not issubclass(value, Extractor):
            continue
        if value.__module__ != module.__name__:
            continue
        try:
            found.append(value())
        except Exception as exc:  # pragma: no cover
            raise PluginError("cannot instantiate %s: %s" % (value.__name__, exc)) from exc
    return found


def register(extractor: Extractor) -> None:
    """Register an extractor instance and keep the registry sorted by priority."""
    EXTRACTORS.append(extractor)
    EXTRACTORS.sort(key=lambda item: item.priority)


def unregister(name: str) -> bool:
    """Remove extractors with this name (used by tests). Returns True if any were removed."""
    global EXTRACTORS
    before = len(EXTRACTORS)
    EXTRACTORS[:] = [item for item in EXTRACTORS if item.name != name]
    return len(EXTRACTORS) != before


def load_plugins(paths: Iterable[str]) -> List[str]:
    """Load plugin files and return the names of registered extractors."""
    registered: List[str] = []
    for index, path in enumerate(paths):
        if not path:
            continue
        if not os.path.isfile(path):
            raise PluginError("plugin not found: %s" % path)
        module = _load_module(os.path.abspath(path), index)
        extractors = _extractors_from_module(module)
        if not extractors:
            raise PluginError("plugin %s did not define any Extractor subclass" % path)
        for extractor in extractors:
            register(extractor)
            registered.append(extractor.name)
    return registered


def plugin_paths_from_env() -> List[str]:
    raw = os.environ.get("GTNH_INSPECTOR_PLUGINS", "")
    separator = ";" if os.name == "nt" else ":"
    return [part for part in raw.split(separator) if part.strip()]


def load_config_plugins(cli_paths: Optional[Iterable[str]] = None) -> List[str]:
    """Load plugins from CLI paths plus the GTNH_INSPECTOR_PLUGINS environment variable."""
    paths: List[str] = []
    if cli_paths:
        paths.extend(cli_paths)
    env_paths = plugin_paths_from_env()
    paths.extend(env_paths)
    if not paths:
        return []
    return load_plugins(paths)
