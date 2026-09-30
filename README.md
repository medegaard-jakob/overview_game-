# Baggage Apron Replay

A pixel-art replay of ULD baggage transport from the T1 baggage hall to the Terminal 2 apron stands,
built from a GHS task-core data export (21–25 Sep 2026).

Open `index.html` in a browser. It loads `data/replay.js`.

- **Tugs** are coloured by driver status: to pickup (no load), full run, empty run, idle.
- **ULDs**: filled amber = full (bags), outlined teal = empty. They wait at their pickup point, ride on the dolly train, and stay at the stand until the flight's departure.
- **Drivers** panel shows each driver's logged status, current order and runs completed that day.
- **Timeline** shows ULDs delivered per hour. Drag it to scrub, or use the day buttons.

## Rebuilding the data

```
python3 tools/build_data.py path/to/extracted/Data
```

This reads `Locations.csv`, `Areas.csv`, `users.csv`, `Companies.csv`, `Flights.csv`, `TransportOrders.csv`,
`CargoTasks.csv`, `Cargos.csv` and the `TransportOrderCreated/Updated` and `flightCreated/Updated` log exports,
and writes `data/replay.json` + `data/replay.js`.

Status timestamps come from the transport-order event logs; tasks missing from the logs fall back to the
`CargoTasks.csv` actual start/finish times. A ULD leaving Empty Can Storage counts as empty; everything else counts as full.
Tug movement between timestamps is simulated at a constant speed.
