import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import json
import os
import google.generativeai as genai
from youtube_transcript_api import YouTubeTranscriptApi
import yt_dlp
import time
import random

# --- KONFIGURATION (CLOUD & LOKAL) ---
SHEET_NAME = "MeineRezepte"

if "GEMINI_API_KEY" in st.secrets:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
else:
    GEMINI_API_KEY = "HIER_DEINEN_API_KEY_EINFÜGEN"

# --- UI SETUP ---
st.set_page_config(page_title="Chef's App", page_icon="🍳", layout="wide")

# --- THEME LOGIC (VERBESSERT) ---
if "theme" not in st.session_state:
    st.session_state.theme = "light"

# Farb-Palette definieren (High Contrast)
if st.session_state.theme == "dark":
    bg_color = "#0e1117"        # Tiefes Schwarz/Grau
    card_bg = "#1e2127"         # Karten etwas heller als Hintergrund
    text_color = "#fafafa"      # Fast Weiß (besser lesbar als reines Weiß)
    border_color = "#30333d"    # Dunkle Ränder
    input_bg = "#262730"        # Hintergrund für Eingabefelder
    shadow = "rgba(0,0,0,0.5)"
    accent_color = "#ff4b4b"
else:
    bg_color = "#ffffff"        # Reines Weiß
    card_bg = "#f0f2f6"         # Leichtes Grau für Karten (besserer Kontrast zu Weiß)
    text_color = "#111111"      # Fast Schwarz
    border_color = "#d5d7de"    # Helle Ränder
    input_bg = "#ffffff"        # Hintergrund für Eingabefelder
    shadow = "rgba(0,0,0,0.1)"
    accent_color = "#ff4b4b"

# --- CSS INJECTION (KONTRAST FIX) ---
st.markdown(f"""
    <style>
    /* 1. GRUNDGERÜST */
    .stApp {{
        background-color: {bg_color};
        color: {text_color};
    }}
    
    /* Text global erzwingen */
    p, h1, h2, h3, h4, h5, h6, li, span, div, label {{
        color: {text_color} !important;
    }}

    /* 2. BUTTONS */
    div.stButton > button {{
        min-height: 3.5rem;
        font-size: 1.1rem;
        border-radius: 12px;
        font-weight: 600;
        margin-bottom: 10px;
        background-color: {card_bg};
        color: {text_color};
        border: 1px solid {border_color};
    }}
    div.stButton > button:hover {{
        border-color: {accent_color};
        color: {accent_color} !important;
    }}
    
    /* Primary Buttons hervorheben */
    div.stButton > button[kind="primary"] {{
        background-color: {accent_color};
        color: white !important;
        border: none;
    }}

    /* 3. INPUTS & SELECTBOXEN (Wichtig für Kontrast!) */
    /* Eingabefelder Hintergrund & Text */
    .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] {{
        background-color: {input_bg} !important;
        color: {text_color} !important;
        border-color: {border_color};
    }}
    /* Dropdown-Menü Optionen */
    ul[data-baseweb="menu"] {{
        background-color: {card_bg} !important;
    }}
    
    /* 4. CHECKBOXEN & LABELS */
    label[data-testid="stCheckbox"] {{
        padding-top: 10px;
        padding-bottom: 10px;
        font-size: 1.1rem;
    }}
    
    /* 5. MOBILE KARTEN */
    .mobile-card {{
        background-color: {card_bg};
        padding: 20px;
        border-radius: 15px;
        box-shadow: 0 4px 10px {shadow};
        margin-bottom: 15px;
        border: 1px solid {border_color};
    }}
    
    /* Text in Karten explizit färben */
    .mobile-card h3, .mobile-card p, .mobile-card div {{
        color: {text_color} !important;
    }}
    
    /* 6. STEP HIGHLIGHT (Aktueller Schritt) */
    .step-highlight {{
        border-left: 6px solid {accent_color};
        background-color: {input_bg}; /* Nutzt Input-BG für Kontrast */
        padding: 15px;
        border-radius: 10px;
    }}

    /* 7. EXPANDER (Aufklapp-Boxen) */
    .streamlit-expanderHeader {{
        background-color: {card_bg} !important;
        color: {text_color} !important;
        border-radius: 8px;
    }}
    .streamlit-expanderContent {{
        background-color: {bg_color} !important;
        color: {text_color} !important;
        border: 1px solid {border_color};
        border-top: none;
    }}
    
    /* 8. METRIKEN (Immer Rot) */
    div[data-testid="stMetricValue"] div {{
        color: {accent_color} !important;
    }}
    
    /* Sidebar Anpassung */
    section[data-testid="stSidebar"] {{
        background-color: {card_bg};
        border-right: 1px solid {border_color};
    }}
    </style>
""", unsafe_allow_html=True)

