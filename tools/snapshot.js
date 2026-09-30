// Opens the replay page headless and records what it shows at the requested moments.
// Usage: node tools/snapshot.js <index.html> <requests.json> <out.json>
//   requests.json: [{ "t": <unix seconds>, "org": "all" | "Menzies" | "United" }, ...]
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

(async () => {
  const [page, reqFile, outFile] = process.argv.slice(2);
  const requests = JSON.parse(fs.readFileSync(reqFile, 'utf8'));
  const exe = process.env.CHROMIUM_PATH || (fs.existsSync('/opt/pw-browsers/chromium') ? '/opt/pw-browsers/chromium' : undefined);
  const browser = await chromium.launch(exe ? { executablePath: exe } : {});
  const p = await browser.newPage({ viewport: { width: 1400, height: 1000 } });
  const errors = [];
  p.on('pageerror', e => errors.push(e.message));
  await p.goto('file://' + path.resolve(page));
  await p.waitForFunction(() => window.apronDebug, null, { timeout: 15000 });
  const range = await p.evaluate(() => window.apronDebug.range());
  const snaps = [];
  for (const r of requests) snaps.push(await p.evaluate(({ t, org }) => window.apronDebug.snapshot(t, org), r));
  fs.writeFileSync(outFile, JSON.stringify({ range, snaps, errors }));
  await browser.close();
})().catch(e => { console.error(e); process.exit(2); });
