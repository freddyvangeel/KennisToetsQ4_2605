import streamlit as st
import pandas as pd
from openai import OpenAI
import re

# 1. Configuratie
st.set_page_config(page_title="Kennistoets Q4 oefenen", layout="wide")

if "score" not in st.session_state:
    st.session_state.score = 0
if "totaal" not in st.session_state:
    st.session_state.totaal = 0
if "vragen_teller" not in st.session_state:
    st.session_state.vragen_teller = 0
if "beoordeeld" not in st.session_state:
    st.session_state.beoordeeld = False
if "feedback" not in st.session_state:
    st.session_state.feedback = None
if "vraag_tekst" not in st.session_state:
    st.session_state.vraag_tekst = None
if "current_row" not in st.session_state:
    st.session_state.current_row = None


# 2. Helper functies voor normaliseren en parsen
def normalize_text(value: str) -> str:
    """Normaliseer tekst voor vergelijking."""
    if pd.isna(value):
        return ""

    text = str(value).strip().lower()
    text = text.replace("2012", "")
    text = text.replace(",", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_wet_name(wet_value: str, artikel_value: str) -> str:
    """
    Bepaal de echte wetnaam.
    In de CSV staat in kolom 'Wet' soms een code zoals 'A.01 Politiewet',
    terwijl in kolom 'Artikel' de echte wetnaam staat, zoals 'Politiewet, artikel 2'.
    """
    wet_value = str(wet_value).strip() if pd.notna(wet_value) else ""
    artikel_value = str(artikel_value).strip() if pd.notna(artikel_value) else ""

    # Pak de wetnaam bij voorkeur uit kolom Artikel
    if "," in artikel_value:
        wetnaam = artikel_value.split(",", 1)[0].strip()
        if wetnaam:
            return normalize_text(wetnaam)

    # Fallback: verwijder eventuele code uit kolom Wet
    wet_schoon = re.sub(r"^[A-Z]\.\d+\s+", "", wet_value, flags=re.IGNORECASE).strip()
    return normalize_text(wet_schoon or wet_value)


def parse_artikel_info(artikel_value: str) -> dict:
    """
    Parse artikelinformatie uit strings zoals:
    - 'Politiewet, artikel 2'
    - 'Politiewet, artikel 7 lid 1 en 7'
    - 'Politiewet, 7 lid 2 en lid 7'
    """
    text = str(artikel_value).strip().lower()

    artikel_match = re.search(r"artikel\s+([\d:.a-z]+)", text)
    if not artikel_match:
        artikel_match = re.search(r",\s*([\d:.a-z]+)", text)

    artikel_nummer = artikel_match.group(1).strip() if artikel_match else ""

    # Zoek alle lidverwijzingen
    lid_matches = re.findall(r"lid\s+([\d]+)", text)
    leden = [lid.strip() for lid in lid_matches if lid.strip()]

    return {
        "artikel_nummer": artikel_nummer,
        "leden": leden
    }


def parse_jurkad_line(line: str) -> dict | None:
    """
    Parse regels zoals:
    Politiewet 2012 Artikel: 7 Lid: 1 → [bevoegdheid gebruik geweld](https://...)
    Politiewet 2012 Artikel: 2 → [ambtenaren van politie](https://...)
    """
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
        "url": url.strip()
    }


def build_jurkad_dataframe(md_lines: list[str]) -> pd.DataFrame:
    rows = []

    for line in md_lines:
        parsed = parse_jurkad_line(line)
        if parsed:
            rows.append(parsed)

    return pd.DataFrame(rows)


def find_best_url(row: pd.Series, df_links: pd.DataFrame) -> str:
    """
    Zoek de best passende URL uit JurKad.md.
    Logica:
    1. Match op wet + artikel + een van de genoemde leden
    2. Anders wet + artikel zonder lid
    3. Anders zoekpagina wetten.overheid.nl
    """
    wet_norm = normalize_wet_name(row["Wet"], row["Artikel"])
    artikel_info = parse_artikel_info(row["Artikel"])
    artikel_nummer = normalize_text(artikel_info["artikel_nummer"])
    leden = artikel_info["leden"]

    fallback_query = f"{row['Wet']} {row['Artikel']}"
    fallback_url = f"https://wetten.overheid.nl/zoeken?Zoektekst={fallback_query}"

    if df_links.empty or not artikel_nummer:
        return fallback_url

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

    # Eerst proberen op specifiek lid
    if leden:
        for lid in leden:
            lid_match = kandidaten[kandidaten["leden"].apply(lambda x: lid in x if isinstance(x, list) else False)]
            if not lid_match.empty:
                return lid_match.iloc[0]["url"]

    # Daarna artikel zonder lid
    zonder_lid = kandidaten[kandidaten["leden"].apply(lambda x: len(x) == 0 if isinstance(x, list) else True)]
    if not zonder_lid.empty:
        return zonder_lid.iloc[0]["url"]

    # Anders eerste beste kandidaat
    return kandidaten.iloc[0]["url"]


