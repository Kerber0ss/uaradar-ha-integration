"""Tests for the NEPTUN WebSocket stream client (docs/ws-notes.md contract).

The WS is mocked with fake sessions/connections; no network is touched.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from radar_ua.api import RadarUaApiError
from radar_ua.stream import HEARTBEAT_TIMEOUT_S, WS_URL, NEPTUNStreamClient

TS1 = "2026-09-20T15:00:00Z"
TS2 = "2026-09-20T15:00:10Z"

SNAPSHOT = {
    "type": "snapshot",
    "ts": TS1,
    "data": {
        "threats": [
            {"id": "trk_1", "type": "uav", "region": "Сумська область"},
            {"id": "trk_2", "type": "mig31k"},
        ]
    },
}
ALERTS = {
    "type": "alerts",
    "ts": TS1,
    "data": {
        "version": 1,
        "updatedAt": TS1,
        "raions": [
            {
                "key": "конотопський",
                "name": "Конотопський район",
                "oblast": "Сумська область",
                "since": TS1,
                "level": "red",
                "reasons": ["Виявлено загрозу"],
            }
        ],
        "oblasts": [
            {
                "key": "sumska",
                "name": "Сумська область",
                "oblast": "Сумська область",
                "since": TS1,
                "level": "red",
            }
        ],
    },
}


class FakeMsg:
    """One text WS message."""

    def __init__(self, data: str):
        self.type = aiohttp.WSMsgType.TEXT
        self.data = data


def msg(frame: dict) -> FakeMsg:
    """Wrap an envelope dict into a text WS message."""
    return FakeMsg(json.dumps(frame))


class FakeWS:
    """One WS connection: replays queued messages, then blocks until closed."""

    def __init__(self, messages=()):
        self._messages = list(messages)
        self._closed = False
        self._wakeup = asyncio.Event()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        self._closed = True
        self._wakeup.set()
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._messages:
            item = self._messages.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        if self._closed:
            raise StopAsyncIteration
        await self._wakeup.wait()
        raise StopAsyncIteration

    async def close(self):
        self._closed = True
        self._wakeup.set()


class FakeWSSession:
    """aiohttp session substitute handing out pre-built WS connections."""

    def __init__(self, connections=()):
        self._connections = list(connections)
        self.calls: list[str] = []

    def ws_connect(self, url, **kwargs):
        self.calls.append(url)
        if not self._connections:
            raise aiohttp.ClientConnectionError("no more fake connections")
        return self._connections.pop(0)


def make_client(session: FakeWSSession, **kwargs) -> NEPTUNStreamClient:
    """Build a stream client with recording callbacks and fast test timing."""
    updates: list[dict] = []
    statuses: list[bool] = []
    client = NEPTUNStreamClient(
        MagicMock(),
        session,
        on_update_cb=updates.append,
        on_status_cb=statuses.append,
        heartbeat_check_interval=0.01,
        backoff_min=0.01,
        **kwargs,
    )
    client.updates = updates
    client.statuses = statuses
    return client


async def run_client(session: FakeWSSession, settle: float = 0.05):
    """Run the client task for a moment, then hand back (client, task)."""
    client = make_client(session)
    task = asyncio.create_task(client._run())
    client._task = task  # mirror what async_start() does
    await asyncio.sleep(settle)
    return client, task


# ---------------------------------------------------------------- first update


async def test_connects_to_neptun_ws_url():
    session = FakeWSSession([FakeWS([msg(SNAPSHOT), msg(ALERTS)])])
    client, _task = await run_client(session)
    assert session.calls == [WS_URL]
    await client.async_stop()


async def test_first_update_only_after_snapshot_and_alerts():
    session = FakeWSSession([FakeWS([msg(SNAPSHOT), msg(ALERTS)])])
    client, _task = await run_client(session)

    assert len(client.updates) == 1
    data = client.updates[0]
    assert data["fetch_ok"] is True
    assert [t["id"] for t in data["threats"]] == ["trk_1", "trk_2"]
    assert data["raions"][0]["key"] == "конотопський"
    assert data["raions"][0]["level"] == "red"
    assert data["raions"][0]["reasons"] == ["Виявлено загрозу"]
    assert data["oblasts"][0]["level"] == "red"
    assert data["updated"] == TS1
    assert client.snapshot() == data
    await client.async_stop()


async def test_no_update_before_both_initial_frames():
    session = FakeWSSession([FakeWS([msg(SNAPSHOT)])])
    client, _task = await run_client(session)

    assert client.updates == []
    assert client.snapshot() is None
    await client.async_stop()


# ------------------------------------------------------- incremental mutations


async def test_upsert_remove_and_alerts_replace():
    session = FakeWSSession(
        [
            FakeWS(
                [
                    msg(SNAPSHOT),
                    msg(ALERTS),
                    msg({"type": "upsert", "ts": TS2, "data": {"id": "trk_3", "type": "missile"}}),
                    msg({"type": "alerts", "ts": TS2, "data": {"raions": [], "oblasts": []}}),
                    msg({"type": "remove", "ts": TS2, "data": {"id": "trk_1"}}),
                ]
            )
        ]
    )
    client, _task = await run_client(session)

    updates = client.updates
    assert len(updates) == 4

    # upsert added a threat and moved the updated timestamp
    assert [t["id"] for t in updates[1]["threats"]] == ["trk_1", "trk_2", "trk_3"]
    assert updates[1]["updated"] == TS2

    # alerts frame replaced raions/oblasts wholesale
    assert updates[2]["raions"] == []
    assert updates[2]["oblasts"] == []
    assert updates[2]["threats"][0]["id"] == "trk_1"

    # remove dropped the threat
    assert [t["id"] for t in updates[3]["threats"]] == ["trk_2", "trk_3"]
    await client.async_stop()


async def test_heartbeat_refreshes_last_heartbeat_without_update():
    session = FakeWSSession(
        [FakeWS([msg(SNAPSHOT), msg(ALERTS), msg({"type": "heartbeat", "ts": TS2})])]
    )
    client, _task = await run_client(session)

    assert len(client.updates) == 1  # heartbeat produces no update callback
    assert client._last_heartbeat is not None
    assert client.connected is True
    await client.async_stop()


async def test_malformed_and_unknown_frames_ignored():
    session = FakeWSSession(
        [
            FakeWS(
                [
                    FakeMsg("not json"),
                    FakeMsg(json.dumps([1, 2, 3])),
                    msg({"type": "mystery", "ts": TS2, "data": {}}),
                    msg(SNAPSHOT),
                    msg(ALERTS),
                ]
            )
        ]
    )
    client, _task = await run_client(session)

    assert len(client.updates) == 1
    assert client.snapshot() is not None
    await client.async_stop()


# ------------------------------------------------------------------ reconnect


async def test_stale_heartbeat_closes_socket_and_reconnects():
    ws1 = FakeWS([msg(SNAPSHOT), msg(ALERTS)])
    ws2 = FakeWS([])
    session = FakeWSSession([ws1, ws2])
    client, _task = await run_client(session)

    assert session.calls == [WS_URL]
    assert client.statuses == [True]

    # Silence: age the last heartbeat beyond the timeout; the watchdog
    # (check interval 10 ms in tests) closes the socket and we reconnect.
    client._last_heartbeat -= HEARTBEAT_TIMEOUT_S + 1
    await asyncio.sleep(0.15)

    assert ws1._closed is True
    assert len(session.calls) == 2
    assert client.statuses == [True, False, True]
    assert client.connected is True
    await client.async_stop()


async def test_reconnect_treats_connection_as_fresh():
    ws1 = FakeWS([msg(SNAPSHOT), msg(ALERTS)])
    ws2 = FakeWS([msg(SNAPSHOT), msg({"type": "alerts", "ts": TS2, "data": {"raions": [], "oblasts": []}})])
    session = FakeWSSession([ws1, ws2])
    client = make_client(session)
    task = asyncio.create_task(client._run())
    client._task = task
    await asyncio.sleep(0.02)

    # Force the first connection to die after full initial data.
    client._last_heartbeat -= HEARTBEAT_TIMEOUT_S + 1
    await asyncio.sleep(0.15)

    assert client._threats != {}  # re-ingested snapshot
    last = client.updates[-1]
    assert last["raions"] == [] and last["oblasts"] == []
    assert last["updated"] == TS2
    await client.async_stop()


async def test_connect_failure_keeps_retrying_with_backoff():
    session = FakeWSSession()  # every connect raises
    client, _task = await run_client(session, settle=0.1)

    assert len(session.calls) >= 2  # kept retrying
    assert client.statuses == []  # never reached the connected state
    assert client.snapshot() is None
    await client.async_stop()


def test_async_start_is_idempotent():
    session = FakeWSSession()
    client = make_client(session)

    def _close_coro(coro):
        coro.close()
        return MagicMock()

    hass = MagicMock()
    hass.async_create_task = _close_coro
    client.hass = hass
    client.async_start()
    first = client._task
    client.async_start()
    assert client._task is first


def test_backoff_doubles_with_jitter_and_caps_at_60():
    session = FakeWSSession()
    client = NEPTUNStreamClient(
        MagicMock(),
        session,
        on_update_cb=lambda data: None,
        on_status_cb=lambda connected: None,
        backoff_min=1.0,
    )
    bases = [1, 2, 4, 8, 16, 32, 60, 60]
    for attempt, base in enumerate(bases):
        for _ in range(25):
            delay = client._delay_for(attempt)
            assert base * 0.8 <= delay <= base * 1.2  # ±20 % jitter


async def test_async_stop_is_clean():
    ws = FakeWS([msg(SNAPSHOT), msg(ALERTS)])
    session = FakeWSSession([ws])
    client, task = await run_client(session)

    await client.async_stop()

    assert task.cancelled() or task.done()
    assert client.connected is False
    assert client.statuses[-1] is False


# ------------------------------------------------- coordinator transport choice


async def test_coordinator_returns_ws_data_when_available(make_coordinator):
    coordinator = make_coordinator(session=FakeWSSession())
    stream = coordinator.stream
    stream._handle_frame(dict(SNAPSHOT))  # sync ingestion, no ws task needed
    stream._handle_frame(dict(ALERTS))

    data = await coordinator._async_update_data()

    assert data["fetch_ok"] is True
    assert [t["id"] for t in data["threats"]] == ["trk_1", "trk_2"]
    assert data["raions"][0]["key"] == "конотопський"
    assert coordinator.transport == "websocket"


async def test_coordinator_falls_back_to_rest_when_stream_down(make_coordinator):
    coordinator = make_coordinator(session=FakeWSSession())
    assert coordinator.stream.snapshot() is None

    coordinator.client = MagicMock()
    coordinator.client.async_get_situation = AsyncMock(
        return_value={
            "updated": "2026-09-20T16:00:00Z",
            "fetch_ok": True,
            "attribution": "attr",
            "threats": [],
            "raions": [],
            "oblasts": [],
        }
    )

    data = await coordinator._async_update_data()

    assert data["updated"] == "2026-09-20T16:00:00Z"
    coordinator.client.async_get_situation.assert_awaited_once()
    assert coordinator.transport == "rest"


async def test_coordinator_rest_error_raises_update_failed(make_coordinator):
    from homeassistant.helpers.update_coordinator import UpdateFailed

    coordinator = make_coordinator(session=FakeWSSession())
    coordinator.client = MagicMock()
    coordinator.client.async_get_situation = AsyncMock(
        side_effect=RadarUaApiError("boom")
    )

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
