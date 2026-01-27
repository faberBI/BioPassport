import streamlit as st
import uuid
from datetime import datetime
from openai import OpenAI
from functions import services

# ======================================================
# CONFIG
# ======================================================
st.set_page_config(
    page_title="EU Digital Product Passport",
    layout="centered"
)

client = OpenAI(api_key=st.secrets["OPEN_AI_KEY"])

# ======================================================
# ROUTING (QR → PAGINA PUBBLICA)
# ======================================================
passport_id = st.query_params.get("passport_id")

if passport_id:
    passport = services.load_passport_from_file(passport_id)

    if not passport:
        st.error("Digital Product Passport not found")
        st.stop()

    # NASCONDI UI STREAMLIT
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

    st.subheader("1️⃣ Product Identity (Certified)")
    for k, v in passport["data_source_pdf"].items():
        st.write(f"**{k}**: {v}")

    st.divider()

    st.subheader("2️⃣ Visual / Estimated Information")
    for k, v in passport["data_source_image"].items():
        st.write(f"**{k}**: {v}")

    st.caption(
        "Public read-only Digital Product Passport. "
        "Generated via AI extraction and human validation."
    )

    st.stop()

# ======================================================
# BACKOFFICE
# ======================================================

# SESSION STATE
for k in ["pdf_data", "image_data", "validated_pdf", "validated_image"]:
    if k not in st.session_state:
        st.session_state[k] = None

st.sidebar.title("🛠 Backoffice")
st.sidebar.info("EU Digital Product Passport")

st.title("🪑 Digital Product Passport – Backoffice")

tipo_prodotto = st.selectbox(
    "Seleziona tipo prodotto",
    ["mobile", "lampada", "bicicletta"]
)

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
                with st.spinner("Analisi GPT in corso…"):
                    pdf_text = services.extract_text_from_pdf(pdf_file)
                    st.session_state.pdf_data = services.gpt_extract_from_pdf(
                        pdf_text, client, tipo_prodotto
                    )

                    st.session_state.image_data = services.gpt_analyze_image(
                        image_file, client, tipo_prodotto
                    )

                st.success("Analisi completata")

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
            title="👁️ Dati stimati da immagine"
        )
    else:
        st.info("Esegui prima l’analisi")

# ======================================================
# TAB 4 — PUBBLICAZIONE DPP
# ======================================================
with tabs[3]:
    if st.session_state.validated_pdf and st.session_state.validated_image:

        if st.button("🚀 Pubblica Digital Product Passport"):

            product_id = f"{tipo_prodotto.upper()}-{uuid.uuid4().hex[:8]}"

            passport_data = {
                "id": product_id,
                "product_type": tipo_prodotto,
                "metadata": {
                    "created_at": datetime.utcnow().isoformat(),
                    "version": "EU-DPP-1.0"
                },
                "data_source_pdf": st.session_state.validated_pdf,
                "data_source_image": st.session_state.validated_image
            }

            # Salva su file
            services.save_passport_to_file(passport_data)

            # URL pubblico
            try:
                app_url = st.secrets["APP_URL"]
            except KeyError:
                st.error("Devi aggiungere APP_URL in st.secrets, ad esempio https://nome-tuo-app.streamlit.app")
                st.stop()

            public_url = f"{app_url}?passport_id={product_id}"
            qr_buf = services.generate_qr_from_url(public_url)

            st.success("Digital Product Passport pubblicato")
            st.subheader("🔗 Accesso pubblico")
            st.image(qr_buf)
            st.code(public_url)

    else:
        st.info("Completa validazione PDF e immagine")
