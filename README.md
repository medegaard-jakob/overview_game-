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
Flights with "Beumer" in the flight number are vendor test flights and are left out, together with their orders.

## Validating the replay

```
cd tools && npm install && cd ..        # once: Playwright for the on-screen checks
python3 tools/validate.py path/to/extracted/Data
```

`validate.py` recomputes the expected values straight from the raw CSV export, without using
`data/replay.json`, and writes `validation-report.md`:

- **Part A:** the replay data vs the raw export. Every task present, final status, delivered
  time, driver, organisation, full/empty rule and event order.
- **Part B:** what the page shows vs the raw export, at 6 moments per day for All / Menzies / United.
  Counters, runs, organisation filter sums, hourly chart total, driver busy/idle, planes on stand.

Checks are PASS, WARN (a documented simplification or a fact about the data) or FAIL.
The script exits with code 1 if anything fails.

In Claude Code you can also ask for the **replay-validator** agent (`.claude/agents/replay-validator.md`).
It rebuilds the data, runs the checks, traces every failure back to the raw rows, spot-checks a few
orders end to end and reports whether the replay can be trusted.
