from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[2] / "experiments" / "solo-agentgateway" / "unified" / "live_unified_obo.py"
SPEC = importlib.util.spec_from_file_location("live_unified_notebook", MODULE_PATH)
assert SPEC and SPEC.loader
live_runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(live_runner)


def test_start_only_starts_stack_without_running_live_validation(monkeypatch, capsys) -> None:
    config = {"ENTRA_TENANT_ID": "tenant-live", "BANKING_TEST_USER_OID": "user-oid"}
    monkeypatch.setenv("BANKING_TEST_USER_OID", "user-oid")
    monkeypatch.setattr(live_runner, "_require_config", lambda: config)
    starts = []
    monkeypatch.setattr(live_runner, "_start_live_stack", lambda *, config: starts.append(config))
    monkeypatch.setattr(live_runner, "run_live_unified_validation", lambda: (_ for _ in ()).throw(AssertionError("must not run")))

    assert live_runner.main(["--start-only"]) == 0
    assert starts == [config]
    assert "PHASE_5_STACK_STATUS: RUNNING" in capsys.readouterr().out


def test_stop_only_stops_persistent_stack(monkeypatch, capsys) -> None:
    config = {"ENTRA_TENANT_ID": "tenant-live"}
    monkeypatch.setattr(live_runner, "_require_config", lambda: config)
    stops = []
    monkeypatch.setattr(live_runner, "_stop_live_stack", lambda *, config: stops.append(config))

    assert live_runner.main(["--stop"]) == 0
    assert stops == [config]
    assert "PHASE_5_STACK_STATUS: STOPPED" in capsys.readouterr().out
