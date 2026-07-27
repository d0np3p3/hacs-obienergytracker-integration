## Credits

Original integration by @mla157:
https://github.com/mla157/hacs-obienergytracker-integration

This fork focuses on:
- improved robustness
- Home Assistant statistics compatibility
- hourly handling improvements
- long-term stability# "OBI Energy Tracker" - HACS Integration
This integration allows you to monitor your **OBI Energy Tracker** device directly within Home Assistant. The OBI Energy Tracker is a cost-effective solution for reading smart energy meters, typically accessed via the heyOBI smartphone application.e.

## Installation

Add this repository, via custom repository: https://www.hacs.xyz/docs/faq/custom_repositories/

## OBI Energy Tracker

<img src="https://bilder.obi.de/d9c6b340-b37f-48fd-92f2-72114bad03ad/prZZK/image.jpeg" width="200" alt="Energy Tracker Device">

The "OBI Energy Tracker" is a low cost device to read out smart energy meters. In default you can access the data in the "heyOBI" application on our smartphone.
I extracted the API Calls from the backend of the application, and created this "Home Assistant" Integration. 

## Gap recovery

A Home Assistant sensor can only publish its *current* value, so any period the
integration could not reach the API — an outage, a DNS/ad blocker, a restart —
used to leave a permanent hole in the history: when polling resumed, only the
newest reading was recorded.

The integration now replays missed readings into long-term statistics under
`obi_energy_tracker:meter_reading`. On every refresh it compares the last stored
hour against the meter endpoint and imports whatever is missing, reaching back
up to 30 days. Long gaps are fetched in 24-hour chunks, at most 32 per refresh,
and continue on the next cycle.

To use it in the Energy dashboard, pick **OBI Energy Tracker Meter Reading**
under *Settings → Dashboards → Energy → Grid consumption*. The existing
`sensor.obi_energytracker_meter_reading` entity keeps working unchanged.

> The statistic is recorded in **kWh**. The meter advances by roughly 9 units per
> day, which is only plausible as kilowatt-hours, while the sensor entity still
> declares `Wh`. Compare a reading against your physical meter and adjust
> `METER_UNIT` in `const.py` if needed.

## Configuration

During setup, you'll need:
- **Email**: Your "OBI" account email address
- **Password**: Your "OBI" account password
- **Country**: Country code (default## API Details & Credits

---

*Disclaimer: This integration is not affiliated with or endorsed by OBI. Use at your own risk.*
