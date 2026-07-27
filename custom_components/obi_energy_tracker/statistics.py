"""Long-term statistics backfill for Obi EnergyTracker.

A Home Assistant sensor can only ever publish its *current* state, so a stretch
of missed polls -- a network outage, a DNS blocker, a restart -- leaves a
permanent hole in the recorded history. The meter endpoint, however, still
serves those past readings. This module replays them into the long-term
statistics table so gaps close retroactively.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.components.recorder.util import get_instance
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .api import ObiEnergyTrackerAPI
from .const import (
    BACKFILL_CHUNK_HOURS,
    BACKFILL_DAYS,
    BACKFILL_MAX_CHUNKS,
    DOMAIN,
    METER_UNIT,
    STATISTIC_ID_METER,
    STATISTIC_NAME_METER,
)

_LOGGER = logging.getLogger(__name__)

# ``has_mean`` was replaced by ``mean_type`` in newer cores. StatisticMetaData is
# a TypedDict, so the wrong key fails inside the recorder rather than here.
try:  # pragma: no cover - depends on the running core version
    from homeassistant.components.recorder.models import StatisticMeanType

    _MEAN_FIELDS: dict[str, Any] = {"mean_type": StatisticMeanType.NONE}
except ImportError:  # pragma: no cover - cores before the rename
    _MEAN_FIELDS = {"has_mean": False}


def _parse_timestamp(raw: Any) -> datetime | None:
    """Parse an API timestamp into an aware UTC datetime."""
    if not isinstance(raw, str):
        return None

    parsed = dt_util.parse_datetime(raw)
    if parsed is None:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)

    return dt_util.as_utc(parsed)


def _statistic_hour(timestamp: datetime) -> datetime:
    """Return the statistics bucket a meter reading belongs to.

    A statistics row starting at hour ``H`` carries the running total at the
    *end* of that hour. A reading taken exactly at 23:00 therefore closes the
    22:00 bucket, while one taken at 23:30 is the best estimate available for
    the 23:00 bucket. Subtracting a microsecond before flooring expresses both
    cases and keeps the imported rows aligned with the ones the recorder
    compiles itself, so the two periods join without a step.
    """
    shifted = timestamp - timedelta(microseconds=1)
    return shifted.replace(minute=0, second=0, microsecond=0)


def _bucket_readings(
    payload: Any,
    earliest: datetime,
    buckets: dict[datetime, tuple[datetime, float]],
) -> None:
    """Fold meter records into hourly buckets, keeping the latest per hour."""
    if not isinstance(payload, list):
        return

    for item in payload:
        if not isinstance(item, dict):
            continue

        timestamp = _parse_timestamp(item.get("time"))
        if timestamp is None:
            continue

        try:
            value = float(item["value"])
        except (KeyError, TypeError, ValueError):
            continue

        hour = _statistic_hour(timestamp)
        if hour < earliest:
            continue

        known = buckets.get(hour)
        if known is None or timestamp >= known[0]:
            buckets[hour] = (timestamp, value)


async def _async_resume_point(hass: HomeAssistant, now: datetime) -> datetime:
    """Return the first hour that still needs importing."""
    last_stats = await get_instance(hass).async_add_executor_job(
        get_last_statistics,
        hass,
        1,
        STATISTIC_ID_METER,
        True,
        {"sum"},
    )

    rows = last_stats.get(STATISTIC_ID_METER) if last_stats else None
    if not rows:
        return now - timedelta(days=BACKFILL_DAYS)

    # The recorder reports ``start`` as a POSIX timestamp.
    return datetime.fromtimestamp(rows[0]["start"], tz=timezone.utc) + timedelta(hours=1)


async def async_backfill_statistics(
    hass: HomeAssistant, api: ObiEnergyTrackerAPI
) -> None:
    """Import any meter readings missing from long-term statistics."""
    now = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    start = await _async_resume_point(hass, now)

    if start >= now:
        return

    gap_hours = int((now - start).total_seconds() // 3600)
    _LOGGER.debug(
        "Backfilling meter statistics from %s (%d hours behind)", start, gap_hours
    )

    buckets: dict[datetime, tuple[datetime, float]] = {}
    cursor = start
    chunks = 0

    while cursor < now and chunks < BACKFILL_MAX_CHUNKS:
        payload = await api.async_get_meter_data(
            start=cursor, hours=BACKFILL_CHUNK_HOURS
        )
        _bucket_readings(payload, start, buckets)
        cursor += timedelta(hours=BACKFILL_CHUNK_HOURS)
        chunks += 1

    if cursor < now:
        _LOGGER.info(
            "Meter backfill stopped after %d requests; resuming at %s on the "
            "next refresh",
            chunks,
            cursor,
        )

    if not buckets:
        _LOGGER.debug("No meter readings returned for the missing period")
        return

    statistics: list[StatisticData] = [
        StatisticData(start=hour, state=value, sum=value)
        for hour, (_, value) in sorted(buckets.items())
    ]

    metadata: StatisticMetaData = {
        "has_sum": True,
        "name": STATISTIC_NAME_METER,
        "source": DOMAIN,
        "statistic_id": STATISTIC_ID_METER,
        "unit_of_measurement": METER_UNIT,
        **_MEAN_FIELDS,
    }

    async_add_external_statistics(hass, metadata, statistics)
    _LOGGER.info(
        "Imported %d hourly meter statistics covering %s to %s",
        len(statistics),
        statistics[0]["start"],
        statistics[-1]["start"],
    )
