from __future__ import annotations

import asyncio

import pytest

from aptgent.tui.widgets.chat_widgets import ActivityBubble, SystemBubble, ThinkingBubble, UserBubble

from tui_helpers import anyio_backend, make_app


def test_chat_bubble_default_css_enforces_lane_distinction():
    assert "margin: 0 4 1 0;" in SystemBubble.DEFAULT_CSS
    assert "width: 84%;" in SystemBubble.DEFAULT_CSS
    assert "border-left: wide $chat-system-accent;" in SystemBubble.DEFAULT_CSS
    assert "margin: 0 0 1 18;" in UserBubble.DEFAULT_CSS
    assert "width: 72%;" in UserBubble.DEFAULT_CSS
    assert "border-right: wide $chat-user-accent;" in UserBubble.DEFAULT_CSS
    assert "border-left: wide $chat-activity-accent;" in ActivityBubble.DEFAULT_CSS
@pytest.mark.anyio
async def test_chat_activity_bubble_is_last_status_message(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("activity_case")
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("activity_case")
        app.push_screen("chat")
        await pilot.pause()

        screen = app.screen
        screen.show_activity("Testing activity")
        await pilot.pause()

        activity = screen.query_one(ActivityBubble)
        chat_log = screen.query_one("#chat-log")
        assert activity is not None
        assert chat_log.children[-1] is activity

        screen.add_system_message("A normal message")
        await pilot.pause()

        assert chat_log.children[-1] is activity
@pytest.mark.anyio
async def test_chat_screen_does_not_force_scroll_when_user_is_reading_history(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("scroll_history_case")
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("scroll_history_case")
        app.push_screen("chat")
        await pilot.pause()

        screen = app.screen
        chat_log = screen.query_one("#chat-log")
        for index in range(40):
            screen.add_system_message(f"History block {index}\nLine A\nLine B")
        await pilot.pause()

        assert chat_log.max_scroll_y > 0

        chat_log.scroll_home(animate=False, immediate=True)
        await pilot.pause()

        scroll_before = chat_log.scroll_y
        screen.add_system_message("Newest update should not hijack the viewport.")
        await pilot.pause()

        assert chat_log.scroll_y == scroll_before
        assert not chat_log.is_vertical_scroll_end
def test_activity_bubble_animates_text_and_icon_together():
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    bubble = ActivityBubble("Testing activity")
    seen = []

    def capture(renderable):
        seen.append(renderable)

    bubble.update = capture  # type: ignore[method-assign]
    bubble._update_render()
    bubble._frame_idx = 3
    bubble._update_render()
    bubble.finalize()

    assert seen[0] == "[bold #A9BAD1]run[/] [#5F6B7A]· Testing activity[/]"
    assert seen[1] == "[bold #A9BAD1]run[/] [bold #F1C15B]✦ Testing activity[/]"
    assert seen[2] == "[bold #A9BAD1]run[/] [bold #F1C15B]•[/] Testing activity"
@pytest.mark.anyio
async def test_chat_screen_tool_messages_use_distinct_bubble_class(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("tool_message_case")
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("tool_message_case")
        app.push_screen("chat")
        await pilot.pause()

        bubble = app.screen.add_tool_message("**Running RNAfold**", label="tool")
        await pilot.pause()

        assert bubble.has_class("tool-bubble")
        assert isinstance(bubble, SystemBubble)
def test_thinking_bubble_toggles_expansion():
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    bubble = ThinkingBubble()
    bubble.update = lambda _: None
    bubble.append_text("First thought.")

    assert bubble.expanded is False

    bubble.toggle()
    assert bubble.expanded is True

    bubble.toggle()
    assert bubble.expanded is False


def test_thinking_bubble_expands_markup_sensitive_reasoning_text():
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    bubble = ThinkingBubble()
    bubble.update = lambda _: None
    bubble.append_text('Checking molecule ["C1=C(C(=O)N(C(=O)N2C)C)"] in JSON.')

    bubble.toggle()

    assert bubble.expanded is True
def test_thinking_bubble_collapsed_header_shows_token_count_and_arrow():
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    bubble = ThinkingBubble()
    seen = []

    def capture(renderable):
        seen.append(renderable)

    bubble.update = capture  # type: ignore[method-assign]
    bubble.append_text("Reasoning in progress.")

    latest = seen[-1]
    assert "Thinking" in latest
    assert "tokens" in latest
    assert "▼" in latest
    assert "(ctrl+o to expand)" in latest
    assert "✦" in latest or "•" in latest or "·" in latest
    assert "Thought process hidden" not in latest
@pytest.mark.anyio
async def test_ctrl_o_toggles_latest_thinking_bubble(tmp_path):
    app = make_app(tmp_path)
    state = app.engine.create_run("thinking_toggle_case")
    app.persistence.save(state)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.set_run_id("thinking_toggle_case")
        app.push_screen("chat")
        await pilot.pause()

        screen = app.screen
        bubble = screen.add_thinking_message()
        bubble.append_text("Thinking details")
        await pilot.pause()

        assert bubble.expanded is False
        await pilot.press("ctrl+o")
        await pilot.pause()
        assert bubble.expanded is True
