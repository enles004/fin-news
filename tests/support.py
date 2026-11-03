"""Test support: global test isolation and per-test home context manager."""
import atexit
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import tempfile

# Global temporary directory for test suite isolation
_GLOBAL_TEST_TEMP_DIR = tempfile.mkdtemp(prefix="fin_global_test_")
os.environ["FIN_NEWS_HOME"] = _GLOBAL_TEST_TEMP_DIR

# Ensure UTF-8 stdout/stderr in test environments on Windows
import sys
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _cleanup_global():
    shutil.rmtree(_GLOBAL_TEST_TEMP_DIR, ignore_errors=True)


atexit.register(_cleanup_global)


@contextmanager
def isolated_home(prefix="fin_test_"):
    """Context manager giving a per-test temp home and restoring previous value."""
    temp_dir = tempfile.mkdtemp(prefix=prefix)
    old_home = os.environ.get("FIN_NEWS_HOME")
    os.environ["FIN_NEWS_HOME"] = temp_dir
    try:
        yield Path(temp_dir)
    finally:
        if old_home is not None:
            os.environ["FIN_NEWS_HOME"] = old_home
        else:
            os.environ.pop("FIN_NEWS_HOME", None)
        shutil.rmtree(temp_dir, ignore_errors=True)
