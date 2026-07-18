from __future__ import annotations

import pytest

from audit_compiler.controls.base import ControlContext
from audit_compiler.controls.registry import ControlEngine, default_controls


def test_no_allowlist_preserves_full_registry() -> None:
    run = ControlEngine().run(ControlContext(dossier=None, params={}))

    assert run.selected == tuple(control.id for control in default_controls())
    assert run.executed == run.selected
    assert run.failed == ()
    assert run.skipped == ()


def test_explicit_allowlist_runs_only_selected_control() -> None:
    run = ControlEngine(("split_payment",)).run(ControlContext(dossier=None, params={}))

    assert run.selected == ("split_payment",)
    assert run.executed == ("split_payment",)
    assert run.failed == ()
    assert "anomaly_discovery" in run.skipped


def test_empty_allowlist_runs_no_controls() -> None:
    run = ControlEngine(()).run(ControlContext(dossier=None, params={}))

    assert run.selected == ()
    assert run.executed == ()
    assert run.failed == ()
    assert run.skipped == tuple(control.id for control in default_controls())


def test_unknown_control_id_fails_visibly() -> None:
    with pytest.raises(ValueError, match=r"unknown control ID\(s\): missing"):
        ControlEngine(("missing",))
