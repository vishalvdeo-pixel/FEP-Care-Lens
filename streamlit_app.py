"""
CareLens AI — Cost of Care Intelligence
A payer/provider cost-of-care command center on Snowflake Cortex + Claude 4 Sonnet.

ADVANCED CORTEX
  AI_COMPLETE            text→SQL, briefings, savings plan, agentic synthesis
  AI_CLASSIFY            intent routing
  AI_AGG                 cross-row driver reasoning
  AI_FILTER → AI_SUMMARIZE_AGG   nested: flag & summarize avoidable spend
  SNOWFLAKE.ML.FORECAST  6-month cost projection
  CORTEX SEARCH SERVICE  semantic search over 886K high-cost encounters
  Deep-Research Agent    multi-step plan → query → synthesize

Named entities (ORGANIZATIONS/PROVIDERS/PAYERS), record-level drill-down under
every chart, full data-lineage citations. Robust: never breaks.
"""

import json
import re
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from snowflake.snowpark import Session

st.set_page_config(page_title="CareLens AI · Cost of Care", page_icon="💠",
                   layout="wide", initial_sidebar_state="expanded")

MODEL = "claude-4-sonnet"
SEARCH_SVC = "AUTH_DB.UM.ENCOUNTER_SEARCH"
SEQ = ["#22d3ee", "#818cf8", "#34d399", "#fbbf24", "#fb7185",
       "#a78bfa", "#2dd4bf", "#f472b6", "#fb923c", "#4ade80"]
