from __future__ import annotations

from aptgent.tui.widgets.step_handlers import (
    _validate_docking_recommendation_result,
    _validate_intake_result,
    _validate_site_proposal_result,
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
    assert result["target_molecule"] == "theophylline"
    assert result["modification_region"] == "loop region"
    assert result["analogs"] == ["adenine"]
    assert result["time_budget_hours"] == 4
    assert result["missing_fields"] == ["target_molecule"]


def test_validate_site_proposal_result_filters_invalid_positions():
    result = _validate_site_proposal_result(
        {
            "proposed_sites": ["2", -1, 99, "bad", 2, 4],
            "reasoning": "Likely loop positions.",
            "confidence": "High",
        },
        sequence_length=6,
    )

    assert result["proposed_sites"] == [2, 4]
    assert result["reasoning"] == "Likely loop positions."
    assert result["confidence"] == "high"


def test_validate_docking_recommendation_result_uses_fallback_for_invalid_top_k():
    result = _validate_docking_recommendation_result(
        {"recommended_top_k": 0, "reason": ""},
        candidate_count=12,
        machine_profile={"cpu_count": 2},
        time_budget_hours=2,
    )

    assert result["recommended_top_k"] == 12
    assert "resources" in result["reason"].lower()
