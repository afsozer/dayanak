"""Bedesten date filters: bare dates are widened to LocalDateTime strings.

Olay (8 Eki 2026): `search_decisions(karar_tarihi_start="2026-01-01")` →
ADALET_EMPTY_EXCEPTION, upstream message "Cannot deserialize value of type
`java.time.LocalDateTime` from String \"2026-01-01\" ... could not be parsed
at index 10".  The tool reported it as a transient error; the same query
fails every time.  `2026-01-01T00:00:00.000Z` works (measured live).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from emsal_mcp.sources.bedesten import BedestenClient, normalize_bedesten_date

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize(
    ("value", "end", "expected"),
    [
        ("2026-01-01", False, "2026-01-01T00:00:00.000Z"),
        ("2026-10-08", True, "2026-10-08T23:59:59.999Z"),
        (" 2026-05-01 ", False, "2026-05-01T00:00:00.000Z"),
        ("13.05.2026", False, "2026-05-13T00:00:00.000Z"),
        ("1.4.2026", True, "2026-04-01T23:59:59.999Z"),
        ("01/04/2026", False, "2026-04-01T00:00:00.000Z"),
    ],
)
def test_bare_dates_get_time_part(value, end, expected):
    assert normalize_bedesten_date(value, end=end) == expected


@pytest.mark.parametrize(
    "value",
    [
        "2016-01-01T00:00:00.000Z",  # crawl CLI already sends full timestamps
        "2016-12-31T23:59:59.999Z",
        "2026",
        "dün",
        "",
        None,
    ],
)
def test_other_values_pass_through(value):
    assert normalize_bedesten_date(value) == value
    assert normalize_bedesten_date(value, end=True) == value


def _sent_payload(**filters):
    from emsal_mcp.sources import bedesten

    sent: list[dict] = []
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"data": {"emsalKararList": [], "total": 0}}

    async def _capture_post(*args, **kwargs):
        sent.append(kwargs.get("json", {}))
        return resp

    with patch.object(bedesten, "client") as mc:
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=MagicMock(post=AsyncMock(side_effect=_capture_post)))
        cm.__aexit__ = AsyncMock(return_value=False)
        mc.return_value = cm
        asyncio.run(BedestenClient().search("karar", limit=5, **filters))
    return sent[0]["data"]


def test_search_sends_timestamps_for_bare_dates():
    data = _sent_payload(karar_tarihi_start="2026-05-01", karar_tarihi_end="2026-10-08")
    assert data["kararTarihiStart"] == "2026-05-01T00:00:00.000Z"
    assert data["kararTarihiEnd"] == "2026-10-08T23:59:59.999Z"


def test_search_keeps_explicit_timestamps():
    data = _sent_payload(
        start_date="2016-01-01T00:00:00.000Z", end_date="2016-12-31T23:59:59.999Z"
    )
    assert data["kararTarihiStart"] == "2016-01-01T00:00:00.000Z"
    assert data["kararTarihiEnd"] == "2016-12-31T23:59:59.999Z"
