"""Re-export shim -- all panel classes now live in :mod:`aptgent.tui.widgets.panels`.

.. deprecated::
    Import from ``aptgent.tui.widgets.panels`` directly instead.
"""

from aptgent.tui.widgets.panels import (  # noqa: F401
    StructuredInputSubmitted,
    StructuredActionRequested,
    _BaseStructuredPanel,
    ActionMenuPanel,
    MutationSitePanel,
    PdbSelectionPanel,
    AnalogCheckboxPanel,
    AnalogCustomPanel,
    DockingStrategyPanel,
    DockingSourcePanel,
    DockingManualUploadPanel,
    DockingRNAComposerProgressPanel,
    DockingParamPanel,
)

__all__ = [
    "StructuredInputSubmitted",
    "StructuredActionRequested",
    "_BaseStructuredPanel",
    "ActionMenuPanel",
    "MutationSitePanel",
    "PdbSelectionPanel",
    "AnalogCheckboxPanel",
    "AnalogCustomPanel",
    "DockingStrategyPanel",
    "DockingSourcePanel",
    "DockingManualUploadPanel",
    "DockingRNAComposerProgressPanel",
    "DockingParamPanel",
]
