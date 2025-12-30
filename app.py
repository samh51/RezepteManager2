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

# --- KONFIGURATION ---
SHEET_NAME = "MeineRezepte"

if "GEMINI_API_KEY" in st.secrets:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
else:
    GEMINI_API_KEY = "HIER_DEINEN_API_KEY_EINFÜGEN"

# --- UI SETUP ---
st.set_page_config(page_title="Chef's App", page_icon="🍳", layout="wide")

# --- THEME LOGIC (KORRIGIERT) ---
if "theme" not in st.session_state:
    st.session_state.theme = "light"

# Farb-Palette definieren
if st.session_state.theme == "dark":
    # --- DARK MODE ---
    bg_color = "#0e1117"
    text_color = "#fafafa"
    
    card_bg = "#1e2127"
    input_bg = "#262730"
    border_color = "#30333d"
    
    shadow = "rgba(0,0,0,0.5)"
    accent_color = "#ff4b4b"
    step_highlight_bg = "#2d2323"
else:
    # --- LIGHT MODE (FIX) ---
    bg_color = "#ffffff"        # Reines Weiß für Hintergrund
    text_color = "#31333F"      # Dunkelgrau für Text (Standard Streamlit)
    
    card_bg = "#f9f9f9"         # Ganz leichtes Grau für Karten
    input_bg = "#ffffff"        # Weiß für Inputs
    border_color = "#d5d7de"    # Sichtbarer grauer Rand
    
    shadow = "rgba(0,0,0,0.05)"
    accent_color = "#ff4b4b"
    step_highlight_bg = "#fff5f5" # Ganz helles Rot

