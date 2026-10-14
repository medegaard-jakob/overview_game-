#!/usr/bin/env python3
"""Fetch the real Heathrow weather for the days in data/replay.json and write data/weather.js.

Usage: python3 tools/build_weather.py

Sources (both free, no key):
- METAR reports for EGLL (every 30 min) from the Iowa Environmental Mesonet archive:
  temperature, wind, gusts, visibility, present weather (rain, fog, ...), cloud.
- Open-Meteo historical archive for the airport: hourly rain in mm and cloud cover, plus sunrise/sunset.
"""
import csv, io, json, os, re, sys, urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
LAT, LON = 51.4700, -0.4543          # EGLL aerodrome reference point


def get(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read().decode()


def replay_days():
    d = json.load(open(os.path.join(ROOT, 'data', 'replay.json')))
    ts = [e[0] for t in d['tasks'] for e in t['ev']] + [f[k] for f in d['flights'] for k in ('sta', 'std', 'etd') if f.get(k)]
    a = datetime.fromtimestamp(min(ts), timezone.utc).date() - timedelta(days=1)
    b = datetime.fromtimestamp(max(ts), timezone.utc).date() + timedelta(days=1)
    return a, b


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def metars(a, b):
    q = '&'.join(f'data={k}' for k in ('tmpc', 'dwpc', 'drct', 'sknt', 'gust', 'vsby', 'wxcodes', 'skyc1', 'skyl1', 'metar'))
    url = (f'https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=EGLL&{q}'
           f'&year1={a.year}&month1={a.month}&day1={a.day}&year2={b.year}&month2={b.month}&day2={b.day}'
           '&tz=Etc/UTC&format=onlycomma&missing=empty&trace=empty')
    out = []
    for r in csv.DictReader(io.StringIO(get(url))):
        t = int(datetime.strptime(r['valid'], '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc).timestamp())
        raw = r['metar']
        vis = num(r['vsby'])
        m = re.search(r'\s(\d{4})\s', raw)           # METAR visibility in metres (9999 = 10 km or more)
        vis_m = int(m.group(1)) if m else (round(vis * 1609) if vis is not None else None)
        if 'CAVOK' in raw:
            vis_m = 9999
        out.append({'t': t, 'temp': num(r['tmpc']), 'dew': num(r['dwpc']), 'dir': num(r['drct']),
                    'kt': num(r['sknt']), 'gust': num(r['gust']), 'vis': vis_m, 'wx': r['wxcodes'] or '',
                    'sky': r['skyc1'] or '', 'base': num(r['skyl1']), 'raw': raw})
    return out


def hourly(a, b):
    url = (f'https://archive-api.open-meteo.com/v1/archive?latitude={LAT}&longitude={LON}'
           f'&start_date={a}&end_date={b}&hourly=precipitation,cloud_cover&daily=sunrise,sunset'
           '&timezone=UTC&timeformat=unixtime')
    d = json.loads(get(url))
    h = d['hourly']
    rows = [{'t': t, 'mm': p, 'cloud': c} for t, p, c in zip(h['time'], h['precipitation'], h['cloud_cover'])]
    sun = [[r, s] for r, s in zip(d['daily']['sunrise'], d['daily']['sunset'])]
    return rows, sun


def main():
    a, b = replay_days()
    obs = metars(a, b)
    hrs, sun = hourly(a, b)
    out = {'station': 'EGLL London Heathrow', 'from': str(a), 'to': str(b),
           'sources': ['METAR via Iowa Environmental Mesonet', 'Open-Meteo historical archive'],
           'obs': obs, 'hourly': hrs, 'sun': sun}
    js = 'window.WEATHER = ' + json.dumps(out, separators=(',', ':')) + ';\n'
    open(os.path.join(ROOT, 'data', 'weather.js'), 'w').write(js)
    wet = sum(1 for o in obs if re.search(r'RA|DZ|SN|SH|TS', o['wx']))
    print(f'{len(obs)} METARs, {len(hrs)} hourly rows, {a}..{b}; {wet} reports with precipitation; '
          f'rain total {sum(r["mm"] or 0 for r in hrs):.1f} mm')


if __name__ == '__main__':
    sys.exit(main())
