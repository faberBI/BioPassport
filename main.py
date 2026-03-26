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
    layout="centered"
)

client = OpenAI(api_key=st.secrets["OPEN_AI_KEY"])

# ======================================================
# SESSION STATE
# ======================================================
keys = [
    "pdf_pages", "pdf_data",
    "image_data",
    "cert_data",
    "uploaded_pdf_bytes",
    "uploaded_images_bytes",
    "uploaded_cert_bytes",
    "validated_pdf",
    "validated_image",
    "validated_cert"
]

for k in keys:
    if k not in st.session_state:
        st.session_state[k] = None

# ======================================================
# UI
# ======================================================
st.title("Digital Product Passport")

tipo = st.selectbox("Tipo prodotto", ["mobile", "lampada", "bicicletta"])
fields = [f["name"] for f in services.PRODUCT_FIELDS[tipo]["pdf"]]

tabs = st.tabs(["Upload", "Validazione", "Pubblica"])

# ======================================================
# TAB 1 — UPLOAD + ANALISI
# ======================================================
with tabs[0]:

    pdf_file = st.file_uploader("PDF prodotto", type=["pdf"])
    image_files = st.file_uploader("Immagini", accept_multiple_files=True)
    cert_files = st.file_uploader("Certificati", accept_multiple_files=True)

    if st.button("Analizza"):

        st.session_state.uploaded_pdf_bytes = pdf_file.read()
        st.session_state.uploaded_images_bytes = [i.read() for i in image_files]
        st.session_state.uploaded_cert_bytes = [c.read() for c in cert_files] if cert_files else []

        # ===== PDF =====
        pages = services.extract_text_with_pages(BytesIO(st.session_state.uploaded_pdf_bytes))
        st.session_state.pdf_pages = pages
        st.session_state.pdf_data = services.gpt_extract_from_pdf(pages, client, tipo, fields)

        # ===== IMMAGINI =====
        img_data = {}
        for img in st.session_state.uploaded_images_bytes:
            res = services.gpt_analyze_image(BytesIO(img), client, tipo)
            img_data.update(res)
        st.session_state.image_data = img_data

        # ===== CERTIFICATI =====
        cert_data = []
        for cert in st.session_state.uploaded_cert_bytes:
            res = services.gpt_extract_cert_info(BytesIO(cert), client)
            cert_data.append(res)
        st.session_state.cert_data = cert_data

        st.success("Analisi completata")

    # ======================================================
    # VISUALIZZAZIONE PDF PRODOTTO
    # ======================================================
    if st.session_state.pdf_data and st.session_state.uploaded_pdf_bytes:

        if st.button("Visualizza PDF prodotto evidenziato"):

            highlighted = services.highlight_pdf_fields(
                BytesIO(st.session_state.uploaded_pdf_bytes),
                st.session_state.pdf_data
            )

            b64 = base64.b64encode(highlighted.getvalue()).decode()

            components.html(f"""
            <iframe src="data:application/pdf;base64,{b64}" width="100%" height="600"></iframe>
            """, height=600)

    # ======================================================
    # VISUALIZZAZIONE PDF CERTIFICATI
    # ======================================================
    if st.session_state.cert_data and st.session_state.uploaded_cert_bytes:

        st.subheader("Certificati evidenziati")

        for i, cert_bytes in enumerate(st.session_state.uploaded_cert_bytes):

            cert_fields = st.session_state.cert_data[i]

            highlighted = services.highlight_pdf_fields(
                BytesIO(cert_bytes),
                cert_fields
            )

            b64 = base64.b64encode(highlighted.getvalue()).decode()

            st.markdown(f"**Certificato {i+1}**")

            components.html(f"""
            <iframe src="data:application/pdf;base64,{b64}" width="100%" height="400"></iframe>
            """, height=400)

# ======================================================
# TAB 2 — VALIDAZIONE
# ======================================================
with tabs[1]:

    if st.session_state.pdf_data:

        validated_pdf = {}
        for k, v in st.session_state.pdf_data.items():

            validated_pdf[k] = {
                "value": st.text_input(
                    f"{k} (pag: {v.get('page')})",
                    v.get("value", ""),
                    help=v.get("source_text", "")
                ),
                "confidence": v.get("confidence", 0),
                "page": v.get("page"),
                "source_text": v.get("source_text")
            }

        st.session_state.validated_pdf = validated_pdf

    if st.session_state.image_data:

        validated_img = {}
        for k, v in st.session_state.image_data.items():
            validated_img[k] = {
                "value": st.text_input(k, v.get("value", "")),
                "confidence": v.get("confidence", 0)
            }

        st.session_state.validated_image = validated_img

    if st.session_state.cert_data:

        validated_cert = []
        for i, cert in enumerate(st.session_state.cert_data):
            st.markdown(f"Certificato {i+1}")
            c = {}
            for k, v in cert.items():
                if isinstance(v, dict):
                    c[k] = {
                        "value": st.text_input(f"{k}", v.get("value", ""), key=f"{i}_{k}"),
                        "confidence": v.get("confidence", 0)
                    }
            validated_cert.append(c)

        st.session_state.validated_cert = validated_cert

# ======================================================
# TAB 3 — PUBBLICA
# ======================================================
with tabs[2]:

    if st.session_state.validated_pdf:

        if st.button("Pubblica"):

            pid = f"DPP-{uuid.uuid4().hex[:6]}"

            passport = services.initialize_passport(pid, tipo, fields)

            services.merge_data(
                passport,
                st.session_state.validated_pdf,
                st.session_state.validated_image,
                st.session_state.validated_cert
            )

            # salva
            services.save_passport_to_file(passport)

            # QR
            url = f"{st.secrets['APP_URL']}?passport_id={pid}"
            qr = services.generate_qr_from_url(url)

            st.success("Pubblicato")

            st.image(qr)
            st.code(url)

            # ======================================================
            # METRICHE (FINALMENTE COMPLETE)
            # ======================================================
            st.subheader("Metriche")

            st.metric("Reliability", f"{passport['overall_rating']*100:.0f}%")
            st.metric("Sustainability", f"{passport['sustainability_score']*100:.0f}%")

            # ======================================================
            # EXPLAINABILITY (CORE FEATURE)
            # ======================================================
            st.subheader("Explainability")

            for k, v in passport["sections"]["Technical"]["fields"].items():

                if v.get("value"):
                    st.write(f"**{k}** → {v['value']}")
                    st.caption(f"Pagina: {v.get('page')}")
                    st.caption(f"Source: {v.get('source_text')}")

    else:
        st.info("Completa prima analisi e validazione")
