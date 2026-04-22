from __future__ import annotations

import json

from aptgent.jobs.events import EventReader, EventWriter, read_last_event


class TestEventProtocol:
    def test_writer_creates_events_jsonl(self, tmp_path):
        writer = EventWriter(tmp_path / "events.jsonl")
        writer.write_started(pid=12345)
        writer.close()

        lines = (tmp_path / "events.jsonl").read_text().strip().splitlines()
        assert len(lines) == 1
        evt = json.loads(lines[0])
        assert evt["type"] == "started"
        assert evt["pid"] == 12345
        assert "ts" in evt

    def test_writer_progress_and_hit(self, tmp_path):
        writer = EventWriter(tmp_path / "events.jsonl")
        writer.write_started(pid=99)
        writer.write_progress(done=500, total=1000, extra={"binding": 12})
        writer.write_hit(candidate_id="cand_0", probability=0.92)
        writer.write_done(summary={"total": 1000, "hits": 12})
        writer.close()

        lines = (tmp_path / "events.jsonl").read_text().strip().splitlines()
        assert len(lines) == 4
        types = [json.loads(l)["type"] for l in lines]
        assert types == ["started", "progress", "hit", "done"]

    def test_writer_error(self, tmp_path):
        writer = EventWriter(tmp_path / "events.jsonl")
        writer.write_error(message="boom")
        writer.close()

        evt = json.loads((tmp_path / "events.jsonl").read_text().strip())
        assert evt["type"] == "error"
        assert evt["message"] == "boom"

    def test_writer_heartbeat(self, tmp_path):
        writer = EventWriter(tmp_path / "events.jsonl")
        writer.write_heartbeat()
        writer.close()

        evt = json.loads((tmp_path / "events.jsonl").read_text().strip())
        assert evt["type"] == "heartbeat"

    def test_reader_reads_events(self, tmp_path):
        path = tmp_path / "events.jsonl"
        path.write_text(
            '{"type":"started","ts":"t1","pid":1}\n'
            '{"type":"progress","ts":"t2","done":5,"total":10}\n'
        )
        reader = EventReader(path)
        events = list(reader.iter_events())
        assert len(events) == 2
        assert events[0]["type"] == "started"
        assert events[1]["done"] == 5

    def test_read_last_event(self, tmp_path):
        path = tmp_path / "events.jsonl"
        path.write_text(
            '{"type":"started","ts":"t1","pid":1}\n'
            '{"type":"done","ts":"t2","summary":{}}\n'
        )
        evt = read_last_event(path)
        assert evt is not None
        assert evt["type"] == "done"

    def test_read_last_event_empty(self, tmp_path):
        path = tmp_path / "events.jsonl"
        assert read_last_event(path) is None

    def test_read_last_event_missing(self, tmp_path):
        assert read_last_event(tmp_path / "nope.jsonl") is None
