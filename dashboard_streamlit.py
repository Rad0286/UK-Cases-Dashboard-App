"""
GCS Dashboard — Streamlit Edition
==================================
Local:  streamlit run dashboard_streamlit.py
Team:   streamlit run dashboard_streamlit.py --server.address 0.0.0.0
Then open http://localhost:8501  (or http://<machine-ip>:8501 for the team)
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import urllib.request
import json
import io
import re
import os
import time
from pypdf import PdfReader
from datetime import datetime

# ── Page Config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="GCS · PDF vs XML",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Configuration ─────────────────────────────────────────────────────────────
BASE_URL    = "http://foe-production.int.thomsonreuters.com:8095"
USERNAME    = "exela_user"
PASSWORD    = "exela_user"
FOLDER_PATH = "/keying/GCS_completed/"
DATA_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
#MainMenu, footer, header { visibility: hidden; }

.gcs-header {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 55%, #0f3460 100%);
    padding: 22px 28px; border-radius: 14px; margin-bottom: 22px; color: white;
    display: flex; justify-content: space-between; align-items: center;
}
.gcs-header h1  { font-size: 21px; font-weight: 700; margin: 0; }
.gcs-header p   { font-size: 11px; opacity: 0.65; margin: 5px 0 0 0; font-family: monospace; }
.gcs-header .ts { font-size: 12px; opacity: 0.8; text-align: right; line-height: 1.8; }

[data-testid="stMetric"] {
    background: white; border-radius: 12px;
    padding: 18px 20px !important;
    box-shadow: 0 1px 5px rgba(0,0,0,0.08);
}
[data-testid="stMetricLabel"]  { font-size: 12px !important; }
[data-testid="stMetricValue"]  { font-size: 26px !important; font-weight: 700 !important; }

.status-ok  { color: #16a34a; font-weight: 600; }
.status-err { color: #dc2626; font-weight: 600; }

div[data-testid="stTabs"] button[role="tab"] { font-weight: 600; font-size: 14px; }

[data-testid="stSidebar"] { background: #f8f9fb; }
</style>
""", unsafe_allow_html=True)


# ── Core Helpers ──────────────────────────────────────────────────────────────

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


# ── Persistence ───────────────────────────────────────────────────────────────

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


# ── Folder Listing (cached 60 s) ──────────────────────────────────────────────

@st.cache_data(ttl=60, show_spinner=False)
def fetch_pairs():
    """Returns (set_of_pair_basenames, token). Refreshes every 60 s."""
    tok   = get_token()
    items = list_folder(tok)
    pdfs  = {i["name"][:-4] for i in items if i["name"].endswith(".pdf")}
    xmls  = {i["name"][:-4] for i in items if i["name"].endswith(".xml")}
    return pdfs & xmls, tok


# ── Process New Pairs ─────────────────────────────────────────────────────────

def process_new(new_pairs, token, results, seen_pairs):
    bar = st.progress(0, text="Processing new files…")
    for i, base in enumerate(sorted(new_pairs)):
        bar.progress((i + 1) / len(new_pairs), text=f"⏳ {base}")
        try:
            pc = pdf_charcount(fetch_file(token, FOLDER_PATH + base + ".pdf"))
            xc = xml_charcount(fetch_file(token, FOLDER_PATH + base + ".xml"))
            results.insert(0, {
                "file": base, "pdf_chars": pc, "xml_chars": xc,
                "diff": xc - pc,
                "pct":  round(xc / pc * 100, 2) if pc else 0,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "error": None,
            })
        except Exception as e:
            results.insert(0, {
                "file": base, "pdf_chars": None, "xml_chars": None,
                "diff": None, "pct": None,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "error": str(e),
            })
        seen_pairs.add(base)
    bar.empty()
    return results, seen_pairs


# ═══════════════════════════════════════════════════════════════════════════════
#  UI
# ═══════════════════════════════════════════════════════════════════════════════

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Controls")
    refresh_btn  = st.button("🔄 Refresh Now", use_container_width=True, type="primary")
    auto_refresh = st.toggle("Auto-refresh every 30 s", value=True)

    st.divider()
    st.markdown("## 🔍 Filters")
    min_pct = st.slider("Minimum Match %", 0, 100, 0, step=5)
    sort_by = st.selectbox("Sort by", ["Processed At (newest)", "Match % (lowest)", "PDF Chars (largest)", "File name"])

    st.divider()
    st.markdown("## 📡 Connection")
    conn_slot = st.empty()

    st.divider()
    st.caption(f"Folder: `{FOLDER_PATH}`")
    st.caption("Data saved to `data.json` — shared across restarts and team members if on a shared machine.")


# ── Load & Sync ───────────────────────────────────────────────────────────────
if refresh_btn:
    st.cache_data.clear()

