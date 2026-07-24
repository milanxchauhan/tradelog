import streamlit as st

CSS = """
<style>
/* Import a proper monospace + a clean UI face */
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
code, .stDataFrame, [data-testid="stMetricValue"] { font-family: 'JetBrains Mono', monospace; }

/* Tighten the top padding Streamlit adds */
.block-container { padding-top: 2.5rem; max-width: 1400px; }

/* Title */
h1 { font-weight: 600; letter-spacing: -0.02em; color: #f8fafc; }
h2, h3 { color: #cbd5e1; font-weight: 500; }

/* Metric cards */
[data-testid="stMetric"] {
    background: linear-gradient(180deg, #161f2c 0%, #121925 100%);
    border: 1px solid #1f2937;
    border-radius: 10px;
    padding: 16px 18px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.3);
}
[data-testid="stMetricLabel"] {
    color: #64748b; font-size: 0.72rem; text-transform: uppercase;
    letter-spacing: 0.06em; font-weight: 600;
}
[data-testid="stMetricValue"] {
    font-size: 1.5rem; font-weight: 700; color: #f1f5f9;
}

/* Tabs — underline style, green active */
.stTabs [data-baseweb="tab-list"] { gap: 4px; border-bottom: 1px solid #1f2937; }
.stTabs [data-baseweb="tab"] {
    background: transparent; border-radius: 6px 6px 0 0;
    padding: 8px 16px; color: #64748b; font-weight: 500;
}
.stTabs [aria-selected="true"] {
    background: #141b26; color: #22c55e !important;
    border-bottom: 2px solid #22c55e;
}

/* Buttons */
.stButton button {
    border-radius: 8px; font-weight: 600; border: 1px solid #22c55e33;
    transition: all 0.15s ease;
}
.stButton button[kind="primary"] {
    background: #16a34a; border: none;
}
.stButton button[kind="primary"]:hover {
    background: #22c55e; box-shadow: 0 0 0 3px #22c55e22;
}

/* Dataframe polish */
.stDataFrame { border: 1px solid #1f2937; border-radius: 10px; }
.stDataFrame thead tr th {
    background: #0d131c !important; color: #94a3b8 !important;
    text-transform: uppercase; font-size: 0.7rem; letter-spacing: 0.04em;
}

/* Refresh button, top-left, quieter */
section.main div.stButton:first-of-type button { background: #141b26; }

/* Alerts — flatter, less candy */
.stAlert { border-radius: 8px; border-left-width: 3px; }
</style>
"""


def apply():
    st.markdown(CSS, unsafe_allow_html=True)