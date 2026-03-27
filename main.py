import streamlit as st
import uuid
from openai import OpenAI
from functions import services
from PIL import Image
import os
import pandas as pd
import base64
from io import BytesIO
import streamlit.components.v1 as components

# ======================================================
# CONFIG
# ======================================================
st.set_page_config(
    page_title="Nuvia Digital Product Passport",
    page_icon="functions/favicon.jpeg",
    layout="centered"
)

# ======================================================
# UI / LOGO
# ======================================================
logo = Image.open("functions/logo_nuvia.jpeg")
logo_base64 = services.image_to_base64(logo)

st.markdown(f"""
<style>
body {{background-color:#f5f1ed; color:#3a2607; font-family:Nunito Sans;}}
.stButton>button {{background-color:#25ce6c; color:white; border-radius:8px;}}
.required-field {{color:#d9534f; font-weight:bold;}}
</style>
<img src="data:image/jpeg;base64,{logo_base64}" width="320">
""", unsafe_allow_html=True)

client = OpenAI(api_key=st.secrets["OPEN_AI_KEY"])

# ======================================================
# SESSION STATE
# ======================================================
defaults = [
    "uploaded_pdf_bytes","uploaded_images_bytes","uploaded_cert_bytes",
    "pdf_data","image_data","cert_data",
    "validated_pdf","validated_image","validated_cert",
    "passport_signature","cert_validation"
]

for k in defaults:
    if k not in st.session_state:
        st.session_state[k] = None

# ======================================================
# PUBLIC VIEW
# ======================================================
passport_id = st.query_params.get("passport_id")

if passport_id:
    passport = services.load_passport_from_file(passport_id)

    if not passport:
        st.error("Passport non trovato")
        st.stop()

    st.title("Digital Product Passport")

    # FIRMA
    if services.verify_passport_signature(passport):
        st.success("Firma valida")
    else:
        st.error("Firma NON valida")

    st.write(passport["id"], passport["product_type"])

    # CERTIFICATI
    if passport.get("certificates"):
        valid = services.verify_certificates(passport["certificates"])
        st.info(f"Certificati validi: {valid*100:.0f}%")

    st.progress(passport.get("overall_rating", 0))

    st.stop()

# ======================================================
# APP EDITOR
# ======================================================
tipo = st.selectbox("Tipo prodotto", ["mobile","lampada","bicicletta"])
fields = [f["name"] for f in services.PRODUCT_FIELDS[tipo]["pdf"]]

tabs = st.tabs(["Upload","Validazione","Pubblica","Archivio"])

# ======================================================
# TAB 1 — ANALISI
# ======================================================
with tabs[0]:

    pdf = st.file_uploader("PDF", type=["pdf"])
    imgs = st.file_uploader("Immagini", accept_multiple_files=True)
    certs = st.file_uploader("Certificati", accept_multiple_files=True)

    if st.button("Analizza"):

        if not pdf or not imgs:
            st.warning("Carica PDF e immagini")
            st.stop()

        st.session_state.uploaded_pdf_bytes = pdf.read()
        st.session_state.uploaded_images_bytes = [i.read() for i in imgs]
        st.session_state.uploaded_cert_bytes = [c.read() for c in certs] if certs else []

        with st.spinner("AI in corso..."):

            text = services.extract_text_from_pdf(BytesIO(st.session_state.uploaded_pdf_bytes))
            st.session_state.pdf_data = services.gpt_extract_from_pdf(text, client, tipo, fields)

            img_data = {}
            for b in st.session_state.uploaded_images_bytes:
                img_data.update(services.gpt_analyze_image(BytesIO(b), client, tipo))
            st.session_state.image_data = img_data

            certs_data = []
            for b in st.session_state.uploaded_cert_bytes:
                certs_data.append(services.gpt_extract_cert_info(BytesIO(b), client))
            st.session_state.cert_data = certs_data

        st.success("Analisi completata")

