import streamlit as st
import uuid
from datetime import datetime
from openai import OpenAI
from functions import services
from PIL import Image

# ======================================================
# CONFIG STREAMLIT
# ======================================================
st.set_page_config(
    page_title="Nuvia Digital Product Passport",
    page_icon="functions/favicon.jpeg",
    layout="centered"
)

# ======================================================
# STILE GLOBALE + LOGO
# ======================================================
logo = Image.open("functions/logo_nuvia.jpeg")
logo_base64 = services.image_to_base64(logo)

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Nunito+Sans&display=swap');

body, div, span, input, button {{
    font-family: 'Nunito Sans', sans-serif;
    background-color: #f5f1ed;
    color: #3a2607;
}}

h1, h2, h3, h4, h5, h6 {{
    color: #3a2607;
}}

.stButton>button {{
    background-color: #25ce6c;
    color: white;
    border-radius: 8px;
    border: none;
}}

.icon-red {{ color: #f06449; }}
.icon-blue {{ color: #2b3a67; }}
.icon-dark {{ color: #0b021f; }}
.icon-purple {{ color: #6320ee; }}

div[data-testid="stAppViewContainer"] > div:first-child {{
    display: flex;
    justify-content: flex-start;
    align-items: center;
    margin-bottom: 20px;
}}
</style>

<div style="display:flex; align-items:center; gap:15px; margin-bottom:20px;">
    <img src="data:image/jpeg;base64,{logo_base64}" width="450">
    <h1 style="margin:0;"></h1>
</div>
""", unsafe_allow_html=True)

client = OpenAI(api_key=st.secrets["OPEN_AI_KEY"])

# ======================================================
# HELPER FUNCTIONS (rating + colore + compliance)
# ======================================================
def compute_field_rating(field):
    """Calcola rating 0-1 basato su confidence e tipo campo"""
    field_type_weight = {
        "technical": 1.0,
        "declaration": 0.6,
        "lca": 0.5,
        "visual": 0.4
    }
    weight = field_type_weight.get(field.get("field_type", "technical"), 0.5)
    confidence = field.get("confidence", 0.0) or 0.0
    return round(confidence * weight, 2)

def score_to_color(score):
    if score >= 0.8:
        return "🟢"
    elif score >= 0.5:
        return "🟡"
    else:
        return "🔴"

def compute_espr_compliance(section_fields, required_fields):
    """
    OK → tutti i campi richiesti >= 0.8
    PARTIAL → almeno un campo >=0.5
    MISSING → tutti <0.5 o None
    """
    ratings = []
    for f in required_fields:
        r = section_fields.get(f, {}).get("rating", 0.0)
        ratings.append(r)
    if not ratings:
        return "MISSING"
    if all(r >= 0.8 for r in ratings):
        return "OK"
    elif any(r >= 0.5 for r in ratings):
        return "PARTIAL"
    else:
        return "MISSING"

# ======================================================
# ROUTING PUBBLICO (QR)
# ======================================================
passport_id = st.query_params.get("passport_id")
if passport_id:
    passport = services.load_passport_from_file(passport_id)
    if not passport:
        st.error("Digital Product Passport not found")
        st.stop()

    st.markdown("""
    <style>
    [data-testid="stSidebar"] {display: none;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

    st.title("🇪🇺 Digital Product Passport")
    st.caption("Regulation (EU) – Ecodesign for Sustainable Products (ESPR)")

    st.markdown(f"""
    **Product ID:** `{passport['id']}`  
    **Product type:** {passport['product_type']}  
    **Created:** {passport['metadata']['created_at']}  
    **Version:** {passport['metadata']['version']}
    """)

    st.divider()
    st.subheader("1️⃣ Dati PDF")
    for k, v in passport["data_source_pdf"].items():
        st.write(f"**{k}**: {v.get('value', v)} {v.get('color','')}")

    st.divider()
    st.subheader("2️⃣ Dati Immagine")
    for k, v in passport["data_source_image"].items():
        if k != "immagine_base64":
            st.write(f"**{k}**: {v.get('value', v)} {v.get('color','')}")

    if "product_image_base64" in passport:
        st.image(
            f"data:image/jpeg;base64,{passport['product_image_base64']}",
            caption="Foto prodotto",
            use_column_width=True
        )

    st.subheader("📊 Overall Reliability")
    st.progress(passport.get("overall_rating", 0.0))
    st.metric("Overall score", f"{int(passport.get('overall_rating', 0.0)*100)}%")

    st.subheader("🇪🇺 ESPR Compliance")
    for section, status in passport.get("espr_compliance", {}).items():
        icon = {"OK":"🟢","PARTIAL":"🟡","MISSING":"🔴"}.get(status,"🔴")
        st.write(f"{icon} **{section}** → {status}")

    st.stop()

# ======================================================
# BACKOFFICE
# ======================================================
for k in ["pdf_data","image_data","validated_pdf","validated_image","uploaded_image_file"]:
    if k not in st.session_state:
        st.session_state[k] = None

tipo_prodotto = st.selectbox("Seleziona tipo prodotto", ["mobile","lampada","bicicletta"])
tabs = st.tabs(["📤 Upload & Analisi","📝 Validazione PDF","👁️ Validazione Immagine","🔗 Pubblica DPP"])

# ======================================================
# TAB 1 — UPLOAD & GPT
# ======================================================
with tabs[0]:
    with st.form("upload_form"):
        pdf_file = st.file_uploader("PDF prodotto", type=["pdf"])
        image_file = st.file_uploader("Immagine prodotto", type=["jpg","png","jpeg"])
        submitted = st.form_submit_button("🔍 Analizza")
        if submitted:
            if not pdf_file or not image_file:
                st.warning("Carica PDF e immagine")
            else:
                with st.spinner("Analisi in corso ⏳…"):
                    pdf_text = services.extract_text_from_pdf(pdf_file)
                    st.session_state.pdf_data = services.gpt_extract_from_pdf(pdf_text, client, tipo_prodotto)
                    st.session_state.uploaded_image_file = image_file
                    st.session_state.image_data = services.gpt_analyze_image(image_file, client, tipo_prodotto)
                st.success("Analisi completata")

# ======================================================
# TAB 2 — VALIDAZIONE PDF
# ======================================================
with tabs[1]:
    if st.session_state.pdf_data:
        st.session_state.validated_pdf = services.render_validation_form(st.session_state.pdf_data, title="✔ Dati certificati (PDF)")
    else:
        st.info("Esegui prima l’analisi")

# ======================================================
# TAB 3 — VALIDAZIONE IMMAGINE
# ======================================================
with tabs[2]:
    if st.session_state.image_data:
        st.session_state.validated_image = services.render_validation_form(st.session_state.image_data, title="👁️ Dati estratti da immagine")
        if st.session_state.uploaded_image_file:
            st.image(st.session_state.uploaded_image_file, caption="Foto prodotto", use_column_width=True)
    else:
        st.info("Esegui prima l’analisi")

# ======================================================
# TAB 4 — PUBBLICAZIONE DPP
# ======================================================
with tabs[3]:
    if st.session_state.validated_pdf and st.session_state.validated_image:
        if st.button("🚀 Pubblica Digital Product Passport"):
            product_id = f"{tipo_prodotto.upper()}-{uuid.uuid4().hex[:8]}"
            created_at = datetime.utcnow().isoformat()

            # --------------------------------------------------
            # UNIONE DATI PDF + IMAGE
            # --------------------------------------------------
            merged_data = {**st.session_state.validated_image, **st.session_state.validated_pdf}

            sections = {}
            overall_scores = []

            # trattiamo tutto come un'unica "sezione PDF" e "sezione IMAGE"
            for source_name, source_fields in [("PDF", st.session_state.validated_pdf), ("IMAGE", st.session_state.validated_image)]:
                section_fields = {}
                for field_name, value in source_fields.items():
                    field = {
                        "value": value,
                        "confidence": 1.0,  # default, non estratto da GPT
                        "field_type": "technical" if source_name=="PDF" else "visual",
                        "source": source_name
                    }
                    rating = compute_field_rating(field)
                    color = score_to_color(rating)
                    field["rating"] = rating
                    field["color"] = color
                    section_fields[field_name] = field
                    overall_scores.append(rating)
                sections[source_name] = {
                    "fields": section_fields,
                    "espr_compliance": compute_espr_compliance(section_fields, list(section_fields.keys()))
                }

            overall_rating = round(sum(overall_scores)/len(overall_scores),2) if overall_scores else 0.0

            passport_data = {
                "id": product_id,
                "product_type": tipo_prodotto,
                "metadata": {"created_at": created_at,"version":"EU-DPP-1.0"},
                "sections": sections,
                "overall_rating": overall_rating,
                "espr_compliance": {s: sections[s]["espr_compliance"] for s in sections}
            }

            if st.session_state.uploaded_image_file:
                passport_data["product_image_base64"] = services.image_to_base64(st.session_state.uploaded_image_file)

            services.save_passport_to_file(passport_data)

            public_url = f"{st.secrets['APP_URL']}?passport_id={product_id}"
            qr_buf = services.generate_qr_from_url(public_url)

            st.success("🇪🇺 Digital Product Passport pubblicato")
            st.subheader("📊 Overall Reliability")
            st.progress(overall_rating)
            st.metric("Overall Score", f"{int(overall_rating*100)}%")

            st.subheader("🇪🇺 ESPR Compliance")
            for sec, status in passport_data["espr_compliance"].items():
                icon = {"OK":"🟢","PARTIAL":"🟡","MISSING":"🔴"}[status]
                st.write(f"{icon} **{sec}** → {status}")

            st.subheader("🔗 Accesso pubblico")
            st.image(qr_buf)
            st.code(public_url)
    else:
        st.info("Completa prima la validazione PDF e immagine")
