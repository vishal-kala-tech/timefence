from pathlib import Path

import pytest


@pytest.fixture
def app_dir(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "state").mkdir()
    return tmp_path
