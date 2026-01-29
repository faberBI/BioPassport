import streamlit as st
import uuid
from datetime import datetime
from openai import OpenAI
from functions import services
from PIL import Image
from io import BytesIO
import base64

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

.stButton>button {{
    background-color: #25ce6c;
    color: white;
    border-radius: 8px;
    border: none;
}}

</style>

<div style="display:flex; align-items:center; gap:15px; margin-bottom:20px;">
    <img src="data:image/jpeg;base64,{logo_base64}" width="450">
</div>
""", unsafe_allow_html=True)

client = OpenAI(api_key=st.secrets["OPEN_AI_KEY"])

# ======================================================
# ROUTING PUBBLICO
# ======================================================
passport_id = st.query_params.get("passport_id")

if passport_id:
    passport = services.load_passport_from_file(passport_id)
    if not passport:
        st.error("Digital Product Passport not found")
        st.stop()

    # Nascondi UI backoffice
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

    st.divider()
    st.subheader("1️⃣ Product Identity (Certified)")
    for k, v in passport["sections"].get("identity", {}).get("fields", {}).items():
        st.write(f"{v.get('color','')} **{k}**: {v.get('value','')}")

    st.divider()
    st.subheader("2️⃣ Materials / Sustainability / End-of-Life")
    for section, content in passport["sections"].items():
        st.write(f"**{section}** (ESPR: {passport['sections'][section]['espr_compliance']})")
        for k, v in content["fields"].items():
            st.write(f"{v.get('color','')} **{k}**: {v.get('value','')}")

    if passport.get("product_image_base64"):
        st.image(f"data:image/jpeg;base64,{passport['product_image_base64']}", caption="Foto prodotto")

    st.caption("Public read-only Digital Product Passport. AI extraction + human validation.")
    st.stop()

# ======================================================
# BACKOFFICE INIT
# ======================================================
for k in ["pdf_data", "image_data", "validated_pdf", "validated_image", "uploaded_image_file"]:
    if k not in st.session_state:
        st.session_state[k] = None

tipo_prodotto = st.selectbox("Seleziona tipo prodotto", ["mobile", "lampada", "bicicletta"])

tabs = st.tabs([
    "📤 Upload & Analisi",
    "📝 Validazione PDF",
    "👁️ Validazione Immagine",
    "🔗 Pubblica DPP"
])

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
                st.info("Dati estratti e popolati automaticamente nei form.")

# ======================================================
# TAB 2 — VALIDAZIONE PDF
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
# TAB 3 — VALIDAZIONE IMMAGINE
# ======================================================
with tabs[2]:
    if st.session_state.image_data:
        st.session_state.validated_image = services.render_validation_form(
            st.session_state.image_data,
            title="👁️ Dati estratti da immagine"
        )
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

            # Merge PDF + IMAGE (PDF prioritario)
            merged = {**st.session_state.validated_image, **st.session_state.validated_pdf}

            sections = {}
            overall_scores = []
            espr_summary = {}

            for section_name, section_schema in services.PRODUCT_FIELDS[tipo_prodotto]["pdf"].items():
                # section_schema rimane come lista di campi obbligatori per semplicità
                section_fields = {}
                for field_name in section_schema:
                    field_value = merged.get(field_name, None)
                    field_data = {
                        "value": field_value,
                        "confidence": 1.0 if field_value else 0.0,
                        "field_type": "technical",
                        "source": "pdf" if field_name in st.session_state.validated_pdf else "image"
                    }
                    rating = services.compute_field_rating(field_data)
                    color = services.score_to_color(rating)
                    field_data["rating"] = rating
                    field_data["color"] = color
                    section_fields[field_name] = field_data
                    overall_scores.append(rating)

                # ESPR compliance per sezione
                espr_status = services.compute_espr_compliance(section_fields,
                                                               {f: {"required": True} for f in section_schema})
                espr_summary[section_name] = espr_status

                sections[section_name] = {
                    "fields": section_fields,
                    "espr_compliance": espr_status
                }

            overall_rating = round(sum(overall_scores)/len(overall_scores), 2) if overall_scores else 0.0

            # Passport finale
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
                passport_data["product_image_base64"] = services.image_to_base64(st.session_state.uploaded_image_file)

            services.save_passport_to_file(passport_data)

            # QR + URL
            public_url = f"{st.secrets['APP_URL']}?passport_id={product_id}"
            qr_buf = services.generate_qr_from_url(public_url)

            st.success("🇪🇺 Digital Product Passport pubblicato ✅")
            st.subheader("📊 Affidabilità complessiva")
            st.progress(overall_rating)
            st.metric("Overall Reliability Score", f"{int(overall_rating*100)}%")

            st.subheader("🇪🇺 ESPR Compliance Summary")
            for section, status in espr_summary.items():
                icon = {"OK":"🟢","PARTIAL":"🟡","MISSING":"🔴"}.get(status,"🔴")
                st.write(f"{icon} **{section.upper()}** → {status}")

            st.subheader("🔗 Accesso pubblico")
            st.image(qr_buf)
            st.code(public_url)
    else:
        st.info("Completa prima la validazione PDF e immagine")
