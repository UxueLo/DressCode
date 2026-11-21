import os
import sys
import tempfile
from pathlib import Path

# La configuración se lee al importar `config`: hay que fijarla antes de nada.
_TMP = tempfile.mkdtemp(prefix="dresscode-test-")
os.environ.update({"DATA_DIR": _TMP, "EMBEDDER": "color-hist", "GEMINI_MODE": "fake",
                   "FEED_SOURCES": "local", "CIUDAD": "Bilbao"})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from database.db import ArmarioDB  # noqa: E402


@pytest.fixture()
def db(tmp_path):
    return ArmarioDB(str(tmp_path / "t.db"))
