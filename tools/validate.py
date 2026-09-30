"""Check that the replay depicts the raw export correctly.

Usage: python3 tools/validate.py <path-to-extracted-Data-folder> [--report validation-report.md] [--no-page]

Expected values are recomputed from the raw CSV export (CargoTasks, TransportOrders, Locations,
Flights, users, Companies). They do not come from data/replay.json, so a bug in build_data.py or
in the page shows up as a mismatch instead of being copied into the expectation.

Part A compares data/replay.json with the raw export.
Part B opens index.html headless (tools/snapshot.js) at sample moments and compares what the page
shows with the raw export.

Result per check: PASS, WARN (explainable by a documented simplification, e.g. animation catch-up)
or FAIL. Exit code 1 if any check fails.
"""
import csv, json, os, subprocess, sys, tempfile, collections
from datetime import datetime, timezone

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
args = [a for a in sys.argv[1:] if not a.startswith('--')]
if not args:
    sys.exit(__doc__)
SRC = args[0]
REPORT = sys.argv[sys.argv.index('--report') + 1] if '--report' in sys.argv else os.path.join(ROOT, 'validation-report.md')
if REPORT in args:
    args.remove(REPORT)
RUN_PAGE = '--no-page' not in sys.argv
TOL = 120          # seconds allowed between log timestamps and DB timestamps
LAG = 10 * 60      # animation catch-up window around a status change


