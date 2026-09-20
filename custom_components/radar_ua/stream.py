"""NEPTUN WebSocket stream client (see docs/ws-notes.md for the contract).

One client instance is shared by all config entries via ``hass.data[DOMAIN]``.
The client keeps the full coordinator-shaped snapshot in memory:

- ``threats``: dict id -> threat (from ``snapshot``/``upsert`` frames)
- ``raions`` / ``oblasts``: replaced on every ``alerts`` frame
- ``updated``: the ``ts`` of the last data frame (ISO 8601 string)

Frame contract (verified live, docs/ws-notes.md):

- envelope ``{"type": ..., "ts": ISO-8601, "data": ...}``; heartbeat has no data
- on connect: ``snapshot`` (data.threats only) followed by ``alerts``
  ({version, updatedAt, raions[], oblasts[]})
- regular: ``heartbeat`` (~15 s), ``upsert`` (full threat incl. trail),
  ``remove`` ({"id": ...}), ``alerts``
- silence longer than ~45 s means a dead stream -> close and reconnect

Reconnect uses exponential backoff 1, 2, 4, ... capped at 60 s with ±20 %
jitter. Gaps during downtime are covered by the coordinator's REST fallback.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections.abc import Callable
from typing import Any

import aiohttp

from .api import ATTRIBUTION, USER_AGENT

_LOGGER = logging.getLogger(__name__)

WS_URL = "wss://neptun.in.ua/api/v1/stream"
HEARTBEAT_TIMEOUT_S = 45.0  # server heartbeats every ~15 s; 45 s => dead stream
HEARTBEAT_CHECK_INTERVAL_S = 5.0
BACKOFF_MIN_S = 1.0
BACKOFF_MAX_S = 60.0
BACKOFF_JITTER = 0.2  # ±20 %
BACKOFF_RESET_AFTER_S = 60.0  # a stable connection this long resets the backoff


class NEPTUNStreamClient:
    """Maintain a live NEPTUN WebSocket stream and a current data snapshot."""

    def __init__(
        self,
        hass,
        session: aiohttp.ClientSession,
        on_update_cb: Callable[[dict[str, Any]], None],
        on_status_cb: Callable[[bool], None],
        *,
        heartbeat_check_interval: float = HEARTBEAT_CHECK_INTERVAL_S,
        backoff_min: float = BACKOFF_MIN_S,
    ) -> None:
        """Initialize the stream client.

        on_update_cb receives a full coordinator-shaped dict; on_status_cb
        receives the connection state. Both are plain sync callbacks and are
        invoked from the event loop task owned by this client.
        """
        self.hass = hass
        self._session = session
        self._on_update_cb = on_update_cb
        self._on_status_cb = on_status_cb
        self._heartbeat_check_interval = heartbeat_check_interval
        self._backoff_min = backoff_min

        self._task: asyncio.Task | None = None
        self._ws: Any | None = None
        self._closing = False
        self._connected = False

        self._threats: dict[str, dict[str, Any]] = {}
        self._raions: list[dict[str, Any]] = []
        self._oblasts: list[dict[str, Any]] = []
        self._updated: str | None = None
        self._snapshot_received = False
        self._alerts_received = False
        self._last_heartbeat: float | None = None

    # ------------------------------------------------------------------ state

    @property
    def connected(self) -> bool:
        """True while the WebSocket is open."""
        return self._connected

    def snapshot(self) -> dict[str, Any] | None:
        """Return the full coordinator-shaped dict, or None before first data.

        Non-None only after both the ``snapshot`` and the initial ``alerts``
        frame of the current connection have been processed.
        """
        if not self._snapshot_received or not self._alerts_received:
            return None
        return {
            "updated": self._updated,
            "fetch_ok": True,
            "attribution": ATTRIBUTION,
            "threats": list(self._threats.values()),
            "raions": self._raions,
            "oblasts": self._oblasts,
        }

    def _reset_session_state(self) -> None:
        """Treat every (re)connect like a fresh connect."""
        self._threats = {}
        self._raions = []
        self._oblasts = []
        self._updated = None
        self._snapshot_received = False
        self._alerts_received = False
        self._last_heartbeat = time.monotonic()

    def _set_connected(self, connected: bool) -> None:
        if self._connected != connected:
            self._connected = connected
            self._on_status_cb(connected)

    # -------------------------------------------------------------- lifecycle

    def async_start(self) -> None:
        """Start the stream task (no-op when already started)."""
        if self._task is not None:
            return
        self._task = self.hass.async_create_task(self._run())

    async def async_stop(self) -> None:
        """Close the socket, cancel the task and wait for it to finish."""
        self._closing = True
        ws = self._ws
        if ws is not None:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001 - best-effort close
                pass
        task = self._task
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001 - shutting down anyway
                pass
        self._task = None
        self._set_connected(False)

    async def _run(self) -> None:
        """Connect, listen and reconnect with exponential backoff."""
        attempt = 0
        while not self._closing:
            started = time.monotonic()
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - reconnect on any failure
                _LOGGER.debug("NEPTUN stream connection failed: %s", err)
            self._set_connected(False)
            if self._closing:
                break
            if time.monotonic() - started >= BACKOFF_RESET_AFTER_S:
                attempt = 0
            await asyncio.sleep(self._delay_for(attempt))
            attempt += 1

    def _delay_for(self, attempt: int) -> float:
        """Exponential backoff with ±20 % jitter (1, 2, 4 ... capped at 60)."""
        return _jittered(min(self._backoff_min * 2**attempt, BACKOFF_MAX_S))

    async def _connect_and_listen(self) -> None:
        """Open one WebSocket connection and process frames until it closes."""
        async with self._session.ws_connect(
            WS_URL, headers={"User-Agent": USER_AGENT}
        ) as ws:
            self._ws = ws
            self._reset_session_state()
            self._set_connected(True)
            watchdog = asyncio.create_task(self._heartbeat_watchdog(ws))
            try:
                async for msg in ws:
                    if msg.type is not aiohttp.WSMsgType.TEXT:
                        if msg.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            break
                        continue
                    try:
                        frame = json.loads(msg.data)
                    except (TypeError, ValueError):
                        _LOGGER.debug("Ignoring non-JSON WS frame")
                        continue
                    self._handle_frame(frame)
            finally:
                watchdog.cancel()
                self._ws = None

    async def _heartbeat_watchdog(self, ws: Any) -> None:
        """Close the socket when no heartbeat arrives within the timeout."""
        try:
            while True:
                await asyncio.sleep(self._heartbeat_check_interval)
                if self._last_heartbeat is None:
                    continue
                if time.monotonic() - self._last_heartbeat > HEARTBEAT_TIMEOUT_S:
                    _LOGGER.debug("NEPTUN stream heartbeat stale, reconnecting")
                    await ws.close()
                    return
        except asyncio.CancelledError:
            pass  # silent shutdown; never swallow the connection task's cancel

    # ----------------------------------------------------------------- frames

    def _handle_frame(self, frame: Any) -> None:
        """Apply one envelope frame to the in-memory snapshot."""
        if not isinstance(frame, dict):
            return
        frame_type = frame.get("type")
        ts = frame.get("ts")
        data = frame.get("data")

        if frame_type == "heartbeat":
            self._last_heartbeat = time.monotonic()
            return

        if frame_type == "snapshot":
            self._ingest_threats(data)
            self._snapshot_received = True
        elif frame_type == "alerts":
            if self._ingest_alerts(data):
                self._alerts_received = True
        elif frame_type == "upsert":
            if isinstance(data, dict) and data.get("id"):
                self._threats[data["id"]] = data
        elif frame_type == "remove":
            if isinstance(data, dict) and data.get("id"):
                self._threats.pop(data["id"], None)
        else:
            _LOGGER.debug("Ignoring unknown WS frame type: %s", frame_type)
            return

        if isinstance(ts, str):
            self._updated = ts
        complete = self.snapshot()
        if complete is not None:
            self._on_update_cb(complete)

    def _ingest_threats(self, data: Any) -> None:
        """Replace the threat dict from a snapshot frame payload."""
        self._threats = {}
        if isinstance(data, dict) and isinstance(data.get("threats"), list):
            for threat in data["threats"]:
                if isinstance(threat, dict) and threat.get("id"):
                    self._threats[threat["id"]] = threat

    def _ingest_alerts(self, data: Any) -> bool:
        """Replace raions/oblasts from an alerts frame payload."""
        if not isinstance(data, dict):
            return False
        raions = data.get("raions")
        oblasts = data.get("oblasts")
        if not isinstance(raions, list) or not isinstance(oblasts, list):
            return False
        self._raions = [item for item in raions if isinstance(item, dict)]
        self._oblasts = [item for item in oblasts if isinstance(item, dict)]
        return True


def _jittered(delay: float) -> float:
    """Apply ±20 % jitter to a backoff delay."""
    return delay * (1.0 + random.uniform(-BACKOFF_JITTER, BACKOFF_JITTER))
