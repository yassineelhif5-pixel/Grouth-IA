import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def pytest_ignore_collect(collection_path, config):
    # Integration tests need Django + PostgreSQL (CI service); unit tests run anywhere.
    if "integration" in str(collection_path) and not os.environ.get("RUN_INTEGRATION"):
        return True
    return None
