import streamlit as st
import pandas as pd
import openai
import re

# 1. Configuratie
st.set_page_config(page_title="Politie Toets Trainer Q3", layout="wide")

if 'score' not in st.session_state:
    st.session_state.score = 0
    st.session_state.totaal = 0
    st.session_state.vragen_teller = 0

# 2. Data Laden & Koppelen
@st.cache_data
def load_combined_data():
    # Inladen leerdoelen.csv
    df = pd.read_csv('leerdoelen.csv', sep=';')
    df.columns = df.columns.str.strip()
    
    md_data = []
    # Regex voor JurKad.md patronen
    pattern = r"(.+?)\s+Artikel:\s+([\d:.]+)\s+→\s+\[.*?\]\((.*?)\)"
    try:
        with open('JurKad.md', 'r', encoding='utf-8') as f:
            for line in f:
                match = re.search(pattern, line)
                if match:
                    wet_md, art_md, url = match.groups()
                    md_data.append({
                        'wet_k': wet_md.strip().lower(), 
                        'art_k': art_md.strip().lower(), 
                        'url': url
                    })
    except FileNotFoundError:
        st.error("Bestand 'JurKad.md' niet gevonden.")
    
    df_links = pd.DataFrame(md_data)

    def get_url(row):
        # Pak artikelnummer uit kolom 'Artikel' (bijv. "artikel 3" -> "3")
        art_raw = str(row['Artikel']).lower()
        art_match = re.search(r"(\d+[:.]?\d*)", art_raw)
        if not art_match: 
            return f"https://wetten.overheid.nl/zoeken?Zoektekst={row['Wet']}"
        
        clean_art = art_match.group(1)
        wet_val = str(row['Wet']).lower()
        
        # Match op artikelnummer en wetnaam
        match = df_links[df_links['art_k'] == clean_art]
        for _, l_row in match.iterrows():
            if l_row['wet_k'] in wet_val or wet_val in l_row['wet_k']:
                return l_row['url']
        return f"https://wetten.overheid.nl/zoeken?Zoektekst={row['Wet']}"

    df['artikel_url'] = df.apply(get_url, axis=1)
    return df

df = load_combined_data()
alle_wetten = sorted(df['Wet'].dropna().unique().tolist())

# 3. API & Sidebar
api_key = st.secrets.get("OPENAI_API_KEY")
with st.sidebar:
    if not api_key: 
        api_key = st.text_input("OpenAI API Key", type="password")
    
    gekozen_wetten = st.multiselect("Filter op wet", options=["Allemaal"] + alle_wetten, default=["Allemaal"])
    aantal_doel = st.number_input("Totaal vragen", value=25)
    
    if st.button("Reset Score"):
        st.session_state.score, st.session_state.totaal, st.session_state.vragen_teller = 0, 0, 0
        st.rerun()

if not api_key: 
    st.stop()

openai.api_key = api_key

# 4. Helper functies
def genereer_vraag():
    filtered_df = df if "Allemaal" in gekozen_wetten or not gekozen_wetten else df[df['Wet'].isin(gekozen_wetten)]
    vraag_data = filtered_df.sample(n=1).iloc[0]
    st.session_state.current_row = vraag_data
    
    prompt = f"""
    Genereer exact ÉÉN examenvraag voor een student van de Politieacademie op **mbo-4 niveau**.

    Gebruik uitsluitend deze invoer:
    - Wet: {vraag_data['Wet']}
    - Artikel: {vraag_data['Artikel']}
    - Leerdoel: {vraag_data['Leerdoel']}

    Opdracht:
    Formuleer één duidelijke, juridisch correcte en ondubbelzinnige vraag die direct aansluit op het leerdoel en op de inhoud en strekking van het genoemde artikel.

    Strikte regels:
    1. Stel exact **één** vraag.
    2. Gebruik **geen** deelvragen.
    3. Gebruik **geen** verdiepingsvraag, toelichtingsvraag of vervolg zoals: "waarom", "licht toe", "verklaar".
    4. Toets één centrale denkhandeling (beschrijven, benoemen, uitleggen, herkennen, toepassen).
    5. Passend bij mbo-4: helder en concreet.
    6. Geen dubbelzinnigheid of samengestelde vragen.
    7. Directe aansluiting op het genoemde artikel.
    8. Geen inleiding of casus ("Stel je voor...").
    9. Alleen de vraag als output.
    """
    
    res = openai.chat.completions.create(
        model="gpt-4o-mini", 
        messages=[{"role": "user", "content": prompt}]
    )
    st.session_state.vraag_tekst = res.choices[0].message.content
    st.session_state.beoordeeld = False
    st.session_state.feedback = None

# 5. UI Layout
st.title("🚓 Politie Toets Trainer")
c1, c2, c3 = st.columns(3)
c1.metric("Vraag", f"{st.session_state.vragen_teller} / {aantal_doel}")
c2.metric("Goed", st.session_state.score)
perc = (st.session_state.score / st.session_state.totaal * 100) if st.session_state.totaal > 0 else 0
c3.metric("Score", f"{round(perc, 1)}%")

# Vraag weergave logica
if 'vraag_tekst' not in st.session_state:
    if st.button("Start / Volgende"):
        genereer_vraag()
        st.rerun()
else:
    row = st.session_state.current_row
    st.info(f"📚 **Bron:** [{row['Wet']} - {row['Artikel']}]({row['artikel_url']})")
    st.subheader(st.session_state.vraag_tekst)
    ans = st.text_area("Antwoord:", key=f"ans_{st.session_state.vragen_teller}")

    if not st.session_state.beoordeeld:
        if st.button("Check"):
            check_p = f"""
            Beoordeel het antwoord voor een Politieacademie examen (mbo-4).
            Vraag: {st.session_state.vraag_tekst}
            Antwoord student: {ans}
            Wet/Artikel: {row['Wet']} {row['Artikel']}
            Leerdoel: {row['Leerdoel']}

            Outputregels:
            - Regel 1: Alleen GOED of FOUT.
            - Regel 2: Korte, zakelijke toelichting (max 2 zinnen).
            - Regel 3: Wat ontbreekt of wat is juist aanwezig.
            Beoordeel redelijk op de juridische kern.
            """
            
            res = openai.chat.completions.create(
                model="gpt-4o-mini", 
                messages=[{"role": "user", "content": check_p}]
            )
            st.session_state.feedback = res.choices[0].message.content
            st.session_state.beoordeeld = True
            st.session_state.totaal += 1
            if "GOED" in st.session_state.feedback.upper()[:10]: 
                st.session_state.score += 1
            st.rerun()

    if st.session_state.beoordeeld:
        st.markdown("---")
        st.write(st.session_state.feedback)
        if st.button("Volgende vraag"):
            st.session_state.vragen_teller += 1
            del st.session_state.vraag_tekst
            st.rerun()
