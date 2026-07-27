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
up to 30 days. The endpoint samples every five minutes and appears to cap a
response at 48 records, so gaps are fetched in 3-hour chunks, at most 32 per
refresh; a multi-week gap therefore closes over several refreshes rather than
all at once.

To use it in the Energy dashboard, pick **OBI Energy Tracker Meter Reading**
under *Settings → Dashboards → Energy → Grid consumption*. The existing
`sensor.obi_energytracker_meter_reading` entity keeps working unchanged.

> Only what the OBI backend actually stored can be recovered. If the tracker
> itself was offline during the outage, those hours were never uploaded and stay
> empty — enable debug logging and look for `Meter chunk ... returned 0 records`
> to tell the two cases apart.

### Units

The API reports the meter reading as whole watt-hours (`"value": 17320752`),
which Home Assistant converts to `17320.752 kWh` for display. Both the sensor
and the imported statistics are therefore declared in `Wh` (`METER_UNIT` in
`const.py`) and carry the raw value.

## Configuration

During setup, you'll need:
- **Email**: Your "OBI" account email address
- **Password**: Your "OBI" account password
- **Country**: Country code (default## API Details & Credits

---

*Disclaimer: This integration is not affiliated with or endorsed by OBI. Use at your own risk.*
