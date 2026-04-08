import pytest

from schemas import make_message, validate_message


def test_valid_message():
    m = make_message(
        message_id="m1",
        from_agent="ceo",
        to_agent="product",
        message_type="task",
        payload={"idea": "x"},
        timestamp="2026-04-08T12:00:00Z",
    )
    validate_message(m)


def test_invalid_message_type():
    with pytest.raises(ValueError):
        make_message(
            message_id="m1",
            from_agent="ceo",
            to_agent="product",
            message_type="invalid",
            payload={},
            timestamp="2026-04-08T12:00:00Z",
        )
