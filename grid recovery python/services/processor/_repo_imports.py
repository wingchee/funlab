from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from functools import lru_cache
from types import ModuleType


@lru_cache(maxsize=None)
def load_repo_module(module_name: str) -> ModuleType:
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / f"{module_name}.py"
    if not module_path.exists():
        raise ModuleNotFoundError(f"Cannot locate repo module {module_name!r} at {module_path}")

    spec = importlib.util.spec_from_file_location(f"_processor_repo_{module_name}", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load spec for repo module {module_name!r}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    path_added = False
    try:
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
            path_added = True
        spec.loader.exec_module(module)
        return module
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    finally:
        if path_added:
            try:
                sys.path.remove(str(repo_root))
            except ValueError:
                pass