# --- HELFER FUNKTIONEN ---
def zutat_bereinigen(name):
    if not isinstance(name, str): return str(name)
    suche = name.lower().strip()
    if "garlic" in suche or "knoblauch" in suche: return "Knoblauch"
    if "onion" in suche or "zwiebel" in suche or "schalotte" in suche: return "Zwiebel"
    if "salt" in suche or "salz" in suche: return "Salz"
    if "pepper" in suche or "pfeffer" in suche: return "Pfeffer"
    if "oil" in suche or "öl" in suche: return "Öl"
    if "ginger" in suche or "ingwer" in suche: return "Ingwer"
    if "sugar" in suche or "zucker" in suche: return "Zucker"
    if "flour" in suche or "mehl" in suche: return "Mehl"
    if "butter" in suche: return "Butter"
    if "cheese" in suche or "käse" in suche or "parmesan" in suche: return "Käse"
    if "egg" in suche or "eier" in suche: return "Ei"
    if "lemon" in suche or "zitrone" in suche: return "Zitrone"
    if "milk" in suche or "milch" in suche: return "Milch"
    if "water" in suche or "wasser" in suche: return "Wasser"
    
    name = name.capitalize()
    mapping = {
        "Eier": "Ei", "Tomaten": "Tomate", "Kartoffeln": "Kartoffel", 
        "Karotten": "Karotte", "Möhren": "Karotte", "Äpfel": "Apfel", 
        "Paprikas": "Paprika", "Gurken": "Gurke", "Dosen": "Dose", 
        "Packungen": "Packung"
    }
    return mapping.get(name, name)

def get_video_id(url):
    try:
        if "shorts/" in url: return url.split("shorts/")[1].split("?")[0]
        elif "v=" in url: return url.split("v=")[1].split("&")[0]
        elif "youtu.be/" in url: return url.split("youtu.be/")[1].split("?")[0]
    except: return None

def get_youtube_content(url):
    vid_id = get_video_id(url)
    if not vid_id: return None
    try:
        transcript = YouTubeTranscriptApi.get_transcript(vid_id, languages=['de', 'en'])
        return f"YOUTUBE_TRANSCRIPT: {' '.join([t['text'] for t in transcript])}"
    except: pass 
    try:
        ydl_opts = {'format': 'bestaudio[ext=m4a]/bestaudio/best', 'outtmpl': f'temp_{vid_id}.%(ext)s', 'quiet': True, 'noplaylist': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info)
    except: return None

def rezept_analysieren(content, is_file=False):
    if not GEMINI_API_KEY or "HIER" in GEMINI_API_KEY:
        st.error("⚠️ API Key fehlt!")
        return None

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-flash-latest') 
    
    prompt = """
    Du bist ein Koch-Übersetzer. Analysiere das Rezept.
    Ergebnis MUSS auf DEUTSCH sein.
    1. Extrahiere Zutaten (Singular, standardisierte Einheiten).
    2. Extrahiere die Anleitung als LISTE von einzelnen Schritten.
    Antworte NUR mit reinem JSON in diesem Format:
    {
      "Rezept": "Name des Gerichts",
      "Zutaten": [{"Zutat": "Name", "Menge": zahl, "Einheit": "g/ml/Stk"}],
      "Schritte": ["Schritt 1...", "Schritt 2..."]
    }
    """
    try:
        if is_file and os.path.exists(content):
            myfile = genai.upload_file(content)
            while myfile.state.name == "PROCESSING": time.sleep(1); myfile = genai.get_file(myfile.name)
            response = model.generate_content([prompt, myfile])
        else:
            response = model.generate_content(f"{prompt}\n\nInput:\n{content}")
        return json.loads(response.text.replace("```json", "").replace("```", "").strip())
    except Exception as e:
        st.error(f"KI Fehler: {e}"); return None

# --- DATENBANK MANAGEMENT ---
def get_data():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        if "gcp_service_account" in st.secrets:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
        elif os.path.exists("credentials.json"):
            with open("credentials.json", "r") as f: creds = ServiceAccountCredentials.from_json_keyfile_dict(json.load(f), scope)
        else: return None, None, None, None, None, None

        client = gspread.authorize(creds)
        try: spreadsheet = client.open(SHEET_NAME)
        except gspread.SpreadsheetNotFound: st.error(f"Tabelle '{SHEET_NAME}' fehlt!"); return None, None, None, None, None, None

        def get_or_create(title, cols, head):
            try: return spreadsheet.worksheet(title)
            except: ws = spreadsheet.add_worksheet(title, 1000, cols); ws.append_row(head); return ws

        sh_z = get_or_create("Zutaten", 10, ["Rezept", "Zutat", "Menge", "Einheit", "Favorit"])
        sh_s = get_or_create("Anleitungen", 5, ["Rezept", "Schritt_Nr", "Anweisung"])
        sh_b = get_or_create("Basics", 2, ["Zutat"])
        
        if len(sh_b.get_all_values()) <= 1:
             for b in ["Salz", "Pfeffer", "Öl", "Butter", "Milch", "Zucker", "Mehl", "Wasser"]: sh_b.append_row([b])

        df_z = pd.DataFrame(sh_z.get_all_records())
        df_s = pd.DataFrame(sh_s.get_all_records())
        basics = [row['Zutat'] for row in sh_b.get_all_records()]

        if not df_z.empty:
            if 'Zutat' in df_z.columns: df_z['Zutat'] = df_z['Zutat'].apply(zutat_bereinigen)
            if 'Menge' in df_z.columns: df_z['Menge']