results, seen_pairs = load_saved()
now_str  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
conn_ok  = False
n_folder = 0

try:
    with st.spinner("Checking folder for new files…"):
        all_pairs, token = fetch_pairs()

    n_folder  = len(all_pairs)
    new_pairs = all_pairs - seen_pairs
    conn_ok   = True

    if new_pairs:
        results, seen_pairs = process_new(new_pairs, token, results, seen_pairs)
        save_data(results, seen_pairs)
        st.cache_data.clear()
        st.toast(f"✅ {len(new_pairs)} new file(s) processed!", icon="✅")

    conn_slot.markdown(
        f'<span class="status-ok">● Connected</span><br>'
        f'<small>{n_folder} pair(s) in folder<br>Checked: {now_str}</small>',
        unsafe_allow_html=True,
    )

except Exception as e:
    conn_slot.markdown(
        f'<span class="status-err">● Unreachable</span><br><small>{e}</small>',
        unsafe_allow_html=True,
    )
    if not results:
        st.warning(f"Cannot reach FileBrowser and no local cache found. ({e})")


# ── Build DataFrame ───────────────────────────────────────────────────────────
ok_results  = [r for r in results if r.get("pdf_chars") is not None]
err_results = [r for r in results if r.get("error")]

df = pd.DataFrame(ok_results) if ok_results else pd.DataFrame(
    columns=["file","pdf_chars","xml_chars","diff","pct","timestamp"]
)

if not df.empty:
    df = df[df["pct"] >= min_pct].copy()
    if sort_by == "Match % (lowest)":
        df = df.sort_values("pct", ascending=True)
    elif sort_by == "PDF Chars (largest)":
        df = df.sort_values("pdf_chars", ascending=False)
    elif sort_by == "File name":
        df = df.sort_values("file")
    # default: newest first (already ordered from insert)


# ── Header ────────────────────────────────────────────────────────────────────
total_pdf = int(df["pdf_chars"].sum()) if not df.empty else 0
total_xml = int(df["xml_chars"].sum()) if not df.empty else 0
overall   = round(total_xml / total_pdf * 100, 1) if total_pdf else 0

st.markdown(f"""
<div class="gcs-header">
  <div>
    <h1>📄 GCS &mdash; PDF vs XML Character Count</h1>
    <p>foe-production.int.thomsonreuters.com &rsaquo; keying/GCS_completed</p>
  </div>
  <div class="ts">
    {'🟢 Live' if conn_ok else '🔴 Offline'} &nbsp;|&nbsp; {n_folder} pair(s) in folder<br>
    Last checked: <strong>{now_str}</strong><br>
    {'⏱ Auto-refreshing every 30 s' if auto_refresh else ''}
  </div>
</div>
""", unsafe_allow_html=True)


# ── Metric Cards ──────────────────────────────────────────────────────────────
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("📂 Files Processed",   f"{len(ok_results)}")
c2.metric("📄 Total PDF Chars",   f"{total_pdf:,}")
c3.metric("🗂️ Total XML Chars",   f"{total_xml:,}")
c4.metric("📊 Overall Match",     f"{overall}%",
          delta=f"{overall - 100:.1f}%",
          delta_color="normal" if overall >= 95 else "inverse")
c5.metric("⚠️ Errors",            f"{len(err_results)}")

st.divider()


# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_table, tab_charts, tab_errors = st.tabs(["📋  Table", "📊  Charts", "⚠️  Errors"])