# --- CSS INJECTION ---
st.markdown(f"""
    <style>
    /* 1. Globaler Reset */
    .stApp {{
        background-color: {bg_color};
    }}
    
    h1, h2, h3, h4, h5, h6, p, li, span, div, label {{
        color: {text_color} !important;
    }}

    /* 2. Buttons */
    div.stButton > button {{
        min-height: 3.5rem;
        font-size: 1.1rem;
        border-radius: 12px;
        font-weight: 600;
        margin-bottom: 10px;
        background-color: {card_bg};
        color: {text_color} !important;
        border: 1px solid {border_color};
    }}
    
    /* Primary Button Text muss immer weiß sein */
    div.stButton > button[kind="primary"] {{
        background-color: {accent_color} !important;
        border: none;
    }}
    div.stButton > button[kind="primary"] * {{
        color: #ffffff !important;
    }}

    /* 3. Inputs & Selectboxen (Der Kontrast-Killer) */
    .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] {{
        background-color: {input_bg} !important;
        color: {text_color} !important;
        border-color: {border_color};
    }}
    
    /* Dropdown-Liste (Popup) */
    ul[data-baseweb="menu"] {{
        background-color: {input_bg} !important;
    }}
    ul[data-baseweb="menu"] li span {{
        color: {text_color} !important;
    }}
    
    /* 4. Checkboxen */
    label[data-testid="stCheckbox"] {{
        color: {text_color} !important;
        padding: 10px 0;
    }}

    /* 5. Mobile Karten */
    .mobile-card {{
        background-color: {card_bg};
        padding: 20px;
        border-radius: 15px;
        box-shadow: 0 4px 6px {shadow};
        margin-bottom: 15px;
        border: 1px solid {border_color};
    }}
    
    .mobile-card h3, .mobile-card p, .mobile-card b {{
        color: {text_color} !important;
    }}
    
    /* 6. Step Highlight */
    .step-highlight {{
        border-left: 6px solid {accent_color};
        background-color: {step_highlight_bg};
        padding: 15px;
        border-radius: 10px;
        border: 1px solid {border_color};
    }}

    /* 7. Expander */
    .streamlit-expanderHeader {{
        background-color: {card_bg} !important;
        color: {text_color} !important;
        border-radius: 8px;
        border: 1px solid {border_color};
    }}
    .streamlit-expanderContent {{
        background-color: {bg_color} !important;
        border-left: 1px solid {border_color};
        border-right: 1px solid {border_color};
        border-bottom: 1px solid {border_color};
        color: {text_color} !important;
    }}
    
    /* 8. Metriken & Sidebar */
    div[data-testid="stMetricValue"] div {{
        color: {accent_color} !important;
    }}
    section[data-testid="stSidebar"] {{
        background-color: {card_bg};
        border-right: 1px solid {border_color};
    }}
    
    /* Tabs */
    button[data-baseweb="tab"] {{
        background-color: transparent !important;
    }}
    div[data-baseweb="tab-highlight"] {{
        background-color: {accent_color} !important;
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
            if 'Menge' in df_z.columns: df_z['Menge'] = pd.to_numeric(df_z['Menge'], errors='coerce').fillna(0)
            if 'Favorit' not in df_z.columns: df_z['Favorit'] = ""
            df_z['is_fav'] = df_z['Favorit'].astype(str).str.lower().isin(['true', 'x', 'ja', '1'])
            
        return df_z, df_s, basics, sh_z, sh_s, sh_b
    except Exception as e: st.error(f"DB Fehler: {e}"); return None, None, [], None, None, None

def save_recipe_to_db(data, sh_z, sh_s):
    name = data["Rezept"]
    sh_z.append_rows([[name, z["Zutat"], z["Menge"], z["Einheit"], ""] for z in data["Zutaten"]])
    sh_s.append_rows([[name, i+1, t] for i, t in enumerate(data["Schritte"])])

def toggle_favorit(name, status, sh):
    try:
        c = sh.find(name)
        if c: h = sh.find("Favorit"); sh.update_cell(c.row, h.col, "" if status else "TRUE"); return True
    except: return False

def update_basics(z, action, sh):
    try:
        if action == "add": sh.append_row([z])
        elif action == "remove": 
            c = sh.find(z); 
            if c: sh.delete_rows(c.row)
        return True
    except: return False

def toggle_view_mode(): st.session_state.view_full_recipe = not st.session_state.get('view_full_recipe', False)
def go_to_recipe(name):
    st.session_state.selected_recipe = name
    st.session_state.current_step_index = 0
    st.session_state.view_full_recipe = False
    st.session_state.nav_menu = "🍳 Kochen"

# --- APP LOAD ---
if "df_zutaten" not in st.session_state:
    st.session_state.df_zutaten, st.session_state.df_steps, st.session_state.basics_list, st.session_state.sheet_z, st.session_state.sheet_s, st.session_state.sheet_b = get_data()

df_z = st.session_state.df_zutaten
df_s = st.session_state.df_steps
basics = st.session_state.basics_list
sh_z = st.session_state.sheet_z
sh_s = st.session_state.sheet_s
sh_b = st.session_state.sheet_b

# --- SIDEBAR & THEME TOGGLE ---
with st.sidebar:
    st.title("🍳 Menü")
    
    is_dark = st.session_state.theme == "dark"
    dark_mode = st.toggle("🌙 Dark Mode", value=is_dark)
    
    if dark_mode and not is_dark:
        st.session_state.theme = "dark"
        st.rerun()
    elif not dark_mode and is_dark:
        st.session_state.theme = "light"
        st.rerun()
    
    st.divider()
    menu = st.radio("Navigation", ["🏠 Start", "🛒 Einkauf", "🍳 Kochen", "🧺 Bestand", "➕ Neu"], index=0, key="nav_menu", label_visibility="collapsed")
    st.divider()
    if st.button("🔄 Sync", use_container_width=True):
        st.session_state.df_zutaten, st.session_state.df_steps, st.session_state.basics_list, st.session_state.sheet_z, st.session_state.sheet_s, st.session_state.sheet_b = get_data()
        st.rerun()

# --- CONTENT ---
if menu == "🏠 Start":
    st.title("Moin Chef! 👋")
    if df_z is not None and not df_z.empty:
        favs = df_z[df_z['is_fav'] == True]['Rezept'].unique()
        if len(favs) > 0:
            st.subheader("❤️ Favoriten")
            for fav in favs:
                st.markdown(f"""<div class="mobile-card"><h3>{fav}</h3></div>""", unsafe_allow_html=True)
                st.button(f"Kochen: {fav}", key=f"f_{fav}", on_click=go_to_recipe, args=(fav,), use_container_width=True)
        
        st.divider()
        st.subheader("🎲 Vorschlag")
        all_r = list(df_z['Rezept'].unique())
        others = [r for r in all_r if r not in favs]
        pool = others if len(others) >= 3 else all_r
        for i in range(min(2, len(pool))):
            r = random.choice(pool)
            st.markdown(f"""<div class="mobile-card" style="border-left: 5px solid #4b88ff;"><h3>{r}</h3></div>""", unsafe_allow_html=True)
            st.button("Ansehen", key=f"rnd_{i}", on_click=go_to_recipe, args=(r,), use_container_width=True)

elif menu == "🛒 Einkauf":
    st.title("🛒 Einkaufsliste")
    if df_z is not None and not df_z.empty:
        auswahl = st.multiselect("Was willst du kochen?", sorted(df_z['Rezept'].unique()))
        if auswahl:
            st.divider()
            sub = df_z[df_z['Rezept'].isin(auswahl)]
            einkauf = sub.groupby(['Zutat', 'Einheit'])['Menge'].sum().reset_index()
            with st.container(border=True):
                for _, row in einkauf.iterrows():
                    m = str(row['Menge']).replace(".0", "") if row['Menge'] > 0 else ""
                    st.checkbox(f"**{m} {row['Einheit']}** {row['Zutat']}")
            st.caption("Tipp: Screenshot machen! 📸")
        else: st.info("Wähle oben Rezepte aus.")

elif menu == "🍳 Kochen":
    if df_z is not None and not df_z.empty:
        all_r = sorted(df_z['Rezept'].unique())
        idx = 0
        if "selected_recipe" in st.session_state and st.session_state.selected_recipe in all_r:
             idx = all_r.index(st.session_state.selected_recipe)
        rezept = st.selectbox("Rezept wählen:", all_r, index=idx)
        
        if "last_recipe" not in st.session_state or st.session_state.last_recipe != rezept:
            st.session_state.last_recipe = rezept
            st.session_state.current_step_index = 0
            st.session_state.view_full_recipe = False

        sub_z = df_z[df_z['Rezept'] == rezept]
        sub_s = df_s[df_s['Rezept'] == rezept]
        steps = sub_s.sort_values('Schritt_Nr')['Anweisung'].tolist() if not sub_s.empty else ["Keine Anleitung."]
        is_fav = sub_z['is_fav'].iloc[0] if not sub_z.empty else False

        c1, c2 = st.columns([3, 1])
        with c1: st.header(rezept)
        with c2: 
            if st.button("❤️" if is_fav else "🤍", type="primary" if is_fav else "secondary", use_container_width=True):
                toggle_favorit(rezept, is_fav, sh_z)
                st.session_state.df_zutaten, _, _, _, _, _ = get_data()
                st.rerun()

        tab_zutaten, tab_anleitung = st.tabs(["🥕 Zutaten", "👨‍🍳 Anleitung"])
        
        with tab_zutaten:
            with st.container(border=True):
                for _, row in sub_z.iterrows():
                    m = str(row['Menge']).replace(".0", "")
                    st.markdown(f"**{m} {row['Einheit']}** {row['Zutat']}")

        with tab_anleitung:
            mode_label = "📜 Liste anzeigen" if not st.session_state.get('view_full_recipe') else "👣 Schritt-Modus"
            st.button(mode_label, on_click=toggle_view_mode, use_container_width=True)
            
            if st.session_state.get('view_full_recipe'):
                for i, s in enumerate(steps):
                    st.markdown(f"""<div class="mobile-card"><b style="color:#ff4b4b">{i+1}.</b> {s}</div>""", unsafe_allow_html=True)
            else:
                curr = st.session_state.get('current_step_index', 0)
                tot = len(steps)
                st.progress((curr + 1) / tot)
                st.caption(f"Schritt {curr + 1}/{tot}")
                st.markdown(f"""<div class="mobile-card step-highlight" style="font-size: 1.4rem;">{steps[curr]}</div>""", unsafe_allow_html=True)
                c_back, c_next = st.columns(2)
                with c_back:
                    if st.button("⬅️", disabled=(curr==0), use_container_width=True):
                        st.session_state.current_step_index -= 1
                        st.rerun()
                with c_next:
                    if curr < tot - 1:
                        if st.button("➡️", type="primary", use_container_width=True):
                            st.session_state.current_step_index += 1
                            st.rerun()
                    else:
                        if st.button("✅ Fertig", type="primary", use_container_width=True):
                            st.balloons(); st.success("Guten Appetit!")

elif menu == "🧺 Bestand":
    st.title("🧐 Kühlschrank")
    if df_z is not None:
        with st.expander("⚙️ Basics anpassen"):
            all_k = sorted(df_z['Zutat'].unique()); curr_b = sorted(basics); pot_b = [i for i in all_k if i not in curr_b]
            c1, c2 = st.columns(2)
            with c1:
                nb = st.selectbox("Neu:", ["-"] + pot_b)
                if st.button("Add", use_container_width=True) and nb != "-":
                    update_basics(nb, "add", sh_b); st.session_state.df_zutaten, _, st.session_state.basics_list, _, _, _ = get_data(); st.rerun()
            with c2:
                db = st.selectbox("Weg:", ["-"] + curr_b)
                if st.button("Del", use_container_width=True) and db != "-":
                    update_basics(db, "remove", sh_b); st.session_state.df_zutaten, _, st.session_state.basics_list, _, _, _ = get_data(); st.rerun()

        st.divider()
        with st.form("stock_check"):
            all_i = sorted(df_z['Zutat'].unique()); my_b = [i for i in all_i if i in basics]; fresh = [i for i in all_i if i not in basics]; sel = []
            with st.expander("🧂 Basics (Vorausgewählt)", expanded=False):
                cols = st.columns(2)
                for i, b in enumerate(my_b):
                    with cols[i%2]: 
                        if st.checkbox(b, value=True, key=f"b_{i}"): sel.append(b)
            st.markdown("### 🥦 Frisches")
            with st.container(height=400, border=True):
                cols = st.columns(2) 
                for i, f in enumerate(fresh):
                    with cols[i%2]:
                        if st.checkbox(f, key=f"f_{i}"): sel.append(f)
            
            if st.form_submit_button("🔍 Was kann ich kochen?", type="primary", use_container_width=True):
                st.divider()
                found = False
                for r in df_z['Rezept'].unique():
                    req = set(df_z[df_z['Rezept']==r]['Zutat']); have = set(sel); match = len(req & have)
                    if match > 0:
                        found = True
                        with st.expander(f"{r} ({match}/{len(req)})"):
                            st.button(f"Zum Rezept: {r}", key=f"s_{r}", on_click=go_to_recipe, args=(r,), use_container_width=True)
                if not found: st.warning("Nichts gefunden.")

elif menu == "➕ Neu":
    st.title("✨ Import")
    t1, t2 = st.tabs(["YouTube", "Text"])
    def run_import(c, is_f):
        with st.spinner("⏳ Analysiere..."):
            d = rezept_analysieren(c, is_f)
            if is_f and os.path.exists(c): os.remove(c)
            if d:
                save_recipe_to_db(d, sh_z, sh_s); st.toast("Gespeichert!", icon="✅"); time.sleep(2)
                st.session_state.df_zutaten, _, _, _, _, _ = get_data(); st.rerun()
    with t1:
        u = st.text_input("YouTube Link:")
        if st.button("Start Import", type="primary", use_container_width=True) and u:
            c = get_youtube_content(u); 
            if c: run_import(c, "YOUTUBE_TRANSCRIPT:" not in c)
    with t2:
        txt = st.text_area("Rezept Text:", height=200)
        if st.button("Text Importieren", type="primary", use_container_width=True) and txt: run_import(txt, False)
