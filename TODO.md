# OBI Energy Tracker TODO

## Stabilität
- [x] Hourly 400 Fehler nur noch als DEBUG loggen
- [x] Hourly endpoint nicht mehr pro Refresh abgefragt (war ungenutzt)
- [x] Retry/Backoff für API Requests
- [x] Bessere Exception-Behandlung
- [x] Token-Refresh (war: Token lief nach ~1h ab, alle Calls still auf None)

## Datenqualität
- [x] Meter-History von 6h auf 24h erhöhen
- [x] Recorder-/Long-Term-Statistics prüfen
- [x] Lücken nach Ausfall rückwirkend nachtragen (Statistics-Import)
- [x] Einheit geklärt: API liefert ganzzahlige Wh, HA rechnet in kWh um
- [ ] Doppelte Werte filtern
- [ ] Fehlende Werte interpolieren
- [x] /meter deckelt nicht: 720h Rückstand real nachgetragen, 3h-Blöcke passen

## Sensoren
- [ ] Verbrauch pro Stunde berechnen
- [ ] Tagesverbrauch Sensor
- [x] Momentanverbrauch (Live-Power via WebSocket)
- [ ] Utility Meter Integration vorbereiten

## Home Assistant
- [x] Diagnostics Support (Batterie, Signalstärke)
- [ ] Repair Suggestions
- [ ] Device Info verbessern
- [ ] Translation Strings ergänzen

## HACS / Release
- [x] SemVer sauber nutzen (im Release-Workflow erzwungen)
- [x] GitHub Actions hinzufügen
- [x] hassfest Integration
- [x] Release Workflow automatisieren

## Forschung
- [x] Websocket/API Reverse Engineering
- [x] Push statt Polling (WebSocket ergänzt das Polling)
- [ ] Weitere Sensoren unterstützen
- [ ] Multi-Meter Support
