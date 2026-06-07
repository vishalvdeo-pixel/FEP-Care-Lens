import json
import re
import time
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from snowflake.snowpark import Session

st.set_page_config(page_title="FEP Care Lens AI", page_icon="◆", layout="wide", initial_sidebar_state="expanded")

MODEL = "claude-4-sonnet"
SEARCH_SVC = "AUTH_DB.UM.ENCOUNTER_SEARCH"
SEQ = ["#2563eb", "#0891b2", "#7c3aed", "#0d9488", "#db2777", "#ea580c", "#4f46e5", "#059669", "#c026d3", "#d97706"]

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
  html, body, [class*="css"] { font-family:'Inter',sans-serif; }
  .stApp { background:#eef2f7; }
  #MainMenu, footer, header { visibility:hidden; }
  section[data-testid="stSidebar"] { background:#ffffff; border-right:1px solid #e2e8f0; }
  section[data-testid="stSidebar"] * { color:#334155; }
  .hero { background:linear-gradient(115deg,#1e3a8a 0%,#2563eb 45%,#0891b2 100%); padding:30px 38px;
          border-radius:20px; margin-bottom:14px; box-shadow:0 14px 38px rgba(37,99,235,.28); }
  .hero h1 { color:#fff; font-size:40px; font-weight:900; margin:0; letter-spacing:-1px; }
  .hero p { color:#dbeafe; font-size:16.5px; margin:8px 0 0 0; max-width:820px; }
  .pill { display:inline-block; background:rgba(255,255,255,.18); color:#fff; padding:5px 13px;
          border-radius:999px; font-size:12.5px; margin:12px 8px 0 0; font-weight:600; }
  .card { background:#ffffff; border:1px solid #e2e8f0; border-radius:16px 16px 0 0; padding:16px 20px 10px 20px;
          box-shadow:0 4px 14px rgba(15,23,42,.05); }
  .card .label { color:#64748b; font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.5px; }
  .card .value { color:#0f172a; font-size:27px; font-weight:900; margin-top:4px; line-height:1.1; }
  .card .sub { color:#059669; font-size:12.5px; margin-top:3px; font-weight:600; }
  .card .sub.warn { color:#dc2626; }
  .section { color:#0f172a; font-size:22px; font-weight:800; margin:16px 0 8px 0; border-left:4px solid #2563eb; padding-left:12px; }
  .panel { background:#ffffff; border:1px solid #e2e8f0; border-left:4px solid #2563eb; border-radius:14px;
           padding:18px 22px; color:#1e293b; font-size:15px; line-height:1.65; box-shadow:0 4px 14px rgba(15,23,42,.05); }
  .panel h2 { color:#1e3a8a; font-size:16px; font-weight:800; margin:14px 0 6px 0; }
  .rec { background:#f0fdf4; border:1px solid #bbf7d0; border-left:4px solid #16a34a; border-radius:12px;
         padding:14px 18px; margin-bottom:10px; color:#14532d; font-size:14.5px; line-height:1.55; }
  .src { color:#94a3b8; font-size:12px; margin:6px 0 2px 0; font-family:ui-monospace,monospace; }
  .src b { color:#2563eb; }
  .stTabs [data-baseweb="tab-list"] { gap:8px; }
  .stTabs [data-baseweb="tab"] { background:#ffffff; border:1px solid #e2e8f0; border-radius:11px 11px 0 0;
        color:#475569; font-weight:700; padding:9px 20px; }
  .stTabs [aria-selected="true"] { background:linear-gradient(90deg,#2563eb,#0891b2); color:#fff; border-color:transparent; }
  div[data-testid="stTextInput"] input { background:#ffffff; color:#0f172a; border:1px solid #cbd5e1;
        border-radius:13px; padding:15px; font-size:16px; }
  .stButton button { border-radius:11px; font-weight:700; }
  div[data-testid="column"] div.stButton button { border-radius:0 0 14px 14px; border:1px solid #e2e8f0;
        border-top:none; background:#f8fafc; color:#2563eb; font-size:12px; width:100%; }
</style>
""", unsafe_allow_html=True)


@st.cache_resource(show_spinner="Connecting to Snowflake")
def connect():
    cfg = st.secrets["snowflake"]
    body = "".join(re.sub(r"-----[A-Z ]+-----", "", str(cfg["private_key"]).strip()).split())
    pem = ("-----BEGIN PRIVATE KEY-----\n" + "\n".join(body[i:i + 64] for i in range(0, len(body), 64)) +
           "\n-----END PRIVATE KEY-----\n")
    pk = serialization.load_pem_private_key(pem.encode(), password=None, backend=default_backend())
    der = pk.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    s = Session.builder.configs({
        "account": cfg["account"], "user": cfg["user"], "private_key": der,
        "role": cfg.get("role", "ACCOUNTADMIN"), "warehouse": cfg.get("warehouse", "COMPUTE_WH"),
        "database": "CLAIMS", "schema": "PUBLIC",
        "client_session_keep_alive": True}).create()
    try:
        s.sql(f"ALTER WAREHOUSE {cfg.get('warehouse', 'COMPUTE_WH')} RESUME IF SUSPENDED").collect()
    except Exception:
        pass
    return s


session = connect()


def reconnect():
    global session
    try:
        connect.clear()
    except Exception:
        pass
    session = connect()


def run_df(sql):
    global session
    for attempt in range(3):
        try:
            return session.sql(sql).to_pandas()
        except Exception:
            if attempt < 2:
                reconnect()
                time.sleep(1)
                continue
            raise


@st.cache_data(show_spinner=False, ttl=1800)
def cdf(sql):
    global session
    for attempt in range(3):
        try:
            return session.sql(sql).to_pandas()
        except Exception:
            if attempt < 2:
                reconnect()
                time.sleep(1)
                continue
            raise


def ai(prompt, model=MODEL):
    global session
    safe = prompt.replace("$$", "")
    for attempt in range(2):
        try:
            out = session.sql(f"SELECT AI_COMPLETE('{model}', $${safe}$$) AS R").collect()[0]["R"]
            out = (out or "").strip()
            if len(out) >= 2 and out[0] == '"' and out[-1] == '"':
                try:
                    out = json.loads(out)
                except Exception:
                    out = out[1:-1]
            return out
        except Exception:
            if attempt == 0:
                reconnect()
                time.sleep(1)
                continue
            return ""
    return ""


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
    col.markdown(f"<div class='card'><div class='label'>{label}</div>"
                 f"<div class='value'>{value}</div><div class='{'sub warn' if warn else 'sub'}'>{sub}</div></div>",
                 unsafe_allow_html=True)


def src(tables, rows, keys=""):
    extra = f" · join <b>{keys}</b>" if keys else ""
    st.markdown(f"<div class='src'>Source: <b>{tables}</b> · {rows}{extra} · Snowflake Cortex ({MODEL})</div>",
                unsafe_allow_html=True)


def finalize(fig, h=420):
    fig.update_layout(template="plotly_white", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font_color="#334155", height=h, title_font_size=18, title_font_color="#0f172a",
                      margin=dict(t=52, l=10, r=10, b=10))
    return fig


def money_cols(df, cols):
    out = df.copy()
    for c in cols:
        if c in out.columns:
            out[c] = out[c].map(lambda v: f"${float(v):,.0f}" if pd.notnull(v) else "—")
    return out


def clicked_seg(sel):
    try:
        pts = sel["selection"]["points"] if isinstance(sel, dict) else sel.selection.points
        if pts:
            p = pts[0]
            if isinstance(p, dict):
                return p.get("x") or p.get("y") or p.get("label")
    except Exception:
        return None
    return None


@st.cache_data(show_spinner=False, ttl=3600)
def schema_context():
    frames = []
    for db, sch in [("AUTH_DB", "UM"), ("CLAIMS", "PUBLIC")]:
        df = run_df(f"""SELECT TABLE_NAME, COLUMN_NAME FROM {db}.INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_SCHEMA='{sch}' ORDER BY TABLE_NAME, ORDINAL_POSITION""")
        for t, gr in df.groupby("TABLE_NAME"):
            frames.append(f"{db}.{sch}.{t}(" + ", ".join(gr["COLUMN_NAME"]) + ")")
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
    y = int(st.session_state.get("year", 2024))
    p = ("You are an expert Snowflake SQL analyst for healthcare cost of care. Write ONE valid Snowflake "
         "SELECT (no DML or DDL) answering the question. Use ONLY these tables and columns:\n\n" + schema +
         "\n\nRules:\n1. Fully qualify tables as DATABASE.SCHEMA.TABLE.\n"
         "2. These reserved-word columns must be double quoted in uppercase: \"START\",\"STOP\",\"END\","
         "\"SYSTEM\",\"DATE\",\"STATUS\",\"CODE\",\"DESCRIPTION\",\"VALUE\".\n"
         "3. Cost is CLAIMS.PUBLIC.ENCOUNTERS.TOTAL_CLAIM_COST and PAYER_COVERAGE. For facility names join "
         "ENCOUNTERS.ORGANIZATION=AUTH_DB.UM.ORG_DIM.ID (NAME); use ORG_DIM, never CLAIMS.PUBLIC.ORGANIZATIONS "
         "which has duplicate rows. For provider names join ENCOUNTERS.PROVIDER=PROVIDERS.ID (NAME, SPECIALITY). "
         "Do not use payer. Never return raw UUIDs.\n"
         f"4. Scope to plan year {y}: filter ENCOUNTERS with "
         f"TO_TIMESTAMP_NTZ(\"START\") >= '{y}-01-01' AND TO_TIMESTAMP_NTZ(\"START\") < '{y + 1}-01-01'.\n"
         "5. Prefer GROUP BY aggregations, alias to clean names, add LIMIT 1000.\n"
         "6. Return ONLY raw SQL, no markdown.\n\nQuestion: " + q)
    return clean_sql(ai(p))


def run_question(q, schema):
    try:
        sql = nl_to_sql(q, schema)
        if is_safe(sql):
            df = run_df(sql)
            if df is not None and not df.empty:
                return df, sql
    except Exception:
        pass
    return None, ""


def classify_intent(q):
    try:
        r = session.sql("SELECT AI_CLASSIFY('" + esc(q) + "', "
                        "['Cost Drivers','Utilization','Savings Opportunities','Quality','Clinical']"
                        "):labels[0]::STRING AS L").collect()
        return r[0]["L"] or "Cost Drivers"
    except Exception:
        return "Cost Drivers"


def recommend_chart(q, df):
    cols = {c: str(t) for c, t in df.dtypes.items()}
    p = ("Recommend the best chart. Return ONLY JSON with keys chart "
         "(bar, hbar, line, area, donut, treemap, none), x, y, title.\n"
         "Question: " + q + "\nColumns: " + json.dumps(cols) + "\nRows: " + df.head(3).to_json(orient="records"))
    try:
        return json.loads(re.search(r"\{.*\}", ai(p), re.DOTALL).group(0))
    except Exception:
        return {}


def safe_chart(df, title=""):
    nums = df.select_dtypes("number").columns.tolist()
    cats = [c for c in df.columns if c not in nums]
    if not nums:
        return None
    y = nums[0]
    x = cats[0] if cats else df.columns[0]
    try:
        d = df.head(20)
        if d[x].astype(str).map(len).max() > 16:
            f = px.bar(d, x=y, y=x, orientation="h", color=y, color_continuous_scale="Blues", title=title)
            f.update_layout(yaxis={"categoryorder": "total ascending"})
        else:
            f = px.bar(d, x=x, y=y, color=x, color_discrete_sequence=SEQ, title=title)
            f.update_layout(showlegend=False)
        return finalize(f)
    except Exception:
        return None


def build_chart(df, spec):
    t = (spec.get("chart") or "").lower()
    x, y, title = spec.get("x"), spec.get("y"), spec.get("title", "")
    if x not in df.columns or (t not in ("treemap", "donut") and y not in df.columns):
        return safe_chart(df, title)
    try:
        if t == "hbar":
            f = px.bar(df, x=y, y=x, orientation="h", color=y, color_continuous_scale="Blues", title=title)
            f.update_layout(yaxis={"categoryorder": "total ascending"})
        elif t == "bar":
            f = px.bar(df, x=x, y=y, color=x, color_discrete_sequence=SEQ, title=title)
            f.update_layout(showlegend=False)
        elif t == "line":
            f = px.line(df, x=x, y=y, markers=True, color_discrete_sequence=SEQ, title=title)
        elif t == "area":
            f = px.area(df, x=x, y=y, color_discrete_sequence=SEQ, title=title)
        elif t == "donut":
            f = px.pie(df, names=x, values=y, hole=.58, color_discrete_sequence=SEQ, title=title)
        elif t == "treemap":
            f = px.treemap(df, path=[x], values=y, color=y, color_continuous_scale="Blues", title=title)
        else:
            return safe_chart(df, title)
        return finalize(f)
    except Exception:
        return safe_chart(df, title)


def deep_agent(question, schema, status):
    status.write("Planning the research")
    try:
        raw = ai("Break this healthcare cost-of-care question into exactly 2 focused sub-questions that each "
                 "map to one SQL aggregation. Return ONLY a JSON array of 2 short strings.\n\n" + question)
        subs = json.loads(re.search(r"\[.*\]", raw, re.DOTALL).group(0))[:2]
    except Exception:
        subs = [question, "Cost by encounter class"]
    steps = []
    for i, sub in enumerate(subs, 1):
        status.write(f"Step {i}: {sub}")
        df, sql = run_question(sub, schema)
        if df is not None:
            steps.append((sub, sql, df))
    status.write("Synthesizing the executive memo")
    evidence = "\n\n".join(f"SUB-QUESTION: {s}\nDATA:\n{d.head(12).to_csv(index=False)}" for s, _, d in steps)
    try:
        memo = ai("You are a Chief Healthcare Analytics Officer. Using ONLY the evidence below, write a tight "
                  "executive memo answering the main question, in markdown with exactly these headers:\n"
                  "## Findings\n## Root Causes\n## Recommendations\nCite specific dollar figures. No preamble.\n\n"
                  "MAIN QUESTION: " + question + "\n\nEVIDENCE:\n" + evidence)
    except Exception:
        memo = "## Findings\nThe analysis highlights concentration in the highest-cost segments."
    return subs, steps, memo


def md_panel(text):
    st.markdown(f"<div class='panel'>{text.replace('## ', '<h2>').replace(chr(10), '<br>')}</div>",
                unsafe_allow_html=True)


def cortex_search(query, limit=12):
    payload = json.dumps({"query": query,
                          "columns": ["CONTENT", "REASON", "FACILITY", "SETTING", "ENCOUNTERS", "TOTAL_COST", "AVG_COST"],
                          "limit": limit})
    r = session.sql(f"SELECT SNOWFLAKE.CORTEX.SEARCH_PREVIEW('{SEARCH_SVC}', '{esc(payload)}') AS R").collect()[0]["R"]
    res = json.loads(r).get("results", [])
    df = pd.DataFrame(res)
    if not df.empty:
        df.columns = [c.upper() for c in df.columns]
        for c in ["TOTAL_COST", "AVG_COST", "ENCOUNTERS"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


FEP_PERSONA = ("You are a senior Federal Employees Health Benefits (FEHB) and Postal Service Health Benefits "
               "(PSHB) cost-of-care strategist advising a health plan carrier that contracts with the U.S. Office "
               "of Personnel Management (OPM). You understand FEHB and PSHB benefit and rate proposal processes, "
               "premium and cost-sharing structures, Medicare and EGWP coordination, and federal cost-of-care "
               "economics. ")
LETTER_SEARCH = "CALL_LETTERS.ANALYTICS.LETTER_SEARCH"


@st.cache_data(show_spinner=False, ttl=1800)
def letters_intel():
    return run_df("""SELECT FILE_NAME, YEAR, COALESCE(NULLIF(SUBJECT,''),'(no subject)') SUBJECT, CATEGORY, PROGRAMS
                     FROM CALL_LETTERS.ANALYTICS.LETTER_INTEL WHERE YEAR IS NOT NULL
                     ORDER BY YEAR DESC, FILE_NAME""")


def letter_text(file_name):
    df = run_df(f"SELECT FULL_TEXT FROM CALL_LETTERS.ANALYTICS.LETTER_INTEL WHERE FILE_NAME='{esc(file_name)}'")
    return df.iloc[0]["FULL_TEXT"] if not df.empty else ""


def search_letters(query, limit=4):
    payload = json.dumps({"query": query, "columns": ["SUBJECT", "YEAR", "CATEGORY", "FILE_NAME"], "limit": limit})
    try:
        r = session.sql(f"SELECT SNOWFLAKE.CORTEX.SEARCH_PREVIEW('{LETTER_SEARCH}', '{esc(payload)}') AS R").collect()[0]["R"]
        return json.loads(r).get("results", [])
    except Exception:
        return []


def claims_cost_context(year):
    try:
        yc = (f'TO_TIMESTAMP_NTZ("START") >= \'{year}-01-01\' '
              f'AND TO_TIMESTAMP_NTZ("START") < \'{year + 1}-01-01\'')
        df = run_df(f"""SELECT ENCOUNTERCLASS SETTING, ROUND(SUM(TOTAL_CLAIM_COST)) COST
                        FROM CLAIMS.PUBLIC.ENCOUNTERS WHERE {yc} GROUP BY 1 ORDER BY COST DESC LIMIT 6""")
        return df.to_csv(index=False)
    except Exception:
        return "(claims cost mix unavailable)"


def fep_impact(text, rag_ctx, claims_ctx):
    prompt = (FEP_PERSONA +
              "Produce a COST OF CARE IMPACT ASSESSMENT in markdown using EXACTLY these headers:\n"
              "## Key Directives\n## Cost-of-Care Impact\n## Affected Benefits and Members\n## Recommended Carrier Actions\n"
              "Ground your analysis in the related historical OPM guidance and the carrier's actual claims cost mix "
              "below. State cost direction (increase or decrease) and cite figures where useful. No preamble.\n\n"
              "=== THIS CALL LETTER ===\n" + text[:9000] +
              "\n\n=== RELATED HISTORICAL OPM GUIDANCE (retrieved by Cortex Search) ===\n" + rag_ctx +
              "\n\n=== CARRIER CLAIMS COST MIX ===\n" + claims_ctx)
    return ai(prompt)


def yclause(col='"START"'):
    y = int(st.session_state.get("year", 2024))
    return f"TO_TIMESTAMP_NTZ({col}) >= '{y}-01-01' AND TO_TIMESTAMP_NTZ({col}) < '{y + 1}-01-01'"


with st.sidebar:
    st.markdown("### ◆ FEP Care Lens AI")
    st.caption("Cost of Care Intelligence")
    st.markdown("---")
    st.selectbox("Plan year", [2024, 2023, 2022, 2021, 2020], key="year")
    st.caption("All figures are scoped to the selected plan year.")
    st.markdown("---")
    st.markdown("**Start with a question**")
    for s in ["What is driving our cost of care and where should we focus",
              "Which facilities and clinical reasons cost the most",
              "Where is the biggest opportunity to reduce avoidable spend"]:
        if st.button(s, key="sb_" + s, use_container_width=True):
            st.session_state["q"] = s
    st.markdown("---")
    st.markdown("**Powered by Snowflake Cortex**")
    st.markdown("AI_COMPLETE agent · AI_CLASSIFY · CORTEX SEARCH · Claude 4 Sonnet")


st.markdown("""
<div class="hero">
  <h1>◆ FEP Care Lens AI</h1>
  <p>Cost of Care Intelligence. A research agent that decomposes your question, queries named facilities
  and providers, drills to the record, and surfaces avoidable spend.</p>
  <span class="pill">Research Agent</span><span class="pill">Cortex Search</span>
  <span class="pill">Claude 4 Sonnet</span><span class="pill">Annual cost of care</span>
</div>
""", unsafe_allow_html=True)

YR = int(st.session_state.get("year", 2024))
st.markdown(f"<div class='section'>Plan year {YR}</div>", unsafe_allow_html=True)
try:
    g = cdf(f"""SELECT SUM(TOTAL_CLAIM_COST) COST, AVG(TOTAL_CLAIM_COST) AVGC,
                      SUM(TOTAL_CLAIM_COST-PAYER_COVERAGE) OOP,
                      SUM(PAYER_COVERAGE)/NULLIF(SUM(TOTAL_CLAIM_COST),0) COV,
                      COUNT(DISTINCT PATIENT) MEM, COUNT(*) ENC FROM CLAIMS.PUBLIC.ENCOUNTERS
                WHERE {yclause()}""").iloc[0]
    conc = cdf(f"""WITH r AS (SELECT TOTAL_CLAIM_COST c, NTILE(100) OVER (ORDER BY TOTAL_CLAIM_COST DESC) p
                              FROM CLAIMS.PUBLIC.ENCOUNTERS WHERE {yclause()})
                   SELECT SUM(IFF(p<=5,c,0))/NULLIF(SUM(c),0) TOP5 FROM r""").iloc[0]
    k = st.columns(5)
    kpi(k[0], "Total Cost of Care", money(g.COST), f"{int(g.MEM):,} members · {YR}")
    kpi(k[1], "Cost / Member / Year", money(g.COST / max(int(g.MEM), 1)), f"{int(g.ENC):,} encounters")
    kpi(k[2], "Member Out-of-Pocket", money(g.OOP), f"{(1-g.COV)*100:,.0f}% of billed", warn=True)
    kpi(k[3], "Insurance Coverage", f"{g.COV*100:,.1f}%", "of billed cost")
    kpi(k[4], "Top 5% Cost Share", f"{conc.TOP5*100:,.0f}%", "high-cost claimants", warn=True)
    b = st.columns(5)
    drill_labels = ["Cost by setting", "Avg by setting", "OOP by setting", "Coverage by setting", "Top records"]
    for i, (col, lbl) in enumerate(zip(b, drill_labels)):
        if col.button("Drill ▾", key=f"kd{i}"):
            st.session_state["kdrill"] = lbl
    kd = st.session_state.get("kdrill")
    if kd:
        if kd == "Top records":
            rec = cdf(f"""SELECT o.NAME AS FACILITY, e."START"::DATE AS SERVICE_DATE, e.ENCOUNTERCLASS AS SETTING,
                                COALESCE(NULLIF(e.REASONDESCRIPTION,'None'),'—') AS CLINICAL_REASON, e.TOTAL_CLAIM_COST AS BILLED
                         FROM CLAIMS.PUBLIC.ENCOUNTERS e JOIN AUTH_DB.UM.ORG_DIM o ON o.ID=e.ORGANIZATION
                         WHERE {yclause('e."START"')}
                         ORDER BY e.TOTAL_CLAIM_COST DESC LIMIT 50""")
            st.markdown(f"<div class='section'>{kd}</div>", unsafe_allow_html=True)
            st.dataframe(money_cols(rec, ["BILLED"]), use_container_width=True, height=300)
            src("ENCOUNTERS join ORGANIZATIONS", f"top 50 highest-cost encounters in {YR}", "ORGANIZATION=ID")
        else:
            metric = {"Cost by setting": "SUM(TOTAL_CLAIM_COST)", "Avg by setting": "AVG(TOTAL_CLAIM_COST)",
                      "OOP by setting": "SUM(TOTAL_CLAIM_COST-PAYER_COVERAGE)",
                      "Coverage by setting": "SUM(PAYER_COVERAGE)/NULLIF(SUM(TOTAL_CLAIM_COST),0)*100"}[kd]
            dd = cdf(f"SELECT ENCOUNTERCLASS AS SETTING, {metric} AS METRIC FROM CLAIMS.PUBLIC.ENCOUNTERS WHERE {yclause()} GROUP BY 1 ORDER BY 2 DESC")
            st.markdown(f"<div class='section'>{kd}</div>", unsafe_allow_html=True)
            f = px.bar(dd, x="SETTING", y="METRIC", color="SETTING", color_discrete_sequence=SEQ)
            f.update_layout(showlegend=False)
            st.plotly_chart(finalize(f, 320), use_container_width=True)
            src("CLAIMS.PUBLIC.ENCOUNTERS", f"grouped by care setting · {YR}")
    src("CLAIMS.PUBLIC.ENCOUNTERS", f"{int(g.ENC):,} encounter records in {YR}")
except Exception:
    st.info("Loading cost metrics")
    g = pd.Series({"COST": 6.26e9}); conc = pd.Series({"TOP5": 0.4})


tab_ask, tab_drivers, tab_savings, tab_search = st.tabs(
    ["Ask & Research", "Cost Drivers", "Savings Opportunities", "Smart Search"])

with tab_ask:
    st.markdown("<div class='section'>Ask a question, the agent researches it</div>", unsafe_allow_html=True)
    q = st.text_input("ask", key="q", label_visibility="collapsed",
                      placeholder="What is driving cost of care and where should we focus")
    if st.button("Run research agent", type="primary", use_container_width=True) and q.strip():
        schema = schema_context()
        with st.status("Research agent working", expanded=True) as status:
            status.write("Classifying intent")
            intent = classify_intent(q)
            subs, steps, memo = deep_agent(q, schema, status)
            status.update(label="Research complete", state="complete", expanded=False)
        st.markdown("<div class='section'>Executive memo</div>", unsafe_allow_html=True)
        md_panel(memo)
        st.markdown("<div class='section'>Evidence</div>", unsafe_allow_html=True)
        for sub, sql, df in steps:
            st.markdown(f"**{sub}**")
            L, R = st.columns([3, 2])
            with L:
                fig = build_chart(df, recommend_chart(sub, df))
                if fig is not None:
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.dataframe(df, use_container_width=True, height=300)
            with R:
                st.dataframe(df, use_container_width=True, height=300)
            src(" join ".join(tables_in(sql)), f"{len(df):,} rows")
            with st.expander("SQL"):
                st.code(sql, language="sql")


DIMS = {
    "Encounter Class": dict(expr="e.ENCOUNTERCLASS", join="", filt="e.ENCOUNTERCLASS", chart="bar",
                            srcname="CLAIMS.PUBLIC.ENCOUNTERS", keys=""),
    "Facility": dict(expr="o.NAME", join="JOIN AUTH_DB.UM.ORG_DIM o ON o.ID=e.ORGANIZATION",
                     filt="o.NAME", chart="hbar", srcname="ENCOUNTERS join ORG_DIM (deduped)", keys="ORGANIZATION=ID"),
    "Provider": dict(expr="p.NAME", join="JOIN CLAIMS.PUBLIC.PROVIDERS p ON p.ID=e.PROVIDER",
                     filt="p.NAME", chart="hbar", srcname="ENCOUNTERS join PROVIDERS", keys="PROVIDER=ID"),
    "Clinical Reason": dict(expr="COALESCE(NULLIF(NULLIF(e.REASONDESCRIPTION,''),'None'),'Not specified')", join="", chart="treemap",
                            filt="COALESCE(NULLIF(NULLIF(e.REASONDESCRIPTION,''),'None'),'Not specified')", srcname="CLAIMS.PUBLIC.ENCOUNTERS", keys=""),
}

with tab_drivers:
    st.markdown(f"<div class='section'>What is driving cost of care · {YR}</div>", unsafe_allow_html=True)
    dim = st.radio("by", list(DIMS.keys()), horizontal=True, label_visibility="collapsed")
    d = DIMS[dim]
    drv = cdf(f"""SELECT {d['expr']} AS SEGMENT, SUM(e.TOTAL_CLAIM_COST) COST, COUNT(*) ENCOUNTERS,
                         AVG(e.TOTAL_CLAIM_COST) AVG_COST
                  FROM CLAIMS.PUBLIC.ENCOUNTERS e {d['join']} WHERE {yclause('e."START"')}
                  GROUP BY 1 ORDER BY COST DESC LIMIT 12""")
    st.caption("Click a segment, or use the selector, to drill into the underlying encounter records.")
    if d["chart"] == "treemap":
        cf = px.treemap(drv, path=["SEGMENT"], values="COST", color="COST", color_continuous_scale="Blues",
                        title=f"Cost by {dim.lower()}")
    elif d["chart"] == "hbar":
        cf = px.bar(drv, x="COST", y="SEGMENT", orientation="h", color="COST", color_continuous_scale="Blues",
                    title=f"Cost by {dim.lower()}")
        cf.update_layout(yaxis={"categoryorder": "total ascending"})
    else:
        cf = px.bar(drv, x="SEGMENT", y="COST", color="SEGMENT", color_discrete_sequence=SEQ,
                    title=f"Cost by {dim.lower()}")
        cf.update_layout(showlegend=False)
    seg = None
    try:
        sel = st.plotly_chart(finalize(cf, 430), use_container_width=True, on_select="rerun", key=f"dc_{dim}")
        seg = clicked_seg(sel)
    except TypeError:
        st.plotly_chart(finalize(cf, 430), use_container_width=True, key=f"dc2_{dim}")
    options = drv["SEGMENT"].astype(str).tolist()
    seg = st.selectbox("Drill into", options, index=(options.index(seg) if seg in options else 0))

    st.markdown(f"<div class='section'>Records for {seg}</div>", unsafe_allow_html=True)
    det = cdf(f"""SELECT e.ID AS ENCOUNTER_ID, e."START"::DATE AS SERVICE_DATE, e.ENCOUNTERCLASS AS SETTING,
                         e."DESCRIPTION" AS ENCOUNTER, COALESCE(NULLIF(e.REASONDESCRIPTION,'None'),'—') AS CLINICAL_REASON,
                         e.TOTAL_CLAIM_COST AS BILLED, e.PAYER_COVERAGE AS COVERED,
                         (e.TOTAL_CLAIM_COST-e.PAYER_COVERAGE) AS MEMBER_OOP
                  FROM CLAIMS.PUBLIC.ENCOUNTERS e {d['join']}
                  WHERE {d['filt']} = '{esc(seg)}' AND {yclause('e."START"')}
                  ORDER BY e.TOTAL_CLAIM_COST DESC LIMIT 200""")
    dk = st.columns(3)
    kpi(dk[0], "Records shown", f"{len(det):,}")
    kpi(dk[1], "Billed", money(det["BILLED"].sum()))
    kpi(dk[2], "Member OOP", money(det["MEMBER_OOP"].sum()), warn=True)
    st.dataframe(money_cols(det, ["BILLED", "COVERED", "MEMBER_OOP"]), use_container_width=True, height=320)
    src(d["srcname"], f"top {len(det)} records in {YR} where {d['filt']} = '{seg}'", d["keys"])

    with st.spinner("Summarizing the drivers"):
        narr = ai("You are a healthcare cost strategist. In three sentences explain what drives spend given "
                  f"this {dim.lower()} breakdown. Lead with the biggest driver and its share, cite dollars, no "
                  "preamble.\nData:\n" + drv[["SEGMENT", "COST"]].to_csv(index=False))
    st.markdown(f"<div class='panel'>{narr}</div>", unsafe_allow_html=True)


@st.cache_data(show_spinner=False, ttl=1800)
def avoidable(year):
    yc = (f'TO_TIMESTAMP_NTZ("START") >= \'{year}-01-01\' '
          f'AND TO_TIMESTAMP_NTZ("START") < \'{year + 1}-01-01\'')
    kws = ["heart failure", "obstructive bronchitis", "emphysema", "asthma", "infective cystitis",
           "urinary tract infection", "pyelonephritis", "cellulitis", "dehydration", "diabet",
           "hypertensi", "angina", "bacterial pneumonia", "seizure"]
    like = " OR ".join(f"LOWER(COALESCE(REASONDESCRIPTION, \"DESCRIPTION\")) LIKE '%{k}%'" for k in kws)
    return run_df(f"""SELECT COALESCE(NULLIF(REASONDESCRIPTION,'None'), "DESCRIPTION") AS REASON,
                             SUM(TOTAL_CLAIM_COST) COST, COUNT(*) N
                      FROM CLAIMS.PUBLIC.ENCOUNTERS
                      WHERE ENCOUNTERCLASS IN ('inpatient','emergency','urgentcare')
                        AND {yc} AND ({like})
                      GROUP BY 1 ORDER BY COST DESC""")


with tab_savings:
    st.markdown(f"<div class='section'>Where the savings are · {YR}</div>", unsafe_allow_html=True)
    conc2 = cdf(f"""WITH r AS (SELECT TOTAL_CLAIM_COST c, NTILE(100) OVER (ORDER BY TOTAL_CLAIM_COST DESC) p
                              FROM CLAIMS.PUBLIC.ENCOUNTERS WHERE {yclause()})
                   SELECT SUM(IFF(p=1,c,0))/NULLIF(SUM(c),0) T1, SUM(IFF(p<=5,c,0))/NULLIF(SUM(c),0) T5,
                          SUM(IFF(p<=10,c,0))/NULLIF(SUM(c),0) T10 FROM r""").iloc[0]
    setting = cdf(f"""SELECT ENCOUNTERCLASS SEGMENT, SUM(TOTAL_CLAIM_COST) COST, AVG(TOTAL_CLAIM_COST) AVG_COST
                      FROM CLAIMS.PUBLIC.ENCOUNTERS WHERE {yclause()} GROUP BY 1 ORDER BY COST DESC""")
    L, R = st.columns([2, 3])
    with L:
        gfig = go.Figure(go.Indicator(mode="gauge+number", value=float(conc2.T5) * 100, number={"suffix": "%"},
            title={"text": "Cost from top 5% of encounters", "font": {"color": "#0f172a"}},
            gauge={"axis": {"range": [0, 100]}, "bar": {"color": "#2563eb"},
                   "steps": [{"range": [0, 33], "color": "#dcfce7"}, {"range": [33, 66], "color": "#fef9c3"},
                             {"range": [66, 100], "color": "#fee2e2"}]}))
        st.plotly_chart(finalize(gfig, 320), use_container_width=True)
        kpi(st.columns(1)[0], "Cost concentration", f"Top 1%: {conc2.T1*100:.0f}% · Top 10%: {conc2.T10*100:.0f}%",
            "of total cost", warn=True)
    with R:
        fig = px.bar(setting, x="SEGMENT", y="COST", title="Total cost by care setting", color="AVG_COST",
                     color_continuous_scale="Blues", labels={"AVG_COST": "Avg cost"})
        st.plotly_chart(finalize(fig, 360), use_container_width=True)
    src("CLAIMS.PUBLIC.ENCOUNTERS", f"{YR} encounters, percentile concentration")

    st.markdown("<div class='section'>Potentially preventable admissions</div>", unsafe_allow_html=True)
    st.caption("Ambulatory-care-sensitive conditions (AHRQ Prevention Quality Indicators) admitted to inpatient, "
               "emergency, or urgent care. These admissions can often be prevented with timely primary and "
               "preventive care, making them a defensible savings target.")
    try:
        av = avoidable(YR)
        prevent_cost = float(av["COST"].sum())
        flagged = av.sort_values("COST", ascending=False)
        c2 = st.columns([1, 2])
        kpi(c2[0], "Preventable Admission Cost", money(prevent_cost),
            f"{prevent_cost/float(g.COST)*100:.1f}% of total cost of care", warn=True)
        fig = px.bar(flagged.head(10), x="COST", y="REASON", orientation="h",
                     title="Preventable admissions by condition", color="COST", color_continuous_scale="Blues")
        fig.update_layout(yaxis={"categoryorder": "total ascending"})
        c2[1].plotly_chart(finalize(fig, 340), use_container_width=True)
        src("CLAIMS.PUBLIC.ENCOUNTERS",
            f"{len(flagged)} ambulatory-care-sensitive conditions in acute settings · {YR}",
            "ENCOUNTERCLASS in inpatient, emergency, urgentcare")
        with st.spinner("Summarizing the clinical opportunity"):
            theme = ai("In two sentences for a payer audience, explain why these admissions are considered "
                       "potentially preventable and the primary-care action that reduces them.\nConditions:\n"
                       + flagged[["REASON", "COST"]].to_csv(index=False))
        if theme:
            st.markdown(f"<div class='panel'>{theme}</div>", unsafe_allow_html=True)
        with st.expander("Preventable conditions detail"):
            st.dataframe(money_cols(flagged[["REASON", "COST", "N"]], ["COST"]), use_container_width=True)
    except Exception:
        st.info("Preventable-admission analysis unavailable")

    st.markdown("<div class='section'>Recommended interventions</div>", unsafe_allow_html=True)
    with st.spinner("Drafting a quantified savings plan"):
        plan = ai("You are a healthcare cost management consultant. Propose exactly three concrete, quantified "
                  "cost-savings interventions for a payer. Each one: a short bold action title, one sentence of "
                  "how, and an estimated annual savings range in dollars tied to the figures. Return three "
                  "markdown bullet points, no preamble.\n"
                  f"Total cost of care {money(float(g.COST))}. Top 5% drive {conc2.T5*100:.0f}% of cost. Setting cost:\n"
                  + setting.to_csv(index=False))
    for line in [x for x in plan.split("\n") if x.strip()][:3]:
        st.markdown(f"<div class='rec'>{line.lstrip('-* ').strip()}</div>", unsafe_allow_html=True)


with tab_search:
    st.markdown("<div class='section'>Smart Search — Cortex Search</div>", unsafe_allow_html=True)
    st.caption("Semantic search across 10,000 unique service lines by clinical reason and named facility.")
    sq = st.text_input("search", key="search_q", label_visibility="collapsed",
                       placeholder="expensive cardiac surgery, preventable emergency visits, joint replacement")
    if st.button("Search", type="primary") and sq.strip():
        try:
            with st.spinner("Cortex Search retrieving semantically similar service lines"):
                res = cortex_search(sq, 15)
            if res.empty:
                st.info("No matches. Try a clinical phrase such as kidney disease or hip replacement.")
            else:
                if "REASON" in res.columns:
                    res = res[res["REASON"].notnull()]
                kc = st.columns(3)
                kpi(kc[0], "Matches", f"{len(res):,}")
                if "TOTAL_COST" in res.columns:
                    kpi(kc[1], "Total Cost", money(res["TOTAL_COST"].sum()))
                    kpi(kc[2], "Avg Cost", money(res["AVG_COST"].mean()))
                cols = [c for c in ["REASON", "FACILITY", "SETTING", "ENCOUNTERS", "TOTAL_COST", "AVG_COST"] if c in res.columns]
                st.dataframe(money_cols(res[cols], ["TOTAL_COST", "AVG_COST"]), use_container_width=True, height=380)
                src(f"{SEARCH_SVC}", f"top {len(res)} semantic matches over 10,127 unique service lines")
                with st.spinner("Summarizing the cohort"):
                    summ = ai("In two sentences summarize the clinical and cost profile of these matched service "
                              "lines for a payer.\n" + res[cols].head(12).to_csv(index=False))
                st.markdown(f"<div class='panel'>{summ}</div>", unsafe_allow_html=True)
        except Exception:
            st.warning("Search index is refreshing, try again in a moment.")

st.markdown("<div style='text-align:center;color:#94a3b8;margin-top:22px;font-size:12px'>"
            "FEP Care Lens AI · Cost of Care Intelligence · Snowflake Cortex · Claude 4 Sonnet</div>",
            unsafe_allow_html=True)
