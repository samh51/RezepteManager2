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

# API Key sicher laden
if "GEMINI_API_KEY" in st.secrets:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
else:
    GEMINI_API_KEY = "HIER_DEINEN_API_KEY_EINFÜGEN" # Fallback für lokal

# --- UI SETUP & MOBILE CSS ---
st.set_page_config(page_title="Chef's App", page_icon="🍳", layout="wide")

# Hier passiert die Magie für das Handy-Design
st.markdown("""
    <style>
    /* 1. BUTTONS: Größer, höher, runder */
    div.stButton > button {
        min-height: 3.5rem;       /* Höhere Buttons */
        font-size: 1.1rem;        /* Größere Schrift */
        border-radius: 12px;      /* Abgerundete Ecken */
        font-weight: 600;
        margin-bottom: 10px;
    }
    
    /* 2. CHECKBOXEN: Mehr Abstand für Wurstfinger ;) */
    label[data-testid="stCheckbox"] {
        padding-top: 10px;
        padding-bottom: 10px;
        font-size: 1.1rem;
    }
    
    /* 3. KARTEN-DESIGN für Schritte & Rezepte */
    .mobile-card {
        background-color: #ffffff;
        padding: 20px;
        border-radius: 15px;
        box-shadow: 0 4px 10px rgba(0,0,0,0.05);
        margin-bottom: 15px;
        border: 1px solid #e0e0e0;
    }
    
    .step-highlight {
        border-left: 6px solid #ff4b4b;
        background-color: #fff0f0;
    }

    /* 4. Metriken größer */
    div[data-testid="stMetricValue"] {
        font-size: 2rem;
    }
    
    /* 5. Navigation etwas aufräumen */
    section[data-testid="stSidebar"] {
        padding-top: 2rem;
    }
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
      "Zutaten": [
        {"Zutat": "Name", "Menge": zahl, "Einheit": "g/ml/Stk"}
      ],
      "Schritte": [
        "Schritt 1 Text...",
        "Schritt 2 Text...",
        "Schritt 3 Text..."
      ]
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
        st.error(f"KI Fehler: {e}")
        return None

# --- DATENBANK MANAGEMENT ---
def get_data():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        
        # Cloud vs Lokal Switch
        if "gcp_service_account" in st.secrets:
            creds = ServiceAccountCredentials.from_json_keyfile_dict(st.secrets["gcp_service_account"], scope)
        elif os.path.exists("credentials.json"):
            with open("credentials.json", "r") as f: creds = ServiceAccountCredentials.from_json_keyfile_dict(json.load(f), scope)
        else:
            st.error("Login fehlgeschlagen."); return None, None, None, None, None, None

        client = gspread.authorize(creds)
        try: spreadsheet = client.open(SHEET_NAME)
        except gspread.SpreadsheetNotFound: st.error(f"Tabelle '{SHEET_NAME}' fehlt!"); return None, None, None, None, None, None

        # Tabs laden/erstellen
        def get_or_create(title, cols, head):
            try: return spreadsheet.worksheet(title)
            except: 
                ws = spreadsheet.add_worksheet(title, 1000, cols)
                ws.append_row(head)
                return ws

        sheet_zutaten = get_or_create("Zutaten", 10, ["Rezept", "Zutat", "Menge", "Einheit", "Favorit"])
        sheet_steps = get_or_create("Anleitungen", 5, ["Rezept", "Schritt_Nr", "Anweisung"])
        sheet_basics = get_or_create("Basics", 2, ["Zutat"])
        
        # Init Basics falls leer
        if len(sheet_basics.get_all_values()) <= 1:
             for b in ["Salz", "Pfeffer", "Öl", "Butter", "Milch", "Zucker", "Mehl", "Wasser"]: sheet_basics.append_row([b])

        df_zutaten = pd.DataFrame(sheet_zutaten.get_all_records())
        df_steps = pd.DataFrame(sheet_steps.get_all_records())
        basics_list = [row['Zutat'] for row in sheet_basics.get_all_records()]

        if not df_zutaten.empty:
            if 'Zutat' in df_zutaten.columns: df_zutaten['Zutat'] = df_zutaten['Zutat'].apply(zutat_bereinigen)
            if 'Menge' in df_zutaten.columns: df_zutaten['Menge'] = pd.to_numeric(df_zutaten['Menge'], errors='coerce').fillna(0)
            if 'Favorit' not in df_zutaten.columns: df_zutaten['Favorit'] = ""
            df_zutaten['is_fav'] = df_zutaten['Favorit'].astype(str).str.lower().isin(['true', 'x', 'ja', '1'])
            
        return df_zutaten, df_steps, basics_list, sheet_zutaten, sheet_steps, sheet_basics
    except Exception as e:
        st.error(f"DB Fehler: {e}"); return None, None, [], None, None, None

def save_recipe_to_db(data_json, sheet_z, sheet_s):
    name = data_json["Rezept"]
    sheet_z.append_rows([[name, z["Zutat"], z["Menge"], z["Einheit"], ""] for z in data_json["Zutaten"]])
    sheet_s.append_rows([[name, i+1, t] for i, t in enumerate(data_json["Schritte"])])

def toggle_favorit(rezept_name, aktueller_status, sheet_obj):
    try:
        cell = sheet_obj.find(rezept_name)
        if cell:
            h = sheet_obj.find("Favorit")
            if h: sheet_obj.update_cell(cell.row, h.col, "" if aktueller_status else "TRUE"); return True
    except: pass
    return False

def update_basics(zutat, action, sheet_b):
    try:
        if action == "add": sheet_b.append_row([zutat])
        elif action == "remove": 
            c = sheet_b.find(zutat)
            if c: sheet_b.delete_rows(c.row)
        return True
    except: return False

# --- CALLBACKS ---
def go_to_recipe(name):
    st.session_state.selected_recipe = name
    st.session_state.current_step_index = 0
    st.session_state.view_full_recipe = False
    st.session_state.nav_menu = "🍳 Kochen"

def toggle_view_mode(): st.session_state.view_full_recipe = not st.session_state.get('view_full_recipe', False)

# --- APP LOAD ---
if "df_zutaten" not in st.session_state:
    st.session_state.df_zutaten, st.session_state.df_steps, st.session_state.basics_list, st.session_state.sheet_z, st.session_state.sheet_s, st.session_state.sheet_b = get_data()

df_z = st.session_state.df_zutaten
df_s = st.session_state.df_steps
basics = st.session_state.basics_list
sh_z = st.session_state.sheet_z
sh_s = st.session_state.sheet_s
sh_b = st.session_state.sheet_b

# --- SIDEBAR (Mobile Friendly) ---
with st.sidebar:
    st.title("🍳 Menü")
    # Einfachere Labels für Mobile
    menu = st.radio("", ["🏠 Start", "🛒 Einkauf", "🍳 Kochen", "🧺 Bestand", "➕ Neu"], index=0, key="nav_menu")
    st.divider()
    if st.button("🔄 Sync", use_container_width=True):
        st.session_state.df_zutaten, st.session_state.df_steps, st.session_state.basics_list, st.session_state.sheet_z, st.session_state.sheet_s, st.session_state.sheet_b = get_data()
        st.rerun()

# --- CONTENT ---
if menu == "🏠 Start":
    st.title("Moin Chef! 👋")
    if df_z is not None and not df_z.empty:
        favs = df_z[df_z['is_fav'] == True]['Rezept'].unique()
        
        # 1. FAVORITEN (Große Karten)
        if len(favs) > 0:
            st.subheader("❤️ Favoriten")
            # Auf Handy lieber untereinander statt nebeneinander
            for fav in favs:
                st.markdown(f"""<div class="mobile-card"><h3>{fav}</h3></div>""", unsafe_allow_html=True)
                st.button(f"Kochen: {fav}", key=f"f_{fav}", on_click=go_to_recipe, args=(fav,), use_container_width=True)
        
        st.divider()
        
        # 2. VORSCHLÄGE (Zufall)
        st.subheader("🎲 Vorschlag")
        all_r = list(df_z['Rezept'].unique())
        others = [r for r in all_r if r not in favs]
        pool = others if len(others) >= 3 else all_r
        
        # Zeige 2 Vorschläge
        for i in range(min(2, len(pool))):
            r = random.choice(pool)
            st.markdown(f"""<div class="mobile-card" style="border-left: 5px solid #4b88ff;"><h3>{r}</h3></div>""", unsafe_allow_html=True)
            st.button("Ansehen", key=f"rnd_{i}", on_click=go_to_recipe, args=(r,), use_container_width=True)

elif menu == "🛒 Einkauf":
    st.title("🛒 Einkaufsliste")
    if df_z is not None and not df_z.empty:
        # Auf Mobile: Auswahl oben, Liste unten (volle Breite)
        auswahl = st.multiselect("Was willst du kochen?", sorted(df_z['Rezept'].unique()))
        
        if auswahl:
            st.divider()
            sub = df_z[df_z['Rezept'].isin(auswahl)]
            einkauf = sub.groupby(['Zutat', 'Einheit'])['Menge'].sum().reset_index()
            
            with st.container(border=True):
                for _, row in einkauf.iterrows():
                    m = str(row['Menge']).replace(".0", "") if row['Menge'] > 0 else ""
                    # Große Checkboxen durch CSS
                    st.checkbox(f"**{m} {row['Einheit']}** {row['Zutat']}")
            
            st.caption("Tipp: Screenshot machen! 📸")
        else:
            st.info("Wähle oben Rezepte aus.")

elif menu == "🍳 Kochen":
    if df_z is not None and not df_z.empty:
        all_r = sorted(df_z['Rezept'].unique())
        
        # Logic to handle selection state
        idx = 0
        if "selected_recipe" in st.session_state and st.session_state.selected_recipe in all_r:
             idx = all_r.index(st.session_state.selected_recipe)
        
        rezept = st.selectbox("Rezept wählen:", all_r, index=idx)
        
        # Reset Logic
        if "last_recipe" not in st.session_state or st.session_state.last_recipe != rezept:
            st.session_state.last_recipe = rezept
            st.session_state.current_step_index = 0
            st.session_state.view_full_recipe = False

        # Data Loading
        sub_z = df_z[df_z['Rezept'] == rezept]
        sub_s = df_s[df_s['Rezept'] == rezept]
        steps = sub_s.sort_values('Schritt_Nr')['Anweisung'].tolist() if not sub_s.empty else ["Keine Anleitung."]
        is_fav = sub_z['is_fav'].iloc[0] if not sub_z.empty else False

        # Header Area
        c1, c2 = st.columns([3, 1])
        with c1: st.header(rezept)
        with c2: 
            if st.button("❤️" if is_fav else "🤍", type="primary" if is_fav else "secondary", use_container_width=True):
                toggle_favorit(rezept, is_fav, sh_z)
                st.session_state.df_zutaten, _, _, _, _, _ = get_data()
                st.rerun()

        # Tabs statt Spalten auf Mobile (spart Platz)
        tab_zutaten, tab_anleitung = st.tabs(["🥕 Zutaten", "👨‍🍳 Anleitung"])
        
        with tab_zutaten:
            with st.container(border=True):
                for _, row in sub_z.iterrows():
                    m = str(row['Menge']).replace(".0", "")
                    st.markdown(f"**{m} {row['Einheit']}** {row['Zutat']}")

        with tab_anleitung:
            # View Toggle
            mode_label = "📜 Liste anzeigen" if not st.session_state.get('view_full_recipe') else "👣 Schritt-Modus"
            st.button(mode_label, on_click=toggle_view_mode, use_container_width=True)
            
            if st.session_state.get('view_full_recipe'):
                # LIST VIEW
                for i, s in enumerate(steps):
                    st.markdown(f"""<div class="mobile-card"><b style="color:#ff4b4b">{i+1}.</b> {s}</div>""", unsafe_allow_html=True)
            else:
                # WIZARD VIEW
                curr = st.session_state.get('current_step_index', 0)
                tot = len(steps)
                st.progress((curr + 1) / tot)
                st.caption(f"Schritt {curr + 1}/{tot}")
                
                # Big Step Card
                st.markdown(f"""<div class="mobile-card step-highlight" style="font-size: 1.4rem;">{steps[curr]}</div>""", unsafe_allow_html=True)
                
                # Big Nav Buttons
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
        # Basics Management
        with st.expander("⚙️ Basics anpassen"):
            all_known = sorted(df_z['Zutat'].unique())
            curr_b = sorted(basics)
            pot_b = [i for i in all_known if i not in curr_b]
            
            c1, c2 = st.columns(2)
            with c1:
                nb = st.selectbox("Neu:", ["-"] + pot_b)
                if st.button("Hinzufügen", use_container_width=True) and nb != "-":
                    update_basics(nb, "add", sh_b)
                    st.session_state.df_zutaten, _, st.session_state.basics_list, _, _, _ = get_data()
                    st.rerun()
            with c2:
                db = st.selectbox("Löschen:", ["-"] + curr_b)
                if st.button("Entfernen", use_container_width=True) and db != "-":
                    update_basics(db, "remove", sh_b)
                    st.session_state.df_zutaten, _, st.session_state.basics_list, _, _, _ = get_data()
                    st.rerun()

        st.divider()

        # Selection Form
        with st.form("stock_check"):
            all_ing = sorted(df_z['Zutat'].unique())
            my_basics = [i for i in all_ing if i in basics]
            fresh = [i for i in all_ing if i not in basics]
            sel = []

            # Basics collapsible
            with st.expander("🧂 Basics (Vorausgewählt)", expanded=False):
                # 2 Spalten auf Mobile besser als 3
                cols = st.columns(2)
                for i, b in enumerate(my_basics):
                    with cols[i%2]:
                        if st.checkbox(b, value=True, key=f"b_{i}"): sel.append(b)

            st.markdown("### 🥦 Frisches")
            # Scroll container
            with st.container(height=400, border=True):
                cols = st.columns(2) 
                for i, f in enumerate(fresh):
                    with cols[i%2]:
                        if st.checkbox(f, key=f"f_{i}"): sel.append(f)
            
            # Big Submit Button
            if st.form_submit_button("🔍 Was kann ich kochen?", type="primary", use_container_width=True):
                st.divider()
                found = False
                for r in df_z['Rezept'].unique():
                    req = set(df_z[df_z['Rezept']==r]['Zutat'])
                    have = set(sel)
                    match = len(req & have)
                    
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
                save_recipe_to_db(d, sh_z, sh_s)
                st.toast("Gespeichert!", icon="✅")
                time.sleep(2)
                st.session_state.df_zutaten, _, _, _, _, _ = get_data()
                st.rerun()

    with t1:
        u = st.text_input("YouTube Link:")
        if st.button("Start Import", type="primary", use_container_width=True) and u:
            c = get_youtube_content(u)
            if c: run_import(c, "YOUTUBE_TRANSCRIPT:" not in c)
            
    with t2:
        txt = st.text_area("Rezept Text:", height=200)
        if st.button("Text Importieren", type="primary", use_container_width=True) and txt:
            run_import(txt, False)
