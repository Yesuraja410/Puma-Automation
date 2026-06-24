import streamlit as st

def inject_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap');

    /* Font Family Settings */
    html, body, [class*="css"], .stApp {
        font-family: 'Plus Jakarta Sans', sans-serif !important;
    }

    /* Vibrant Neon Dark Gradient Background (Teal, Magenta, and Blue glows on Dark Black) */
    .stApp, 
    [data-testid="stAppViewContainer"], 
    [data-testid="stMainViewContainer"],
    [data-testid="stMain"],
    [data-testid="stHeader"] {
        background-color: #05070f !important;
        background-image: 
            radial-gradient(circle at 90% 10%, rgba(6, 182, 212, 0.2) 0%, transparent 45%),
            radial-gradient(circle at 10% 50%, rgba(217, 70, 239, 0.25) 0%, transparent 50%),
            radial-gradient(circle at 80% 90%, rgba(37, 99, 235, 0.3) 0%, transparent 55%) !important;
        background-attachment: fixed !important;
        color: #f1f5f9 !important;
    }

    /* Force Sidebar Background - Very Dark Charcoal */
    [data-testid="stSidebar"], 
    [data-testid="stSidebar"] > div {
        background-color: #030408 !important;
        border-right: 1px solid rgba(217, 70, 239, 0.15) !important;
    }

    /* Premium Header Container - Translucent Indigo-Dark Card with Magenta border */
    .header-container {
        padding: 2rem;
        background-color: rgba(18, 20, 38, 0.6) !important;
        border: 1px solid rgba(217, 70, 239, 0.25) !important;
        border-radius: 16px;
        box-shadow: 0 10px 30px -10px rgba(0, 0, 0, 0.9), 0 0 20px rgba(217, 70, 239, 0.05);
        backdrop-filter: blur(12px);
        margin-bottom: 2rem;
    }
    
    /* Crisp White Title with Soft Purple glow */
    .main-title {
        font-size: 2.8rem;
        font-weight: 800;
        color: #ffffff !important;
        letter-spacing: -0.02em;
        margin-bottom: 0.5rem;
        text-shadow: 0 0 25px rgba(217, 70, 239, 0.3);
    }
    
    /* Soft Cyan/Purple Subtitle */
    .sub-title {
        font-size: 1.05rem;
        font-weight: 400;
        color: #a5b4fc !important; /* Soft indigo-cyan */
        letter-spacing: 0.01em;
    }

    /* Sidebar Headings and Labels - Electric Magenta */
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] .stSelectbox label,
    [data-testid="stSidebar"] .stFileUploader label,
    [data-testid="stSidebar"] .stRadio label,
    [data-testid="stSidebar"] .stTextInput label,
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 {
        color: #d946ef !important; /* Electric Magenta */
        font-size: 0.85rem !important;
        font-weight: 700 !important;
        letter-spacing: 0.06em !important;
        text-transform: uppercase !important;
        margin-bottom: 6px !important;
    }

    /* KPI Cards Container styling - Translucent Violet-Black Base */
    .metric-card {
        background-color: rgba(18, 20, 38, 0.8) !important;
        border: 1px solid rgba(255, 255, 255, 0.04) !important;
        border-radius: 12px;
        padding: 1.4rem;
        box-shadow: 0 8px 20px -5px rgba(0, 0, 0, 0.7);
        transition: all 0.25s ease-in-out;
    }
    
    .metric-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 15px 30px -8px rgba(0, 0, 0, 0.8);
        border-color: rgba(217, 70, 239, 0.4) !important;
    }

    .metric-title {
        font-size: 0.8rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #cbd5e1;
        margin-bottom: 0.4rem;
        opacity: 0.85;
    }
    
    .metric-value {
        font-size: 2.1rem;
        font-weight: 800;
        font-family: 'JetBrains Mono', monospace;
        letter-spacing: -0.02em;
    }

    /* Left-border colored indicators */
    .metric-total {
        border-left: 4px solid #38bdf8 !important; /* Light Blue */
    }
    .metric-total .metric-value {
        color: #38bdf8 !important;
    }

    .metric-passed {
        border-left: 4px solid #10b981 !important; /* Green */
    }
    .metric-passed .metric-value {
        color: #34d399 !important;
    }

    .metric-warnings {
        border-left: 4px solid #f59e0b !important; /* Amber */
    }
    .metric-warnings .metric-value {
        color: #fbbf24 !important;
    }

    .metric-failed {
        border-left: 4px solid #ef4444 !important; /* Red */
    }
    .metric-failed .metric-value {
        color: #f87171 !important;
    }

    /* Tabs Component Styling - Deep Indigo-Dark Backdrop with Magenta active selection */
    .stTabs [data-baseweb="tab-list"] {
        background-color: #030408 !important;
        border-radius: 10px;
        padding: 5px;
        border: 1px solid rgba(217, 70, 239, 0.15) !important;
        gap: 6px;
    }
    .stTabs [data-baseweb="tab"] {
        color: #c084fc !important;
        opacity: 0.7;
        font-weight: 600 !important;
        font-size: 0.88rem !important;
        padding: 8px 16px !important;
        border-radius: 6px !important;
        border: none !important;
        transition: all 0.2s;
    }
    .stTabs [data-baseweb="tab"]:hover {
        opacity: 1;
    }
    .stTabs [aria-selected="true"] {
        color: #ffffff !important;
        background-color: #d946ef !important; /* Electric Magenta */
        font-weight: 700 !important;
        box-shadow: 0 4px 12px rgba(217, 70, 239, 0.4);
        opacity: 1;
    }

    /* Custom buttons (primary & download) */
    .stButton > button {
        border-radius: 10px !important;
        font-weight: 700 !important;
        font-size: 0.95rem !important;
        letter-spacing: 0.02em !important;
        transition: all 0.25s ease-in-out !important;
    }
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #d946ef 0%, #2563eb 100%) !important; /* Magenta to Blue gradient */
        color: white !important;
        border: none !important;
        box-shadow: 0 4px 15px rgba(217, 70, 239, 0.25) !important;
    }
    .stButton > button[kind="primary"]:hover {
        background: linear-gradient(135deg, #f472b6 0%, #3b82f6 100%) !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 6px 20px rgba(217, 70, 239, 0.4) !important;
    }

    .stDownloadButton > button {
        background-color: #0f172a !important;
        border: 1px solid #d946ef !important;
        color: #f472b6 !important;
        box-shadow: 0 4px 12px rgba(217, 70, 239, 0.15) !important;
    }
    .stDownloadButton > button:hover {
        background-color: #1e1b4b !important;
        color: white !important;
        border-color: #f472b6 !important;
        transform: translateY(-1px) !important;
        box-shadow: 0 6px 18px rgba(217, 70, 239, 0.3) !important;
    }

    /* Expanders & details dropdowns */
    .streamlit-expanderHeader {
        background-color: rgba(18, 20, 38, 0.8) !important;
        border: 1px solid rgba(217, 70, 239, 0.15) !important;
        border-radius: 10px !important;
        font-size: 0.9rem !important;
        font-weight: 600 !important;
        color: #ffffff !important;
        margin-bottom: 0.4rem !important;
    }
    .streamlit-expanderContent {
        border-left: 1px solid rgba(217, 70, 239, 0.15) !important;
        border-right: 1px solid rgba(217, 70, 239, 0.15) !important;
        border-bottom: 1px solid rgba(217, 70, 239, 0.15) !important;
        background-color: #030408 !important;
        padding: 1.25rem !important;
        border-radius: 0 0 10px 10px !important;
    }

    /* Logs view block */
    .log-box {
        font-family: 'JetBrains Mono', monospace !important;
        background-color: #010204 !important;
        border: 1px solid rgba(217, 70, 239, 0.2) !important;
        border-radius: 10px !important;
        padding: 1rem !important;
        height: 250px !important;
        overflow-y: auto !important;
        color: #38bdf8 !important;
        font-size: 0.85rem !important;
        line-height: 1.5 !important;
        box-shadow: inset 0 2px 6px rgba(0, 0, 0, 0.8) !important;
    }

    /* Alert notification boxes */
    div[data-testid="stNotification"] {
        background-color: rgba(18, 20, 38, 0.8) !important;
        border: 1px solid rgba(217, 70, 239, 0.2) !important;
        color: #f1f5f9 !important;
        border-radius: 10px !important;
    }

    /* Custom badges (pills) */
    .qc-error-badge {
        background-color: #7f1d1d !important;
        color: #fca5a5 !important;
        padding: 3px 8px !important;
        border-radius: 12px !important;
        font-size: 0.72rem !important;
        font-weight: 700 !important;
        display: inline-block !important;
    }
    .qc-warn-badge {
        background-color: #78350f !important;
        color: #fde047 !important;
        padding: 3px 8px !important;
        border-radius: 12px !important;
        font-size: 0.72rem !important;
        font-weight: 700 !important;
        display: inline-block !important;
    }
    .qc-pass-badge {
        background-color: #064e3b !important;
        color: #6ee7b7 !important;
        padding: 3px 8px !important;
        border-radius: 12px !important;
        font-size: 0.72rem !important;
        font-weight: 700 !important;
        display: inline-block !important;
    }

    /* QC Validation Checklist Table */
    .qc-table {
        width: 100%;
        border-collapse: separate !important;
        border-spacing: 0 !important;
        background-color: rgba(18, 20, 38, 0.7) !important;
        border: 1px solid rgba(217, 70, 239, 0.25) !important;
        border-radius: 12px !important;
        overflow: hidden !important;
        margin-top: 1rem !important;
        margin-bottom: 2rem !important;
        box-shadow: 0 10px 25px -10px rgba(0, 0, 0, 0.7);
    }
    .qc-table th {
        background-color: rgba(30, 41, 59, 0.9) !important;
        color: #ffffff !important;
        font-weight: 700 !important;
        font-size: 0.85rem !important;
        text-transform: uppercase !important;
        letter-spacing: 0.05em !important;
        padding: 12px 16px !important;
        border-bottom: 1px solid rgba(217, 70, 239, 0.2) !important;
    }
    .qc-table td {
        padding: 12px 16px !important;
        font-size: 0.88rem !important;
        border-bottom: 1px solid rgba(255, 255, 255, 0.05) !important;
        color: #e2e8f0 !important;
    }
    .qc-table tr:last-child td {
        border-bottom: none !important;
    }
    .qc-status-ok {
        background-color: rgba(6, 78, 59, 0.4) !important;
        color: #34d399 !important;
        border: 1px solid rgba(52, 211, 153, 0.3) !important;
        padding: 4px 10px !important;
        border-radius: 6px !important;
        font-weight: 700 !important;
        font-size: 0.75rem !important;
        text-align: center !important;
        display: inline-block !important;
    }
    .qc-status-mismatch {
        background-color: rgba(127, 29, 29, 0.4) !important;
        color: #f87171 !important;
        border: 1px solid rgba(248, 113, 113, 0.3) !important;
        padding: 4px 10px !important;
        border-radius: 6px !important;
        font-weight: 700 !important;
        font-size: 0.75rem !important;
        text-align: center !important;
        display: inline-block !important;
        box-shadow: 0 0 10px rgba(239, 68, 68, 0.1);
    }

    </style>
    """, unsafe_allow_html=True)
