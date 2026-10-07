# Baggage Apron Replay

A replay of ULD baggage transport from the T1 baggage hall to the Terminal 2 apron stands,
built from a GHS task-core data export (21–25 Sep 2026).

Open `index.html` in a browser. It loads `data/replay.js`.

- **`index.html`: Apron Control Room** (main view). A light isometric 3D apron: the blue-roofed hall with dock
  doors, 3D tugs pulling dolly trains, ULD stacks and planes on stand. Floating cards show today's KPIs
  (with on-time delivery), the selected tug, order tracking steps, and live lists of tugs, banks and flights.
  Drag to pan, scroll or use the buttons to zoom, click a tug to follow it, scrub time along the bottom.
- **`classic.html`: pixel view.** The original top-down game-style view with a drivers panel, day summary,
  hourly chart and order log.

- **`map.html`: Apron Map** (prototype). The 3D view on the real Heathrow layout: the T1 baggage hall,
  Terminal 2A and the 2B pier, with every stand at its published position and heading. Stands in use on the
  shown day (for the chosen organisation) are drawn in yellow with planes and ULDs. The rest are faint
  outlines. Tugs drive a simplified airside road network, so travel times follow real distances.
  The layout comes from `data/map_layout.js`, built by `tools/build_map_layout.py` from the UK AIP chart
  AD 2-EGLL-2-7 (stand coordinate table and terminal outlines). The chart itself is not stored.

All views share the same replay logic, and the validator checks any of them (`--page map.html`).

On the map:
- **Tugs** are coloured by driver status: assigned, to pickup, full run, empty run, idle.
- **ULDs**: amber = full (bags), light grey/teal = empty. They wait at their pickup point, ride on the dolly
  train, and stay at the stand until their flight departs. Red marks show urgent, overdue and late ULDs.

## Rebuilding the data

```
python3 tools/build_data.py path/to/extracted/Data
```

This reads `Locations.csv`, `Areas.csv`, `users.csv`, `Companies.csv`, `Flights.csv`, `TransportOrders.csv`,
`CargoTasks.csv`, `Cargos.csv` and the `TransportOrderCreated/Updated` and `flightCreated/Updated` log exports,
and writes `data/replay.json` + `data/replay.js`.

Status timestamps come from the transport-order event logs, replayed oldest-first. Orders the database never had
(test orders that only exist in the logs) are left out, and ULDs removed from an order end at the moment they
were removed. Creation times come from CargoTaskHistory / TransportOrders when the creation log is missing; tasks missing from the logs fall back to the
`CargoTasks.csv` actual start/finish times. A ULD leaving Empty Can Storage counts as empty; everything else counts as full.
Tug movement between timestamps is simulated at a constant speed.
Flights with "Beumer" in the flight number are vendor test flights and are left out, together with their orders.

## Validating the replay

```
cd tools && npm install && cd ..        # once: Playwright for the on-screen checks
python3 tools/validate.py path/to/extracted/Data                       # main view (index.html)
python3 tools/validate.py path/to/extracted/Data --page classic.html   # pixel view
```

`validate.py` recomputes the expected values straight from the raw CSV export, without using
`data/replay.json`, and writes `validation-report.md`:

- **Part A:** the replay data vs the raw export. Every task present, final status, delivered
  time, driver, organisation, full/empty rule and event order.
- **Part B:** what the page shows vs the raw export, every 15 minutes across the whole replay (hourly per
  organisation). Counters, runs, flights, urgent and late counts, organisation filter sums, hourly chart
  total, driver busy/idle and which order each driver shows, planes on stand.

Checks are PASS, WARN (a documented simplification or a fact about the data) or FAIL.
The script exits with code 1 if anything fails.

In Claude Code you can also ask for the **replay-validator** agent (`.claude/agents/replay-validator.md`).
It rebuilds the data, runs the checks, traces every failure back to the raw rows, spot-checks a few
orders end to end and reports whether the replay can be trusted.
