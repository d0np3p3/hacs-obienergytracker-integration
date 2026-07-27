"""Constants for the obienergytracker integration."""

DOMAIN = "obi_energy_tracker"

# Config constants
CONF_COUNTRY = "country"
CONF_BRIDGE_ID = "bridge_id"
CONF_DEVICE_ID = "device_id"

# Default values
DEFAULT_COUNTRY = "DE"
DEFAULT_SCAN_INTERVAL = 300  # 5 minutes

# Data attributes
ATTR_BRIDGE_ID = "bridge_id"
ATTR_DEVICE_ID = "device_id"

# Long-term statistics
#
# The meter endpoint reports the absolute meter reading (Zaehlerstand) as a whole
# number of watt-hours -- a raw sample looks like {"time": ..., "value": 17320752}
# and surfaces as 17320.752 kWh once Home Assistant converts it for display. The
# imported statistics carry the raw value, so they must be declared in Wh to
# match; the dashboard applies the same conversion.
METER_UNIT = "Wh"
STATISTIC_ID_METER = f"{DOMAIN}:meter_reading"
STATISTIC_NAME_METER = "OBI Energy Tracker Meter Reading"

# Window for the live reading. Kept short deliberately: a wide window has been
# observed to make the API answer with older records instead of the newest one,
# which leaves the sensor stuck on a stale value. One hour still tolerates a
# missed poll at the five-minute scan interval.
LIVE_METER_HOURS = 1

# How far back to reach when no statistics exist yet.
BACKFILL_DAYS = 30
# Window size of a single meter request while catching up on a gap. The endpoint
# samples every five minutes and was observed returning exactly 48 records for a
# 24 hour request, so it appears to cap a response rather than honour the full
# window. Three hours stays well inside that ceiling; raise it once a longer
# window is confirmed to come back complete.
BACKFILL_CHUNK_HOURS = 3
# Upper bound of requests per refresh so a long outage cannot stall the
# coordinator; remaining chunks are picked up on the following refresh.
BACKFILL_MAX_CHUNKS = 32
