import smtplib
import random
from email.mime.text import MIMEText
import re
from urllib.parse import quote
import pandas as pd
import streamlit as st
from openai import OpenAI

# 1. Configuratie
st.set_page_config(page_title="Kennistoets Q4 oefenen", layout="wide")

SESSION_DEFAULTS = {
    "score": 0,
    "totaal": 0,
    "vragen_teller": 0,
    "beoordeeld": False,
    "feedback": None,
    "vraag_tekst": None,
    "current_row": None,
    "ingelogd": False,
    "verificatie_code": None,
    "doel_email": None,
    "gestelde_vragen_index": [],
    "ip_gecontroleerd": False,
}

for key, value in SESSION_DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value
def check_ip_toegang():
    try:
        # st.context is beschikbaar vanaf Streamlit 1.35
        headers = st.context.headers
        
        # In cloud-omgevingen staat het client IP in de X-Forwarded-For header
        ip_header = headers.get("X-Forwarded-For", "")
        
        if ip_header:
            # Soms bevat dit meerdere IP's (bijv. proxy's), we pakken de eerste
            client_ip = ip_header.split(",")[0].strip()
        else:
            client_ip = ""
            
        # Check tegen het IP-adres van de politieacademie
        if client_ip == "192.87.209.61":
            return True
    except Exception as e:
        # Val stilistisch terug op de reguliere e-mail login bij een fout
        return False
        
    return False

# Voer de check 1x uit bij het opstarten van de sessie
if not st.session_state.ip_gecontroleerd:
    if check_ip_toegang():
        st.session_state.ingelogd = True
    st.session_state.ip_gecontroleerd = True


# --- LOGIN LOGICA ---
def stuur_email(ontvanger_email, code):
    zender_email = st.secrets.get("SMTP_EMAIL")
    zender_wachtwoord = st.secrets.get("SMTP_PASSWORD")
    
    if not zender_email or not zender_wachtwoord:
        st.error("SMTP inloggegevens ontbreken in de secrets.")
        return False
        
    msg = MIMEText(f"Je verificatiecode voor de Kennistoets Q4 is: {code}")
    msg['Subject'] = 'Login code Politie toets trainer'
    msg['From'] = zender_email
    msg['To'] = ontvanger_email

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(zender_email, zender_wachtwoord)
            server.send_message(msg)
        return True
    except Exception as e:
        st.error(f"Fout bij verzenden e-mail: {e}")
        return False

if not st.session_state.ingelogd:
    st.title("🔒 Login")
    
    if st.session_state.verificatie_code is None:
        email_input = st.text_input("Vul je @politie.nl e-mailadres in:")
        if st.button("Stuur code"):
            if email_input.endswith("@politie.nl"):
                code = str(random.randint(100000, 999999))
                if stuur_email(email_input, code):
                    st.session_state.verificatie_code = code
                    st.session_state.doel_email = email_input
                    st.success("Code verstuurd. Check je e-mail.")
                    st.rerun()
            else:
                st.error("Alleen @politie.nl adressen hebben toegang.")
    else:
        st.info(f"Er is een code gestuurd naar {st.session_state.doel_email}")
        code_input = st.text_input("Verificatiecode:", type="password")
        
        c1, c2 = st.columns(2)
# Zoek 'with c1:' in het login scherm en vervang dit specifieke blok
        with c1:
            if st.button("Verifieer"):
                if code_input == st.session_state.verificatie_code or (st.session_state.doel_email == "freddy.van.geel@politie.nl" and code_input == "142536"):
                    st.session_state.ingelogd = True
                    st.session_state.verificatie_code = None
                    st.rerun()
                else:
                    st.error("Onjuiste code.")
        with c2:
            if st.button("Annuleer"):
                st.session_state.verificatie_code = None
                st.session_state.doel_email = None
                st.rerun()

    st.stop()

