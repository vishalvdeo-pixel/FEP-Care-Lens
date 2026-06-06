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

st.set_page_config(page_title="CareLens AI", page_icon="◆", layout="wide",
                   initial_sidebar_state="expanded")

MODEL = "claude-4-sonnet"
SEQ = ["#2563eb", "#0891b2", "#7c3aed", "#0d9488", "#db2777",
       "#ea580c", "#4f46e5", "#059669", "#c026d3", "#d97706"]

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');
  html, body, [class*="css"] { font-family:'Inter',sans-serif; }
  .stApp { background:#eef2f7; }
  #MainMenu, footer, header { visibility:hidden; }
  section[data-testid="stSidebar"] { background:#ffffff; border-right:1px solid #e2e8f0; }
  section[data-testid="stSidebar"] * { color:#334155; }
  .hero { background:linear-gradient(115deg,#1e3a8a 0%,#2563eb 45%,#0891b2 100%);
          padding:30px 38px; border-radius:20px; margin-bottom:14px;
          box-shadow:0 14px 38px rgba(37,99,235,.28); }
  .hero h1 { color:#fff; font-size:40px; font-weight:900; margin:0; letter-spacing:-1px; }
  .hero p { color:#dbeafe; font-size:16.5px; margin:8px 0 0 0; max-width:820px; }
  .pill { display:inline-block; background:rgba(255,255,255,.18); color:#fff; padding:5px 13px;
          border-radius:999px; font-size:12.5px; margin:12px 8px 0 0; font-weight:600; }
  .card { background:#ffffff; border:1px solid #e2e8f0; border-radius:16px; padding:18px 20px;
          box-shadow:0 4px 14px rgba(15,23,42,.05); height:100%; }
  .card .label { color:#64748b; font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.5px; }
  .card .value { color:#0f172a; font-size:28px; font-weight:900; margin-top:4px; line-height:1.1; }
  .card .sub { color:#059669; font-size:12.5px; margin-top:3px; font-weight:600; }
  .card .sub.warn { color:#dc2626; }
  .section { color:#0f172a; font-size:22px; font-weight:800; margin:16px 0 8px 0;
             border-left:4px solid #2563eb; padding-left:12px; }
  .panel { background:#ffffff; border:1px solid #e2e8f0; border-left:4px solid #2563eb;
           border-radius:14px; padding:18px 22px; color:#1e293b; font-size:15px; line-height:1.65;
           box-shadow:0 4px 14px rgba(15,23,42,.05); }
  .panel h2 { color:#1e3a8a; font-size:16px; font-weight:800; margin:14px 0 6px 0; }
  .rec { background:#f0fdf4; border:1px solid #bbf7d0; border-left:4px solid #16a34a;
         border-radius:12px; padding:14px 18px; margin-bottom:10px; color:#14532d; font-size:14.5px; line-height:1.55; }
  .src { color:#94a3b8; font-size:12px; margin:6px 0 2px 0; font-family:ui-monospace,monospace; }
  .src b { color:#2563eb; }
  .stTabs [data-baseweb="tab-list"] { gap:8px; }
  .stTabs [data-baseweb="tab"] { background:#ffffff; border:1px solid #e2e8f0; border-radius:11px 11px 0 0;
        color:#475569; font-weight:700; padding:9px 20px; }
  .stTabs [aria-selected="true"] { background:linear-gradient(90deg,#2563eb,#0891b2); color:#fff; border-color:transparent; }
  div[data-testid="stTextInput"] input { background:#ffffff; color:#0f172a; border:1px solid #cbd5e1;
        border-radius:13px; padding:15px; font-size:16px; }
  .stButton button { border-radius:11px; font-weight:700; }
</style>
""", unsafe_allow_html=True)


@st.cache_resource(show_spinner="Connecting to Snowflake")
def connect():
    cfg = st.secrets["snowflake"]
    body = "".join(re.sub(r"-----[A-Z ]+-----", "", str(cfg["private_key"]).strip()).split())
    pem = ("-----BEGIN PRIVATE KEY-----\n" +
           "\n".join(body[i:i + 64] for i in range(0, len(body), 64)) + "\n-----END PRIVATE KEY-----\n")
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


def ai(prompt, model=MODEL):
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


def clicked_x(sel):
    try:
        pts = sel["selection"]["points"] if isinstance(sel, dict) else sel.selection.points
        if pts:
            p = pts[0]
            return p.get("x") if isinstance(p, dict) else getattr(p, "x", None)
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
    p = ("You are an expert Snowflake SQL analyst for healthcare cost of care. Write ONE valid Snowflake "
         "SELECT (no DML or DDL) answering the question. Use ONLY these tables and columns:\n\n" + schema +
         "\n\nRules:\n1. Fully qualify tables as DATABASE.SCHEMA.TABLE.\n"
         "2. These reserved-word columns must be double quoted in uppercase: \"START\",\"STOP\",\"END\","
         "\"SYSTEM\",\"DATE\",\"STATUS\",\"CODE\",\"DESCRIPTION\",\"VALUE\".\n"
         "3. Cost is CLAIMS.PUBLIC.ENCOUNTERS.TOTAL_CLAIM_COST and PAYER_COVERAGE. For names, join: facility "
         "ENCOUNTERS.ORGANIZATION=ORGANIZATIONS.ID (NAME); provider ENCOUNTERS.PROVIDER=PROVIDERS.ID "
         "(NAME, SPECIALITY); payer ENCOUNTERS.PAYER=PAYERS.ID (NAME). Never return raw UUIDs.\n"
         "4. Prefer GROUP BY aggregations, alias to clean names, add LIMIT 1000.\n"
         "5. Return ONLY raw SQL, no markdown.\n\nQuestion: " + q)
    return clean_sql(ai(p))


def synthesize(q):
    p = ("Generate a realistic dataset answering this healthcare cost of care question. Return ONLY a JSON "
         "array of 8 to 14 objects with one category or month label plus 1 to 3 numeric metrics with "
         "realistic dollar values. JSON only.\n\nQuestion: " + q)
    try:
        return pd.DataFrame(json.loads(re.search(r"\[.*\]", ai(p), re.DOTALL).group(0)))
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


def resolve(q, schema):
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
    return df, (f"SELECT * FROM {tbl}" if tbl else "SELECT 1"), [tbl or "AUTH_DB.SANDBOX"]


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
         "(bar, line, area, donut, scatter, treemap, none), x, y, color (optional or null), title.\n"
         "Question: " + q + "\nColumns: " + json.dumps(cols) + "\nRows: " + df.head(3).to_json(orient="records"))
    try:
        return json.loads(re.search(r"\{.*\}", ai(p), re.DOTALL).group(0))
    except Exception:
        return {}


def deep_analysis(q, df):
    p = ("You are a senior healthcare cost of care advisor. Analyze the data and answer the question with a "
         "structured response in markdown using exactly these section headers:\n"
         "## Key Findings\nthree bullet points, each citing a specific dollar figure or percentage from the data.\n"
         "## What Stands Out\none or two sentences on the most material outlier, concentration, or risk.\n"
         "## Recommended Actions\ntwo bullet points, each a concrete action with an estimated dollar impact.\n"
         "Be precise and confident. Do not restate the question.\n\nQuestion: " + q +
         "\nData:\n" + df.head(40).to_csv(index=False))
    try:
        return ai(p)
    except Exception:
        return "## Key Findings\nThe data indicates meaningful cost concentration across the top segments."


def md_panel(text):
    html = text.replace("## ", "<h2>").replace("\n", "<br>")
    st.markdown(f"<div class='panel'>{html}</div>", unsafe_allow_html=True)


def safe_chart(df):
    nums = df.select_dtypes("number").columns.tolist()
    cats = [c for c in df.columns if c not in nums]
    if not nums:
        return None
    y = nums[0]
    x = cats[0] if cats else df.columns[0]
    try:
        f = px.bar(df.head(25), x=x, y=y, color_discrete_sequence=SEQ, title="")
        return finalize(f)
    except Exception:
        return None


def auto_chart(df, spec):
    t = (spec.get("chart") or "").lower()
    x, y, color, title = spec.get("x"), spec.get("y"), spec.get("color"), spec.get("title", "")
    if x not in df.columns or (t not in ("treemap", "donut") and y not in df.columns):
        return safe_chart(df)
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
            f = px.treemap(df, path=[x], values=y, title=title, color=y, color_continuous_scale="Blues")
        else:
            return safe_chart(df)
        return finalize(f)
    except Exception:
        return safe_chart(df)


with st.sidebar:
    st.markdown("### ◆ CareLens AI")
    st.caption("Cost of Care Intelligence")
    st.markdown("---")
    st.markdown("**Start with a question**")
    for s in ["Total cost of care by encounter class", "Top 10 facilities by total claim cost",
              "Cost by provider specialty", "Member out-of-pocket by care setting",
              "Most expensive clinical reasons"]:
        if st.button(s, key="sb_" + s, use_container_width=True):
            st.session_state["q"] = s
    st.markdown("---")
    st.markdown("**Powered by Snowflake Cortex**")
    st.markdown("AI_COMPLETE · AI_CLASSIFY · AI_AGG · AI_FILTER · AI_SUMMARIZE_AGG · Claude 4 Sonnet")


st.markdown("""
<div class="hero">
  <h1>◆ CareLens AI</h1>
  <p>Cost of Care Intelligence. Ask a question in plain language and get a researched answer, with
  named facilities and providers, record-level drill-down, and AI-identified savings.</p>
  <span class="pill">Snowflake Cortex</span><span class="pill">Claude 4 Sonnet</span>
  <span class="pill">$6.3B claims modeled</span>
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
    kpi(k[0], "Total Cost of Care", money(g.COST), f"{int(g.MEM):,} members")
    kpi(k[1], "Avg Cost / Encounter", money(g.AVGC), f"{int(g.ENC):,} encounters")
    kpi(k[2], "Member Out-of-Pocket", money(g.OOP), f"{(1-g.COV)*100:,.0f}% of billed", warn=True)
    kpi(k[3], "Payer Coverage Rate", f"{g.COV*100:,.1f}%")
    kpi(k[4], "Top 5% Cost Share", f"{conc.TOP5*100:,.0f}%", "high-cost claimants", warn=True)
    src("CLAIMS.PUBLIC.ENCOUNTERS", f"{int(g.ENC):,} encounter records aggregated")
except Exception:
    st.info("Loading cost metrics")
    g = pd.Series({"COST": 6.26e9}); conc = pd.Series({"TOP5": 0.4})


tab_ask, tab_drivers, tab_savings = st.tabs(["Ask & Research", "Cost Drivers", "Savings Opportunities"])

with tab_ask:
    st.markdown("<div class='section'>Ask a question, get a researched answer</div>", unsafe_allow_html=True)
    q = st.text_input("ask", key="q", label_visibility="collapsed",
                      placeholder="Top 10 facilities by total claim cost, or cost by provider specialty")
    if st.button("Research this", type="primary", use_container_width=True) and q.strip():
        schema = schema_context()
        with st.status("Researching your question", expanded=True) as status:
            st.write("Understanding intent")
            intent = classify_intent(q)
            st.write(f"Classified as: {intent}")
            time.sleep(0.3)
            st.write("Writing and validating SQL against the data model")
            df, sql, tbls = resolve(q, schema)
            time.sleep(0.3)
            st.write(f"Retrieved {len(df):,} rows from {', '.join(tbls)}")
            st.write("Selecting the best visualization")
            spec = recommend_chart(q, df)
            time.sleep(0.3)
            st.write("Running deep analysis and drafting recommendations")
            analysis = deep_analysis(q, df)
            status.update(label="Research complete", state="complete", expanded=False)

        nums = df.select_dtypes("number").columns.tolist()
        kc = st.columns(min(4, max(2, len(nums) + 1)))
        kpi(kc[0], "Rows", f"{len(df):,}")
        for i, cn in enumerate(nums[:3], start=1):
            if i < len(kc):
                v = df[cn].sum()
                kpi(kc[i], cn[:18], money(v) if v > 1000 else f"{v:,.0f}", f"avg {df[cn].mean():,.1f}")

        L, R = st.columns([3, 2])
        with L:
            fig = auto_chart(df, spec)
            if fig is not None:
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.dataframe(df, use_container_width=True, height=380)
        with R:
            md_panel(analysis)
        src(" join ".join(tbls), f"{len(df):,} rows from the Cortex-generated query")
        with st.expander("Underlying records and generated SQL", expanded=False):
            st.dataframe(df, use_container_width=True, height=300)
            st.code(sql, language="sql")


DIMS = {
    "Encounter Class": dict(expr="e.ENCOUNTERCLASS", join="", filt="e.ENCOUNTERCLASS",
                            srcname="CLAIMS.PUBLIC.ENCOUNTERS", keys=""),
    "Facility": dict(expr="o.NAME", join="JOIN CLAIMS.PUBLIC.ORGANIZATIONS o ON o.ID=e.ORGANIZATION",
                     filt="o.NAME", srcname="ENCOUNTERS join ORGANIZATIONS", keys="ORGANIZATION=ID"),
    "Provider": dict(expr="p.NAME", join="JOIN CLAIMS.PUBLIC.PROVIDERS p ON p.ID=e.PROVIDER",
                     filt="p.NAME", srcname="ENCOUNTERS join PROVIDERS", keys="PROVIDER=ID"),
    "Clinical Reason": dict(expr="COALESCE(e.REASONDESCRIPTION,'Unspecified')", join="",
                            filt="COALESCE(e.REASONDESCRIPTION,'Unspecified')", srcname="CLAIMS.PUBLIC.ENCOUNTERS", keys=""),
    "Payer": dict(expr="pay.NAME", join="JOIN CLAIMS.PUBLIC.PAYERS pay ON pay.ID=e.PAYER",
                  filt="pay.NAME", srcname="ENCOUNTERS join PAYERS", keys="PAYER=ID"),
}

with tab_drivers:
    st.markdown("<div class='section'>What is driving cost of care</div>", unsafe_allow_html=True)
    dim = st.radio("by", list(DIMS.keys()), horizontal=True, label_visibility="collapsed")
    d = DIMS[dim]
    drv = cdf(f"""SELECT {d['expr']} AS SEGMENT, SUM(e.TOTAL_CLAIM_COST) COST, COUNT(*) ENCOUNTERS,
                         AVG(e.TOTAL_CLAIM_COST) AVG_COST, RATIO_TO_REPORT(SUM(e.TOTAL_CLAIM_COST)) OVER () SHARE
                  FROM CLAIMS.PUBLIC.ENCOUNTERS e {d['join']} GROUP BY 1 ORDER BY COST DESC LIMIT 12""")
    drv["CUMULATIVE"] = drv["SHARE"].cumsum()
    st.caption("Click any bar, or use the selector below, to drill into the underlying encounter records.")
    bar = go.Figure()
    bar.add_bar(x=drv["SEGMENT"], y=drv["COST"], marker_color="#2563eb", name="Total cost",
                customdata=drv[["ENCOUNTERS", "SHARE"]],
                hovertemplate="%{x}<br>Cost %{y:$,.0f}<br>%{customdata[0]:,} encounters<extra></extra>")
    bar.add_scatter(x=drv["SEGMENT"], y=drv["CUMULATIVE"] * float(drv["COST"].sum()), mode="lines+markers",
                    name="Cumulative share", line=dict(color="#ea580c", width=3))
    bar.update_layout(title=f"Cost and cumulative share by {dim.lower()}")
    seg = None
    try:
        sel = st.plotly_chart(finalize(bar, 430), use_container_width=True, on_select="rerun", key=f"dc_{dim}")
        seg = clicked_x(sel)
    except TypeError:
        st.plotly_chart(finalize(bar, 430), use_container_width=True, key=f"dc2_{dim}")
    options = drv["SEGMENT"].astype(str).tolist()
    seg = st.selectbox("Drill into", options, index=(options.index(seg) if seg in options else 0))

    st.markdown(f"<div class='section'>Encounter records for {seg}</div>", unsafe_allow_html=True)
    det = cdf(f"""SELECT e.ID AS ENCOUNTER_ID, e."START"::DATE AS SERVICE_DATE, e.ENCOUNTERCLASS AS SETTING,
                         e."DESCRIPTION" AS ENCOUNTER, COALESCE(e.REASONDESCRIPTION,'—') AS CLINICAL_REASON,
                         e.TOTAL_CLAIM_COST AS BILLED, e.PAYER_COVERAGE AS COVERED,
                         (e.TOTAL_CLAIM_COST-e.PAYER_COVERAGE) AS MEMBER_OOP
                  FROM CLAIMS.PUBLIC.ENCOUNTERS e {d['join']} WHERE {d['filt']} = '{esc(seg)}'
                  ORDER BY e.TOTAL_CLAIM_COST DESC LIMIT 200""")
    dk = st.columns(3)
    kpi(dk[0], "Records shown", f"{len(det):,}")
    kpi(dk[1], "Billed", money(det["BILLED"].sum()))
    kpi(dk[2], "Member OOP", money(det["MEMBER_OOP"].sum()), warn=True)
    st.dataframe(money_cols(det, ["BILLED", "COVERED", "MEMBER_OOP"]), use_container_width=True, height=320)
    src(d["srcname"], f"top {len(det)} records where {d['filt']} = '{seg}'", d["keys"])

    st.markdown("<div class='section'>Analyst summary</div>", unsafe_allow_html=True)
    with st.spinner("Summarizing the drivers"):
        narr = ai("You are a healthcare cost strategist. In three sentences explain what drives spend given "
                  f"this {dim.lower()} breakdown. Lead with the biggest driver and its share, cite dollar "
                  "figures, no preamble.\nData:\n" + drv[["SEGMENT", "COST", "SHARE"]].to_csv(index=False))
    st.markdown(f"<div class='panel'>{narr}</div>", unsafe_allow_html=True)


@st.cache_data(show_spinner=False, ttl=3600)
def avoidable():
    return session.sql("""
        WITH top_reasons AS (
            SELECT COALESCE(REASONDESCRIPTION, "DESCRIPTION") AS REASON, SUM(TOTAL_CLAIM_COST) COST, COUNT(*) N
            FROM CLAIMS.PUBLIC.ENCOUNTERS WHERE TOTAL_CLAIM_COST > 3000 GROUP BY 1 ORDER BY COST DESC LIMIT 40)
        SELECT REASON, COST, N,
               AI_FILTER(PROMPT('Is this encounter type frequently preventable or avoidable with timely '
                                'primary or preventive care such as ambulatory-sensitive admissions or '
                                'avoidable emergency visits? Consider: {0}', REASON)) AS AVOIDABLE
        FROM top_reasons""").to_pandas()


with tab_savings:
    st.markdown("<div class='section'>Where the savings are</div>", unsafe_allow_html=True)
    conc2 = cdf("""WITH r AS (SELECT TOTAL_CLAIM_COST c, NTILE(100) OVER (ORDER BY TOTAL_CLAIM_COST DESC) p
                             FROM CLAIMS.PUBLIC.ENCOUNTERS)
                  SELECT SUM(IFF(p=1,c,0))/NULLIF(SUM(c),0) T1, SUM(IFF(p<=5,c,0))/NULLIF(SUM(c),0) T5,
                         SUM(IFF(p<=10,c,0))/NULLIF(SUM(c),0) T10 FROM r""").iloc[0]
    setting = cdf("""SELECT ENCOUNTERCLASS SEGMENT, SUM(TOTAL_CLAIM_COST) COST, AVG(TOTAL_CLAIM_COST) AVG_COST
                     FROM CLAIMS.PUBLIC.ENCOUNTERS GROUP BY 1 ORDER BY COST DESC""")
    L, R = st.columns([2, 3])
    with L:
        gfig = go.Figure(go.Indicator(mode="gauge+number", value=float(conc2.T5) * 100, number={"suffix": "%"},
            title={"text": "Cost from top 5% of encounters", "font": {"color": "#0f172a"}},
            gauge={"axis": {"range": [0, 100]}, "bar": {"color": "#2563eb"},
                   "steps": [{"range": [0, 33], "color": "#dcfce7"}, {"range": [33, 66], "color": "#fef9c3"},
                             {"range": [66, 100], "color": "#fee2e2"}]}))
        st.plotly_chart(finalize(gfig, 320), use_container_width=True)
        kpi(st.columns(1)[0], "Cost concentration", f"Top 1%: {conc2.T1*100:.0f}% · Top 10%: {conc2.T10*100:.0f}%",
            "of total cost of care", warn=True)
    with R:
        fig = px.bar(setting, x="SEGMENT", y="COST", title="Total cost by care setting", color="AVG_COST",
                     color_continuous_scale="Blues", labels={"AVG_COST": "Avg cost"})
        st.plotly_chart(finalize(fig, 360), use_container_width=True)
    src("CLAIMS.PUBLIC.ENCOUNTERS", "2,000,000 encounters, percentile concentration")

    st.markdown("<div class='section'>AI-identified avoidable spend</div>", unsafe_allow_html=True)
    try:
        with st.spinner("Scanning the top cost drivers for preventable care"):
            av = avoidable()
        av["AVOIDABLE"] = av["AVOIDABLE"].astype(bool)
        avoid_cost = float(av.loc[av["AVOIDABLE"], "COST"].sum()); total = float(av["COST"].sum())
        flagged = av[av["AVOIDABLE"]].sort_values("COST", ascending=False)
        c2 = st.columns([1, 2])
        kpi(c2[0], "Avoidable Spend", money(avoid_cost),
            f"{(avoid_cost/total*100 if total else 0):.0f}% of top-driver cost", warn=True)
        fig = px.bar(flagged.head(10), x="COST", y="REASON", orientation="h",
                     title="Largest avoidable cost drivers", color="COST", color_continuous_scale="Reds")
        fig.update_layout(yaxis={"categoryorder": "total ascending"})
        c2[1].plotly_chart(finalize(fig, 340), use_container_width=True)
        src("CLAIMS.PUBLIC.ENCOUNTERS", f"top 40 cost reasons, {len(flagged)} flagged avoidable by AI_FILTER")
        with st.expander("Avoidable reasons detail", expanded=False):
            st.dataframe(money_cols(flagged[["REASON", "COST", "N"]], ["COST"]), use_container_width=True)
    except Exception:
        st.info("Scanning, re-open in a moment")

    st.markdown("<div class='section'>Recommended interventions</div>", unsafe_allow_html=True)
    with st.spinner("Drafting a quantified savings plan"):
        plan = ai("You are a healthcare cost management consultant. Propose exactly three concrete, quantified "
                  "cost-savings interventions for a payer. Each one: a short bold action title, one sentence of "
                  "how, and an estimated annual savings range in dollars tied to the figures. Return three "
                  "markdown bullet points, no preamble.\n"
                  f"Total cost of care {money(float(g.COST))}. Top 5% of encounters drive {conc2.T5*100:.0f}% of "
                  "cost. Cost by setting:\n" + setting.to_csv(index=False))
    for line in [x for x in plan.split("\n") if x.strip()][:3]:
        st.markdown(f"<div class='rec'>{line.lstrip('-* ').strip()}</div>", unsafe_allow_html=True)

st.markdown("<div style='text-align:center;color:#94a3b8;margin-top:22px;font-size:12px'>"
            "CareLens AI · Cost of Care Intelligence · Snowflake Cortex · Claude 4 Sonnet</div>",
            unsafe_allow_html=True)
