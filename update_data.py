"""
Local Updater — run this on your TR-network machine to pull new files,
compute character counts, update data.json, and push to GitHub so
the Streamlit Cloud dashboard stays current.

Usage: python update_data.py
  or double-click update_and_push.bat
"""

import urllib.request
import json
import io
import re
import os
import subprocess
from pypdf import PdfReader
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL    = "http://foe-production.int.thomsonreuters.com:8095"
USERNAME    = "exela_user"
PASSWORD    = "exela_user"
FOLDER_PATH = "/keying/GCS_completed/"
DATA_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
# ─────────────────────────────────────────────────────────────────────────────


def get_token():
    payload = json.dumps({"username": USERNAME, "password": PASSWORD}).encode()
    req = urllib.request.Request(
        BASE_URL + "/api/login", data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode().strip()


def fetch_file(token, path):
    req = urllib.request.Request(
        BASE_URL + "/api/raw" + path + "?inline=true",
        headers={"X-Auth": token},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def list_folder(token):
    req = urllib.request.Request(
        BASE_URL + "/api/resources" + FOLDER_PATH,
        headers={"X-Auth": token},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode()).get("items", [])


def pdf_charcount(data):
    reader = PdfReader(io.BytesIO(data))
    return len("".join(p.extract_text() or "" for p in reader.pages))


def xml_charcount(data):
    raw  = data.decode("utf-8", errors="replace")
    text = re.sub(r"<[^>]+>", "", raw)
    for esc, ch in [("&amp;","&"),("&lt;","<"),("&gt;",">"),("&quot;",'"'),("&apos;","'")]:
        text = text.replace(esc, ch)
    return len(text)


def load_saved():
    if not os.path.exists(DATA_FILE):
        return [], set()
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d.get("results", []), set(d.get("seen_pairs", []))
    except Exception:
        return [], set()


def save_data(results, seen_pairs):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"results": results, "seen_pairs": list(seen_pairs)}, f, indent=2)


def git_push(n_new):
    repo = os.path.dirname(os.path.abspath(__file__))
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M")
    msg  = f"data: add {n_new} new file(s) [{ts}]"
    cmds = [
        ["git", "add", "data.json"],
        ["git", "commit", "-m", msg],
        ["git", "push"],
    ]
    for cmd in cmds:
        result = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  git warning: {result.stderr.strip()}")
        else:
            print(f"  {' '.join(cmd[:2])} OK")


def main():
    print("=" * 55)
    print("  GCS Data Updater")
    print("=" * 55)

    print("\n[1/4] Authenticating with FileBrowser...")
    try:
        token = get_token()
        print("       OK")
    except Exception as e:
        print(f"       FAILED — {e}")
        print("\nMake sure you are on the TR network / ZScaler is connected.")
        return

    print("[2/4] Listing folder...")
    items = list_folder(token)
    pdfs  = {i["name"][:-4] for i in items if i["name"].endswith(".pdf")}
    xmls  = {i["name"][:-4] for i in items if i["name"].endswith(".xml")}
    pairs = pdfs & xmls
    print(f"       {len(pairs)} PDF/XML pair(s) found")

    results, seen_pairs = load_saved()
    new_pairs = pairs - seen_pairs

    if not new_pairs:
        print("\n       No new files — data.json is already up to date.")
        print("=" * 55)
        return

    print(f"[3/4] Processing {len(new_pairs)} new pair(s)...")
    for base in sorted(new_pairs):
        print(f"       {base} ... ", end="", flush=True)
        try:
            pc = pdf_charcount(fetch_file(token, FOLDER_PATH + base + ".pdf"))
            xc = xml_charcount(fetch_file(token, FOLDER_PATH + base + ".xml"))
            diff = xc - pc
            pct  = round(xc / pc * 100, 2) if pc else 0
            results.insert(0, {
                "file": base, "pdf_chars": pc, "xml_chars": xc,
                "diff": diff, "pct": pct,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "error": None,
            })
            print(f"PDF={pc:,}  XML={xc:,}  Match={pct}%")
        except Exception as e:
            results.insert(0, {
                "file": base, "pdf_chars": None, "xml_chars": None,
                "diff": None, "pct": None,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "error": str(e),
            })
            print(f"ERROR: {e}")
        seen_pairs.add(base)

    save_data(results, seen_pairs)
    print("\n       data.json saved.")

    print("[4/4] Pushing to GitHub...")
    git_push(len(new_pairs))

    print("\n  Done! Streamlit Cloud will pick up the new data on next refresh.")
    print("=" * 55)


if __name__ == "__main__":
    main()
