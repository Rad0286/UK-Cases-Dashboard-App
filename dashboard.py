"""
GCS Completed Folder - PDF vs XML Character Count Dashboard
============================================================
Polls the FileBrowser every 5 minutes for new PDF/XML pairs,
computes character counts, and serves a live web dashboard.

Open http://localhost:8888 in your browser.
Press Ctrl+C to stop.
"""

import urllib.request
import json
import io
import re
import time
import threading
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

try:
    from pypdf import PdfReader
except ImportError:
    raise SystemExit("ERROR: pypdf not installed. Run: pip install pypdf")

# ─── Configuration ────────────────────────────────────────────────────────────
BASE_URL         = "http://foe-production.int.thomsonreuters.com:8095"
USERNAME         = "exela_user"
PASSWORD         = "exela_user"
FOLDER_PATH      = "/keying/GCS_completed/"
POLL_INTERVAL    = 300          # seconds between folder checks (5 min)
DASHBOARD_PORT   = 8888
DATA_FILE        = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
# ──────────────────────────────────────────────────────────────────────────────

state = {
    "results":      [],   # list of result dicts, newest first
    "seen_pairs":   set(),
    "last_checked": None,
    "next_check":   None,
    "status":       "Initializing...",
    "error":        None,
}
state_lock = threading.Lock()


# ─── FileBrowser helpers ──────────────────────────────────────────────────────