# ────────────────────────────────────────────────────────────────────────────
# TABLE TAB
# ────────────────────────────────────────────────────────────────────────────
with tab_table:
    if df.empty:
        st.info("No files processed yet. Drop PDF/XML pairs into the folder and hit Refresh.")
    else:
        def fmt_badge(pct):
            if pct >= 97:   return f"🟢 {pct}%"
            elif pct >= 90: return f"🟡 {pct}%"
            else:           return f"🔴 {pct}%"

        display = df[["file","pdf_chars","xml_chars","diff","pct","timestamp"]].copy()
        display.columns = ["File", "PDF Chars", "XML Chars", "Difference", "Match %", "Processed At"]
        display["PDF Chars"]  = display["PDF Chars"].apply(lambda x: f"{x:,}")
        display["XML Chars"]  = display["XML Chars"].apply(lambda x: f"{x:,}")
        display["Difference"] = display["Difference"].apply(
            lambda x: f"+{x:,}" if x >= 0 else f"{x:,}"
        )
        display["Match %"] = display["Match %"].apply(fmt_badge)

        st.dataframe(display, use_container_width=True, hide_index=True, height=440)

        st.markdown("**Export:**")
        dl1, dl2, _ = st.columns([1, 1, 5])
        with dl1:
            csv = df.to_csv(index=False).encode("utf-8")
            st.download_button("⬇️ CSV", csv, "gcs_charcount.csv", "text/csv",
                               use_container_width=True)
        with dl2:
            buf = io.BytesIO()
            df.to_excel(buf, index=False, engine="openpyxl")
            st.download_button(
                "⬇️ Excel", buf.getvalue(), "gcs_charcount.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )


# ────────────────────────────────────────────────────────────────────────────
# CHARTS TAB
# ────────────────────────────────────────────────────────────────────────────
with tab_charts:
    if df.empty:
        st.info("No data to chart yet.")
    else:
        labels = df["file"].str[-24:]   # trim long names

        # Chart 1 — Grouped bar: PDF vs XML
        fig1 = go.Figure()
        fig1.add_trace(go.Bar(
            name="PDF Chars", x=labels, y=df["pdf_chars"],
            marker_color="#0f3460",
            text=df["pdf_chars"].apply(lambda x: f"{x:,}"),
            textposition="outside", textfont=dict(size=10),
        ))
        fig1.add_trace(go.Bar(
            name="XML Chars", x=labels, y=df["xml_chars"],
            marker_color="#4ade80",
            text=df["xml_chars"].apply(lambda x: f"{x:,}"),
            textposition="outside", textfont=dict(size=10),
        ))
        fig1.update_layout(
            title=dict(text="PDF vs XML Character Count per File", font=dict(size=15)),
            barmode="group", height=430,
            plot_bgcolor="white", paper_bgcolor="white",
            xaxis_title="File", yaxis_title="Character Count",
            xaxis_tickangle=-25,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(t=70, b=60, l=60, r=20),
        )
        st.plotly_chart(fig1, use_container_width=True)

        # Chart 2 — Match % bar with color coding
        colors = [
            "#16a34a" if p >= 97 else ("#ca8a04" if p >= 90 else "#dc2626")
            for p in df["pct"]
        ]
        fig2 = go.Figure(go.Bar(
            x=labels, y=df["pct"],
            marker_color=colors,
            text=df["pct"].apply(lambda p: f"{p}%"),
            textposition="outside", textfont=dict(size=10),
        ))
        fig2.add_hline(y=97, line_dash="dot", line_color="#16a34a",
                       annotation_text="97% (target)", annotation_position="bottom right")
        fig2.add_hline(y=90, line_dash="dot", line_color="#ca8a04",
                       annotation_text="90% (warning)", annotation_position="bottom right")
        fig2.update_layout(
            title=dict(text="XML / PDF Match % per File", font=dict(size=15)),
            height=400, plot_bgcolor="white", paper_bgcolor="white",
            xaxis_title="File", yaxis_title="Match %",
            yaxis_range=[0, 115],
            xaxis_tickangle=-25,
            margin=dict(t=70, b=60, l=60, r=20),
        )
        st.plotly_chart(fig2, use_container_width=True)

        # Chart 3 — Scatter: file size vs match %
        fig3 = go.Figure(go.Scatter(
            x=df["pdf_chars"], y=df["pct"],
            mode="markers+text",
            text=labels,
            textposition="top center",
            textfont=dict(size=9),
            marker=dict(
                size=12, color=df["pct"],
                colorscale=[[0,"#dc2626"],[0.5,"#ca8a04"],[1,"#16a34a"]],
                showscale=True,
                colorbar=dict(title="Match %"),
            ),
        ))
        fig3.update_layout(
            title=dict(text="Document Size vs Match %", font=dict(size=15)),
            height=400, plot_bgcolor="white", paper_bgcolor="white",
            xaxis_title="PDF Character Count", yaxis_title="Match %",
            margin=dict(t=70, b=60),
        )
        st.plotly_chart(fig3, use_container_width=True)


# ────────────────────────────────────────────────────────────────────────────
# ERRORS TAB
# ────────────────────────────────────────────────────────────────────────────
with tab_errors:
    if not err_results:
        st.success("✅ No errors — all files processed successfully.")
    else:
        for r in err_results:
            st.error(f"**{r['file']}** &nbsp;—&nbsp; {r['error']}  \n*Attempted: {r['timestamp']}*")
        if st.button("🗑️ Clear error records"):
            results = [r for r in results if not r.get("error")]
            seen_pairs -= {r["file"] for r in err_results}  # allow retry
            save_data(results, seen_pairs)
            st.cache_data.clear()
            st.rerun()


# ── Auto-refresh ──────────────────────────────────────────────────────────────
if auto_refresh:
    st.markdown(
        """<script>setTimeout(()=>window.location.reload(), 30000);</script>""",
        unsafe_allow_html=True,
    )
    st.caption("⏱️ Page auto-refreshes every 30 seconds")