def rows(name):
    with open(os.path.join(SRC, name), encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def nul(v):
    return None if v in (None, '', 'NULL') else v


def ts(v):
    v = nul(v)
    if not v:
        return None
    d, t, _ = v.split(' ')
    hh, mm, ss, _frac = t.split('.')
    return int(datetime.fromisoformat(f'{d}T{hh}:{mm}:{ss}').replace(tzinfo=timezone.utc).timestamp())


def fmt(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime('%a %d %H:%M') if t else '—'


# ---------------- raw export ----------------
companies = {c['Id']: c['Name'] for c in rows('Companies.csv')}
locs = {l['Id']: l for l in rows('Locations.csv')}
users = {u['Id']: u for u in rows('users.csv')}
orders = {o['Id']: o for o in rows('TransportOrders.csv')}
cargos = {c['Id']: c for c in rows('Cargos.csv')}
flights = {f['Id']: f for f in rows('Flights.csv')}
test_flights = {i for i, f in flights.items() if 'beumer' in f['FlightNumber'].lower()}

raw = {}
for c in rows('CargoTasks.csv'):
    if c['IsDeleted'] == '1' or c['FlightId'] in test_flights:
        continue
    o = orders.get(c['TransportOrderId'], {})
    pick = locs.get(c['PickupLocationId'], {})
    raw[c['Id']] = {
        'id': c['Id'], 'order': c['TransportOrderId'], 'orderNo': o.get('DisplayId'),
        'status': c['Status'], 'start': ts(c['ActualStartTime']), 'finish': ts(c['ActualFinishTime']),
        'driver': nul(o.get('AssignedUserId')), 'company': companies.get(o.get('CompanyId')),
        'full': pick.get('LocationType') != 'EmptyStorage', 'pickup': pick.get('Name'),
        'drop': locs.get(c['DropOffLocationId'], {}).get('Name'),
        'loaded_flag': (cargos.get(c['CargoId']) or {}).get('IsLoaded'),
        'flight': nul(c['FlightId']),
    }
delivered = [t for t in raw.values() if t['status'] == 'Delivered' and t['finish']]

replay = json.load(open(os.path.join(ROOT, 'data', 'replay.json')))
rtasks = {t['id']: t for t in replay['tasks']}
rloc = {l['id']: l for l in replay['locations']}

results = []   # (part, name, level, summary, examples)


def check(part, name, bad, total, summary, examples=(), warn_only=False):
    level = 'PASS' if not bad else ('WARN' if warn_only else 'FAIL')
    results.append((part, name, level, summary.format(bad=bad, total=total), list(examples)[:8]))


def last(t, st):
    r = None
    for e in t['ev']:
        if e[1] == st:
            r = e[0]
    return r


# ---------------- A. replay.json vs raw export ----------------
missing = [i for i in raw if i not in rtasks]
check('A', 'Every raw ULD task is in the replay', len(missing), len(raw),
      '{bad} of {total} raw tasks missing from replay.json', [f'task {i}' for i in missing])
extra = [i for i in rtasks if i not in raw]
check('A', 'Replay tasks not in CargoTasks.csv', len(extra), len(rtasks),
      '{bad} tasks come only from the event logs (created after the DB snapshot or deleted since)',
      [f"order #{rtasks[i]['orderNo']} task {i}" for i in extra], warn_only=True)

STATUS = {'Delivered': 'delivered', 'Cancelled': 'cancelled', 'Ready': 'ready'}
bad = []
for i, r in raw.items():
    t = rtasks.get(i)
    if t and STATUS.get(r['status'], r['status'].lower()) != t['ev'][-1][1]:
        bad.append(f"order #{r['orderNo']}: DB {r['status']}, replay ends {t['ev'][-1][1]}")
check('A', 'Final status matches DB', len(bad), len(raw), '{bad} of {total} tasks end in a different status', bad)

bad = []
for t in delivered:
    rt = rtasks.get(t['id'])
    d = rt and last(rt, 'delivered')
    if rt and (not d or abs(d - t['finish']) > TOL):
        bad.append(f"order #{t['orderNo']}: DB finish {fmt(t['finish'])}, replay delivered {fmt(d)}")
check('A', f'Delivered time within {TOL}s of DB ActualFinishTime', len(bad), len(delivered),
      '{bad} of {total} delivered tasks off by more than the tolerance', bad)

bad = []
for t in raw.values():
    rt = rtasks.get(t['id'])
    if rt and t['driver'] and rt['driver'] != t['driver']:
        bad.append(f"order #{t['orderNo']}: DB {users.get(t['driver'], {}).get('DisplayName')}, replay {users.get(rt['driver'], {}).get('DisplayName')}")
check('A', 'Driver matches TransportOrders.AssignedUserId', len(bad), len(raw), '{bad} of {total} tasks assigned to a different driver', bad)

bad = [f"order #{t['orderNo']}: DB {t['company']}, replay {rtasks[t['id']]['company']}" for t in raw.values()
       if t['id'] in rtasks and t['company'] and rtasks[t['id']]['company'] != t['company']]
check('A', 'Organisation matches TransportOrders.CompanyId', len(bad), len(raw), '{bad} of {total} tasks with another organisation', bad)

bad = [f"order #{t['orderNo']}: pickup {t['pickup']}" for t in raw.values()
       if t['id'] in rtasks and rtasks[t['id']]['full'] != t['full']]
check('A', 'Full/empty follows the pickup rule', len(bad), len(raw), '{bad} of {total} tasks classified against the rule', bad)

flagged = [t for t in raw.values() if t['loaded_flag'] in ('0', '1')]
disagree = [f"order #{t['orderNo']} {t['pickup']} → {t['drop']}: IsLoaded={t['loaded_flag']}" for t in flagged
            if (t['loaded_flag'] == '1') != t['full']]
check('A', 'Pickup rule vs Cargos.IsLoaded (info)', len(disagree), len(flagged),
      '{bad} of {total} ULDs where the cargo record disagrees with the pickup rule (IsLoaded is the ULD\'s current state, not per trip)',
      disagree, warn_only=True)

ORDER = {'ready': 0, 'waiting': 0, 'accepted': 1, 'collected': 2, 'delivered': 3}
bad = []
for t in rtasks.values():
    seq = [ORDER[e[1]] for e in t['ev'] if e[1] in ORDER and e[1] not in ('ready', 'waiting')]
    if seq != sorted(seq):
        bad.append(f"order #{t['orderNo']}: " + ' → '.join(e[1] for e in t['ev']))
check('A', 'Status events in logical order', len(bad), len(rtasks), '{bad} of {total} tasks with steps out of order', bad, warn_only=True)

# ---------------- B. page vs raw export ----------------
if RUN_PAGE:
    orgs = ['all'] + sorted({t['company'] for t in raw.values() if t['company']})
    days = sorted({t['finish'] // 86400 * 86400 for t in delivered})
    times = [d + h * 3600 for d in days for h in (6, 8, 10, 12, 15, 18)]
    reqs = [{'t': t, 'org': o} for t in times for o in orgs]
    with tempfile.TemporaryDirectory() as tmp:
        rq, out = os.path.join(tmp, 'req.json'), os.path.join(tmp, 'out.json')
        json.dump(reqs, open(rq, 'w'))
        env = dict(os.environ)
        subprocess.run(['node', os.path.join(ROOT, 'tools', 'snapshot.js'), os.path.join(ROOT, 'index.html'), rq, out], check=True, env=env)
        page = json.load(open(out))
    snaps = page['snaps']
    check('B', 'Page runs without script errors', len(page['errors']), len(snaps), '{bad} script errors', page['errors'])

    in_org = lambda c, o: o == 'all' or c == o
    # B1 delivered today + runs completed
    bad_f, bad_r, bad_fl = [], [], []
    for s in snaps:
        T, o, d0 = s['t'], s['org'], s['t'] // 86400 * 86400
        mine = [t for t in delivered if in_org(t['company'], o)]
        for key, full in (('full', True), ('empty', False)):
            sure = sum(1 for t in mine if t['full'] == full and d0 <= t['finish'] <= T - TOL)
            maybe = sum(1 for t in mine if t['full'] == full and T - TOL < t['finish'] <= T + TOL)
            got = s['stats'][key]
            if not (sure <= got <= sure + maybe + len(extra)):
                bad_f.append(f"{fmt(T)} {o}: {key} delivered today page {got}, DB {sure}(+{maybe} at the boundary)")
        by_order = collections.defaultdict(list)
        for t in mine:
            by_order[t['order']].append(t['finish'])
        sure = sum(1 for f in by_order.values() if d0 <= max(f) <= T - TOL)
        maybe = sum(1 for f in by_order.values() if T - TOL < max(f) <= T + TOL)
        if not (sure <= s['stats']['runs'] <= sure + maybe + len(extra)):
            bad_r.append(f"{fmt(T)} {o}: runs page {s['stats']['runs']}, DB {sure}(+{maybe})")
        sure = {t['flight'] for t in mine if t['flight'] and d0 <= t['finish'] <= T - TOL}
        maybe = {t['flight'] for t in mine if t['flight'] and d0 <= t['finish'] <= T + TOL} - sure
        if not (len(sure) <= s['stats']['flights'] <= len(sure) + len(maybe) + len(extra)):
            bad_fl.append(f"{fmt(T)} {o}: flights processed page {s['stats']['flights']}, DB {len(sure)}(+{len(maybe)})")
    check('B', 'Counters: full/empty ULDs delivered today', len(bad_f), len(snaps) * 2, '{bad} of {total} counter readings disagree with the DB', bad_f)
    check('B', 'Day summary: flights processed', len(bad_fl), len(snaps), '{bad} of {total} readings disagree with the DB', bad_fl)
    check('B', 'Counters: runs completed today', len(bad_r), len(snaps), '{bad} of {total} readings disagree with the DB', bad_r)

    # B2 organisation filter adds up and hides the other organisation
    bad = []
    by_t = collections.defaultdict(dict)
    for s in snaps:
        by_t[s['t']][s['org']] = s
    for T, group in by_t.items():
        for key in ('full', 'empty', 'runs', 'waiting'):
            parts = sum(group[o]['stats'][key] for o in orgs[1:])
            if group['all']['stats'][key] != parts:
                bad.append(f"{fmt(T)} {key}: all {group['all']['stats'][key]} ≠ sum of organisations {parts}")
        for o in orgs[1:]:
            wrong = [d['tag'] for d in group[o]['drivers'] if d['company'] != o]
            if wrong:
                bad.append(f"{fmt(T)} filter {o} still shows {', '.join(wrong)}")
    check('B', 'Organisation filter adds up to All', len(bad), len(by_t), '{bad} inconsistencies', bad)

    # B3 hourly chart total
    bad = []
    for s in snaps:
        if s['t'] != snaps[0]['t']:
            continue
        exp = sum(1 for t in delivered if in_org(t['company'], s['org']))
        if not (exp <= s['chartTotal'] <= exp + len(extra)):
            bad.append(f"{s['org']}: chart {s['chartTotal']} ULDs, DB {exp}")
    check('B', 'Hourly chart total = delivered ULDs', len(bad), len(orgs), '{bad} of {total} chart totals disagree', bad)

    # B4 driver busy/idle vs DB order window. In the DB, ActualStartTime is when the driver accepted
    # the order and ActualFinishTime when it was delivered; collection time exists only in the logs.
    carry = collections.defaultdict(list)   # driver -> [(accepted, delivered, full, orderNo)]
    by_order = collections.defaultdict(list)
    for t in raw.values():
        if t['driver'] and t['start'] and t['finish']:
            by_order[(t['driver'], t['order'])].append(t)
    for (drv, _), ts_ in by_order.items():
        carry[drv].append((min(t['start'] for t in ts_), max(t['finish'] for t in ts_), any(t['full'] for t in ts_), ts_[0]['orderNo']))
    BUSY = {'To pickup', 'Loading', 'Full run', 'Empty run', 'Unloading'}
    hard, soft, n = [], [], 0
    for s in snaps:
        if s['org'] != 'all':
            continue
        for d in s['drivers']:
            n += 1
            win = [c for c in carry.get(d['id'], []) if c[0] <= s['t'] < c[1]]
            near = any(abs(s['t'] - c[0]) < LAG or abs(s['t'] - c[1]) < LAG for c in carry.get(d['id'], []))
            page_busy = d['status'] in BUSY
            if bool(win) != page_busy:
                msg = f"{fmt(s['t'])} {d['tag']}: page '{d['status']}', DB " + (f"working on order #{win[0][3]}" if win else 'no active order')
                (soft if near else hard).append(msg)
            elif win and d['status'] in ('Full run', 'Empty run') and (d['status'] == 'Full run') != win[0][2]:
                hard.append(f"{fmt(s['t'])} {d['tag']}: page '{d['status']}' but order #{win[0][3]} is {'full' if win[0][2] else 'empty'}")
    check('B', 'Driver busy/idle matches DB order window', len(hard), n, '{bad} of {total} driver readings contradict the DB', hard)
    check('B', f'Driver status within {LAG // 60} min of a status change', len(soft), n,
          '{bad} of {total} readings differ only because the tug is still catching up with the log', soft, warn_only=True)

    # B5 planes on stand follow the documented rule
    bad, overlap, logonly = [], [], []
    csv_flights = {f['FlightNumber'] for f in flights.values()}
    for s in snaps:
        exp = collections.defaultdict(list)
        for fid, f in flights.items():
            if fid in test_flights or f['IsDeleted'] == '1':
                continue
            out = ts(f['EstimatedTimeOfDeparture']) or ts(f['ScheduledTimeOfDeparture'])
            stand = locs.get(f['AircraftStandLocationId'], {})
            if not out or stand.get('LocationType') != 'FlightStand' or not any(l['name'] == stand['Name'] for l in rloc.values()):
                continue
            if s['org'] != 'all' and not any(t['flight'] == fid and t['company'] == s['org'] for t in raw.values()):
                continue
            inn = ts(f['ScheduledTimeOfArrival']) or out - 150 * 60
            if inn <= s['t'] <= out + 300:
                exp[stand['Name']].append(f['FlightNumber'])
        got = {p['stand']: p['flight'] for p in s['planes']}
        for stand, fl in exp.items():
            if len(fl) > 1:
                overlap.append(f"{fmt(s['t'])} stand {stand}: {', '.join(fl)} at the same time (page shows {got.get(stand)})")
            if got.get(stand) not in fl:
                bad.append(f"{fmt(s['t'])} {s['org']} stand {stand}: expected {fl}, page {got.get(stand)}")
        for stand, fl in got.items():
            if stand not in exp and fl not in csv_flights:
                logonly.append(f"{fmt(s['t'])} stand {stand}: {fl}")
            elif stand not in exp:
                bad.append(f"{fmt(s['t'])} {s['org']} stand {stand}: page shows {fl}, not expected")
    check('B', 'Planes on stand follow the arrival/departure rule', len(bad), len(snaps), '{bad} mismatches', bad)
    check('B', 'Flights known only from the flight event logs', len(set(logonly)), len(snaps),
          '{bad} planes come from FlightCreated/Updated logs, not the Flights.csv snapshot', sorted(set(logonly)), warn_only=True)
    check('B', 'Two flights on one stand at the same time (data)', len(set(overlap)), len(snaps),
          '{bad} overlapping stand allocations; the page can only draw one plane per stand', sorted(set(overlap)), warn_only=True)

# ---------------- report ----------------
icon = {'PASS': '✅', 'WARN': '⚠️', 'FAIL': '❌'}
lines = ['# Replay validation report', '',
         f"Export: `{os.path.abspath(SRC)}`  ", f"Generated: {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}  ",
         f"Raw ULD tasks (test flights excluded): {len(raw)} · delivered: {len(delivered)} · replay tasks: {len(rtasks)}", '',
         '| | Part | Check | Result |', '|---|---|---|---|']
for part, name, level, summary, _ in results:
    lines.append(f'| {icon[level]} | {part} | {name} | {summary} |')
for part, name, level, summary, ex in results:
    if ex:
        lines += ['', f'## {icon[level]} {name}', ''] + [f'- {e}' for e in ex]
open(REPORT, 'w').write('\n'.join(lines) + '\n')
counts = collections.Counter(r[2] for r in results)
print(f"{counts['PASS']} pass, {counts['WARN']} warn, {counts['FAIL']} fail → {os.path.relpath(REPORT)}")
for part, name, level, summary, _ in results:
    print(f'  {level:4} {part} {name}: {summary}')
sys.exit(1 if counts['FAIL'] else 0)
