# OBI Energy Tracker TODO

## Stabilität
- [x] Hourly 400 Fehler nur noch als DEBUG loggen
- [ ] Hourly endpoint optional behandeln
- [ ] Retry/Backoff für API Requests
- [ ] Bessere Exception-Behandlung

## Datenqualität
- [x] Meter-History von 6h auf 24h erhöhen
- [x] Recorder-/Long-Term-Statistics prüfen
- [x] Lücken nach Ausfall rückwirkend nachtragen (Statistics-Import)
- [x] Einheit geklärt: API liefert ganzzahlige Wh, HA rechnet in kWh um
- [ ] Doppelte Werte filtern
- [ ] Fehlende Werte interpolieren
- [ ] Klären ob /meter bei 48 Records deckelt (dann Chunk-Größe anheben)

## Sensoren
- [ ] Verbrauch pro Stunde berechnen
- [ ] Tagesverbrauch Sensor
- [ ] Momentanverbrauch ableiten
- [ ] Utility Meter Integration vorbereiten

## Home Assistant
- [ ] Diagnostics Support
- [ ] Repair Suggestions
- [ ] Device Info verbessern
- [ ] Translation Strings ergänzen

## HACS / Release
- [ ] SemVer sauber nutzen
- [ ] GitHub Actions hinzufügen
- [ ] hassfest Integration
- [ ] Release Workflow automatisieren

## Forschung
- [ ] Websocket/API Reverse Engineering
- [ ] Push statt Polling prüfen
- [ ] Weitere Sensoren unterstützen
- [ ] Multi-Meter Support