def get_token():
    payload = json.dumps({"username": USERNAME, "password": PASSWORD}).encode()
    req = urllib.request.Request(
        BASE_URL + "/api/login", data=payload,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode().strip()


def fetch_file(token, path):
    req = urllib.request.Request(
        BASE_URL + "/api/raw" + path + "?inline=true",
        headers={"X-Auth": token}
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def list_folder(token):
    req = urllib.request.Request(
        BASE_URL + "/api/resources" + FOLDER_PATH,
        headers={"X-Auth": token}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode()).get("items", [])


# ─── Character counting ───────────────────────────────────────────────────────

def pdf_charcount(data):
    reader = PdfReader(io.BytesIO(data))
    text = ""
    for page in reader.pages:
        t = page.extract_text()
        if t:
            text += t
    return len(text)


def xml_charcount(data):
    raw = data.decode("utf-8", errors="replace")
    text = re.sub(r"<[^>]+>", "", raw)
    text = (text.replace("&amp;", "&").replace("&lt;", "<")
                .replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'"))
    return len(text)


# ─── Persistence ─────────────────────────────────────────────────────────────

def load_data():
    if not os.path.exists(DATA_FILE):
        return
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        with state_lock:
            state["results"]    = saved.get("results", [])
            state["seen_pairs"] = set(saved.get("seen_pairs", []))
        print(f"  Loaded {len(state['results'])} previously processed file(s).")
    except Exception as e:
        print(f"  Warning: could not load data.json — {e}")


def save_data():
    with state_lock:
        payload = {
            "results":    state["results"],
            "seen_pairs": list(state["seen_pairs"]),
        }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


# ─── Polling thread ───────────────────────────────────────────────────────────

def poll_loop():
    while True:
        now = datetime.now()
        with state_lock:
            state["status"]       = "Checking folder..."
            state["error"]        = None
            state["last_checked"] = now.strftime("%Y-%m-%d %H:%M:%S")
            state["next_check"]   = None

        try:
            token = get_token()
            items = list_folder(token)

            pdfs = {i["name"][:-4] for i in items if i["name"].endswith(".pdf")}
            xmls = {i["name"][:-4] for i in items if i["name"].endswith(".xml")}
            pairs = pdfs & xmls

            with state_lock:
                seen = set(state["seen_pairs"])
            new_pairs = pairs - seen

            if new_pairs:
                with state_lock:
                    state["status"] = f"Processing {len(new_pairs)} new file(s)..."
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Found {len(new_pairs)} new pair(s): {sorted(new_pairs)}")

                for base in sorted(new_pairs):
                    print(f"  Processing {base} ...", end=" ", flush=True)
                    try:
                        pdf_data = fetch_file(token, FOLDER_PATH + base + ".pdf")
                        xml_data = fetch_file(token, FOLDER_PATH + base + ".xml")
                        pc = pdf_charcount(pdf_data)
                        xc = xml_charcount(xml_data)
                        diff = xc - pc
                        pct = round((xc / pc * 100), 1) if pc else 0
                        result = {
                            "file":      base,
                            "pdf_chars": pc,
                            "xml_chars": xc,
                            "diff":      diff,
                            "pct":       pct,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "error":     None,
                        }
                        print(f"PDF={pc:,}  XML={xc:,}  Match={pct}%")
                    except Exception as e:
                        result = {
                            "file":      base,
                            "pdf_chars": None,
                            "xml_chars": None,
                            "diff":      None,
                            "pct":       None,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "error":     str(e),
                        }
                        print(f"ERROR: {e}")

                    with state_lock:
                        state["results"].insert(0, result)
                        state["seen_pairs"].add(base)

                save_data()
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] No new pairs. {len(pairs)} pair(s) in folder.")

            next_dt = datetime.fromtimestamp(time.time() + POLL_INTERVAL)
            with state_lock:
                state["status"]     = f"Watching — {len(pairs)} pair(s) in folder"
                state["next_check"] = next_dt.strftime("%H:%M:%S")

        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Poll error: {e}")
            with state_lock:
                state["status"] = "Error during poll"
                state["error"]  = str(e)

        time.sleep(POLL_INTERVAL)


# ─── Dashboard HTML ───────────────────────────────────────────────────────────

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GCS Dashboard — PDF vs XML Char Count</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;background:#f0f2f5;color:#1a1a2e}

.header{
  background:linear-gradient(135deg,#1a1a2e 0%,#16213e 55%,#0f3460 100%);
  color:#fff;padding:22px 32px;
  display:flex;justify-content:space-between;align-items:center;
  box-shadow:0 2px 12px rgba(0,0,0,.3)
}
.header h1{font-size:20px;font-weight:600;letter-spacing:.4px}
.header .sub{font-size:11px;opacity:.65;margin-top:5px;font-family:Consolas,monospace}
.header .meta{text-align:right;font-size:12px;opacity:.85;line-height:1.9}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#4ade80;margin-right:5px;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}

.wrap{max-width:1280px;margin:24px auto;padding:0 20px}

.status-bar{
  background:#fff;border-radius:10px;padding:12px 18px;margin-bottom:18px;
  box-shadow:0 1px 5px rgba(0,0,0,.07);
  display:flex;align-items:center;gap:10px;font-size:13px
}
.sdot{width:9px;height:9px;border-radius:50%;background:#4ade80;flex-shrink:0;animation:pulse 2s infinite}
.sdot.warn{background:#facc15}.sdot.err{background:#f87171;animation:none}
.err-msg{color:#dc2626;margin-left:8px}

.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin-bottom:20px}
.card{background:#fff;border-radius:10px;padding:18px 20px;box-shadow:0 1px 5px rgba(0,0,0,.07)}
.card .lbl{font-size:11px;text-transform:uppercase;letter-spacing:.8px;color:#888;margin-bottom:7px}
.card .val{font-size:26px;font-weight:700;color:#0f3460}
.card .note{font-size:11px;color:#bbb;margin-top:4px}

.panel{background:#fff;border-radius:10px;box-shadow:0 1px 5px rgba(0,0,0,.07);overflow:hidden}
.panel-hdr{padding:14px 22px;border-bottom:1px solid #f0f0f0;display:flex;justify-content:space-between;align-items:center}
.panel-hdr h2{font-size:14px;font-weight:600}
.panel-hdr .legend{font-size:11px;color:#aaa}

table{width:100%;border-collapse:collapse}
thead th{
  padding:10px 18px;text-align:left;
  font-size:11px;text-transform:uppercase;letter-spacing:.7px;
  color:#888;background:#fafafa;border-bottom:1px solid #efefef
}
th.r{text-align:right}
tbody tr{border-bottom:1px solid #f7f7f7;transition:background .12s}
tbody tr:last-child{border-bottom:none}
tbody tr:hover{background:#f9fafb}
td{padding:13px 18px;font-size:13px}
td.r{text-align:right;font-variant-numeric:tabular-nums}
td.mono{font-family:Consolas,monospace;font-size:12px;color:#444}

.badge{
  display:inline-block;padding:3px 11px;border-radius:20px;
  font-size:11px;font-weight:700;min-width:55px;text-align:center
}
.green{background:#dcfce7;color:#16a34a}
.yellow{background:#fef9c3;color:#b45309}
.red{background:#fee2e2;color:#dc2626}
.gray{background:#f3f4f6;color:#6b7280}

.neg{color:#dc2626}.pos{color:#16a34a}
.err-row td{color:#dc2626;font-size:12px}

.empty{padding:60px;text-align:center;color:#ccc;font-size:14px}
footer{text-align:center;padding:18px;font-size:11px;color:#ccc}

.refresh-note{font-size:11px;color:#aaa;margin-top:2px}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>GCS &mdash; PDF vs XML Character Count</h1>
    <div class="sub">foe-production.int.thomsonreuters.com &nbsp;&rsaquo;&nbsp; keying/GCS_completed</div>
  </div>
  <div class="meta">
    <span class="dot"></span>Live &nbsp;|&nbsp; Polls every 5 min<br>
    Last checked: <strong>LAST_CHECKED</strong><br>
    Next check: <strong>NEXT_CHECK</strong><br>
    <span class="refresh-note">Page auto-refreshes every 30s</span>
  </div>
</div>

<div class="wrap">

  <div class="status-bar">
    <div class="sdot STATUS_CLS"></div>
    <span>STATUS_MSG</span>
    ERROR_HTML
  </div>

  <div class="cards">
    <div class="card">
      <div class="lbl">Files Processed</div>
      <div class="val">TOTAL_FILES</div>
      <div class="note">PDF + XML pairs</div>
    </div>
    <div class="card">
      <div class="lbl">Total PDF Chars</div>
      <div class="val">TOTAL_PDF</div>
      <div class="note">all files combined</div>
    </div>
    <div class="card">
      <div class="lbl">Total XML Chars</div>
      <div class="val">TOTAL_XML</div>
      <div class="note">tags excluded</div>
    </div>
    <div class="card">
      <div class="lbl">Overall Match</div>
      <div class="val">OVERALL_PCT%</div>
      <div class="note">XML / PDF ratio</div>
    </div>
  </div>

  <div class="panel">
    <div class="panel-hdr">
      <h2>File Results</h2>
      <div class="legend">&ge;97% <span class="badge green">green</span> &nbsp; 90&ndash;97% <span class="badge yellow">yellow</span> &nbsp; &lt;90% <span class="badge red">red</span></div>
    </div>
    <table>
      <thead>
        <tr>
          <th>File</th>
          <th class="r">PDF Chars</th>
          <th class="r">XML Chars</th>
          <th class="r">Difference</th>
          <th class="r">Match %</th>
          <th>Processed At</th>
        </tr>
      </thead>
      <tbody>
        ROWS
      </tbody>
    </table>
  </div>

</div>

<footer>GCS Dashboard &nbsp;&bull;&nbsp; Auto-refresh every 30 s &nbsp;&bull;&nbsp; Polls folder every 5 min</footer>

<script>
  // Auto-refresh the page every 30 seconds
  setTimeout(() => location.reload(), 30000);
</script>
</body>
</html>"""


def fmt(n):
    if n is None:
        return "&mdash;"
    return f"{n:,}"


def render():
    with state_lock:
        results      = list(state["results"])
        last_checked = state["last_checked"] or "&mdash;"
        next_check   = state["next_check"]   or "&mdash;"
        status       = state["status"]
        error        = state["error"]

    ok = [r for r in results if r.get("pdf_chars") is not None]
    total_pdf = sum(r["pdf_chars"] for r in ok)
    total_xml = sum(r["xml_chars"] for r in ok)
    overall   = round(total_xml / total_pdf * 100, 1) if total_pdf else 0

    # Build rows
    if not results:
        rows = '<tr><td colspan="6" class="empty">No files processed yet — waiting for PDF/XML pairs to appear in the folder.</td></tr>'
    else:
        rows = ""
        for r in results:
            if r.get("error"):
                rows += (
                    f'<tr class="err-row">'
                    f'<td class="mono">{r["file"]}</td>'
                    f'<td colspan="4">Error: {r["error"]}</td>'
                    f'<td>{r["timestamp"]}</td></tr>'
                )
            else:
                pct  = r["pct"]
                diff = r["diff"]
                bc   = "green" if pct >= 97 else ("yellow" if pct >= 90 else "red")
                dc   = "pos" if diff >= 0 else "neg"
                ds   = f'+{fmt(diff)}' if diff >= 0 else fmt(diff)
                rows += (
                    f'<tr>'
                    f'<td class="mono">{r["file"]}</td>'
                    f'<td class="r">{fmt(r["pdf_chars"])}</td>'
                    f'<td class="r">{fmt(r["xml_chars"])}</td>'
                    f'<td class="r {dc}">{ds}</td>'
                    f'<td class="r"><span class="badge {bc}">{pct}%</span></td>'
                    f'<td>{r["timestamp"]}</td>'
                    f'</tr>'
                )

    sc        = "err" if error else ("warn" if "Error" in status else "")
    error_html = f'<span class="err-msg">{error}</span>' if error else ""

    return (TEMPLATE
        .replace("LAST_CHECKED",  last_checked)
        .replace("NEXT_CHECK",    next_check)
        .replace("STATUS_CLS",    sc)
        .replace("STATUS_MSG",    status)
        .replace("ERROR_HTML",    error_html)
        .replace("TOTAL_FILES",   str(len(ok)))
        .replace("TOTAL_PDF",     fmt(total_pdf))
        .replace("TOTAL_XML",     fmt(total_xml))
        .replace("OVERALL_PCT",   str(overall))
        .replace("ROWS",          rows)
    )


# ─── HTTP server ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/data":
            with state_lock:
                body = json.dumps({
                    "results":      state["results"],
                    "last_checked": state["last_checked"],
                    "status":       state["status"],
                }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            body = render().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # keep console clean


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  GCS PDF vs XML Character Count Dashboard")
    print("=" * 60)
    print(f"  Folder : {BASE_URL}{FOLDER_PATH}")
    print(f"  Poll   : every {POLL_INTERVAL // 60} minutes")
    print(f"  Port   : http://localhost:{DASHBOARD_PORT}")
    print("=" * 60)

    load_data()

    poller = threading.Thread(target=poll_loop, daemon=True)
    poller.start()

    try:
        server = HTTPServer(("", DASHBOARD_PORT), Handler)
        print(f"\n  Open http://localhost:{DASHBOARD_PORT} in your browser\n")
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Dashboard stopped.")
