"""Build data/replay.json (and data/replay.js) from the raw GHS export folder.

Usage: python3 tools/build_data.py <path-to-extracted-Data-folder>
"""
import csv, json, sys, os, collections
from datetime import datetime, timezone

SRC = sys.argv[1]
OUT = os.path.join(os.path.dirname(__file__), '..', 'data')


def rows(name):
    with open(os.path.join(SRC, name), encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def nul(v):
    return None if v in (None, '', 'NULL') else v


def ts_csv(v):
    # "2026-09-25 09.20.00.7982405 +00:00"
    v = nul(v)
    if not v:
        return None
    d, t, _ = v.split(' ')
    hh, mm, ss, frac = t.split('.')
    dt = datetime.fromisoformat(f"{d}T{hh}:{mm}:{ss}").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def ts_iso(v):
    return int(datetime.fromisoformat(v[:19]).replace(tzinfo=timezone.utc).timestamp())


areas = {a['Id']: a['Name'] for a in rows('Areas.csv')}
locations = {}
for l in rows('Locations.csv'):
    locations[l['Id']] = {'id': l['Id'], 'name': l['Name'], 'type': l['LocationType'], 'area': areas.get(l['AreaId'])}
companies = {c['Id']: c['Name'] for c in rows('Companies.csv')}
users = {u['Id']: {'id': u['Id'], 'name': u['DisplayName'], 'company': companies.get(u['CompanyId'])} for u in rows('users.csv')}
flights = {}
for f in rows('Flights.csv'):
    flights[f['Id']] = {
        'id': f['Id'], 'no': f['FlightNumber'], 'status': f['FlightStatus'],
        'stand': nul(f['AircraftStandLocationId']),
        'sta': ts_csv(f['ScheduledTimeOfArrival']), 'std': ts_csv(f['ScheduledTimeOfDeparture']),
        'etd': ts_csv(f['EstimatedTimeOfDeparture']),
    }
# Flight logs may contain flights / stand changes not in the CSV snapshot
for fn in ('Logs-flightCreated.json', 'Logs-flightUpdated.json'):
    for e in json.load(open(os.path.join(SRC, fn))):
        body = json.loads(e['line']).get('metadata', {}).get('body')
        if not body:
            continue
        fl = json.loads(body).get('flight')
        if not fl:
            continue
        cur = flights.setdefault(fl['id'], {'id': fl['id'], 'no': fl.get('flightNumber'), 'status': None,
                                             'stand': None, 'sta': None, 'std': None, 'etd': None})
        cur['no'] = cur['no'] or fl.get('flightNumber')
        cur['stand'] = cur['stand'] or fl.get('aircraftStandId')
        for k, src in (('sta', 'scheduledTimeOfArrival'), ('std', 'scheduledTimeOfDeparture'), ('etd', 'estimatedTimeOfDeparture')):
            if not cur[k] and fl.get(src):
                cur[k] = ts_iso(fl[src])

# Test flights set up by the system vendor, not real operations
test_flights = {i for i, f in flights.items() if 'beumer' in (f['no'] or '').lower()}
for i in test_flights:
    del flights[i]

STATUS = {'READY': 'ready', 'AWAITING_START_TIME': 'waiting', 'AWAITING_DEPENDENCY': 'waiting',
          'ACCEPTED': 'accepted', 'COLLECTED': 'collected', 'DELIVERED': 'delivered', 'CANCELLED': 'cancelled'}

# ---- tasks: event stream from logs --------------------------------------
tasks = {}
order_of_task = {}
for fn in ('TransportOrderCreated-logs.json', 'TransportOrderUpdated-logs.json'):
    for e in json.load(open(os.path.join(SRC, fn))):
        line = json.loads(e['line'])
        body = line.get('metadata', {}).get('body')
        if not body:
            continue
        to = json.loads(body)['transportOrder']
        t = ts_iso(line['@timestamp'])
        for tk in to['tasks']:
            cargo = tk.get('cargo', {})
            task = tasks.setdefault(tk['id'], {'id': tk['id'], 'events': []})
            task.update({
                'order': to['id'], 'orderNo': to.get('displayId'),
                'company': companies.get(to.get('companyId')) or task.get('company'),
                'from': tk.get('pickupLocationId'), 'to': tk.get('dropoffLocationId'),
                'flight': tk.get('flightId') or task.get('flight'),
                'uld': cargo.get('identifierCode') or task.get('uld'),
                'type': (tk.get('type') or 'UNSPECIFIED').replace('TRANSPORT_ORDER_TYPE_', ''),
                'urgent': tk.get('priority') == 'PRIORITY_TYPE_URGENT',
            })
            st = STATUS.get(tk['status'].replace('TRANSPORT_ORDER_STATUS_', ''), 'ready')
            task['events'].append([t, st, to.get('assignedUserId')])
            # first moment the task is logged as urgent (escalation or urgent from the start)
            if tk.get('priority') == 'PRIORITY_TYPE_URGENT' and not task.get('urgentAt'):
                task['urgentAt'] = t
            if tk.get('latestFinishTime'):
                task['due'] = ts_iso(tk['latestFinishTime'])
            order_of_task[tk['id']] = to['id']

# ---- fallback / enrichment from DB snapshot ----------------------------
orders = {o['Id']: o for o in rows('TransportOrders.csv')}
cargos = {c['Id']: c for c in rows('Cargos.csv')}
TYPE_CSV = {'FinalSortFlight': 'FINAL_SORT_FLIGHT', 'EusFinalSort': 'EUS_FINAL_SORT', 'FinalSortLus': 'FINAL_SORT_LUS',
            'LusFlight': 'LUS_FLIGHT', 'Unspecified': 'UNSPECIFIED'}
for ct in rows('CargoTasks.csv'):
    if ct['IsDeleted'] == '1':
        continue
    o = orders.get(ct['TransportOrderId'], {})
    task = tasks.get(ct['Id'])
    if task is None:
        created = ts_csv(o.get('CreatedAt')) or ts_csv(ct['EarliestStartTime'])
        start, fin = ts_csv(ct['ActualStartTime']), ts_csv(ct['ActualFinishTime'])
        drv = nul(o.get('AssignedUserId'))
        ev = [[created, 'ready', None]]
        if start:
            ev += [[start, 'accepted', drv], [start, 'collected', drv]]
        if fin:
            ev.append([fin, 'delivered', drv])
        if ct['Status'] == 'Cancelled':
            ev.append([ts_csv(o.get('UpdatedAt')) or created, 'cancelled', drv])
        task = tasks[ct['Id']] = {
            'id': ct['Id'], 'events': [x for x in ev if x[0]], 'order': ct['TransportOrderId'],
            'orderNo': o.get('DisplayId'), 'company': companies.get(o.get('CompanyId')),
            'from': ct['PickupLocationId'], 'to': ct['DropOffLocationId'],
            'flight': nul(ct['FlightId']), 'type': TYPE_CSV.get(ct['Type'], 'UNSPECIFIED'),
            'urgent': ct['Priority'] == 'Urgent',
            'uld': (cargos.get(ct['CargoId']) or {}).get('IdentifierCode'),
        }
    elif ct['Status'] == 'Cancelled' and not any(e[1] == 'cancelled' for e in task['events']):
        task['events'].append([ts_csv(o.get('UpdatedAt')) or task['events'][-1][0], 'cancelled', None])
    task['flight'] = task.get('flight') or nul(ct['FlightId'])
    task['company'] = task.get('company') or companies.get(o.get('CompanyId'))
    # DB values win for deadlines; urgency time falls back to task creation
    task['due'] = ts_csv(ct['LatestFinishTime']) or task.get('due')
    task['elevateAt'] = ts_csv(ct['ElevateUrgencyTime'])
    task['urgent'] = ct['Priority'] == 'Urgent'
    if task['urgent'] and not task.get('urgentAt'):
        task['urgentAt'] = task['events'][0][0]
    # The logs only show an escalation at the task's next update; the DB's ElevateUrgencyTime is when it happened.
    first = min(e[0] for e in task['events'])
    if task['urgent'] and task['elevateAt'] and first < task['elevateAt'] <= task['urgentAt']:
        task['urgentAt'] = task['elevateAt']

# ---- normalise ------------------------------------------------------------
out_tasks = []
used_locs, used_users, used_flights = set(), set(), set()
for t in tasks.values():
    if t['from'] not in locations or t['to'] not in locations or t.get('flight') in test_flights:
        continue
    ev = sorted(t['events'], key=lambda e: e[0])
    # collapse consecutive duplicates
    clean = []
    for e in ev:
        if clean and clean[-1][1] == e[1]:
            if e[2] and not clean[-1][2]:
                clean[-1][2] = e[2]
            continue
        clean.append(e)
    ft, tt = locations[t['from']]['type'], locations[t['to']]['type']
    # A ULD coming out of empty storage is empty; everything leaving a chute/early storage is loaded.
    full = ft != 'EmptyStorage'
    driver = next((e[2] for e in reversed(clean) if e[2]), None)
    for e in clean:
        if e[2]:
            used_users.add(e[2])
    used_locs.update([t['from'], t['to']])
    if t.get('flight'):
        used_flights.add(t['flight'])
    out_tasks.append({
        'id': t['id'], 'order': t['order'], 'orderNo': t.get('orderNo'), 'from': t['from'], 'to': t['to'],
        'company': t.get('company') or (users.get(driver) or {}).get('company'),
        'flight': t.get('flight'), 'uld': t.get('uld') or '?', 'type': t['type'], 'urgent': t['urgent'],
        'full': full, 'driver': driver, 'ev': clean,
        'urgentAt': t.get('urgentAt') if t['urgent'] else None, 'elevateAt': t.get('elevateAt'), 'due': t.get('due'),
    })

for f in flights.values():
    if f['stand']:
        used_locs.add(f['stand'])

out_tasks.sort(key=lambda t: t['ev'][0][0])
data = {
    'generated': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    'locations': [locations[i] for i in sorted(used_locs) if i in locations],
    'drivers': [users[i] for i in sorted(used_users) if i in users],
    'flights': [f for f in flights.values() if f['id'] in used_flights or f['stand']],
    'tasks': out_tasks,
}
os.makedirs(OUT, exist_ok=True)
js = json.dumps(data, separators=(',', ':'))
open(os.path.join(OUT, 'replay.json'), 'w').write(js)
open(os.path.join(OUT, 'replay.js'), 'w').write('window.REPLAY_DATA=' + js + ';\n')
c = collections.Counter((t['full'], t['ev'][-1][1]) for t in out_tasks)
print(len(out_tasks), 'tasks,', len(data['drivers']), 'drivers,', len(data['locations']), 'locations,', len(data['flights']), 'flights')
print(c)
