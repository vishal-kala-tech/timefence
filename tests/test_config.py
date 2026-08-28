import json
from pathlib import Path

import pytest

from timefence.config import load_config

from tests.helpers import make_config, write_rules


def test_load_config_returns_valid_document(app_dir):
    expected = make_config(revision=3)
    path = write_rules(app_dir, expected)
    assert load_config(path) == expected


def test_load_config_accepts_shipped_rules():
    shipped = Path(__file__).resolve().parents[1] / "config" / "rules.json"
    cfg = load_config(shipped)
    assert cfg["version"] == 1
    assert set(cfg["resources"]) >= {"roblox", "youtube"}


@pytest.mark.parametrize(
    "payload",
    [
        {"version": 2, "resources": {}},
        {"version": "1", "resources": {}},
        {"resources": {}},
        {"version": 1, "resources": []},
        {"version": 1, "resources": None},
        {"version": 1},
    ],
)
def test_load_config_rejects_unsupported_or_invalid_documents(app_dir, payload):
    path = write_rules(app_dir, payload)
    with pytest.raises(ValueError, match="Unsupported or invalid config"):
        load_config(path)


def test_load_config_raises_when_file_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.json")


def test_load_config_raises_on_invalid_json(app_dir):
    path = app_dir / "config" / "rules.json"
    path.write_text("{not json")
    with pytest.raises(json.JSONDecodeError):
        load_config(path)
