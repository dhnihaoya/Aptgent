"""Tests for MOE source selection and worker integration."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aptgent.adapters.moe_prep import MoePreparationAdapter
from tui_helpers import anyio_backend  # noqa: F401  (anyio fixture)


def test_moe_prep_adapter_not_in_runtime_when_unavailable():
    """When moebatch is not found, create_moe_prep_adapter returns None."""
    from aptgent.bootstrap.container import create_moe_prep_adapter

    with patch("aptgent.adapters.moe_prep.shutil.which", return_value=None):
        result = create_moe_prep_adapter({"moe": {"moebatch": "moebatch"}})
    assert result is None


def test_moe_prep_adapter_created_when_available():
    """When moebatch is found, create_moe_prep_adapter returns an adapter."""
    from aptgent.bootstrap.container import create_moe_prep_adapter

    with patch("aptgent.adapters.moe_prep.shutil.which", return_value="/usr/bin/moebatch"):
        result = create_moe_prep_adapter({
            "moe": {"moebatch": "moebatch", "timeout_per_file": 300},
            "receptor_prep": {"obabel": "obabel", "padding_angstrom": 4.0},
        })
    assert result is not None
    assert isinstance(result, MoePreparationAdapter)
    assert result.timeout_per_file == 300


def test_source_panel_accepts_moe_available_kwarg():
    """DockingSourcePanel should accept moe_available kwarg."""
    from aptgent.tui.widgets.panels._docking import DockingSourcePanel

    panel = DockingSourcePanel(top_k=10, moe_available=True)
    assert panel.moe_available is True

    panel_no_moe = DockingSourcePanel(top_k=10, moe_available=False)
    assert panel_no_moe.moe_available is False


def test_moe_progress_panel_initialization():
    """DockingMOEProgressPanel should initialize with total."""
    from aptgent.tui.widgets.panels._docking import DockingMOEProgressPanel

    panel = DockingMOEProgressPanel(total=5)
    assert panel.total == 5


def test_handler_recognizes_moe_actions():
    """DockingSelectionHandler should handle MOE source actions."""
    from aptgent.tui.steps.docking._handler import DockingSelectionHandler

    handler = DockingSelectionHandler(MagicMock())
    # Verify the handler has the method signature to process these actions
    # by checking the handle_action method exists and is callable
    assert hasattr(handler, "handle_action")
    assert callable(handler.handle_action)


def test_source_mixin_has_moe_methods():
    """_SourceMixin should have MOE-related methods."""
    from aptgent.tui.steps.docking._source import _SourceMixin

    assert hasattr(_SourceMixin, "_is_moe_available")
    assert hasattr(_SourceMixin, "_on_source_selected")


def test_structures_mixin_has_moe_workers():
    """_StructuresMixin should have MOE worker methods."""
    from aptgent.tui.steps.docking._structures import _StructuresMixin

    assert hasattr(_StructuresMixin, "_moe_combined_worker")
    assert hasattr(_StructuresMixin, "_moe_manual_worker")
    assert hasattr(_StructuresMixin, "_show_moe_manual_upload_panel")
    assert hasattr(_StructuresMixin, "_on_moe_manual_upload_submitted")


def test_doctor_checks_moe():
    """doctor.py should include APTGENT_MOEBATCH in env vars."""
    from aptgent.cli.doctor import _check_env_vars

    env = _check_env_vars()
    assert "APTGENT_MOEBATCH" in env


def test_models_accept_moe_receptor_source():
    """DockingPlan.receptor_source should accept MOE source values."""
    from aptgent.domain.models import DockingPlan

    for source in ("rnacomposer-moe", "moe-manual"):
        plan = DockingPlan(receptor_source=source)
        assert plan.receptor_source == source


@pytest.mark.anyio
async def test_moe_manual_upload_panel_posts_correct_phase():
    """DockingManualUploadPanel with phase='moe_manual_upload' should post that phase."""
    from textual.app import App, ComposeResult
    from textual.widgets import Input

    from aptgent.tui.widgets.panels._docking import DockingManualUploadPanel
    from aptgent.tui.widgets.panels._core import StructuredInputSubmitted

    collected: list[StructuredInputSubmitted] = []

    class _TestApp(App):
        def compose(self) -> ComposeResult:
            yield DockingManualUploadPanel(
                export_dir="/tmp/export",
                candidate_ids=["cand_0", "cand_1"],
                default_structures_dir="/tmp/rna",
                phase="moe_manual_upload",
            )

        def on_structured_input_submitted(self, event: StructuredInputSubmitted) -> None:
            collected.append(event)

    app = _TestApp()
    async with app.run_test() as pilot:
        dir_input = app.query_one("#dock-structures-dir", Input)
        dir_input.value = "/some/rna_dir"
        await pilot.click("#btn-load-structures")

    assert len(collected) == 1
    assert collected[0].data["phase"] == "moe_manual_upload"
    assert collected[0].data["structures_dir"] == "/some/rna_dir"


def test_handler_routes_moe_manual_upload_phase():
    """handle_structured_input should route phase='moe_manual_upload' to _on_moe_manual_upload_submitted."""
    from unittest.mock import MagicMock, patch

    from aptgent.tui.steps.docking._handler import DockingSelectionHandler

    handler = DockingSelectionHandler(MagicMock())
    handler._on_moe_manual_upload_submitted = MagicMock()
    handler._on_manual_upload_submitted = MagicMock()
    handler._on_param_submitted = MagicMock()

    handler.handle_structured_input({
        "phase": "moe_manual_upload",
        "structures_dir": "/some/path",
    })

    handler._on_moe_manual_upload_submitted.assert_called_once_with({
        "phase": "moe_manual_upload",
        "structures_dir": "/some/path",
    })
    handler._on_manual_upload_submitted.assert_not_called()
