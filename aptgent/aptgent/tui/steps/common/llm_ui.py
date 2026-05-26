from __future__ import annotations

from typing import Any, Callable


def run_llm_interaction(
    screen: Any,
    *,
    display_stream: Callable[[], Any] | None,
    structured_call: Callable[[], Any],
    structured_client: Any | None = None,
) -> dict[str, Any]:
    from textual.worker import get_current_worker

    worker = get_current_worker()
    if worker.is_cancelled:
        return {}

    bubble = None
    thinking_bubble = None
    display_error: Exception | None = None

    if display_stream is not None:
        def make_thinking_bubble() -> None:
            nonlocal thinking_bubble
            thinking_bubble = screen.add_thinking_message()

        screen.app.call_from_thread(screen.clear_activity)
        screen.app.call_from_thread(make_thinking_bubble)
        try:
            for chunk in display_stream():
                if worker.is_cancelled:
                    return {}
                if isinstance(chunk, dict):
                    chunk_type = chunk.get("type", "content")
                    text = chunk.get("text", "")
                else:
                    chunk_type = "content"
                    text = chunk
                if not text:
                    continue
                if chunk_type == "reasoning":
                    screen.app.call_from_thread(thinking_bubble.append_text, text)
                    continue
                if bubble is None:
                    def make_bubble() -> None:
                        nonlocal bubble
                        bubble = screen.add_streaming_message(markdown=True)

                    screen.app.call_from_thread(make_bubble)
                screen.app.call_from_thread(bubble.append_text, text)
        except Exception as exc:
            display_error = exc
        finally:
            if thinking_bubble:
                if thinking_bubble.has_content:
                    screen.app.call_from_thread(thinking_bubble.finalize)
                else:
                    screen.app.call_from_thread(thinking_bubble.remove)
            if bubble:
                screen.app.call_from_thread(bubble.finalize)

    if worker.is_cancelled:
        return {}

    screen.app.call_from_thread(screen.update_activity, "Processing structured result...")
    result = structured_call()
    if not isinstance(result, dict):
        raise RuntimeError("LLM returned a non-object response.")

    if display_error is not None:
        screen.app.call_from_thread(
            screen.add_system_message,
            f"LLM explanation unavailable; using structured fallback. {display_error}",
            "warning-text",
        )

    return result
