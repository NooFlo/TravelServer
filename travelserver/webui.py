import http.server
import os
import socket
import threading

import status

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TravelServer</title>
<style>
  :root { color-scheme: dark; }
  body { font-family: system-ui, -apple-system, sans-serif; background: #14161a; color: #e6e6e6;
         max-width: 720px; margin: 0 auto; padding: 1.2rem; }
  h1 { font-size: 1.4rem; margin: 0 0 0.2rem; }
  h1 small { color: #888; font-weight: normal; font-size: 0.9rem; }
  .state { font-size: 1.15rem; font-weight: 600; margin: 1rem 0; }
  .state.idle { color: #9aa4b2; } .state.backup { color: #5ac8fa; }
  .state.verify { color: #ffd60a; } .state.done { color: #30d158; } .state.error { color: #ff453a; }
  table { width: 100%; border-collapse: collapse; margin: 0.5rem 0 1.4rem; font-size: 0.95rem; }
  th, td { text-align: left; padding: 0.45rem 0.6rem; border-bottom: 1px solid #26292f; }
  th { color: #9aa4b2; font-weight: 500; width: 45%; }
  .bar { background: #26292f; border-radius: 6px; height: 10px; margin: 0.8rem 0 1.4rem; overflow: hidden; }
  .bar > div { height: 100%; background: #5ac8fa; width: 0%; transition: width .4s; }
  .bar.done > div { background: #30d158; } .bar.error > div { background: #ff453a; }
  .drive { padding: 0.55rem 0.7rem; border: 1px solid #26292f; border-radius: 8px; margin: 0.4rem 0; }
  .drive.present { border-color: #30d158; } .drive.missing { border-color: #ff453a; color: #ff453a; }
  pre { background: #1b1e23; padding: 0.9rem; border-radius: 8px; overflow-x: auto;
        font-size: 0.8rem; max-height: 260px; overflow-y: auto; }
  .muted { color: #9aa4b2; } a { color: #5ac8fa; }
  .footer { margin-top: 1.6rem; font-size: 0.85rem; color: #777; }
</style>
</head>
<body>
<h1>TravelServer <small id="host"></small></h1>
<div class="bar" id="bar"><div id="barfill"></div></div>
<div class="state" id="state"></div>
<table>
  <tr><th>Source</th><td id="source"></td></tr>
  <tr><th>Progress</th><td id="progress"></td></tr>
  <tr><th>Current file</th><td id="current"></td></tr>
  <tr><th>New files</th><td id="copied"></td></tr>
  <tr><th>Already backed up (skipped)</th><td id="skipped"></td></tr>
  <tr><th>Failed / unverified</th><td id="failed"></td></tr>
  <tr><th>Elapsed</th><td id="elapsed"></td></tr>
  <tr><th>LED</th><td id="led"></td></tr>
</table>
<h2>Storage</h2>
<div id="disks"></div>
<h2>Log</h2>
<pre id="log"></pre>
<div class="footer">Backup devices insert themselves (SD card / iPhone over USB).
Other installed webapps are not managed here. Page refreshes every 3 s.</div>
<script>
function fmts(s) { if (s == null) return "-"; const m = Math.floor(s/60); return m ? m + "m " + Math.round(s%60) + "s" : s.toFixed(1) + "s"; }
async function poll() {
  try {
    const r = await fetch('/api/status.json'); const j = await r.json();
    const st = document.getElementById('state');
    st.textContent = j.state_label; st.className = 'state ' + j.state;
    const pct = j.files_total ? Math.round(100 * j.files_done / j.files_total) : null;
    const bar = document.getElementById('bar'), fill = document.getElementById('barfill');
    fill.style.width = (pct == null ? (j.state === 'done' ? 100 : 0) : pct) + '%';
    bar.className = 'bar ' + (j.state === 'done' ? 'done' : (j.state === 'error' ? 'error' : ''));
    document.getElementById('source').textContent = j.source || "-";
    document.getElementById('progress').textContent = pct == null ? "-" : j.files_done + " / " + j.files_total + " (" + pct + "%)";
    document.getElementById('current').textContent = j.current_file || "-";
    document.getElementById('copied').textContent = j.files_copied;
    document.getElementById('skipped').textContent = j.files_skipped;
    document.getElementById('failed').textContent = j.files_failed + " / " + j.files_unverified;
    document.getElementById('elapsed').textContent = fmts(j.elapsed_seconds);
    document.getElementById('led').textContent = j.led_pattern || "-";
    const disks = document.getElementById('disks');
    disks.innerHTML = '';
    for (const d of j.disks) {
      const div = document.createElement('div');
      div.className = 'drive ' + (d.present ? 'present' : 'missing');
      if (!d.present) {
        div.textContent = d.label + ' - not found';
      } else {
        let text = d.label + ' - ' + (d.mountpoint || 'present, not mounted');
        if (d.size) { text += ' (' + d.size + ' total' + (d.free ? ', ' + d.free + ' free' : '') + ')'; }
        div.textContent = text;
      }
      disks.appendChild(div);
    }
    if (!j.disks.length) disks.innerHTML = '<div class="drive">No storage disks detected yet</div>';
    document.getElementById('log').textContent = j.log_tail.join("\\n");
    if (j.last_error) { const p = document.createElement('div'); p.className = 'drive missing'; p.textContent = 'Last error: ' + j.last_error; disks.appendChild(p); }
  } catch (e) {
    document.getElementById('state').textContent = 'Lost connection to daemon...';
  }
}
document.getElementById('host').textContent = 'http://' + location.host;
setInterval(poll, 3000); poll();
</script>
</body>
</html>
"""

WEBUI_APPS_HINT = "See the webapps section of the README for installing other web applications."


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._send(200, "text/html; charset=utf-8", PAGE.encode())
        elif self.path == "/api/status.json":
            self._send(200, "application/json", status.STATUS.json().encode())
        elif self.path == "/api/status":
            self._send(200, "application/json", status.STATUS.json().encode())
        elif self.path == "/apps":
            self._send(200, "text/plain; charset=utf-8", WEBUI_APPS_HINT.encode())
        else:
            self._send(404, "text/plain; charset=utf-8", b"not found")

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def start(cfg):
    server = http.server.ThreadingHTTPServer((cfg.webui_bind, cfg.webui_port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
