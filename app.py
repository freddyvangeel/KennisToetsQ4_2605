import streamlit as st
import pandas as pd
import openai
import re

# 1. Configuratie
st.set_page_config(page_title="Politie Toets Trainer Q3", layout="wide")

if 'score' not in st.session_state:
    st.session_state.score = 0
if 'totaal' not in st.session_state:
    st.session_state.totaal = 0
if 'vragen_teller' not in st.session_state:
    st.session_state.vragen_teller = 0
if 'beoordeeld' not in st.session_state:
    st.session_state.beoordeeld = False
if 'feedback' not in st.session_state:
    st.session_state.feedback = None

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
        st.session_state.score = 0
        st.session_state.totaal = 0
        st.session_state.vragen_teller = 0
        st.session_state.beoordeeld = False
        st.session_state.feedback = None
        if 'vraag_tekst' in st.session_state:
            del st.session_state.vraag_tekst
        if 'current_row' in st.session_state:
            del st.session_state.current_row
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
Genereer exact ÉÉN examenvraag voor een student van de Politieacademie op mbo-4 niveau.

Gebruik uitsluitend deze invoer:
- Wet: {vraag_data['Wet']}
- Artikel: {vraag_data['Artikel']}
- Leerdoel: {vraag_data['Leerdoel']}

Opdracht:
Formuleer één duidelijke, juridisch correcte en ondubbelzinnige vraag die direct aansluit op het leerdoel en op de inhoud en strekking van het genoemde artikel.

Strikte regels:
1. Stel exact één vraag.
2. Gebruik geen deelvragen.
3. Gebruik geen verdiepingsvraag, toelichtingsvraag of vervolg zoals:
   - "waarom"
   - "licht toe"
   - "verklaar"
   - "beargumenteer"
   - "wat vind je"
4. De vraag moet één centrale denkhandeling toetsen, passend bij het leerdoel, bijvoorbeeld:
   - beschrijven
   - benoemen
   - uitleggen
   - herkennen
   - toepassen
   Kies alleen de denkhandeling die logisch volgt uit het leerdoel.
5. De vraag moet passen bij mbo-4 niveau:
   - helder en concreet taalgebruik
   - geen onnodig ingewikkelde formuleringen
   - wel vakinhoudelijk correct
6. De vraag mag niet dubbelzinnig zijn:
   - slechts één redelijke interpretatie mogelijk
   - geen samengestelde vraag
   - geen verborgen tweede opdracht
7. De vraag moet direct aansluiten op het genoemde artikel en mag niet afdwalen naar andere artikelen of brede algemene leerstof.
8. Gebruik geen inleiding, casus, fictieve situatie of openingszin zoals:
   - "Stel je voor"
   - "Je bent"
   - "In een situatie waarin"
9. Formuleer de vraag zo dat het juiste antwoord direct aansluit op het leerdoel.
10. Geef alleen de vraag als output. Dus:
   - geen antwoordmodel
   - geen toelichting
   - geen motivatie
   - geen opsomming
   - geen aanhalingstekens

Controleer vóór output:
- Toetst de vraag precies het leerdoel?
- Bevat de vraag echt maar één opdracht?
- Is de vraag voor één uitleg vatbaar?
- Past de formulering bij mbo-4 niveau?

Geef daarna alleen de definitieve vraag.
"""
    
    res = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    st.session_state.vraag_tekst = res.choices[0].message.content.strip()
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
Beoordeel het antwoord van een student op een examenvraag van de Politieacademie.

Gegevens:
- Vraag: {st.session_state.vraag_tekst}
- Antwoord student: {ans}
- Wet: {row['Wet']}
- Artikel: {row['Artikel']}
- Leerdoel: {row['Leerdoel']}

Beoordelingsopdracht:
Beoordeel uitsluitend of het antwoord inhoudelijk past bij het leerdoel en bij de juridische kern van het genoemde artikel.

Beoordelingsrichtlijn:
1. Start ALTIJD met exact één van deze woorden:
   GOED
   FOUT

2. Beoordeel op de juridische kern en niet op nette formulering of exacte wetswoorden.
3. Beoordeel redelijk:
   - Is de kern juridisch juist en passend bij het leerdoel, dan is het GOED.
   - Ontbreekt de kern, is deze juridisch onjuist, of past het antwoord niet bij het leerdoel, dan is het FOUT.
4. Gebruik alleen het opgegeven artikel en leerdoel als beoordelingskader.
5. Straf niet af op kleine taal- of formulatiefouten, zolang de inhoud duidelijk juist is.
6. Straf wel af als:
   - een verkeerd juridisch begrip wordt gebruikt
   - de strekking van het artikel onjuist wordt weergegeven
   - het antwoord te vaag is om te laten zien dat het leerdoel is behaald
7. Houd rekening met mbo-4 niveau:
   - correct in inhoud
   - niet onnodig streng op academische formulering

Outputregels:
- Regel 1: alleen GOED of FOUT
- Regel 2: een korte, zakelijke toelichting van maximaal 2 zinnen
- Regel 3: noem heel kort wat in het antwoord juist ontbreekt of juist aanwezig is

Geef geen cijfers, geen uitgebreide feedback, geen wetsartikelen uitschrijven en geen extra uitleg buiten dit format.
"""
            
            res = openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": check_p}]
            )
            st.session_state.feedback = res.choices[0].message.content.strip()
            st.session_state.beoordeeld = True
            st.session_state.totaal += 1
            if st.session_state.feedback.upper().startswith("GOED"):
                st.session_state.score += 1
            st.rerun()

    if st.session_state.beoordeeld:
        st.markdown("---")
        st.write(st.session_state.feedback)
        if st.button("Volgende vraag"):
            st.session_state.vragen_teller += 1
            st.session_state.beoordeeld = False
            st.session_state.feedback = None
            del st.session_state.vraag_tekst
            st.rerun()
