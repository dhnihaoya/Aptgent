"""Re-export shim for backward compatibility.

All implementation lives in the ``docking`` package.
"""
from aptgent.tui.steps.docking import DockingSelectionHandler
from aptgent.tui.steps.docking._helpers import _machine_profile, _top_k_bundle

__all__ = ["DockingSelectionHandler"]