def extract_first_line(text: str) -> str:
    """Gebruik alleen de eerste niet-lege regel."""
    if not text:
        return ""
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    return lines[0] if lines else ""


def is_goed(feedback: str) -> bool:
    """Controleer of feedback start met GOED."""
    first_line = extract_first_line(feedback).upper()
    return first_line.startswith("GOED")


# 3. Data laden
@st.cache_data
def load_combined_data():
    # CSV met BOM veilig inlezen
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

    # JurKad.md inlezen
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
        default=["Allemaal"]
    )

    aantal_doel = st.number_input("Totaal vragen", min_value=1, value=25, step=1)

    if st.button("Reset score"):
        st.session_state.score = 0
        st.session_state.totaal = 0
        st.session_state.vragen_teller = 0
        st.session_state.beoordeeld = False
        st.session_state.feedback = None
        st.session_state.vraag_tekst = None
        st.session_state.current_row = None
        st.rerun()

if not api_key:
    st.stop()

client = OpenAI(api_key=api_key)


# 5. OpenAI functies
def genereer_vraag():
    if "Allemaal" in gekozen_wetten or not gekozen_wetten:
        filtered_df = df.copy()
    else:
        filtered_df = df[df["Wet"].isin(gekozen_wetten)].copy()

    if filtered_df.empty:
        st.error("Geen leerdoelen gevonden voor de gekozen filter.")
        return

    vraag_data = filtered_df.sample(n=1).iloc[0]
    st.session_state.current_row = vraag_data

    prompt = f"""Genereer exact ÉÉN examenvraag voor een student van de Politieacademie op mbo-4 niveau.

Gebruik uitsluitend deze invoer:
Wet: {vraag_data['Wet']}
Artikel: {vraag_data['Artikel']}
Leerdoel: {vraag_data['Leerdoel']}

Doel:
Formuleer één duidelijke, juridisch correcte en ondubbelzinnige vraag die direct aansluit op het leerdoel en op de inhoud en strekking van het genoemde artikel.

Strikte regels:
1. Stel exact één vraag.
2. Gebruik geen deelvragen.
3. Gebruik geen tweede vraag, ook niet impliciet.
4. Gebruik geen verdiepingsvraag of vervolg zoals: waarom, licht toe, verklaar, motiveer.
5. Toets één centrale denkhandeling die past bij het leerdoel.
6. De vraag moet passen bij mbo-4: helder, concreet en niet onnodig complex.
7. De vraag moet direct aansluiten op het genoemde artikel.
8. Geen casus, geen inleiding, geen contextzin.
9. De vraag mag niet dubbelzinnig zijn.
10. Alleen de vraag als output. Geen toelichting, geen antwoordmodel."""

    res = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.2,
        messages=[
            {"role": "system", "content": "Je schrijft korte, juridisch correcte examenvragen voor de Politieacademie."},
            {"role": "user", "content": prompt}
        ]
    )

    vraag_tekst = extract_first_line(res.choices[0].message.content)
    st.session_state.vraag_tekst = vraag_tekst
    st.session_state.beoordeeld = False
    st.session_state.feedback = None


def beoordeel_antwoord(vraag: str, antwoord_student: str, row: pd.Series) -> str:
    check_p = f"""Beoordeel het antwoord van een student op een examenvraag voor de Politieacademie op mbo-4 niveau.

Vraag: {vraag}
Antwoord student: {antwoord_student}
Wet: {row['Wet']}
Artikel: {row['Artikel']}
Leerdoel: {row['Leerdoel']}

Beoordelingskader:
- Beoordeel uitsluitend op basis van het leerdoel en het genoemde artikel.
- De vraag toetst één centrale juridische kern.
- Wees redelijk: als de juridische kern van het antwoord klopt, is het GOED.
- Reken een antwoord niet fout als de formulering van de student anders is, maar juridisch inhoudelijk juist.
- Reken extra informatie niet fout, zolang die de kern niet onjuist maakt.

Outputregels:
1. Regel 1 is exact: GOED of FOUT
2. Regel 2 is een korte, zakelijke toelichting van maximaal 2 zinnen
3. Benoem kort wat juridisch juist is of wat juridisch ontbreekt
4. Geen opsommingstekens
5. Geen uitgebreide uitleg"""

    res = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.1,
        messages=[
            {"role": "system", "content": "Je bent een strikte maar redelijke beoordelaar van juridische examenantwoorden op mbo-4 niveau."},
            {"role": "user", "content": check_p}
        ]
    )

    return res.choices[0].message.content.strip()


# 6. UI
st.title("🚓 Politie Toets Trainer")

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

    st.info(f"📚 **Bron:** [{row['Wet']} - {row['Artikel']}]({row['artikel_url']})")
    st.subheader(st.session_state.vraag_tekst)

    ans = st.text_area(
        "Antwoord:",
        key=f"ans_{st.session_state.vragen_teller}",
        height=180
    )

    if not st.session_state.beoordeeld:
        if st.button("Check"):
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
            st.session_state.vraag_tekst = None
            st.session_state.beoordeeld = False
            st.session_state.feedback = None
            st.session_state.current_row = None
            st.rerun()
