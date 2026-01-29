# ===============================
# NUVIA – EU DIGITAL PRODUCT PASSPORT (MOBILE)
# EU‑READY, REFATTORED, AUDIT‑FRIENDLY
# ===============================

import streamlit as st
import uuid
from datetime import datetime
from openai import OpenAI
from functions import services
from PIL import Image
from io import BytesIO
import json

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
h1, h2, h3, h4, h5, h6 {{ color: #3a2607; }}
.stButton>button {{
    background-color: #25ce6c;
    color: white;
    border-radius: 8px;
    border: none;
}}
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

# ======================================================
# OPENAI CLIENT
# ======================================================
client = OpenAI(api_key=st.secrets["OPEN_AI_KEY"])

# ======================================================
# MOBILE EU-READY SCHEMA
# ======================================================
MOBILE_SCHEMA = {
    "identity": {
        "Nome prodotto": {"type": "technical", "required": True},
        "Produttore": {"type": "technical", "required": True},
        "Numero di modello": {"type": "technical", "required": True},
        "Anno di produzione": {"type": "technical", "required": False}
    },
    "materials": {
        "Materiali": {"type": "technical", "required": True},
        "% contenuto riciclato": {"type": "declaration", "required": False},
        "Sostanze preoccupanti": {"type": "declaration", "required": False}
    },
    "sustainability": {
        "Certificazione di sostenibilità": {"type": "declaration", "required": False},
        "Impronta carbonio GWP": {"type": "lca", "required": False}
    },
    "end_of_life": {
        "Gestione fine vita (CER)": {"type": "declaration", "required": False}
    }
}

# ======================================================
# BACKOFFICE SESSION STATE
# ======================================================
for k in ["pdf_data", "image_data", "validated_pdf", "validated_image", "uploaded_image_file"]:
    if k not in st.session_state:
        st.session_state[k] = None

tipo_prodotto = st.selectbox(
    "Seleziona tipo prodotto",
    ["mobile"]
)

tabs = st.tabs([
    "📤 Upload & Analisi",
    "📝 Validazione PDF",
    "👁️ Validazione Immagine",
    "🔗 Pubblica DPP"
])

# ======================================================
# FUNZIONI UTILI
# ======================================================
def compute_field_rating(field):
    if not field.get("value"):
        return 0.0
    weight = {
        "technical": 1.0,
        "declaration": 0.6,
        "lca": 0.5,
        "visual": 0.4
    }.get(field.get("field_type"), 0.5)
    return round(field.get("confidence", 0.0) * weight, 2)

def score_to_color(score):
    if score >= 0.66: return "🟢"
    elif score >= 0.33: return "🟡"
    return "🔴"

def compute_espr_compliance(section_data, section_schema):
    required_fields = [f for f, meta in section_schema.items() if meta.get("required")]
    present_required = sum(1 for f in required_fields if section_data.get(f, {}).get("value"))
    scores = [compute_field_rating(f) for f in section_data.values()]
    avg_score = sum(scores)/len(scores) if scores else 0.0
    if present_required == len(required_fields) and avg_score >= 0.6:
        return "OK"
    elif present_required > 0 or avg_score >= 0.3:
        return "PARTIAL"
    else:
        return "MISSING"

def compute_overall_rating(sections):
    scores = []
    for section in sections.values():
        for field in section["fields"].values():
            scores.append(field.get("rating",0))
    return round(sum(scores)/len(scores),2) if scores else 0.0

# ======================================================
# TAB 1 – UPLOAD & ANALISI
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
                with st.spinner("Analisi in corso..."):
                    st.session_state.pdf_data = services.gpt_extract_from_pdf(
                        pdf_file, client, tipo_prodotto
                    )
                    st.session_state.uploaded_image_file = image_file
                    st.session_state.image_data = services.gpt_analyze_image(
                        image_file, client, tipo_prodotto
                    )
                st.success("Analisi completata")
                st.info("Dati estratti automaticamente nei form di validazione.")

# ======================================================
# TAB 2 – VALIDAZIONE PDF
# ======================================================
with tabs[1]:
    if st.session_state.pdf_data:
        st.session_state.validated_pdf = services.render_validation_form(
            st.session_state.pdf_data,
            title="✔ Dati certificati (PDF)"
        )
    else:
        st.info("Esegui prima l’analisi")

# ======================================================
# TAB 3 – VALIDAZIONE IMMAGINE
# ======================================================
with tabs[2]:
    if st.session_state.image_data:
        st.session_state.validated_image = services.render_validation_form(
            st.session_state.image_data,
            title="👁️ Dati estratti da immagine"
        )
        if st.session_state.uploaded_image_file:
            st.image(
                st.session_state.uploaded_image_file,
                caption="Foto prodotto",
                use_column_width=True
            )
    else:
        st.info("Esegui prima l’analisi")

# ======================================================
# TAB 4 – PUBBLICAZIONE DPP (EU-READY)
# ======================================================
with tabs[3]:
    if st.session_state.validated_pdf and st.session_state.validated_image:
        if st.button("🚀 Pubblica Digital Product Passport"):

            product_id = f"MOBILE-{uuid.uuid4().hex[:8]}"
            created_at = datetime.utcnow().isoformat()

            # unisci PDF + image
            merged_data = {**st.session_state.validated_image, **st.session_state.validated_pdf}

            sections = {}
            espr_summary = {}
            overall_scores = []

            for section_name, section_schema in MOBILE_SCHEMA.items():
                section_fields = {}
                for field_name, meta in section_schema.items():
                    field = merged_data.get(field_name, {"value": None, "confidence": 0.0, "field_type": meta["type"], "source": "unknown"})
                    rating = compute_field_rating(field)
                    color = score_to_color(rating)
                    section_fields[field_name] = {
                        "value": field.get("value"),
                        "confidence": field.get("confidence",0.0),
                        "field_type": field.get("field_type"),
                        "source": field.get("source"),
                        "rating": rating,
                        "color": color
                    }
                    overall_scores.append(rating)

                compliance = compute_espr_compliance(section_fields, section_schema)
                sections[section_name] = {"fields": section_fields, "espr_compliance": compliance}
                espr_summary[section_name] = compliance

            overall_rating = round(sum(overall_scores)/len(overall_scores),2) if overall_scores else 0.0

            passport_data = {
                "id": product_id,
                "product_type": tipo_prodotto,
                "metadata": {
                    "created_at": created_at,
                    "schema_version": "EU-DPP-2026-01",
                    "regulation": "ESPR",
                    "ai_generated": True
                },
                "sections": sections,
                "espr_compliance": espr_summary,
                "overall_rating": overall_rating
            }

            if st.session_state.uploaded_image_file:
                passport_data["product_image_base64"] = services.image_to_base64(
                    st.session_state.uploaded_image_file
                )

            services.save_passport_to_file(passport_data)

            public_url = f"{st.secrets['APP_URL']}?passport_id={product_id}"
            qr_buf = services.generate_qr_from_url(public_url)

            st.success("🇪🇺 Digital Product Passport pubblicato con successo")
            st.subheader("📊 Affidabilità complessiva")
            st.progress(overall_rating)
            st.metric("Overall Reliability Score", f"{int(overall_rating*100)}%")

            st.subheader("🇪🇺 ESPR Compliance Summary")
            for section, status in espr_summary.items():
                icon = {"OK":"🟢","PARTIAL":"🟡","MISSING":"🔴"}[status]
                st.write(f"{icon} **{section.upper()}** → {status}")

            st.subheader("🔗 Accesso pubblico")
            st.image(qr_buf)
            st.code(public_url)

    else:
        st.info("Completa prima la validazione PDF e immagine")
