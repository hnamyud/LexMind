from app.core.responses import envelope
from app.api.resources import _decode_cursor, _encode_cursor
from datetime import datetime, timezone
from uuid import uuid4


def test_success_envelope_matches_established_contract():
    assert envelope({"id": "x"}, "ok") == {"statusCode": 200, "message": "ok", "data": {"id": "x"}}


def test_cursor_round_trip():
    timestamp = datetime(2026, 7, 13, 12, 30, tzinfo=timezone.utc)
    record_id = uuid4()
    assert _decode_cursor(_encode_cursor(timestamp, record_id)) == (timestamp, record_id)