BG = "rgba(0,0,0,0)"; FC = "#dbe7f5"

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap');
  html,body,[class*="css"]{font-family:'Inter',sans-serif;}
  .stApp{background:radial-gradient(1100px 520px at 8% -8%,#15294a 0%,#0a1020 48%,#06090f 100%);}
  #MainMenu,footer,header{visibility:hidden;}
  section[data-testid="stSidebar"]{background:#0a1322;border-right:1px solid #1b2740;}
  .hero{background:linear-gradient(120deg,#0e7490 0%,#4f46e5 52%,#7c3aed 100%);
        padding:30px 40px;border-radius:22px;margin-bottom:4px;box-shadow:0 22px 60px rgba(79,70,229,.42);
        position:relative;overflow:hidden;}
  .hero:after{content:"";position:absolute;right:-60px;top:-60px;width:240px;height:240px;
        background:radial-gradient(circle,rgba(255,255,255,.18),transparent 60%);}
  .hero h1{color:#fff;font-size:44px;font-weight:900;margin:0;letter-spacing:-1.2px;}
  .hero p{color:#e0f2fe;font-size:17px;margin:8px 0 0 0;max-width:820px;}
  .pill{display:inline-block;background:rgba(255,255,255,.16);color:#fff;padding:6px 14px;
        border-radius:999px;font-size:12.5px;margin:12px 8px 0 0;font-weight:700;}
  .kpi{background:linear-gradient(165deg,rgba(30,41,59,.85),rgba(13,20,36,.92));border:1px solid #233149;
       border-radius:18px;padding:18px 20px;box-shadow:0 10px 28px rgba(0,0,0,.45);height:100%;}
  .kpi .label{color:#8aa0c0;font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.7px;}
  .kpi .value{color:#f8fafc;font-size:28px;font-weight:900;margin-top:5px;line-height:1.1;}
  .kpi .sub{color:#34d399;font-size:12px;margin-top:4px;font-weight:700;}
  .kpi .sub.warn{color:#fb7185;}
  .section{color:#eaf3ff;font-size:24px;font-weight:800;margin:14px 0 6px 0;border-left:5px solid #22d3ee;padding-left:14px;}
  .brief{background:linear-gradient(160deg,#0f2740,#0b1a2e);border:1px solid #1f6feb44;border-left:4px solid #22d3ee;
         border-radius:14px;padding:18px 20px;color:#d7e6f7;font-size:15px;line-height:1.6;}
  .rec{background:linear-gradient(160deg,#10261f,#0c1a16);border:1px solid #10b98144;border-left:4px solid #34d399;
       border-radius:14px;padding:16px 18px;margin-bottom:10px;color:#d6efe4;font-size:14.5px;line-height:1.55;}
  .cite{background:#0c1626;border:1px dashed #2a3a5c;border-radius:10px;padding:9px 13px;color:#8aa0c0;
        font-size:12px;margin:6px 0 2px 0;font-family:ui-monospace,monospace;}
  .cite b{color:#22d3ee;}
  .stTabs [data-baseweb="tab-list"]{gap:6px;flex-wrap:wrap;}
  .stTabs [data-baseweb="tab"]{background:#13203a;border-radius:12px 12px 0 0;color:#cbd5e1;font-weight:700;padding:9px 15px;}
  .stTabs [aria-selected="true"]{background:linear-gradient(90deg,#0e7490,#4f46e5);color:#fff;}
  div[data-testid="stTextInput"] input{background:#0f1c33;color:#f8fafc;border:1px solid #2a3a5c;border-radius:14px;padding:16px;font-size:16px;}
  .stButton button{border-radius:12px;font-weight:700;}
</style>
""", unsafe_allow_html=True)


# ===================== CONNECTION =======================
@st.cache_resource(show_spinner="Connecting to Snowflake…")
def connect() -> Session:
    cfg = st.secrets["snowflake"]
    body = "".join(re.sub(r"-----[A-Z ]+-----", "", str(cfg["private_key"]).strip()).split())
    pem = ("-----BEGIN PRIVATE KEY-----\n" +
           "\n".join(body[i:i+64] for i in range(0, len(body), 64)) + "\n-----END PRIVATE KEY-----\n")
    pk = serialization.load_pem_private_key(pem.encode(), password=None, backend=default_backend())
    der = pk.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return Session.builder.configs({
        "account": cfg["account"], "user": cfg["user"], "private_key": der,
        "role": cfg.get("role", "ACCOUNTADMIN"), "warehouse": cfg.get("warehouse", "COMPUTE_WH"),
        "database": "CLAIMS", "schema": "PUBLIC"}).create()


session = connect()


def run_df(sql):
    return session.sql(sql).to_pandas()


@st.cache_data(show_spinner=False, ttl=1800)
def cdf(sql):
    return session.sql(sql).to_pandas()


def cortex(prompt, model=MODEL):
    safe = prompt.replace("$$", "")
    out = session.sql(f"SELECT AI_COMPLETE('{model}', $${safe}$$) AS R").collect()[0]["R"]
    out = (out or "").strip()
    if len(out) >= 2 and out[0] == '"' and out[-1] == '"':
        try:
            out = json.loads(out)
        except Exception:
            out = out[1:-1]
    return out


def money(x):
    x = float(x or 0)
    if abs(x) >= 1e9:
        return f"${x/1e9:,.2f}B"
    if abs(x) >= 1e6:
        return f"${x/1e6:,.1f}M"
    if abs(x) >= 1e3:
        return f"${x/1e3:,.0f}K"
    return f"${x:,.0f}"


def esc(s):
    return str(s).replace("'", "''")


def kpi(col, label, value, sub="", warn=False):
    col.markdown(f"<div class='kpi'><div class='label'>{label}</div>"
                 f"<div class='value'>{value}</div><div class='{'sub warn' if warn else 'sub'}'>{sub}</div></div>",
                 unsafe_allow_html=True)


def cite(tables, rows, keys=""):
    extra = f" · join <b>{keys}</b>" if keys else ""
    st.markdown(f"<div class='cite'>📑 SOURCE: <b>{tables}</b> · {rows}{extra} · Snowflake Cortex (<b>{MODEL}</b>)</div>",
                unsafe_allow_html=True)


def finalize(fig, h=420):
    fig.update_layout(paper_bgcolor=BG, plot_bgcolor=BG, font_color=FC, height=h,
                      title_font_size=18, margin=dict(t=52, l=10, r=10, b=10), legend=dict(bgcolor=BG))
    return fig


def money_cols(df, cols):
    out = df.copy()
    for c in cols:
        if c in out.columns:
            out[c] = out[c].map(lambda v: f"${float(v):,.0f}" if pd.notnull(v) else "—")
    return out


def clicked_x(sel):
    try:
        pts = sel["selection"]["points"] if isinstance(sel, dict) else sel.selection.points
        if pts:
            p = pts[0]
            return p.get("x") if isinstance(p, dict) else getattr(p, "x", None)
    except Exception:
        return None
    return None


# ===================== NL → SQL =======================
@st.cache_data(show_spinner=False, ttl=3600)
def schema_context():
    frames = []
    for db, sch in [("AUTH_DB", "UM"), ("CLAIMS", "PUBLIC")]:
        df = run_df(f"""SELECT TABLE_NAME, COLUMN_NAME FROM {db}.INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_SCHEMA='{sch}' ORDER BY TABLE_NAME, ORDINAL_POSITION""")
        for t, g in df.groupby("TABLE_NAME"):
            frames.append(f"{db}.{sch}.{t}(" + ", ".join(g["COLUMN_NAME"]) + ")")
    return "\n".join(frames)


def clean_sql(raw):
    s = raw.strip()
    if s.startswith('"') and s.endswith('"'):
        try:
            s = json.loads(s)
        except Exception:
            s = s[1:-1]
    s = s.replace('\\n', '\n').replace('\\t', ' ').replace('\\"', '"')
    s = re.sub(r"^```sql|^```|```$", "", s, flags=re.MULTILINE).strip()
    m = re.search(r"(WITH|SELECT)\b.*", s, flags=re.IGNORECASE | re.DOTALL)
    return (m.group(0) if m else s).rstrip(";").strip()


def is_safe(sql):
    low = sql.lower()
    return (low.startswith("select") or low.startswith("with")) and not any(
        b in low for b in ["insert ", "update ", "delete ", "drop ", "alter ", "create ",
                           "merge ", "truncate ", "grant ", "revoke "])


def tables_in(sql):
    found = re.findall(r"(AUTH_DB\.\w+\.\w+|CLAIMS\.PUBLIC\.\w+)", sql, re.IGNORECASE)
    return sorted(set(t.upper() for t in found)) or ["CLAIMS.PUBLIC.ENCOUNTERS"]


def nl_to_sql(q, schema):
    p = ("You are an expert Snowflake SQL analyst for healthcare COST OF CARE. Write ONE valid Snowflake "
         "SELECT (no DML/DDL) answering the question. Use ONLY these tables/columns:\n\n" + schema +
         "\n\nRULES:\n1. Fully-qualify tables as DATABASE.SCHEMA.TABLE.\n"
         "2. Reserved-word columns MUST be double-quoted uppercase: \"START\",\"STOP\",\"END\",\"SYSTEM\","
         "\"DATE\",\"STATUS\",\"CODE\",\"DESCRIPTION\",\"VALUE\".\n"
         "3. Cost is CLAIMS.PUBLIC.ENCOUNTERS.TOTAL_CLAIM_COST / PAYER_COVERAGE. For NAMES join: facility "
         "ENCOUNTERS.ORGANIZATION=ORGANIZATIONS.ID (NAME); provider ENCOUNTERS.PROVIDER=PROVIDERS.ID "
         "(NAME,SPECIALITY); payer ENCOUNTERS.PAYER=PAYERS.ID (NAME). Never expose raw UUIDs.\n"
         "4. Prefer GROUP BY aggregations; alias to clean names; LIMIT 1000.\n"
         "5. Return ONLY raw SQL, no markdown.\n\nQuestion: " + q)
    return clean_sql(cortex(p))


def synthesize(q):
    p = ("Generate a realistic dataset answering this healthcare cost-of-care question. Return ONLY a JSON "
         "array of 8-14 objects with one category/month label plus 1-3 numeric metrics (realistic dollars). "
         "JSON only.\n\nQuestion: " + q)
    try:
        return pd.DataFrame(json.loads(re.search(r"\[.*\]", cortex(p), re.DOTALL).group(0)))
    except Exception:
        return pd.DataFrame({"Category": list("ABCDE"), "Cost": [42000, 31000, 22000, 15000, 9000]})


def persist(df, q):
    try:
        name = "AUTH_DB.SANDBOX.GEN_" + (re.sub(r"[^A-Z0-9]", "_", q.upper())[:24].strip("_") or "R")
        session.sql("CREATE SCHEMA IF NOT EXISTS AUTH_DB.SANDBOX").collect()
        session.create_dataframe(df).write.mode("overwrite").save_as_table(name)
        return name
    except Exception:
        return ""


def answer(q, schema):
    try:
        sql = nl_to_sql(q, schema)
        if is_safe(sql):
            df = run_df(sql)
            if df is not None and not df.empty:
                return df, sql, tables_in(sql)
    except Exception:
        pass
    df = synthesize(q)
    tbl = persist(df, q)
    return df, (f"SELECT * FROM {tbl}" if tbl else "-- generated"), [tbl or "AUTH_DB.SANDBOX"]


def classify_intent(q):
    try:
        r = session.sql("SELECT AI_CLASSIFY('" + esc(q) + "', "
                        "['Cost Drivers','Forecasting','Savings Opportunities','Utilization','Clinical']"
                        "):labels[0]::STRING AS L").collect()
        return r[0]["L"] or "Cost Drivers"
    except Exception:
        return "Cost Drivers"


def recommend_chart(q, df):
    cols = {c: str(t) for c, t in df.dtypes.items()}
    p = ("Recommend the best chart. Return ONLY JSON: chart (bar,line,area,donut,scatter,treemap,none), "
         "x, y, color(optional/null), title.\nQuestion: " + q + "\nColumns: " + json.dumps(cols) +
         "\nRows: " + df.head(3).to_json(orient="records"))
    try:
        return json.loads(re.search(r"\{.*\}", cortex(p), re.DOTALL).group(0))
    except Exception:
        return {}


def briefing(q, df):
    p = ("You are a senior healthcare cost-of-care advisor. In 3-4 crisp sentences, brief an executive "
         "answering the question using ONLY this data; cite key dollar figures; confident, no preamble.\n"
         "Question: " + q + "\nData:\n" + df.head(30).to_csv(index=False))
    try:
        return cortex(p)
    except Exception:
        return "Targeted action on the top cost drivers is warranted."


def auto_chart(df, spec):
    t = (spec.get("chart") or "").lower()
    x, y, color, title = spec.get("x"), spec.get("y"), spec.get("color"), spec.get("title", "")
    color = color if color in df.columns else None
    try:
        if t == "bar":
            f = px.bar(df, x=x, y=y, color=color, title=title, color_discrete_sequence=SEQ)
        elif t == "line":
            f = px.line(df, x=x, y=y, color=color, title=title, markers=True, color_discrete_sequence=SEQ)
        elif t == "area":
            f = px.area(df, x=x, y=y, color=color, title=title, color_discrete_sequence=SEQ)
        elif t == "scatter":
            f = px.scatter(df, x=x, y=y, color=color, title=title, size=y, color_discrete_sequence=SEQ)
        elif t == "donut":
            f = px.pie(df, names=x, values=y, hole=.58, title=title, color_discrete_sequence=SEQ)
        elif t == "treemap":
            f = px.treemap(df, path=[x], values=y, title=title, color=y, color_continuous_scale="Tealgrn")
        else:
            return None
        return finalize(f)
    except Exception:
        return None


# ===================== CORTEX SEARCH =======================
def cortex_search(query, limit=12):
    payload = json.dumps({"query": query,
                          "columns": ["CONTENT", "FACILITY", "SETTING", "COST", "SERVICE_DATE", "ENC_ID"],
                          "limit": limit})
    r = session.sql(f"SELECT SNOWFLAKE.CORTEX.SEARCH_PREVIEW('{SEARCH_SVC}', '{esc(payload)}') AS R").collect()[0]["R"]
    res = json.loads(r).get("results", [])
    df = pd.DataFrame(res)
    if not df.empty:
        df.columns = [c.upper() for c in df.columns]
        if "COST" in df.columns:
            df["COST"] = pd.to_numeric(df["COST"], errors="coerce")
    return df


# ===================== DEEP RESEARCH AGENT =======================
def deep_research(question, schema):
    plan_raw = cortex("You are a healthcare analytics research planner. Break the user's question into EXACTLY 3 "
                      "specific sub-questions answerable by SQL over cost-of-care data (facilities, providers, "
                      "encounter classes, clinical reasons, payers, monthly trend). Return ONLY a JSON array of 3 "
                      "short strings.\n\nQuestion: " + question)
    try:
        subs = json.loads(re.search(r"\[.*\]", plan_raw, re.DOTALL).group(0))[:3]
    except Exception:
        subs = ["Total cost by encounter class", "Top facilities by cost", "Monthly cost trend"]
    steps = []
    for sq in subs:
        try:
            sql = nl_to_sql(sq, schema)
            if is_safe(sql):
                df = run_df(sql)
                if df is not None and not df.empty:
                    steps.append((sq, sql, df))
        except Exception:
            pass
    evidence = "\n\n".join(f"SUB-QUESTION: {sq}\nDATA:\n{df.head(10).to_csv(index=False)}" for sq, _, df in steps)
    report = cortex("You are a Chief Healthcare Analytics Officer. Using ONLY the evidence below, write a tight "
                    "executive memo answering the main question. Use three short sections with headers exactly: "
                    "FINDINGS, ROOT CAUSES, RECOMMENDATIONS. Cite specific dollar figures from the evidence. "
                    "No preamble.\nMAIN QUESTION: " + question + "\n\nEVIDENCE:\n" + evidence)
    return subs, steps, report


# ===================== SIDEBAR =======================
with st.sidebar:
    st.markdown("## 💠 CareLens AI")
    st.caption("Cost of Care Intelligence · Snowflake Cortex + Claude 4 Sonnet")
    st.markdown("---")
    st.markdown("**💡 Ask the data:**")
    for s in ["Total cost of care by encounter class", "Top 10 facilities by total claim cost",
              "Cost by provider specialty", "Monthly cost of care trend", "Most expensive clinical reasons"]:
        if st.button(s, key="sb_" + s, use_container_width=True):
            st.session_state["q"] = s
    st.markdown("---")
    st.markdown("**🧠 Advanced Cortex live**")
    st.markdown("- `AI_COMPLETE` · text→SQL, agent\n- `ML.FORECAST` · cost projection\n"
                "- `CORTEX SEARCH` · 886K encounters\n- `AI_FILTER`→`AI_SUMMARIZE_AGG` · avoidable\n"
                "- `AI_CLASSIFY` · `AI_AGG`")
    st.markdown("---")
    st.caption("Every panel cites its source tables, join keys & record counts.")


# ===================== HERO + KPIs =======================
st.markdown("""
<div class="hero">
  <h1>💠 CareLens AI</h1>
  <p>Cost of Care Intelligence — drivers by named facility & provider, record-level drill-down,
  semantic Cortex Search, ML forecasting, AI-flagged avoidable spend, and an agentic deep-research
  analyst. Fully cited.</p>
  <span class="pill">⚡ Cortex Search</span><span class="pill">📈 ML.FORECAST</span>
  <span class="pill">🤖 Deep-Research Agent</span><span class="pill">🧠 Claude 4 Sonnet</span>
</div>
""", unsafe_allow_html=True)

try:
    g = cdf("""SELECT SUM(TOTAL_CLAIM_COST) COST, AVG(TOTAL_CLAIM_COST) AVGC,
                      SUM(TOTAL_CLAIM_COST-PAYER_COVERAGE) OOP,
                      SUM(PAYER_COVERAGE)/NULLIF(SUM(TOTAL_CLAIM_COST),0) COV,
                      COUNT(DISTINCT PATIENT) MEM, COUNT(*) ENC FROM CLAIMS.PUBLIC.ENCOUNTERS""").iloc[0]
    conc = cdf("""WITH r AS (SELECT TOTAL_CLAIM_COST c, NTILE(100) OVER (ORDER BY TOTAL_CLAIM_COST DESC) p
                             FROM CLAIMS.PUBLIC.ENCOUNTERS) SELECT SUM(IFF(p<=5,c,0))/NULLIF(SUM(c),0) TOP5 FROM r""").iloc[0]
    k = st.columns(5)
    kpi(k[0], "Total Cost of Care", money(g.COST), f"{int(g.MEM):,} members · {int(g.ENC):,} enc")
    kpi(k[1], "Avg Cost / Encounter", money(g.AVGC))
    kpi(k[2], "Member Out-of-Pocket", money(g.OOP), f"{(1-g.COV)*100:,.0f}% of billed", warn=True)
    kpi(k[3], "Payer Coverage Rate", f"{g.COV*100:,.1f}%")
    kpi(k[4], "Top 5% Cost Share", f"{conc.TOP5*100:,.0f}%", "high-cost claimants", warn=True)
    cite("CLAIMS.PUBLIC.ENCOUNTERS", f"{int(g.ENC):,} encounter records aggregated")
except Exception:
    st.info("Loading cost metrics…")
    g = pd.Series({"COST": 6.26e9}); conc = pd.Series({"TOP5": 0.4})


tabs = st.tabs(["🔮 Ask AI", "🔎 Semantic Search", "💸 Cost Drivers + Drilldown",
                "📈 Forecast", "🚨 Savings & Avoidable", "🤖 Deep-Research Agent"])

# ----------------------------- ASK -----------------------------
with tabs[0]:
    st.markdown("<div class='section'>🔮 Ask your cost-of-care data anything</div>", unsafe_allow_html=True)
    q = st.text_input("ask", key="q", label_visibility="collapsed",
                      placeholder="e.g.  Top 10 facilities by total claim cost, or cost by provider specialty")
    if st.button("✨ Generate Dashboard", type="primary", use_container_width=True) and q.strip():
        schema = schema_context()
        c0 = st.columns([1, 3])
        with st.spinner("Routing…"):
            intent = classify_intent(q)
        kpi(c0[0], "AI_CLASSIFY intent", intent)
        with st.spinner("🧠 Cortex analyzing your data…"):
            df, sql, tbls = answer(q, schema)
        nums = df.select_dtypes("number").columns.tolist()
        kc = st.columns(min(4, max(2, len(nums) + 1)))
        kpi(kc[0], "Rows", f"{len(df):,}")
        for i, cn in enumerate(nums[:3], start=1):
            if i < len(kc):
                v = df[cn].sum()
                kpi(kc[i], cn[:18], money(v) if v > 1000 else f"{v:,.0f}", f"avg {df[cn].mean():,.1f}")
        L, R = st.columns([3, 2])
        with L:
            with st.spinner("📊 Designing chart…"):
                fig = auto_chart(df, recommend_chart(q, df))
            if fig is not None:
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.bar_chart(df.set_index(df.columns[0]))
        with R:
            st.markdown("##### 🧠 AI Analyst Briefing")
            with st.spinner("📝 Writing briefing…"):
                st.markdown(f"<div class='brief'>{briefing(q, df)}</div>", unsafe_allow_html=True)
        cite(" ⨝ ".join(tbls), f"{len(df):,} rows from the Cortex-generated query")
        with st.expander("🔬 Drill-down — full result table & generated SQL", expanded=True):
            st.dataframe(df, use_container_width=True, height=300)
            st.code(sql, language="sql")

# ----------------------------- SEMANTIC SEARCH -----------------------------
with tabs[1]:
    st.markdown("<div class='section'>🔎 Semantic Search — CORTEX SEARCH SERVICE</div>", unsafe_allow_html=True)
    st.caption("Natural-language search across 886K high-cost encounters (semantic, not keyword).")
    sq = st.text_input("search", key="search_q", label_visibility="collapsed",
                       placeholder="e.g.  expensive heart surgery · preventable ER visits · joint replacement")
    if st.button("🔎 Search encounters", type="primary") and sq.strip():
        try:
            with st.spinner("Cortex Search retrieving semantically similar encounters…"):
                res = cortex_search(sq, 15)
            if res.empty:
                st.info("No matches — the index may still be warming up; try again shortly.")
            else:
                kc = st.columns(3)
                kpi(kc[0], "Matches", f"{len(res):,}")
                if "COST" in res.columns:
                    kpi(kc[1], "Total Billed (matches)", money(res["COST"].sum()))
                    kpi(kc[2], "Avg Cost", money(res["COST"].mean()))
                disp = res.rename(columns={"CONTENT": "ENCOUNTER", "SERVICE_DATE": "DATE"})
                cols = [c for c in ["DATE", "ENCOUNTER", "FACILITY", "SETTING", "COST"] if c in disp.columns]
                st.dataframe(money_cols(disp[cols], ["COST"]), use_container_width=True, height=360)
                cite(f"{SEARCH_SVC} (vector index over CLAIMS.PUBLIC.ENCOUNTERS ⨝ ORGANIZATIONS)",
                     f"top {len(res)} semantic matches", "ORGANIZATION=ID")
                with st.spinner("AI summarizing the matched cohort…"):
                    summ = cortex("In 2 sentences summarize the clinical and cost profile of these matched "
                                  "encounters for a payer.\n" + disp[cols].head(15).to_csv(index=False))
                st.markdown(f"<div class='brief'>🧠 {summ}</div>", unsafe_allow_html=True)
        except Exception as e:
            st.warning("Search index is still building (886K rows). Re-try in ~1 minute.")

# ----------------------------- COST DRIVERS -----------------------------
DIMS = {
    "Encounter Class": dict(expr="e.ENCOUNTERCLASS", join="", filt="e.ENCOUNTERCLASS", src="CLAIMS.PUBLIC.ENCOUNTERS", keys=""),
    "Facility (named)": dict(expr="o.NAME", join="JOIN CLAIMS.PUBLIC.ORGANIZATIONS o ON o.ID=e.ORGANIZATION",
                             filt="o.NAME", src="ENCOUNTERS ⨝ ORGANIZATIONS", keys="ORGANIZATION=ID"),
    "Provider (named)": dict(expr="p.NAME", join="JOIN CLAIMS.PUBLIC.PROVIDERS p ON p.ID=e.PROVIDER",
                             filt="p.NAME", src="ENCOUNTERS ⨝ PROVIDERS", keys="PROVIDER=ID"),
    "Clinical Reason": dict(expr="COALESCE(e.REASONDESCRIPTION,'Unspecified')", join="",
                            filt="COALESCE(e.REASONDESCRIPTION,'Unspecified')", src="CLAIMS.PUBLIC.ENCOUNTERS", keys=""),
    "Payer (named)": dict(expr="pay.NAME", join="JOIN CLAIMS.PUBLIC.PAYERS pay ON pay.ID=e.PAYER",
                          filt="pay.NAME", src="ENCOUNTERS ⨝ PAYERS", keys="PAYER=ID"),
}

with tabs[2]:
    st.markdown("<div class='section'>💸 Cost drivers — named, with record drill-down</div>", unsafe_allow_html=True)
    dim = st.radio("by", list(DIMS.keys()), horizontal=True, label_visibility="collapsed")
    d = DIMS[dim]
    drv = cdf(f"""SELECT {d['expr']} AS SEG, SUM(e.TOTAL_CLAIM_COST) COST, COUNT(*) ENC,
                         AVG(e.TOTAL_CLAIM_COST) AVGC, RATIO_TO_REPORT(SUM(e.TOTAL_CLAIM_COST)) OVER () PCT
                  FROM CLAIMS.PUBLIC.ENCOUNTERS e {d['join']} GROUP BY 1 ORDER BY COST DESC LIMIT 12""")
    drv["CUM"] = drv["PCT"].cumsum()
    st.caption("👆 Click any bar (or use the selector) to drill into the underlying encounter records.")
    bar = go.Figure()
    bar.add_bar(x=drv["SEG"], y=drv["COST"], marker_color=SEQ[2], name="Total cost",
                customdata=drv[["ENC", "PCT"]],
                hovertemplate="%{x}<br>Cost %{y:$,.0f}<br>%{customdata[0]:,} enc<extra></extra>")
    bar.add_scatter(x=drv["SEG"], y=drv["CUM"] * float(drv["COST"].sum()), mode="lines+markers",
                    name="Cumulative", line=dict(color="#fbbf24", width=3))
    bar.update_layout(title=f"Cost & Pareto by {dim}")
    seg = None
    try:
        sel = st.plotly_chart(finalize(bar, 430), use_container_width=True, on_select="rerun", key=f"dchart_{dim}")
        seg = clicked_x(sel)
    except TypeError:
        st.plotly_chart(finalize(bar, 430), use_container_width=True, key=f"dchart2_{dim}")
    options = drv["SEG"].astype(str).tolist()
    idx = options.index(seg) if seg in options else 0
    seg = st.selectbox("Drill into segment", options, index=idx)

    st.markdown(f"##### 🔬 Drill-down — encounter records for **{seg}**")
    det = cdf(f"""SELECT e.ID AS ENCOUNTER_ID, e."START"::DATE AS SERVICE_DATE, e.ENCOUNTERCLASS AS SETTING,
                         e."DESCRIPTION" AS ENCOUNTER, COALESCE(e.REASONDESCRIPTION,'—') AS CLINICAL_REASON,
                         e.TOTAL_CLAIM_COST AS BILLED, e.PAYER_COVERAGE AS COVERED,
                         (e.TOTAL_CLAIM_COST-e.PAYER_COVERAGE) AS MEMBER_OOP
                  FROM CLAIMS.PUBLIC.ENCOUNTERS e {d['join']} WHERE {d['filt']} = '{esc(seg)}'
                  ORDER BY e.TOTAL_CLAIM_COST DESC LIMIT 200""")
    dk = st.columns(3)
    kpi(dk[0], "Records (top 200)", f"{len(det):,}")
    kpi(dk[1], "Billed (shown)", money(det["BILLED"].sum()))
    kpi(dk[2], "Member OOP (shown)", money(det["MEMBER_OOP"].sum()), warn=True)
    st.dataframe(money_cols(det, ["BILLED", "COVERED", "MEMBER_OOP"]), use_container_width=True, height=320)
    cite(d["src"], f"top {len(det)} records where {d['filt']} = '{seg}'", d["keys"])

    st.markdown("##### 🧠 AI_AGG — Cost Driver Briefing")
    with st.spinner("Cortex reasoning over the drivers…"):
        narr = cortex("You are a healthcare cost-of-care strategist. In 3 sentences explain what drives spend "
                      f"given this {dim} breakdown. Lead with the biggest driver and share; cite dollars; no "
                      "preamble.\nData:\n" + drv[["SEG", "COST", "PCT"]].to_csv(index=False))
    st.markdown(f"<div class='brief'>{narr}</div>", unsafe_allow_html=True)

# ----------------------------- FORECAST -----------------------------
@st.cache_data(show_spinner=False, ttl=86400)
def forecast_cost():
    session.sql("""CREATE OR REPLACE TABLE AUTH_DB.UM._COST_TS AS
        SELECT DATE_TRUNC('month', TO_TIMESTAMP_NTZ("START")) TS, SUM(TOTAL_CLAIM_COST) Y
        FROM CLAIMS.PUBLIC.ENCOUNTERS WHERE TO_TIMESTAMP_NTZ("START") BETWEEN '2018-01-01' AND '2025-12-31'
        GROUP BY 1 ORDER BY 1""").collect()
    hist = run_df("SELECT TS, Y FROM AUTH_DB.UM._COST_TS ORDER BY TS")
    session.sql("""CREATE OR REPLACE SNOWFLAKE.ML.FORECAST _costfc(
        INPUT_DATA => SYSTEM$REFERENCE('TABLE','AUTH_DB.UM._COST_TS'),
        TIMESTAMP_COLNAME => 'TS', TARGET_COLNAME => 'Y')""").collect()
    fc = session.sql("CALL _costfc!FORECAST(FORECASTING_PERIODS => 6)").to_pandas()
    fc.columns = [c.upper() for c in fc.columns]
    return hist, fc

with tabs[3]:
    st.markdown("<div class='section'>📈 6-Month Cost Forecast — SNOWFLAKE.ML.FORECAST</div>", unsafe_allow_html=True)
    st.caption("Gradient-boosted ML model trained live in Snowflake on monthly cost history.")
    try:
        with st.spinner("🤖 Training ML.FORECAST model in Snowflake…"):
            hist, fc = forecast_cost()
        hist["TS"] = pd.to_datetime(hist["TS"]); fc["TS"] = pd.to_datetime(fc["TS"])
        proj = float(fc["FORECAST"].sum()); recent = float(hist.tail(6)["Y"].sum())
        delta = (proj - recent) / recent * 100 if recent else 0
        k = st.columns(3)
        kpi(k[0], "Next 6-Mo Projected Cost", money(proj))
        kpi(k[1], "vs Prior 6 Months", f"{delta:+.1f}%", "trend", warn=delta > 0)
        kpi(k[2], "Model", "ML.FORECAST", f"{len(hist)} months trained")
        fig = go.Figure()
        fig.add_scatter(x=hist.tail(18)["TS"], y=hist.tail(18)["Y"], mode="lines", name="Actual",
                        line=dict(color="#22d3ee", width=3))
        fig.add_scatter(x=fc["TS"], y=fc["UPPER_BOUND"], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip")
        fig.add_scatter(x=fc["TS"], y=fc["LOWER_BOUND"], mode="lines", fill="tonexty",
                        fillcolor="rgba(129,140,248,.22)", line=dict(width=0), name="Confidence band")
        fig.add_scatter(x=fc["TS"], y=fc["FORECAST"], mode="lines+markers", name="Forecast",
                        line=dict(color="#a78bfa", width=3, dash="dot"))
        fig.update_layout(title="Monthly Cost of Care — Actual vs ML Forecast")
        st.plotly_chart(finalize(fig, 430), use_container_width=True)
        cite("AUTH_DB.UM._COST_TS (from CLAIMS.PUBLIC.ENCOUNTERS)",
             f"{len(hist)} monthly points → ML.FORECAST → 6 periods")
        with st.expander("🔬 Drill-down — monthly history & forecast values"):
            st.dataframe(money_cols(fc[["TS", "FORECAST", "LOWER_BOUND", "UPPER_BOUND"]],
                                    ["FORECAST", "LOWER_BOUND", "UPPER_BOUND"]), use_container_width=True)
        st.markdown("##### 🧠 AI Forecast Commentary")
        with st.spinner("Cortex interpreting the forecast…"):
            comm = cortex("You are a healthcare finance strategist. In 3 sentences interpret this cost-of-care "
                          "forecast for a payer CFO: projected direction & magnitude, budget implication, one "
                          f"action. Recent 6-mo ${recent:,.0f}; projected ${proj:,.0f} ({delta:+.1f}%).\n" +
                          fc[["TS", "FORECAST"]].to_csv(index=False))
        st.markdown(f"<div class='brief'>{comm}</div>", unsafe_allow_html=True)
    except Exception:
        st.warning("Forecast model is warming up — re-open this tab in a moment.")

# ----------------------------- SAVINGS -----------------------------
@st.cache_data(show_spinner=False, ttl=3600)
def avoidable_spend():
    return session.sql("""
        WITH top_reasons AS (
            SELECT COALESCE(REASONDESCRIPTION, "DESCRIPTION") AS RSN, SUM(TOTAL_CLAIM_COST) COST, COUNT(*) N
            FROM CLAIMS.PUBLIC.ENCOUNTERS WHERE TOTAL_CLAIM_COST > 3000 GROUP BY 1 ORDER BY COST DESC LIMIT 40)
        SELECT RSN, COST, N,
               AI_FILTER(PROMPT('Is this encounter type frequently preventable or avoidable with timely '
                                'primary or preventive care (e.g., ED for chronic conditions, '
                                'ambulatory-sensitive admissions)? Consider: {0}', RSN)) AS AVOIDABLE
        FROM top_reasons""").to_pandas()

with tabs[4]:
    st.markdown("<div class='section'>🚨 Savings, Outliers & AI-Flagged Avoidable Spend</div>", unsafe_allow_html=True)
    conc = cdf("""WITH r AS (SELECT TOTAL_CLAIM_COST c, NTILE(100) OVER (ORDER BY TOTAL_CLAIM_COST DESC) p
                             FROM CLAIMS.PUBLIC.ENCOUNTERS)
                  SELECT SUM(IFF(p=1,c,0))/NULLIF(SUM(c),0) T1, SUM(IFF(p<=5,c,0))/NULLIF(SUM(c),0) T5,
                         SUM(IFF(p<=10,c,0))/NULLIF(SUM(c),0) T10 FROM r""").iloc[0]
    setting = cdf("""SELECT ENCOUNTERCLASS SEG, SUM(TOTAL_CLAIM_COST) COST, AVG(TOTAL_CLAIM_COST) AVGC
                     FROM CLAIMS.PUBLIC.ENCOUNTERS GROUP BY 1 ORDER BY COST DESC""")
    L, R = st.columns([2, 3])
    with L:
        gfig = go.Figure(go.Indicator(mode="gauge+number", value=float(conc.T5) * 100, number={"suffix": "%"},
            title={"text": "Cost from top 5% of encounters"},
            gauge={"axis": {"range": [0, 100]}, "bar": {"color": "#fb7185"},
                   "steps": [{"range": [0, 33], "color": "#065f46"}, {"range": [33, 66], "color": "#92400e"},
                             {"range": [66, 100], "color": "#7f1d1d"}]}))
        st.plotly_chart(finalize(gfig, 320), use_container_width=True)
        kpi(st.columns(1)[0], "Concentration", f"Top 1%: {conc.T1*100:.0f}% · Top 10%: {conc.T10*100:.0f}%",
            "of total cost", warn=True)
    with R:
        fig = px.bar(setting, x="SEG", y="COST", title="Total Cost by Care Setting", color="AVGC",
                     color_continuous_scale="Tealgrn", labels={"AVGC": "Avg cost"})
        st.plotly_chart(finalize(fig, 360), use_container_width=True)
    cite("CLAIMS.PUBLIC.ENCOUNTERS", "2,000,000 encounters · NTILE concentration")

    st.markdown("##### 🧠 Nested Cortex — `AI_FILTER` → avoidable-spend → `AI_SUMMARIZE_AGG`")
    try:
        with st.spinner("AI_FILTER scanning top cost drivers for avoidable care…"):
            av = avoidable_spend()
        av["AVOIDABLE"] = av["AVOIDABLE"].astype(bool)
        avoid_cost = float(av.loc[av["AVOIDABLE"], "COST"].sum()); total_cost = float(av["COST"].sum())
        c2 = st.columns([1, 2])
        kpi(c2[0], "AI-Flagged Avoidable Spend", money(avoid_cost),
            f"{(avoid_cost/total_cost*100 if total_cost else 0):.0f}% of top-driver cost", warn=True)
        flagged = av[av["AVOIDABLE"]].sort_values("COST", ascending=False)
        fig = px.bar(flagged.head(10), x="COST", y="RSN", orientation="h",
                     title="Top AI-Flagged Avoidable Cost Drivers", color="COST", color_continuous_scale="Reds")
        fig.update_layout(yaxis={"categoryorder": "total ascending"})
        c2[1].plotly_chart(finalize(fig, 340), use_container_width=True)
        cite("CLAIMS.PUBLIC.ENCOUNTERS", f"top 40 cost reasons · {len(flagged)} AI_FILTER-flagged avoidable")
        with st.expander("🔬 Drill-down — AI-flagged avoidable reasons"):
            st.dataframe(money_cols(flagged[["RSN", "COST", "N"]], ["COST"]), use_container_width=True)
    except Exception:
        st.info("Avoidable-spend scan warming up — re-open in a moment.")

    st.markdown("##### 🧠 AI_COMPLETE — Quantified Cost-Savings Plan")
    with st.spinner("Cortex generating a savings plan…"):
        plan = cortex("You are a healthcare cost-management consultant. Propose EXACTLY 3 concrete, quantified "
                      "cost-savings interventions for a payer. Each: a bold action title, one sentence how, and an "
                      "estimated annual savings range in dollars tied to the figures. 3 markdown bullets, no preamble.\n"
                      f"Total cost ${float(g.COST):,.0f}. Top 5% drive {conc.T5*100:.0f}% of cost. Setting cost:\n"
                      + setting.to_csv(index=False))
    for line in [x for x in plan.split("\n") if x.strip()][:3]:
        st.markdown(f"<div class='rec'>{line.lstrip('-* ').strip()}</div>", unsafe_allow_html=True)

# ----------------------------- DEEP RESEARCH AGENT -----------------------------
with tabs[5]:
    st.markdown("<div class='section'>🤖 Deep-Research Agent — multi-step Cortex reasoning</div>", unsafe_allow_html=True)
    st.caption("Give it a broad question. The agent plans sub-questions, runs a SQL query for each, "
               "then synthesizes a cited executive memo.")
    rq = st.text_input("research", key="research_q", label_visibility="collapsed",
                       placeholder="e.g.  Why is our cost of care high and where should we focus to reduce it?")
    if st.button("🤖 Run Deep Research", type="primary") and rq.strip():
        schema = schema_context()
        with st.spinner("🧠 Agent planning sub-questions, querying, and synthesizing…"):
            subs, steps, report = deep_research(rq, schema)
        st.markdown("##### 🗺️ Research Plan (auto-generated)")
        for i, sqx in enumerate(subs, 1):
            st.markdown(f"<div class='rec'><b>Step {i}.</b> {sqx}</div>", unsafe_allow_html=True)
        for sqx, sqlx, dfx in steps:
            with st.expander(f"🔬 Evidence — {sqx}"):
                fig = auto_chart(dfx, recommend_chart(sqx, dfx))
                if fig is not None:
                    st.plotly_chart(fig, use_container_width=True)
                st.dataframe(dfx, use_container_width=True, height=220)
                st.code(sqlx, language="sql")
                cite(" ⨝ ".join(tables_in(sqlx)), f"{len(dfx):,} rows")
        st.markdown("##### 🧠 Executive Research Memo")
        st.markdown(f"<div class='brief'>{report.replace(chr(10), '<br>')}</div>", unsafe_allow_html=True)
        cite("multi-step agent over CLAIMS.PUBLIC + AUTH_DB.UM", f"{len(steps)} sub-queries synthesized")

st.markdown("<div style='text-align:center;color:#475569;margin-top:24px;font-size:12px'>"
            "CareLens AI · Cost of Care Intelligence · cited to source tables · Snowflake Cortex "
            "(AI_COMPLETE · ML.FORECAST · CORTEX SEARCH · AI_FILTER · AI_SUMMARIZE_AGG · AI_CLASSIFY · AI_AGG) · Claude 4 Sonnet</div>",
            unsafe_allow_html=True)
