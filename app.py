import streamlit as st
import pandas as pd
import openai
import re

# 1. Configuratie
st.set_page_config(page_title="Politie Toets Trainer Q3", layout="wide")

# 2. Sessie variabelen
if 'score' not in st.session_state:
    st.session_state.score = 0
    st.session_state.totaal = 0
    st.session_state.vragen_teller = 0

# 3. Data Laden & Koppelen
@st.cache_data
def load_combined_data():
    # Laad de CSV
    df = pd.read_csv('geanalyseerde_leerdoelen Q3 kennistoets.csv', sep=';')
    
    # MD Parser voor de links
    md_data = []
    pattern = r"(.+?)\s+Artikel:\s+([\d:.]+)\s+→\s+\[.*?\]\((.*?)\)"
    
    try:
        with open('JurKad.md', 'r', encoding='utf-8') as f:
            for line in f:
                match = re.search(pattern, line)
                if match:
                    wet_md, art_md, url = match.groups()
                    md_data.append({
                        'wet_key': wet_md.strip().lower(),
                        'art_key': art_md.strip().lower(),
                        'url': url
                    })
    except FileNotFoundError:
        st.error("Markdown bestand niet gevonden.")
        
    df_links = pd.DataFrame(md_data)

    # Functie om de juiste URL te vinden bij een rij uit de CSV
    def get_url(row):
        art_val = str(row['Artikel']).lower()
        wet_val = str(row['Wet']).lower()
        # Zoek match op artikelnummer
        potential = df_links[df_links['art_key'].apply(lambda x: x in art_val or art_val in x)]
        for _, l_row in potential.iterrows():
            if l_row['wet_key'] in wet_val or wet_val in l_row['wet_key']:
                return l_row['url']
        return None

    df['artikel_url'] = df.apply(get_url, axis=1)
    return df

df = load_combined_data()
alle_wetten = sorted(df['Wet'].dropna().unique().tolist())

# Zoek de key in Secrets (zonder melding in de UI)
api_key = st.secrets.get("OPENAI_API_KEY")

with st.sidebar:
    st.header("⚙️ Instellingen")
    # Alleen als de key NIET in Secrets staat, tonen we het invoerveld
    if not api_key:
        api_key = st.text_input("OpenAI API Key", type="password")
        
    gekozen_wetten = st.multiselect("Filter op wet", options=["Allemaal"] + alle_wetten, default=["Allemaal"])
    aantal_doel = st.number_input("Totaal vragen", value=25)
    
    if st.button("Reset Score"):
        st.session_state.score, st.session_state.totaal, st.session_state.vragen_teller = 0, 0, 0
        st.rerun()

if not api_key:
    st.warning("Voer je API Key in de zijbalk in of configureer de Secrets.")
    st.stop()

openai.api_key = api_key

# 5. Filtering & Scoreboard
filtered_df = df if "Allemaal" in gekozen_wetten else df[df['Wet'].isin(gekozen_wetten)]
st.title("🚓 Politie Toets Trainer")

c1, c2, c3 = st.columns(3)
c1.metric("Vraag", f"{st.session_state.vragen_teller} / {aantal_doel}")
c2.metric("Goed", st.session_state.score)
percentage = (st.session_state.score / st.session_state.totaal * 100) if st.session_state.totaal > 0 else 0
c3.metric("Percentage", f"{round(percentage, 1)}%")

# 6. Vraag Generatie
if st.session_state.vragen_teller < aantal_doel:
    if st.button("Nieuwe vraag"):
        vraag_data = filtered_df.sample(n=1).iloc[0]
        st.session_state.current_row = vraag_data
        
        prompt = f"Examen: {vraag_data['Wet']} Art. {vraag_data['Artikel']}. Doel: {vraag_data['Leerdoel']}. Geef vraag."
        res = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )
        st.session_state.vraag_tekst = res.choices[0].message.content
        st.session_state.beoordeeld = False

if 'vraag_tekst' in st.session_state:
    row = st.session_state.current_row
    st.info(f"📚 **Bron:** [{row['Wet']} Art. {row['Artikel']}]({row['artikel_url'] if row['artikel_url'] else '#'})")
    st.subheader(st.session_state.vraag_tekst)
    
    # Door de key te koppelen aan vragen_teller, wordt het veld leeg bij elke nieuwe vraag
    ans = st.text_area("Jouw antwoord:", key=f"input_vraag_{st.session_state.vragen_teller}")

    if st.button("Check") and not st.session_state.beoordeeld:
        check_prompt = f"Vraag: {st.session_state.vraag_tekst}\nAntwoord: {ans}\nContext: {row['Wet']} {row['Artikel']}. Begin met GOED of FOUT."
        eval_res = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": check_prompt}]
        )
        feedback = eval_res.choices[0].message.content
        st.write(feedback)
        
        st.session_state.totaal += 1
        st.session_state.vragen_teller += 1
        if "GOED" in feedback.upper():
            st.session_state.score += 1
        st.session_state.beoordeeld = True