# ======================================================
# TAB 2 — VALIDAZIONE (aggiornato sicuro)
# ======================================================
with tabs[1]:
    if st.session_state.pdf_data or st.session_state.image_data or st.session_state.cert_data:
        # --------- Validazione dati PDF ---------
        if st.session_state.pdf_data:
            st.subheader("Validazione dati PDF")
            validated_pdf = {}
            for k, v in st.session_state.pdf_data.items():
                val = v.get("value", "") if isinstance(v, dict) else str(v)
                conf = v.get("confidence", 0) if isinstance(v, dict) else 0
                explanation = v.get("explanation", "") if isinstance(v, dict) else ""
                validated_pdf[k] = {
                    "value": st.text_input(f"{k} (conf: {conf})", val, help=explanation),
                    "confidence": conf
                }
            st.session_state.validated_pdf = validated_pdf

        # --------- Validazione dati Immagini ---------
        if st.session_state.image_data:
            st.subheader("Validazione dati Immagini")
            validated_img = {}
            for k, v in st.session_state.image_data.items():
                val = v.get("value", "") if isinstance(v, dict) else str(v)
                conf = v.get("confidence", 0) if isinstance(v, dict) else 0
                explanation = v.get("explanation", "") if isinstance(v, dict) else ""
                validated_img[k] = {
                    "value": st.text_input(f"{k} (conf: {conf})", val, help=explanation),
                    "confidence": conf
                }
            st.session_state.validated_image = validated_img

        # --------- Validazione certificati ---------
        if st.session_state.cert_data:
            st.subheader("Validazione certificati")
            validated_cert_list = []
            for i, cert in enumerate(st.session_state.cert_data):
                validated_cert = {}
                st.markdown(f"**Certificato {i+1}**")
                for k, v in cert.items():
                    val = v.get("value", "") if isinstance(v, dict) else str(v)
                    conf = v.get("confidence", 0) if isinstance(v, dict) else 0
                    validated_cert[k] = {
                        "value": st.text_input(f"{k} (conf: {conf})", val, key=f"cert_{i}_{k}"),
                        "confidence": conf
                    }
                validated_cert_list.append(validated_cert)
            st.session_state.validated_cert = validated_cert_list

        # --------- Bottone completa validazione ---------
        if st.button("Completa validazione"):
            st.success("Validazione completata ✅")

    else:
        st.info("Esegui prima l’analisi PDF, immagini o certificati")success("Campi obbligatori OK")

# ======================================================
# TAB 3 — PUBBLICA
# ======================================================
with tabs[2]:

    if not st.session_state.validated_pdf:
        st.info("Completa validazione")
        st.stop()

    # CHECK BLOCCANTI
    missing = services.check_required_fields(st.session_state.validated_pdf, tipo)

    if missing:
        st.error("Non puoi pubblicare")
        st.stop()

    if st.session_state.cert_validation and st.session_state.cert_validation < 0.5:
        st.error("Certificati non validi")
        st.stop()

    if st.button("Pubblica"):

        pid = f"{tipo}-{uuid.uuid4().hex[:6]}"

        passport = services.initialize_passport(pid, tipo, fields)

        services.merge_data(
            passport,
            st.session_state.validated_pdf,
            st.session_state.validated_image,
            st.session_state.validated_cert
        )

        # FIRMA
        passport["signature"] = services.sign_passport(passport)

        # VERIFY
        if not services.verify_passport_signature(passport):
            st.error("Errore firma")
            st.stop()

        # SALVA
        services.save_passport_to_file(passport)
        services.save_passport_to_excel_append(passport)

        st.success("Pubblicato")

        st.write("Firma:", passport["signature"][:20], "...")

# ======================================================
# TAB 4 — ARCHIVIO
# ======================================================
with tabs[3]:

    if os.path.exists(services.EXCEL_FILE):

        df = pd.read_excel(services.EXCEL_FILE, sheet_name="passport")

        st.dataframe(df)

    else:
        st.info("Nessun dato")