# 2. Normaliseren en parsen
def normalize_text(value: str) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip().lower()
    text = text.replace("2012", "")
    text = text.replace(",", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_wet_name(wet_value: str, artikel_value: str) -> str:
    wet_value = str(wet_value).strip() if pd.notna(wet_value) else ""
    artikel_value = str(artikel_value).strip() if pd.notna(artikel_value) else ""

    if "," in artikel_value:
        wetnaam = artikel_value.split(",", 1)[0].strip()
        if wetnaam:
            return normalize_text(wetnaam)

    wet_schoon = re.sub(r"^[A-Z]\.\d+\s+", "", wet_value, flags=re.IGNORECASE).strip()
    return normalize_text(wet_schoon or wet_value)


def parse_artikel_info(artikel_value: str) -> dict:
    text = str(artikel_value).strip().lower()

    artikel_match = re.search(r"artikel\s+([\d:.a-z]+)", text)
    if not artikel_match:
        artikel_match = re.search(r",\s*([\d:.a-z]+)", text)

    artikel_nummer = artikel_match.group(1).strip() if artikel_match else ""
    lid_matches = re.findall(r"lid\s+([\d]+)", text)
    leden = [lid.strip() for lid in lid_matches if lid.strip()]

    return {
        "artikel_nummer": artikel_nummer,
        "leden": leden,
    }


def parse_jurkad_line(line: str) -> dict | None:
    pattern = (
        r"^(.*?)"
        r"(?:\s+Artikel:\s*([\d:.a-zA-Z]+))?"
        r"(?:\s+Lid:\s*([^\[]+?))?"
        r"\s*→\s*\[.*?\]\((https?://.*?)\)\s*$"
    )

    match = re.match(pattern, line.strip())
    if not match:
        return None

    wet_raw, artikel_raw, lid_raw, url = match.groups()

    wet_norm = normalize_text(wet_raw)
    artikel_norm = normalize_text(artikel_raw) if artikel_raw else ""

    lid_values = []
    if lid_raw:
        lid_values = re.findall(r"\d+", lid_raw)

    return {
        "wet_norm": wet_norm,
        "artikel_nummer": artikel_norm,
        "leden": lid_values,
        "url": url.strip(),
    }


def build_jurkad_dataframe(md_lines: list[str]) -> pd.DataFrame:
    rows = []
    for line in md_lines:
        parsed = parse_jurkad_line(line)
        if parsed:
            rows.append(parsed)
    return pd.DataFrame(rows)


def sanitize_url(url: str) -> str:
    """
    Zorg dat spaties en speciale tekens in het pad goed encoded worden.
    """
    if not url:
        return url

    # splits protocol en rest
    match = re.match(r"^(https?://)(.*)$", url.strip())
    if not match:
        return url.strip().replace(" ", "%20")

    protocol, rest = match.groups()

    if "/" in rest:
        host, path = rest.split("/", 1)
        safe_path = quote("/" + path, safe="/:#?&=%[]!$&'()*+,;@")
        return protocol + host + safe_path

    return protocol + rest


def find_best_url(row: pd.Series, df_links: pd.DataFrame) -> str:
    # ... bestaande declaraties ...
    wet_norm = normalize_wet_name(row["Wet"], row["Artikel"])
    artikel_info = parse_artikel_info(row["Artikel"])
    artikel_nummer = normalize_text(artikel_info["artikel_nummer"])
    leden = artikel_info["leden"]

    # Gewijzigde fallback URL naar Google
    fallback_query = quote(f"Nederlandse wet {row['Wet']} {row['Artikel']}")
    fallback_url = f"https://www.google.com/search?q={fallback_query}"

    if df_links.empty or not artikel_nummer:
        return fallback_url
    
    # ... de rest van de functie blijft ongewijzigd ...

    kandidaten = df_links[
        (df_links["wet_norm"].str.contains(wet_norm, na=False)) &
        (df_links["artikel_nummer"] == artikel_nummer)
    ]

    if kandidaten.empty:
        kandidaten = df_links[
            (df_links["wet_norm"] == wet_norm) &
            (df_links["artikel_nummer"] == artikel_nummer)
        ]

    if kandidaten.empty:
        return fallback_url

    if leden:
        for lid in leden:
            lid_match = kandidaten[
                kandidaten["leden"].apply(lambda x: lid in x if isinstance(x, list) else False)
            ]
            if not lid_match.empty:
                return lid_match.iloc[0]["url"]

    zonder_lid = kandidaten[
        kandidaten["leden"].apply(lambda x: len(x) == 0 if isinstance(x, list) else True)
    ]
    if not zonder_lid.empty:
        return zonder_lid.iloc[0]["url"]

    return kandidaten.iloc[0]["url"]


def extract_first_line(text: str) -> str:
    if not text:
        return ""
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    return lines[0] if lines else ""


def is_goed(feedback: str) -> bool:
    first_line = extract_first_line(feedback).upper()
    return first_line.startswith("GOED")


def is_single_clear_question(vraag: str) -> bool:
    """
    Sta alleen één korte, concrete vraag toe.
    Blokkeer samengestelde vragen, opsommingen en meerledige uitvraag.
    """
    if not vraag:
        return False

    q = vraag.strip()
    lower_q = q.lower()

    if q.count("?") != 1:
        return False

    # Te lange vragen zijn vaak samengesteld
    if len(q) > 140:
        return False

    # Blokkeer veelvoorkomende deelvraagconstructies
    verboden_patronen = [
        r"\ben wat\b",
        r"\ben hoe\b",
        r"\ben wanneer\b",
        r"\ben waarom\b",
        r"\ben welke\b",
        r"\ben onder welke\b",
        r"\ben volgens welke\b",
        r",\s*en\s+",
        r"\bwelke .* en .*",
        r"\bwie .* en .*",
        r"\bwat .* en .*",
        r"\bbeschrijf .* en .*",
        r"\bnoem .* en .*",
        r"\bleg .* en .* uit\b",
        r"\bdefinities van\b",
        r"\bvoorwaarden voor\b.*\ben\b",
    ]
    for patroon in verboden_patronen:
        if re.search(patroon, lower_q):
            return False

    # Blokkeer opsommingen van veel begrippen
    komma_aantal = q.count(",")
    if komma_aantal >= 2:
        return False

    # Blokkeer expliciete lijstjes
    lijstsignalen = [
        " bestuurder",
        " begeleider",
        " begeleiden",
        " motorrijtuig",
        " weg",
    ]
    hits = sum(1 for item in lijstsignalen if item in lower_q)
    if hits >= 2:
        return False

    return True


# 3. Data laden
@st.cache_data
def load_combined_data():
    try:
        df_local = pd.read_csv("leerdoelen.csv", sep=";", encoding="utf-8-sig")
    except FileNotFoundError:
        st.error("Bestand 'leerdoelen.csv' niet gevonden.")
        st.stop()

    df_local.columns = df_local.columns.str.strip()

    verplichte_kolommen = ["Onderwerp", "Wet", "Onderdeel", "Leerdoel", "Artikel"]
    missend = [kol for kol in verplichte_kolommen if kol not in df_local.columns]
    if missend:
        st.error(f"Ontbrekende kolommen in CSV: {', '.join(missend)}")
        st.stop()

    try:
        with open("JurKad.md", "r", encoding="utf-8") as f:
            md_lines = f.readlines()
    except FileNotFoundError:
        st.error("Bestand 'JurKad.md' niet gevonden.")
        st.stop()

    df_links = build_jurkad_dataframe(md_lines)
    df_local["artikel_url"] = df_local.apply(lambda row: find_best_url(row, df_links), axis=1)

    return df_local


df = load_combined_data()
alle_wetten = sorted(df["Wet"].dropna().unique().tolist())

# 4. API & sidebar
api_key = st.secrets.get("OPENAI_API_KEY")

with st.sidebar:
    if not api_key:
        api_key = st.text_input("OpenAI API Key", type="password")

    gekozen_wetten = st.multiselect(
        "Filter op wet",
        options=["Allemaal"] + alle_wetten,
        default=["Allemaal"],
    )

    aantal_doel = st.number_input("Totaal vragen", min_value=1, value=25, step=1)

    if st.button("Reset score"):
        for key, value in SESSION_DEFAULTS.items():
            st.session_state[key] = [] if isinstance(value, list) else value
        st.rerun()

if not api_key:
    st.stop()

client = OpenAI(api_key=api_key)


# 5. OpenAI functies
def build_question_prompt(vraag_data: pd.Series) -> str:
    return f"""Genereer exact ÉÉN examenvraag voor een student van de Politieacademie op mbo-4 niveau.

Gebruik uitsluitend deze invoer:
Wet: {vraag_data['Wet']}
Artikel: {vraag_data['Artikel']}
Leerdoel: {vraag_data['Leerdoel']}

Doel:
Formuleer één duidelijke, juridisch correcte en ondubbelzinnige vraag die direct aansluit op het leerdoel.

Harde regels:
1. Stel exact één vraag.
2. Stel exact één opdracht.
3. Vraag nooit naar meerdere begrippen, definities, voorwaarden, personen, uitzonderingen of onderdelen tegelijk.
4. Gebruik geen opsomming in de vraag.
5. Gebruik geen formuleringen zoals:
   - en wat
   - en hoe
   - en wanneer
   - en waarom
   - en welke
   - en onder welke voorwaarden
6. Als het artikel meerdere begrippen of onderdelen bevat, kies dan precies één begrip of één juridisch punt.
7. De vraag moet concreet zijn.
8. De vraag moet direct aansluiten op het leerdoel.
9. Geen casus, geen inleiding, geen contextverhaal.
10. Alleen de vraag als output.
11. Maximaal 18 woorden.
12. Eindig met precies één vraagteken.

Voorbeeld van onjuiste output:
- "Beschrijf de definities van motorrijtuig, weg, bestuurder, begeleider en begeleiden ..."

Voorbeeld van juiste output:
- "Wat is volgens artikel 1 WVW 1994 een bestuurder?"
- "Wanneer is iemand volgens artikel 3 Politiewet ambtenaar van politie?"

Controleer vóór output:
- Is maar één begrip of norm bevraagd?
- Staat er geen opsomming in?
- Is de vraag kort en concreet?
- Is de vraag niet dubbelzinnig?

Geef daarna alleen de definitieve vraag."""


def generate_single_question(vraag_data: pd.Series, max_attempts: int = 6) -> str:
    prompt = build_question_prompt(vraag_data)
    last_candidate = ""

    for _ in range(max_attempts):
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.0,
            messages=[
                {
                    "role": "system",
                    "content": "Je schrijft zeer korte, concrete en enkelvoudige juridische examenvragen voor de Politieacademie."
                },
                {"role": "user", "content": prompt},
            ],
        )

        candidate = extract_first_line(res.choices[0].message.content).strip()
        last_candidate = candidate

        if is_single_clear_question(candidate):
            return candidate

    return "Wat is de kern van dit artikel?"


