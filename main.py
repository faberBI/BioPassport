# ===============================
# NUVIA – EU DIGITAL PRODUCT PASSPORT (MOBILE)
# STREAMLIT TEMPLATE ADAPTATION – EU‑READY, AUDIT‑FRIENDLY
# ===============================

# ======================================================
# IMPORTS
# ======================================================
import streamlit as st
import uuid
import json
import os
from datetime import datetime
from openai import OpenAI
from functions import services
from PIL import Image
from io import BytesIO

# ======================================================
# CONFIG STREAMLIT
# ======================================================
st.set_page_config(
    page_title="Nuvia Digital Product Passport",
    page_icon="functions/favicon.jpeg",
    layout="centered"
)

client = OpenAI(api_key=st.secrets["OPEN_AI_KEY"])

# ======================================================
# EU‑READY MOBILE SCHEMA
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
# RATING LOGIC
# ======================================================

def rate_field(field):
    if not field.get("value"):
        return 0.0
    weight = {
        "technical": 1.0,
        "declaration": 0.6,
        "lca": 0.5,
        "visual": 0.4
    }.get(field.get("field_type"), 0.5)
    return round(field.get("confidence", 0.0) * weight, 2)


def compute_overall_rating(sections):
    scores = []
    for section in sections.values():
        for field in section.values():
            scores.append(rate_field(field))
    return round(sum(scores) / len(scores), 2) if scores else 0.0

# ======================================================
# ROUTING (QR → PAGINA PUBBLICA)
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
    **Version:** {passport['metadata']['schema_version']}
    """)

    st.subheader("📊 DPP Reliability Score")
    st.progress(passport["overall_rating"])
    st.metric("Affidabilità complessiva", f"{int(passport['overall_rating']*100)}%")

    for section, fields in passport["sections"].items():
        st.divider()
        st.subheader(section.replace("_", " ").title())
        for name, data in fields.items():
            score = rate_field(data)
            st.write(f"**{name}**: {data['value']}")
            st.progress(score)
            st.caption(f"Affidabilità campo: {int(score*100)}%")

    st.stop()

# ======================================================
# BACKOFFICE
# ======================================================
for k in ["pdf_structured", "validated_sections"]:
    if k not in st.session_state:
        st.session_state[k] = None

tabs = st.tabs([
    "📤 Upload & Analisi",
    "📝 Validazione",
    "🔗 Pubblica DPP"
])

# ======================================================
# TAB 1 — UPLOAD & GPT
# ======================================================
with tabs[0]:
    with st.form("upload_form"):
        pdf_file = st.file_uploader("PDF prodotto", type=["pdf"])
        submitted = st.form_submit_button("🔍 Analizza")

        if submitted:
            if not pdf_file:
                st.warning("Carica un PDF")
            else:
                with st.spinner("Analisi in corso ⏳…"):
                    pdf_text = services.extract_text_from_pdf(pdf_file)
                    raw = services.gpt_extract_mobile_structured(pdf_text, client)
                    st.session_state.pdf_structured = services.normalize_mobile_schema(raw)
                st.success("Analisi completata")

# ======================================================
# TAB 2 — VALIDAZIONE
# ======================================================
with tabs[1]:
    if st.session_state.pdf_structured:
        validated = {}
        for section, fields in st.session_state.pdf_structured.items():
            st.subheader(section.upper())
            validated[section] = {}
            for name, data in fields.items():
                val = st.text_input(name, data.get("value") or "")
                validated[section][name] = {
                    **data,
                    "value": val,
                    "human_validated": True
                }
        st.session_state.validated_sections = validated
    else:
        st.info("Esegui prima l’analisi")

# ======================================================
# TAB 3 — PUBBLICAZIONE DPP + QR
# ======================================================
with tabs[2]:
    if st.session_state.validated_sections:
        if st.button("🚀 Pubblica Digital Product Passport"):
            overall = compute_overall_rating(st.session_state.validated_sections)

            passport = {
                "id": f"MOBILE-{uuid.uuid4().hex[:8]}",
                "product_type": "mobile",
                "metadata": {
                    "created_at": datetime.utcnow().isoformat(),
                    "schema_version": "EU-DPP-2026-01"
                },
                "sections": st.session_state.validated_sections,
                "overall_rating": overall
            }

            services.save_passport_to_file(passport)

            public_url = f"{st.secrets['APP_URL']}?passport_id={passport['id']}"
            qr_buf = services.generate_qr_from_url(public_url)

            st.success("Digital Product Passport pubblicato ✅")
            st.image(qr_buf)
            st.code(public_url)
    else:
        st.info("Completa la validazione")
