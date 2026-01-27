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
    page_title="EU Digital Product Passport",
    layout="centered"
)

# ======================================================
# STILE GLOBALE + LOGO
# ======================================================
# Carica logo
logo = Image.open("functions/logo_nuvia.jpeg")  # sostituisci con il tuo percorso
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

/* Logo centrato in cima */
div[data-testid="stAppViewContainer"] > div:first-child {{
    display: flex;
    justify-content: center;
    margin-bottom: 20px;
}}
</style>

<div style="text-align:center; margin-bottom: 20px;">
    <img src="data:image/jpeg;base64,{logo_base64}" width="200">
</div>
""", unsafe_allow_html=True)

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
        if k != "immagine_base64":
            st.write(f"**{k}**: {v}")

    # Mostra immagine se presente
    if "immagine_base64" in passport["data_source_image"]:
        st.image(
            f"data:image/jpeg;base64,{passport['data_source_image']['immagine_base64']}",
            caption="Foto prodotto",
            use_column_width=True
        )

    st.caption(
        "Public read-only Digital Product Passport. "
        "Generated via AI extraction and human validation."
    )

    st.stop()

# ======================================================
# BACKOFFICE
# ======================================================
for k in ["pdf_data", "image_data", "validated_pdf", "validated_image", "uploaded_image_file"]:
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
                    # Estrai testo PDF
                    pdf_text = services.extract_text_from_pdf(pdf_file)
                    st.session_state.pdf_data = services.gpt_extract_from_pdf(
                        pdf_text, client, tipo_prodotto
                    )

                    # Salva immagine caricata per pubblicazione
                    st.session_state.uploaded_image_file = image_file
                    # CONVERTI IN BASE64 PRIMA DI PASSARE A GPT
                    st.session_state.image_data = services.gpt_analyze_image(
                    image_file, client, tipo_prodotto
                    )
                st.success("Analisi completata")
                st.info("I dati sono stati estratti e popolati automaticamente nei form di validazione.")

# ======================================================
# TAB 2 — VALIDAZIONE PDF
# ======================================================
with tabs[1]:
    if st.session_state.pdf_data:
        # Chiama la nuova funzione
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

        # Mostra immagine caricata
        if st.session_state.uploaded_image_file:
            st.image(
                st.session_state.uploaded_image_file,
                caption="Foto prodotto",
                use_column_width=True
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
                "data_source_image": st.session_state.validated_image.copy()
            }

            # Salva anche immagine Base64
            if st.session_state.uploaded_image_file:
                passport_data["data_source_image"]["immagine_base64"] = services.image_to_base64(
                    st.session_state.uploaded_image_file
                )

            services.save_passport_to_file(passport_data)

            # URL pubblico (metti l’URL della tua app in st.secrets['APP_URL'])
            public_url = f"{st.secrets['APP_URL']}?passport_id={product_id}"
            qr_buf = services.generate_qr_from_url(public_url)

            st.success("Digital Product Passport pubblicato ✅")
            st.subheader("🔗 Accesso pubblico")
            st.image(qr_buf)
            st.code(public_url)

    else:
        st.info("Completa validazione PDF e immagine")
