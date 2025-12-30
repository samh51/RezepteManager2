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
GEMINI_API_KEY = "HIER_DEINEN_API_KEY_EINFÜGEN"
SHEET_NAME = "MeineRezepte"

# (Die hardcodierte BASICS_LISTE entfernen wir, da sie jetzt aus der DB kommt)

# --- UI SETUP ---
st.set_page_config(page_title="Chef's Dashboard", page_icon="👨‍🍳", layout="wide")

st.markdown("""
    <style>
    div[data-testid="stMetricValue"] { font-size: 1.8rem; color: #ff4b4b; }
    div.stButton > button { border-radius: 8px; }
    
    .step-card {
        background-color: #f0f2f6;
        padding: 30px;
        border-radius: 15px;
        border-left: 8px solid #ff4b4b;
        font-size: 1.3rem;
        line-height: 1.6;
        margin-bottom: 20px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .full-list-item {
        padding: 10px 0;
        border-bottom: 1px solid #e0e0e0;
        font-size: 1.1rem;
    }
    .step-number {
        font-weight: bold;
        color: #ff4b4b;
        margin-right: 10px;
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
        st.error("⚠️ API Key fehlt im Code!")
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

# --- DATENBANK MANAGEMENT (3 TABS) ---
def get_data():
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        
        # --- ANPASSUNG FÜR CLOUD & LOKAL ---
        # 1. Versuche, Secrets aus der Cloud zu laden
        if "gcp_service_account" in st.secrets:
            creds_dict = st.secrets["gcp_service_account"]
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        # 2. Sonst versuche, die lokale Datei zu laden
        elif os.path.exists("credentials.json"):
            with open("credentials.json", "r") as f:
                creds_dict = json.load(f)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        else:
            st.error("Keine Anmeldedaten gefunden (weder secrets.toml noch credentials.json).")
            return None, None, None, None, None, None
        # -----------------------------------

        client = gspread.authorize(creds)
        
        try: spreadsheet = client.open(SHEET_NAME)
        except gspread.SpreadsheetNotFound:
            st.error(f"Konnte Tabelle '{SHEET_NAME}' nicht finden."); return None, None, None, None, None, None

        # (Der Rest bleibt identisch wie vorher...)
        # 1. ZUTATEN
        try: sheet_zutaten = spreadsheet.worksheet("Zutaten")
        except gspread.WorksheetNotFound:
            sheet_zutaten = spreadsheet.add_worksheet(title="Zutaten", rows=1000, cols=10)
            sheet_zutaten.append_row(["Rezept", "Zutat", "Menge", "Einheit", "Favorit"])
            
        # 2. ANLEITUNGEN
        try: sheet_steps = spreadsheet.worksheet("Anleitungen")
        except gspread.WorksheetNotFound:
            sheet_steps = spreadsheet.add_worksheet(title="Anleitungen", rows=1000, cols=5)
            sheet_steps.append_row(["Rezept", "Schritt_Nr", "Anweisung"])
            
        # 3. BASICS
        try: sheet_basics = spreadsheet.worksheet("Basics")
        except gspread.WorksheetNotFound:
            sheet_basics = spreadsheet.add_worksheet(title="Basics", rows=1000, cols=1)
            sheet_basics.append_row(["Zutat"])
            start_basics = ["Salz", "Pfeffer", "Öl", "Butter", "Milch", "Zucker", "Mehl", "Wasser"]
            for b in start_basics: sheet_basics.append_row([b])
        
        df_zutaten = pd.DataFrame(sheet_zutaten.get_all_records())
        df_steps = pd.DataFrame(sheet_steps.get_all_records())
        
        basics_records = sheet_basics.get_all_records()
        basics_list = [row['Zutat'] for row in basics_records] if basics_records else []
        
        if not df_zutaten.empty:
            if 'Zutat' in df_zutaten.columns: df_zutaten['Zutat'] = df_zutaten['Zutat'].apply(zutat_bereinigen)
            if 'Menge' in df_zutaten.columns: df_zutaten['Menge'] = pd.to_numeric(df_zutaten['Menge'], errors='coerce').fillna(0)
            if 'Favorit' not in df_zutaten.columns: df_zutaten['Favorit'] = ""
            df_zutaten['is_fav'] = df_zutaten['Favorit'].astype(str).str.lower().isin(['true', 'x', 'ja', '1'])
            
        return df_zutaten, df_steps, basics_list, sheet_zutaten, sheet_steps, sheet_basics

    except Exception as e:
        st.error(f"Datenbank-Fehler: {e}")
        return None, None, [], None, None, None

def save_recipe_to_db(data_json, sheet_z, sheet_s):
    rezept_name = data_json["Rezept"]
    rows_zutaten = []
    for z in data_json["Zutaten"]:
        rows_zutaten.append([rezept_name, z["Zutat"], z["Menge"], z["Einheit"], ""])
    
    rows_schritte = []
    for idx, text in enumerate(data_json["Schritte"]):
        rows_schritte.append([rezept_name, idx + 1, text])
        
    sheet_z.append_rows(rows_zutaten)
    sheet_s.append_rows(rows_schritte)

def toggle_favorit(rezept_name, aktueller_status, sheet_obj):
    if not sheet_obj: return False
    try:
        cell = sheet_obj.find(rezept_name)
        if cell:
            header_cell = sheet_obj.find("Favorit")
            if header_cell:
                new_value = "" if aktueller_status else "TRUE"
                sheet_obj.update_cell(cell.row, header_cell.col, new_value)
                return True
    except: pass
    return False

# --- NEU: BASICS VERWALTEN ---
def update_basics(zutat, action, sheet_b):
    """Fügt Basic hinzu oder löscht es"""
    try:
        if action == "add":
            sheet_b.append_row([zutat])
        elif action == "remove":
            cell = sheet_b.find(zutat)
            if cell:
                sheet_b.delete_rows(cell.row)
        return True
    except Exception as e:
        st.error(f"Fehler beim Speichern: {e}")
        return False

# --- UI STATES & CALLBACKS ---
def toggle_view_mode():
    st.session_state.view_full_recipe = not st.session_state.get('view_full_recipe', False)

def go_to_recipe(name):
    st.session_state.selected_recipe = name
    st.session_state.current_step_index = 0
    st.session_state.view_full_recipe = False
    st.session_state.nav_menu = "🍳 Kochen"

# --- APP START ---
if "df_zutaten" not in st.session_state:
    st.session_state.df_zutaten, st.session_state.df_steps, st.session_state.basics_list, st.session_state.sheet_z, st.session_state.sheet_s, st.session_state.sheet_b = get_data()

df_zutaten = st.session_state.df_zutaten
df_steps = st.session_state.df_steps
basics_list = st.session_state.basics_list
sheet_z = st.session_state.sheet_z
sheet_s = st.session_state.sheet_s
sheet_b = st.session_state.sheet_b

# --- SIDEBAR ---
with st.sidebar:
    st.title("👨‍🍳 Chef's Menu")
    menu = st.radio("", ["🏠 Dashboard", "🛒 Einkaufsliste", "🍳 Kochen", "🧺 Kühlschrank-Check", "➕ Neues Rezept"], index=0, key="nav_menu")
    st.divider()
    if st.button("🔄 Datenbank aktualisieren", use_container_width=True):
        st.session_state.df_zutaten, st.session_state.df_steps, st.session_state.basics_list, st.session_state.sheet_z, st.session_state.sheet_s, st.session_state.sheet_b = get_data()
        st.toast("Aktualisiert!", icon="✅"); time.sleep(1); st.rerun()

# --- INHALT ---
if menu == "🏠 Dashboard":
    st.title("Willkommen zurück!")
    if df_zutaten is not None and not df_zutaten.empty:
        favoriten = df_zutaten[df_zutaten['is_fav'] == True]['Rezept'].unique()
        if len(favoriten) > 0:
            st.subheader("❤️ Deine Favoriten")
            cols = st.columns(3)
            for i, fav in enumerate(favoriten):
                with cols[i % 3]:
                    with st.container(border=True):
                        st.markdown(f"**{fav}**")
                        st.button("Kochen", key=f"fav_{i}", on_click=go_to_recipe, args=(fav,))
            st.divider()
            
        st.subheader("🎲 Vorschläge")
        all_rezepte = list(df_zutaten['Rezept'].unique())
        non_favs = [r for r in all_rezepte if r not in favoriten]
        pool = non_favs if len(non_favs) >= 3 else all_rezepte
        c1, c2, c3 = st.columns(3)
        for i, col in enumerate([c1, c2, c3]):
            if i < len(pool):
                r = pool[i] if len(pool) < 4 else random.choice(pool)
                with col:
                    with st.container(border=True):
                        st.markdown(f"**{r}**")
                        st.button("Ansehen", key=f"rand_{i}", on_click=go_to_recipe, args=(r,))

elif menu == "🛒 Einkaufsliste":
    st.title("🛒 Einkaufsliste")
    if df_zutaten is not None and not df_zutaten.empty:
        c1, c2 = st.columns([1, 2])
        with c1: auswahl = st.multiselect("Gerichte:", sorted(df_zutaten['Rezept'].unique()))
        with c2:
            if auswahl:
                with st.container(border=True):
                    sub = df_zutaten[df_zutaten['Rezept'].isin(auswahl)]
                    einkauf = sub.groupby(['Zutat', 'Einheit'])['Menge'].sum().reset_index()
                    for _, row in einkauf.iterrows():
                        m = str(row['Menge']).replace(".0", "") if row['Menge'] > 0 else ""
                        st.markdown(f"☐ **{m} {row['Einheit']}** {row['Zutat']}")
            else: st.info("Wähle Gerichte aus.")

elif menu == "🍳 Kochen":
    if df_zutaten is not None and not df_zutaten.empty:
        rezepte_liste = sorted(df_zutaten['Rezept'].unique())
        
        idx = 0
        if "selected_recipe" in st.session_state and st.session_state.selected_recipe in rezepte_liste:
             idx = rezepte_liste.index(st.session_state.selected_recipe)
        
        rezept_wahl = st.selectbox("Rezept wählen:", rezepte_liste, index=idx)
        
        if "last_recipe" not in st.session_state or st.session_state.last_recipe != rezept_wahl:
            st.session_state.last_recipe = rezept_wahl
            st.session_state.current_step_index = 0
            st.session_state.view_full_recipe = False

        sub_zutaten = df_zutaten[df_zutaten['Rezept'] == rezept_wahl]
        sub_steps = df_steps[df_steps['Rezept'] == rezept_wahl]
        
        if not sub_steps.empty and 'Schritt_Nr' in sub_steps.columns:
            steps_list = sub_steps.sort_values('Schritt_Nr')['Anweisung'].tolist()
        else:
            steps_list = ["Keine Anleitung gefunden."]

        is_current_fav = sub_zutaten['is_fav'].iloc[0] if 'is_fav' in sub_zutaten.columns else False
        c_h1, c_h2 = st.columns([4, 1])
        with c_h1: st.title(rezept_wahl)
        with c_h2:
            if st.button("❤️ Fav" if is_current_fav else "🤍 Fav", type="primary" if is_current_fav else "secondary", use_container_width=True):
                toggle_favorit(rezept_wahl, is_current_fav, sheet_z)
                st.session_state.df_zutaten, _, _, _, _, _ = get_data() # Reload all
                st.rerun()

        st.divider()

        col_ingredients, col_steps = st.columns([1, 2])
        
        with col_ingredients:
            st.subheader("Zutaten")
            with st.container(border=True):
                for _, row in sub_zutaten.iterrows():
                    m = str(row['Menge']).replace(".0", "")
                    st.markdown(f"**{m} {row['Einheit']}** {row['Zutat']}")

        with col_steps:
            c_s1, c_s2 = st.columns([2, 1])
            with c_s1: st.subheader("Anleitung")
            with c_s2: 
                label = "👣 Schritt-für-Schritt" if st.session_state.get('view_full_recipe', False) else "📜 Alle Schritte"
                st.button(label, on_click=toggle_view_mode, use_container_width=True)

            if st.session_state.get('view_full_recipe', False):
                with st.container(border=True):
                    for i, step in enumerate(steps_list):
                        st.markdown(f"""<div class="full-list-item"><span class="step-number">{i+1}.</span> {step}</div>""", unsafe_allow_html=True)
            else:
                total_steps = len(steps_list)
                current_idx = st.session_state.get('current_step_index', 0)
                progress = (current_idx + 1) / total_steps
                st.progress(progress)
                st.caption(f"Schritt {current_idx + 1} von {total_steps}")
                st.markdown(f"""<div class="step-card">{steps_list[current_idx]}</div>""", unsafe_allow_html=True)
                b_prev, b_next = st.columns(2)
                with b_prev:
                    if st.button("⬅️ Zurück", disabled=(current_idx == 0), use_container_width=True):
                        st.session_state.current_step_index -= 1
                        st.rerun()
                with b_next:
                    if current_idx < total_steps - 1:
                        if st.button("Weiter ➡️", type="primary", use_container_width=True):
                            st.session_state.current_step_index += 1
                            st.rerun()
                    else:
                        if st.button("✅ Fertig!", type="primary", use_container_width=True):
                            st.balloons(); st.success("Guten Appetit!")

elif menu == "🧺 Kühlschrank-Check":
    st.title("🧐 Was kann ich kochen?")
    
    if df_zutaten is not None and not df_zutaten.empty:
        
        # --- NEUE FUNKTION: BASICS VERWALTEN ---
        with st.expander("⚙️ Basics (Standard-Vorrat) verwalten"):
            c_add, c_rem = st.columns(2)
            
            # Alle bekannten Zutaten
            all_known = sorted(df_zutaten['Zutat'].unique())
            # Basics
            current_basics = sorted(basics_list)
            # Mögliche neue Basics (alles was noch kein Basic ist)
            potential_basics = [i for i in all_known if i not in current_basics]
            
            with c_add:
                new_basic = st.selectbox("Zu Basics hinzufügen:", ["Wählen..."] + potential_basics)
                if st.button("➕ Hinzufügen") and new_basic != "Wählen...":
                    if update_basics(new_basic, "add", sheet_b):
                        st.toast(f"{new_basic} ist jetzt ein Basic!", icon="🧂")
                        # State Reload
                        st.session_state.df_zutaten, _, st.session_state.basics_list, _, _, _ = get_data()
                        time.sleep(1); st.rerun()
            
            with c_rem:
                del_basic = st.selectbox("Aus Basics entfernen:", ["Wählen..."] + current_basics)
                if st.button("➖ Entfernen") and del_basic != "Wählen...":
                    if update_basics(del_basic, "remove", sheet_b):
                        st.toast(f"{del_basic} entfernt!", icon="🗑️")
                        st.session_state.df_zutaten, _, st.session_state.basics_list, _, _, _ = get_data()
                        time.sleep(1); st.rerun()
        
        st.divider()

        # --- NORMALE SUCHE ---
        with st.form("bestand_form"):
            all_ing = sorted(df_zutaten['Zutat'].unique())
            # Hier nutzen wir jetzt die dynamische Liste aus der DB!
            basics = [i for i in all_ing if i in basics_list]
            others = [i for i in all_ing if i not in basics_list]
            sel = []

            with st.expander("🧂 Standard-Vorrat (Automatisch markiert)", expanded=False):
                cols = st.columns(3)
                for i, ing in enumerate(basics):
                    with cols[i%3]: 
                        if st.checkbox(ing, key=f"b_{i}", value=True): sel.append(ing)

            st.markdown("### 🥦 Frisches & Sonstiges")
            with st.container(height=400, border=True):
                cols = st.columns(3)
                for i, ing in enumerate(others):
                    with cols[i%3]: 
                        if st.checkbox(ing, key=f"c_{i}"): sel.append(ing)
            
            if st.form_submit_button("🔍 Suchen", type="primary"):
                st.divider()
                if not sel: st.warning("Wähle Zutaten.")
                else:
                    found = False
                    for r in df_zutaten['Rezept'].unique():
                        req = set(df_zutaten[df_zutaten['Rezept']==r]['Zutat'])
                        have = set(sel)
                        match = len(req & have)
                        if match > 0:
                            found = True
                            with st.expander(f"{r} ({match}/{len(req)})"):
                                st.button("Rezept öffnen", key=f"stock_{r}", on_click=go_to_recipe, args=(r,))
                    if not found: st.warning("Nichts gefunden.")

elif menu == "➕ Neues Rezept":
    st.title("✨ Rezept Import")
    t1, t2 = st.tabs(["YouTube", "Text"])
    
    def process_import(content, is_file):
        with st.spinner("Analysiere..."):
            data = rezept_analysieren(content, is_file)
            if is_file and os.path.exists(content): os.remove(content)
            
            if data and sheet_z and sheet_s:
                save_recipe_to_db(data, sheet_z, sheet_s)
                st.toast("Gespeichert!", icon="✅")
                time.sleep(2)
                st.session_state.df_zutaten, st.session_state.df_steps, _, _, _, _ = get_data() 
                st.rerun()
    
    with t1:
        u = st.text_input("Link:")
        if st.button("Video Import", type="primary") and u:
            c = get_youtube_content(u)
            if c: process_import(c, "YOUTUBE_TRANSCRIPT:" not in c)
    with t2:
        t = st.text_area("Text:")
        if st.button("Text Import", type="primary") and t:
            process_import(t, False)