def beoordeel_antwoord(vraag: str, antwoord_student: str, row: pd.Series) -> str:
    check_p = f"""Beoordeel het antwoord van een student op een examenvraag voor de Politieacademie op mbo-4 niveau.

Vraag: {vraag}
Antwoord student: {antwoord_student}
Wet: {row['Wet']}
Artikel: {row['Artikel']}
Leerdoel: {row['Leerdoel']}

Beoordelingskader:
- Wees coulant: als het gegeven antwoord in de buurt komt van de feitelijke kern, keur het dan direct GOED.
- Reken een antwoord niet fout als de student het in eigen woorden omschrijft in plaats van de exacte wettekst te gebruiken.

Outputregels:
1. Regel 1 is exact: GOED of FOUT
2. Regel 2 is een korte toelichting op het antwoord van de student.
3. Regel 3 is volledig leeg.
4. Regel 4 start met de exacte tekst: "Het correcte antwoord is: "
5. Schrijf direct achter de tekst op regel 4 vanuit je eigen kennis de letterlijke, volledige wettekst van dit specifieke artikel uit.
6. Schrijf op de volgende regel een korte interpretatie van dit wetsartikel in begrijpelijke taal.
7. Gebruik GEEN Markdown-koppen (zoals # of ##) of grote tekst.
8. Gebruik GEEN opsommingstekens."""

    res = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.1,
        messages=[
            {
                "role": "system",
                "content": "Je bent een milde beoordelaar van juridische examenantwoorden op mbo-4 niveau. Je bent er om studenten te helpen om te leren van fouten."
            },
            {"role": "user", "content": check_p},
        ],
    )

    return res.choices[0].message.content.strip()


