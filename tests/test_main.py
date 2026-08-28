from pathlib import Path
from unittest.mock import MagicMock

from timefence import main


def test_main_uses_time_fence_home(monkeypatch, tmp_path):
    run = MagicMock()
    monkeypatch.setattr(main, "run", run)
    monkeypatch.setenv("TIME_FENCE_HOME", str(tmp_path))

    main.main()

    run.assert_called_once_with(tmp_path)


def test_main_defaults_to_application_support(monkeypatch):
    run = MagicMock()
    monkeypatch.setattr(main, "run", run)
    monkeypatch.delenv("TIME_FENCE_HOME", raising=False)
    monkeypatch.setattr(main.os, "environ", {})

    main.main()

    expected = Path.home() / "Library/Application Support/TimeFence"
    run.assert_called_once_with(expected)
