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
# The meter endpoint reports an absolute meter reading (Zaehlerstand). Observed
# readings advance by roughly 9 kWh per day on a normal household connection,
# which is only plausible if the API reports kilowatt-hours -- interpreting the
# same numbers as watt-hours would imply an average draw of 0.4 W. If a physical
# meter comparison ever contradicts this, METER_UNIT is the single place to fix.
METER_UNIT = "kWh"
STATISTIC_ID_METER = f"{DOMAIN}:meter_reading"
STATISTIC_NAME_METER = "OBI Energy Tracker Meter Reading"

# How far back to reach when no statistics exist yet.
BACKFILL_DAYS = 30
# Window size of a single meter request while catching up on a gap.
BACKFILL_CHUNK_HOURS = 24
# Upper bound of requests per refresh so a long outage cannot stall the
# coordinator; remaining chunks are picked up on the following refresh.
BACKFILL_MAX_CHUNKS = 32
