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

# API Key laden
if "GEMINI_API_KEY" in st.secrets:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
else:
    GEMINI_API_KEY = "HIER_DEINEN_API_KEY_EINFÜGEN"

# --- UI SETUP ---
st.set_page_config(page_title="Chef's App", page_icon="🍳", layout="wide")

# --- MOBILE CSS (Nur Größen & Abstände, KEINE Farben!) ---
st.markdown("""
    <style>
    /* 1. Große Buttons für Touch */
    div.stButton > button {
        min-height: 3.5rem;
        font-size: 1.1rem;
        border-radius: 12px;
        font-weight: 600;
        margin-bottom: 8px;
        width: 100%; /* Immer volle Breite auf Mobile */
    }
    
    /* 2. Checkboxen besser treffbar machen */
    label[data-testid="stCheckbox"] {
        padding-top: 12px;
        padding-bottom: 12px;
        font-size: 1.05rem;
    }
    
    /* 3. Metriken */
    div[data-testid="stMetricValue"] {
        font-size: 1.8rem;
    }
    
    /* 4. Tabs etwas größer */
    button[data-baseweb="tab"] {
        font-size: 1.1rem;
        padding: 10px;
    }
    
    /* 5. Sidebar auf Mobile anpassen */
    section[data-testid="stSidebar"] {
        padding-top: 1rem;
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
    return name

def get_video_id(url):
    try:
        if "shorts/" in url: return url.split("shorts/")[1].split("?")[0]
        elif "v=" in url: return url.split("v=")[1].split("&")[0]
        elif "youtu.be/" in url: return url.split("youtu.be/")[1].split("?")[0]
    except: return None

def get_youtube_content(url):
    vid_id = get_video_id(url)
    if not vid_id: return "ERROR: Keine gültige YouTube-ID gefunden."
    
    # 1. VERSUCH: Untertitel (Transcript) - Schnell & Sicher
    try:
        transcript = YouTubeTranscriptApi.get_transcript(vid_id, languages=['de', 'en', 'en-US', 'de-DE'])
        text = " ".join([t['text'] for t in transcript])
        return f"YOUTUBE_TEXT: {text}"
    except: pass
    
    # 2. VERSUCH: Nur Metadaten (Beschreibung) - Falls Download blockiert wird
    try:
        ydl_opts_meta = {'quiet': True, 'noplaylist': True}
        with yt_dlp.YoutubeDL(ydl_opts_meta) as ydl:
            info = ydl.extract_info(url, download=False) # Nur Infos holen, nicht downloaden
            desc = info.get('description', '')
            title = info.get('title', '')
            # Wenn Beschreibung lang genug ist, nutzen wir die!
            if len(desc) > 50:
                return f"YOUTUBE_TEXT: Titel: {title}\nBeschreibung: {desc}"
    except: pass

    # 3. VERSUCH: Audio Download (Der "Heavy" Weg) - Scheitert oft in der Cloud
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f'temp_{vid_id}.%(ext)s',
            'quiet': True, 
            'noplaylist': True, 
            'socket_timeout': 10
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return ydl.prepare_filename(info)
    except Exception as e:
        return f"ERROR: YouTube blockiert den Zugriff. Fehler: {str(e)}"

def rezept_analysieren(content, is_file=False):
    if not GEMINI_API_KEY or "HIER" in GEMINI_API_KEY:
        st.error("⚠️ API Key fehlt!"); return None
    
    # Fehler abfangen
    if isinstance(content, str) and content.startswith("ERROR:"):
        st.error(content.replace("ERROR:", "❌")); return None

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-flash-latest') 
    
    prompt = """
    Du bist ein Koch-Übersetzer. Analysiere das Rezept.
    Ergebnis MUSS auf DEUTSCH sein.
    
    Quelle kann ein Transkript, eine Videobeschreibung oder eine Audiodatei sein.
    Versuche Zutaten und Schritte logisch zu extrahieren.
    
    Antworte NUR mit reinem JSON:
    {
      "Rezept": "Name",
      "Zutaten": [{"Zutat": "Name", "Menge": zahl, "Einheit": "g/ml/Stk"}],
      "Schritte": ["Schritt 1...", "Schritt 2..."]
    }
    """
    try:
        if is_file and os.path.exists(content):
            # Fall: Echte Audio-Datei (selten in Cloud)
            myfile = genai.upload_file(content)
            while myfile.state.name == "PROCESSING": time.sleep(1); myfile = genai.get_file(myfile.name)
            response = model.generate_content([prompt, myfile])
        else:
            # Fall: Text (Transcript oder Beschreibung)
            response = model.generate_content(f"{prompt}\n\nInput:\n{content}")
            
        return json.loads(response.text.replace("```json", "").replace("```", "").strip())
    except Exception as e:
        st.error(f"KI Fehler: {e}"); return None
# --- DATENBANK ---
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

# --- SIDEBAR ---
with st.sidebar:
    st.header("Menü")
    # Einfaches Menü für Mobile
    menu = st.radio("Nav", ["🏠 Start", "🛒 Einkauf", "🍳 Kochen", "🧺 Bestand", "➕ Neu"], index=0, key="nav_menu", label_visibility="collapsed")
    st.divider()
    if st.button("🔄 Sync"):
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
                # Wir nutzen native Container, die passen sich Hell/Dunkel automatisch an
                with st.container(border=True):
                    st.markdown(f"### {fav}")
                    st.button(f"Kochen", key=f"f_{fav}", on_click=go_to_recipe, args=(fav,), type="primary", use_container_width=True)
        
        st.divider()
        st.subheader("🎲 Vorschlag")
        all_r = list(df_z['Rezept'].unique())
        others = [r for r in all_r if r not in favs]
        pool = others if len(others) >= 3 else all_r
        
        for i in range(min(2, len(pool))):
            r = random.choice(pool)
            with st.container(border=True):
                st.markdown(f"**{r}**")
                st.button("Ansehen", key=f"rnd_{i}", on_click=go_to_recipe, args=(r,), use_container_width=True)

elif menu == "🛒 Einkauf":
    st.title("🛒 Einkaufsliste")
    if df_z is not None and not df_z.empty:
        auswahl = st.multiselect("Gerichte wählen:", sorted(df_z['Rezept'].unique()))
        if auswahl:
            st.divider()
            sub = df_z[df_z['Rezept'].isin(auswahl)]
            einkauf = sub.groupby(['Zutat', 'Einheit'])['Menge'].sum().reset_index()
            with st.container(border=True):
                for _, row in einkauf.iterrows():
                    m = str(row['Menge']).replace(".0", "") if row['Menge'] > 0 else ""
                    st.checkbox(f"**{m} {row['Einheit']}** {row['Zutat']}")
        else: st.info("Wähle oben Rezepte aus.")

elif menu == "🍳 Kochen":
    if df_z is not None and not df_z.empty:
        all_r = sorted(df_z['Rezept'].unique())
        idx = 0
        if "selected_recipe" in st.session_state and st.session_state.selected_recipe in all_r:
             idx = all_r.index(st.session_state.selected_recipe)
        rezept = st.selectbox("Rezept:", all_r, index=idx)
        
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

        t1, t2 = st.tabs(["Zutaten", "Anleitung"])
        with t1:
            with st.container(border=True):
                for _, row in sub_z.iterrows():
                    m = str(row['Menge']).replace(".0", "")
                    st.markdown(f"**{m} {row['Einheit']}** {row['Zutat']}")

        with t2:
            lbl = "📜 Liste" if not st.session_state.get('view_full_recipe') else "👣 Schritte"
            st.button(lbl, on_click=toggle_view_mode, use_container_width=True)
            st.divider()
            
            if st.session_state.get('view_full_recipe'):
                for i, s in enumerate(steps):
                    with st.container(border=True):
                        st.markdown(f"**{i+1}.** {s}")
            else:
                curr = st.session_state.get('current_step_index', 0)
                tot = len(steps)
                st.progress((curr + 1) / tot)
                st.caption(f"Schritt {curr + 1} von {tot}")
                
                # Große Step-Card (Native)
                with st.container(border=True):
                    st.markdown(f"#### {steps[curr]}")
                
                c_b, c_n = st.columns(2)
                with c_b:
                    if st.button("⬅️", disabled=(curr==0), use_container_width=True):
                        st.session_state.current_step_index -= 1
                        st.rerun()
                with c_n:
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
        with st.expander("⚙️ Basics"):
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
            with st.expander("🧂 Basics", expanded=False):
                cols = st.columns(2)
                for i, b in enumerate(my_b):
                    with cols[i%2]: 
                        if st.checkbox(b, value=True, key=f"b_{i}"): sel.append(b)
            st.markdown("### 🥦 Frisches")
            with st.container(height=300, border=True):
                cols = st.columns(2) 
                for i, f in enumerate(fresh):
                    with cols[i%2]:
                        if st.checkbox(f, key=f"f_{i}"): sel.append(f)
            
            if st.form_submit_button("🔍 Suchen", type="primary", use_container_width=True):
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
    st.info("💡 Tipp: YouTube-Import funktioniert am besten mit Videos, die Untertitel haben.")
    t1, t2 = st.tabs(["YouTube", "Text"])
    
    def run_import(c, is_f):
        if isinstance(c, str) and c.startswith("ERROR:"): st.error(c.replace("ERROR:", "❌")); return
        with st.spinner("⏳ Analysiere..."):
            d = rezept_analysieren(c, is_f)
            if is_f and isinstance(c, str) and os.path.exists(c): os.remove(c)
            if d:
                save_recipe_to_db(d, sh_z, sh_s); st.balloons(); st.toast("Gespeichert!", icon="✅"); time.sleep(2)
                st.session_state.df_zutaten, _, _, _, _, _ = get_data(); st.rerun()

    with t1:
        u = st.text_input("YouTube Link:")
        if st.button("Video Importieren 🚀", type="primary", use_container_width=True):
            if u:
                with st.status("Lade Video...", expanded=True) as s:
                    c = get_youtube_content(u)
                    if c and not c.startswith("ERROR:"): s.write("✅ Gefunden!"); run_import(c, "YOUTUBE_TRANSCRIPT:" not in c)
                    else: s.update(label="Fehler", state="error"); st.error(c if c else "Fehler")
            else: st.warning("Bitte Link eingeben.")
    with t2:
        txt = st.text_area("Rezept Text:", height=200)
        if st.button("Text Importieren 📝", type="primary", use_container_width=True):
            if txt: run_import(txt, False)
            else: st.warning("Bitte Text eingeben.")
