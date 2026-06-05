# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a HACS (Home Assistant Community Store) custom integration for monitoring **OBI Energy Tracker** devices. It connects to OBI's cloud backend via JWT-authenticated REST APIs and exposes energy meter readings as Home Assistant sensor entities.

- Domain: `obi_energy_tracker`
- Integration type: Hub (cloud polling, 5-minute intervals)
- Current version: `0.0.5` (early-stage, see `TODO.md` for planned work)

## Development Commands

There is no local test suite yet — the quality scale marks test coverage as exempt pending pytest fixture setup. CI runs on push/PR to `main`:

```bash
# Lint with Ruff (mirrors CI)
ruff check custom_components/

# Validate manifest (requires Home Assistant dev environment)
python -m script.hassfest

# HACS validation runs via GitHub Actions only
```

CI pipelines defined in `.github/workflows/`:
- `lint.yml` — Ruff linting
- `validate.yml` — `hassfest` (HA manifest validation) + HACS action (daily cron + manual dispatch)

## Architecture

### Data Flow

```
Config Flow (email + password + country)
    └─> ObiEnergyTrackerAPI.async_login()         # POST to OBI SSO, gets JWT
            └─> async_get_bridge_info()           # Decodes JWT, fetches device IDs
ObiEnergyTrackerCoordinator (every 5 min)
    ├─> api.async_get_meter_data()                # Latest meter reading (6h window)
    └─> api.async_get_hourly_data()               # Hourly data (7 days history)
ObiMeterReadingSensor
    └─> reads coordinator.data, falls back to coordinator.last_meter_value if data missing
```

### Key Files

| File | Role |
|---|---|
| `custom_components/obi_energy_tracker/api.py` | All HTTP calls to OBI cloud endpoints; JWT login, device discovery, meter/hourly data |
| `coordinator.py` | `DataUpdateCoordinator` subclass; owns the polling loop and `last_meter_value` cache |
| `sensor.py` | Single sensor entity (`ObiMeterReadingSensor`): Wh, `TOTAL_INCREASING`, with fallback to cached value |
| `config_flow.py` | UI setup flow; validates credentials and auto-discovers `bridge_id`/`device_id` |
| `__init__.py` | Entry setup/unload; wires API → Coordinator → Sensor platform |
| `const.py` | All constants (domain, config keys, defaults) |
| `diagnostics.py` | HA diagnostics support; tests API login and returns connection status |

### External API Endpoints

- **Auth**: `https://www.obi.de/regi/auth/api/public/login` (email/password → JWT)
- **Backend**: `https://energy-tracking-backend.prod-eks.dbs.obi.solutions` (bridge info, meter data, hourly data)

The `bridge_id` and `device_id` are extracted once during config flow and stored in the config entry — they are not re-fetched on every poll.

### Sensor Behaviour

`ObiMeterReadingSensor` uses `STATE_CLASS_TOTAL_INCREASING` so Home Assistant's Energy Dashboard can track consumption. If the coordinator returns no data, the sensor falls back to `coordinator.last_meter_value` and sets `fallback_active: true` in its extra state attributes.

## Conventions

- **Typing**: The `.strict-typing` marker file is present — all code must pass strict mypy/type checks. Use the `ObiEnergyTrackerConfigEntry` type alias (`ConfigEntry[ObiEnergyTrackerCoordinator]`) rather than bare `ConfigEntry`.
- **Async**: All I/O must be `async`; use `aiohttp` (provided by Home Assistant) rather than `requests`.
- **Strings**: User-facing strings go in `strings.json` (used by HA tooling) and mirrored in `translations/en.json`. Add new languages under `translations/<lang>.json`.
- **Constants**: Add new config keys, defaults, and attribute names to `const.py`, not inline.
- **Quality scale**: `quality_scale.yaml` tracks HA quality scale compliance. Update it when adding features that affect rated rules (e.g., adding reauthentication, tests, reconfiguration flow).

## Config Entry Data Structure

The config entry stores:
```python
{
    "email": str,
    "password": str,
    "country": str,          # default "DE"
    CONF_BRIDGE_ID: str,
    CONF_DEVICE_ID: str,
}
```

`bridge_id` and `device_id` are resolved at setup time via `async_get_bridge_info()` and stored so the coordinator never needs to re-authenticate just to look them up.
