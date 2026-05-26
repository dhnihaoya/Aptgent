from __future__ import annotations

from aptgent.domain.models import TargetMolecule
from aptgent.tui.steps.common import (
    format_intake_confirmation as _format_intake_confirmation,
    validate_docking_recommendation_result as _validate_docking_recommendation_result,
    validate_intake_result as _validate_intake_result,
    validate_site_proposal_result as _validate_site_proposal_result,
)


def test_validate_intake_result_normalizes_fields():
    result = _validate_intake_result(
        {
            "initial_sequence": " a c g u \n",
            "target_molecule": " theophylline ",
            "modification_region": " loop region ",
            "analogs": [" adenine ", "", None],
            "time_budget_hours": "4",
            "missing_fields": [" target_molecule "],
            "follow_up_question": "Please confirm the target.",
        }
    )

    assert result["initial_sequence"] == "ACGU"
    assert result["pdb_id"] is None
    assert result["input_mode"] == "direct"
    assert result["target_molecule"] == "theophylline"
    assert result["modification_region"] == "loop region"
    assert result["analogs"] == ["adenine"]
    assert result["time_budget_hours"] == 4
    assert result["missing_fields"] == ["target_molecule"]
def test_validate_intake_result_normalizes_pdb_fields():
    result = _validate_intake_result(
        {
            "pdb_id": " 1ehz ",
            "input_mode": "mixed",
            "initial_sequence": "acgu",
            "target_molecule": None,
            "mixed_input_detected": True,
        }
    )

    assert result["pdb_id"] == "1EHZ"
    assert result["input_mode"] == "mixed"
    assert result["mixed_input_detected"] is True
def test_validate_site_proposal_result_filters_invalid_positions():
    result = _validate_site_proposal_result(
        {
            "proposals": [
                {
                    "label": "Loop-focused",
                    "proposed_sites": ["2", -1, 99, "bad", 2, 4],
                    "reasoning": "Likely loop positions.",
                    "confidence": "High",
                },
                {
                    "label": "Conservative",
                    "proposed_sites": [1, 1, 3],
                    "reasoning": "Keeps edits compact.",
                    "confidence": "medium",
                },
                {
                    "label": "Junction probe",
                    "proposed_sites": [0, 5],
                    "reasoning": "Provides a third LLM-selected direction.",
                    "confidence": "low",
                },
            ],
        },
        sequence_length=6,
    )

    assert result["proposed_sites"] == [2, 4]
    assert result["reasoning"] == "Likely loop positions."
    assert result["confidence"] == "high"
    assert result["proposals"] == [
        {
            "label": "Loop-focused",
            "proposed_sites": [2, 4],
            "reasoning": "Likely loop positions.",
            "confidence": "high",
        },
        {
            "label": "Conservative",
            "proposed_sites": [1, 3],
            "reasoning": "Keeps edits compact.",
            "confidence": "medium",
        },
        {
            "label": "Junction probe",
            "proposed_sites": [0, 5],
            "reasoning": "Provides a third LLM-selected direction.",
            "confidence": "low",
        },
    ]
def test_validate_site_proposal_result_keeps_legacy_single_proposal_shape():
    result = _validate_site_proposal_result(
        {
            "proposed_sites": ["2", 4],
            "reasoning": "Likely loop positions.",
            "confidence": "High",
        },
        sequence_length=6,
    )

    assert result["proposed_sites"] == [2, 4]
    assert result["proposals"] == [
        {
            "label": "Recommended plan",
            "proposed_sites": [2, 4],
            "reasoning": "Likely loop positions.",
            "confidence": "high",
        }
    ]
def test_validate_site_proposal_result_preserves_region_assessment():
    result = _validate_site_proposal_result(
        {
            "region_assessment": [
                {
                    "label": "Safer scaffold edge",
                    "category": "safer_scaffold",
                    "start": "1",
                    "end": 4,
                    "positions": ["1", 2, 99, "bad"],
                    "rationale": "Peripheral unpaired bases are less likely to form the core pocket.",
                    "confidence": "Medium",
                },
                {
                    "label": "Loop core",
                    "category": "suspected_binding_core",
                    "positions": [5, 6],
                    "rationale": "Central loop may contact the ligand.",
                    "confidence": "High",
                },
            ],
            "proposals": [
                {
                    "label": "Conservative",
                    "proposed_sites": [1, 2],
                    "reasoning": "Uses the safer scaffold edge.",
                    "confidence": "medium",
                }
            ],
        },
        sequence_length=8,
    )

    assert result["region_assessment"] == [
        {
            "label": "Safer scaffold edge",
            "category": "safer_scaffold",
            "start": 1,
            "end": 4,
            "positions": [1, 2],
            "rationale": "Peripheral unpaired bases are less likely to form the core pocket.",
            "confidence": "medium",
        },
        {
            "label": "Loop core",
            "category": "suspected_binding_core",
            "start": None,
            "end": None,
            "positions": [5, 6],
            "rationale": "Central loop may contact the ligand.",
            "confidence": "high",
        },
    ]
def test_validate_docking_recommendation_result_uses_fallback_for_invalid_top_k():
    result = _validate_docking_recommendation_result(
        {"recommended_top_k": 0, "reason": ""},
        candidate_count=12,
        machine_profile={"cpu_count": 2},
        time_budget_hours=2,
    )

    assert result["recommended_top_k"] == 12
    assert result["recommended_time_budget_hours"] == 2
    assert result["recommended_exhaustiveness"] in (8, 16, 32)
    assert "grid_size" not in result
    assert "recommended_grid_size" not in result


def test_validate_docking_recommendation_result_ignores_grid_size_field():
    """Old LLM responses may still carry recommended_grid_size; ignore it."""
    result = _validate_docking_recommendation_result(
        {"recommended_top_k": 3, "recommended_grid_size": [99, 99, 99]},
        candidate_count=20,
        machine_profile={"cpu_count": 4},
        time_budget_hours=4,
    )
    assert result["recommended_top_k"] == 3
    assert "recommended_grid_size" not in result
def test_format_intake_confirmation_includes_structured_details():
    message = _format_intake_confirmation(
        sequence="ACGU",
        target_text="theophylline",
        resolved=TargetMolecule(
            input_text="theophylline",
            resolved_name="theophylline",
            smiles="CN1C=NC2=C1C(=O)N(C)C(=O)N2C",
            resolution_status="resolved",
        ),
        modification_region="loop region",
        analogs=["caffeine", "theobromine"],
        time_budget_hours=6,
    )

    assert "**Captured Intake Details**" in message
    assert "- **Sequence**: `ACGU`" in message
    assert "- **Target**: **theophylline**" in message
    assert "- **Requested modification region**: loop region" in message
    assert "- **Specificity analogs**: `caffeine`, `theobromine`" in message
    assert "- **Time budget**: 6 hour(s)" in message
