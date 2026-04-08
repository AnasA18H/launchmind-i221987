from message_bus import MessageBus
from schemas import make_message


def test_bus_send_receive():
    bus = MessageBus()
    m = make_message(
        message_id="a",
        from_agent="ceo",
        to_agent="product",
        message_type="task",
        payload={"idea": "test"},
        timestamp="2026-04-08T12:00:00Z",
    )
    bus.send(m)
    got = bus.receive_all("product")
    assert len(got) == 1
    assert got[0]["message_id"] == "a"
    assert bus.receive_all("product") == []
    assert len(bus.history()) == 1
