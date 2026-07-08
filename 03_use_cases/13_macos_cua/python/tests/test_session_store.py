import base64

from metacua.session_store import SessionStore, _TraceImageWriter, _image_extension


def test_sanitized_string_redacts_image_data():
    raw = "data:image/png;base64,abcdef"
    assert SessionStore._sanitized_string(raw) == "data:image/png;base64,<redacted 6 base64 bytes>"
    assert SessionStore._sanitized_string("hello") == "hello"
    assert SessionStore._sanitized_string("data:image/png;base64") == "data:image/<redacted>"


def test_image_extension_from_prefix():
    assert _image_extension("data:image/png;base64") == ".png"
    assert _image_extension("data:image/jpeg;base64") == ".jpg"
    assert _image_extension("data:image/webp;base64") == ".webp"
    assert _image_extension("data:image/;base64") == ".png"


def test_image_writer_saves_sidecar_and_dedupes(tmp_path):
    png = bytes.fromhex("89504e470d0a1a0a")  # PNG magic bytes are enough for the test
    encoded = base64.b64encode(png).decode("ascii")
    writer = _TraceImageWriter(image_dir=tmp_path / "trace-1", rel_prefix="trace-1")

    ref = writer.save("data:image/png;base64", encoded)
    assert ref is not None
    # Reference keeps the media prefix and points at a relative sidecar path.
    prefix, marker = ref.split(",", 1)
    assert prefix == "data:image/png;base64"
    assert marker.startswith("<saved trace-1/")
    assert f"({len(png)} bytes)>" in marker

    relpath = marker[len("<saved "):].split(" (")[0]
    saved = tmp_path / relpath
    assert saved.read_bytes() == png

    # Same content -> same file, written once.
    again = writer.save("data:image/png;base64", encoded)
    assert again == ref
    assert writer.saved_count == 1

    # Undecodable payloads fall back to redaction (None).
    assert writer.save("data:image/png;base64", "not*base64*") is None or writer.saved_count == 1


def test_sanitized_json_extracts_nested_images(tmp_path):
    png = bytes.fromhex("89504e470d0a1a0a")
    encoded = base64.b64encode(png).decode("ascii")
    writer = _TraceImageWriter(image_dir=tmp_path / "trace-2", rel_prefix="trace-2")
    conversation = [
        {"role": "user", "content": [
            {"type": "input_text", "text": "hi"},
            {"type": "input_image", "image_url": f"data:image/png;base64,{encoded}"},
        ]},
    ]

    sanitized = SessionStore._sanitized_json(conversation, writer)
    image_url = sanitized[0]["content"][1]["image_url"]
    assert "<saved trace-2/" in image_url
    assert writer.saved_count == 1
    assert list((tmp_path / "trace-2").glob("*.png"))


def test_safe_trace_id_sanitizes():
    safe = SessionStore._safe_trace_id(" abc/def:ghi_123 ")
    assert safe == "abc-def-ghi_123"
    assert SessionStore._safe_trace_id("ok-ID_1") == "ok-ID_1"


def test_record_matches_variants():
    record = {
        "record_id": "record",
        "response_id": "response",
        "trace_id": "trace",
        "goal_id": "goal",
        "trace_file": "/tmp/my-trace.jsonl",
        "session_ids": ["session-a", "session-b"],
    }
    for needle in ["record", "response", "trace", "goal", "my-trace", "my-trace.jsonl", "session-a"]:
        assert SessionStore._record_matches(record, needle)
    assert not SessionStore._record_matches(record, "missing")