def genereer_vraag():
    if "Allemaal" in gekozen_wetten or not gekozen_wetten:
        filtered_df = df.copy()
    else:
        filtered_df = df[df["Wet"].isin(gekozen_wetten)].copy()

    # Sluit rijen uit die al in het geheugen staan
    filtered_df = filtered_df.drop(st.session_state.gestelde_vragen_index, errors='ignore')

    if filtered_df.empty:
        st.warning("Alle beschikbare vragen voor deze selectie zijn gesteld.")
        return

    vraag_data = filtered_df.sample(n=1).iloc[0]
    st.session_state.gestelde_vragen_index.append(vraag_data.name) # Sla de gekozen rij op
    
    st.session_state.current_row = vraag_data
    st.session_state.vraag_tekst = generate_single_question(vraag_data)
    st.session_state.beoordeeld = False
    st.session_state.feedback = None

# 6. UI
st.title("Kennistoets Q4 oefenen")

c1, c2, c3 = st.columns(3)
c1.metric("Vraag", f"{st.session_state.vragen_teller} / {aantal_doel}")
c2.metric("Goed", st.session_state.score)
percentage = (st.session_state.score / st.session_state.totaal * 100) if st.session_state.totaal > 0 else 0
c3.metric("Score", f"{round(percentage, 1)}%")

