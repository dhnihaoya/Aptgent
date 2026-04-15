from __future__ import annotations

from aptgent.workflow.context import (
    build_site_proposal_llm_context,
    build_run_overview,
    get_sequence,
    record_docking_recommendation_context,
    record_intake_context,
    record_site_proposal_context,
)
from aptgent.workflow.state import RunState
from aptgent.llm.client import LLMClient
from aptgent.tui.widgets.step_handlers import (
    _format_intake_confirmation,
    _validate_docking_recommendation_result,
    _validate_intake_result,
    _validate_site_proposal_result,
)
from aptgent.domain.models import SecondaryStructure, TargetMolecule


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
    assert result["recommended_time_budget_hours"] == 2
    assert result["recommended_grid_size"] == [20.0, 20.0, 20.0]
    assert "resources" in result["reason"].lower()


def test_kimi_k25_payload_omits_temperature(tmp_path):
    config_path = tmp_path / "llm.toml"
    config_path.write_text(
        "\n".join(
            [
                "[provider.openai]",
                'base_url = "https://api.moonshot.cn/v1"',
                'model = "kimi-k2.5"',
                'api_key = "test-key"',
                "temperature = 1",
            ]
        ),
        encoding="utf-8",
    )

    client = LLMClient(config_path=config_path)
    payload = client._payload(
        "system",
        "user",
        temperature=0.2,
        response_format={"type": "json_object"},
    )

    assert "temperature" not in payload
    assert payload["thinking"] == {"type": "enabled"}


def test_iter_sse_events_emits_reasoning_before_content(tmp_path):
    config_path = tmp_path / "llm.toml"
    config_path.write_text(
        "\n".join(
            [
                "[provider.openai]",
                'base_url = "https://api.moonshot.cn/v1"',
                'model = "kimi-k2.5"',
                'api_key = "test-key"',
            ]
        ),
        encoding="utf-8",
    )

    class FakeResponse:
        def iter_lines(self):
            yield 'data: {"choices":[{"delta":{"reasoning_content":"thinking "}}]}'
            yield 'data: {"choices":[{"delta":{"content":"answer"}}]}'
            yield "data: [DONE]"

    client = LLMClient(config_path=config_path)
    events = list(client._iter_sse_events(FakeResponse()))

    assert events == [
        {"type": "reasoning", "text": "thinking "},
        {"type": "content", "text": "answer"},
    ]


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

    assert "Captured intake details." in message
    assert "Sequence: ACGU" in message
    assert "Target: theophylline" in message
    assert "Requested modification region: loop region" in message
    assert "Specificity analogs: caffeine, theobromine" in message
    assert "Time budget: 6 hour(s)" in message


def test_context_helpers_prefer_confirmed_facts():
    state = RunState(run_id="ctx_case")
    state.input_payload["initial_sequence"] = "AAAA"
    state.input_payload["user_text"] = "old note"

    record_intake_context(
        state,
        user_brief="Design a tighter caffeine binder",
        sequence="ACGU",
        target_text="caffeine",
        resolved_target=TargetMolecule(
            input_text="caffeine",
            resolved_name="Caffeine",
            smiles="Cn1cnc2n(C)c(=O)n(C)c(=O)c12",
            resolution_status="resolved",
        ),
        analogs=["theobromine"],
        time_budget_hours=4,
    )

    assert get_sequence(state) == "ACGU"
    assert build_run_overview(state) == "Caffeine | ACGU"


def test_build_site_proposal_llm_context_collects_extensible_context():
    state = RunState(run_id="site_ctx_case")
    state.input_payload["user_text"] = "Keep the loop flexible."
    state.time_budget = 3
    state.secondary_structure = SecondaryStructure(
        sequence="ACGUAC",
        dot_bracket="..(..)",
        mfe=-2.4,
        features={"length": 6, "source": "rnafold"},
    )
    record_intake_context(
        state,
        sequence="ACGUAC",
        target_text="caffeine",
        resolved_target=TargetMolecule(
            input_text="caffeine",
            resolved_name="Caffeine",
            smiles="Cn1cnc2n(C)c(=O)n(C)c(=O)c12",
            resolution_status="resolved",
        ),
        modification_region="loop region",
        analogs=["theobromine"],
        time_budget_hours=4,
    )
    record_site_proposal_context(
        state,
        proposed_sites=[2],
        extra_context={
            "structure_lookup": {
                "status": "available",
                "pdb_ids": ["1ABC"],
            }
        },
    )

    result = build_site_proposal_llm_context(state)

    assert result["sequence"] == "ACGUAC"
    assert result["secondary_structure"]["dot_bracket"] == "..(..)"
    assert result["secondary_structure"]["features"]["source"] == "rnafold"
    assert result["target_molecule"]["label"] == "Caffeine"
    assert result["user_request"]["modification_region"] == "loop region"
    assert result["workflow_context"]["previous_proposed_sites"] == [2]
    assert result["extra_context"]["structure_lookup"]["pdb_ids"] == ["1ABC"]


def test_record_docking_recommendation_context_persists_reason():
    state = RunState(run_id="dock_ctx_case")

    record_docking_recommendation_context(
        state,
        candidate_count=48,
        machine_profile={"cpu_count": 8, "memory_gb": 32},
        time_budget_hours=4,
        recommended_time_budget_hours=4,
        recommended_top_k=12,
        recommended_grid_size=[22.0, 24.0, 20.0],
        receptor_path_note="Provide the receptor path manually.",
        grid_center_note="Confirm the grid center from the binding site.",
        reason="Fits the available CPU budget.",
        display_markdown="- Time budget: 4",
        strategy="llm",
        phase="awaiting_decision",
        accepted=True,
    )

    context = state.context.docking_recommendation
    assert context.recommended_time_budget_hours == 4
    assert context.recommended_top_k == 12
    assert context.recommended_grid_size == [22.0, 24.0, 20.0]
    assert context.display_markdown == "- Time budget: 4"
    assert context.strategy == "llm"
    assert context.phase == "awaiting_decision"
    assert context.reason == "Fits the available CPU budget."
    assert context.accepted is True