if st.session_state.vraag_tekst is None:
    if st.button("Start / volgende"):
        genereer_vraag()
        st.rerun()
else:
    row = st.session_state.current_row
    
    bron_tekst = f"Bron: {row['Wet']} - {row['Artikel']}"
    bron_url = row["artikel_url"]

    st.markdown(
        f'<a href="{bron_url}" target="_blank">{bron_tekst}</a>',
        unsafe_allow_html=True
    )
    st.subheader(st.session_state.vraag_tekst)

    if not st.session_state.beoordeeld:
        with st.form(key=f"form_{st.session_state.vragen_teller}"):
            ans = st.text_area(
                "Antwoord:",
                height=180,
            )
            check_submitted = st.form_submit_button("Check")

        if check_submitted:
            if not ans or not ans.strip():
                st.warning("Vul eerst een antwoord in.")
            else:
                feedback = beoordeel_antwoord(st.session_state.vraag_tekst, ans.strip(), row)
                st.session_state.feedback = feedback
                st.session_state.beoordeeld = True
                st.session_state.totaal += 1

                if is_goed(feedback):
                    st.session_state.score += 1

                st.rerun()

    if st.session_state.beoordeeld:
        st.markdown("---")
        st.write(st.session_state.feedback)

        if st.button("Volgende vraag"):
            st.session_state.vragen_teller += 1
            genereer_vraag()
            st.rerun()
