import streamlit as st
import uuid
from openai import OpenAI
from PIL import Image
from functions import services
from io import BytesIO

# ======================================================
# CONFIG STREAMLIT
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
</style>
<img src="data:image/jpeg;base64,{logo_base64}" width="350">
""", unsafe_allow_html=True)

client = OpenAI(api_key=st.secrets["OPEN_AI_KEY"])

# ======================================================
# SESSION STATE
# ======================================================
keys = ["uploaded_pdf", "uploaded_images", "pdf_data", "image_data", 
        "validated_pdf", "validated_image"]
for k in keys:
    if k not in st.session_state:
        st.session_state[k] = None

# ======================================================
# VISUALIZZAZIONE PUBBLICA
# ======================================================
passport_id = st.query_params.get("passport_id")
if passport_id:
    passport = services.load_passport_from_file(passport_id)
    if not passport:
        st.error("Passport non trovato")
        st.stop()

    st.title("🇪🇺 Digital Product Passport")
    st.write(f"**ID:** {passport['id']}")
    st.write(f"**Tipo:** {passport['product_type']}")
    
    for sec_name, sec in passport["sections"].items():
        st.subheader(f"{sec_name} ({sec['section_rating']*100:.0f}%)")
        for fname, f in sec["fields"].items():
            st.write(f"**{fname}**: {f['value']} {f['color']}")
            if f.get("explanation"):
                st.caption(f["explanation"])

    services.render_espr_compliance(passport)

    st.progress(passport["overall_rating"])
    st.metric("Reliability", f"{int(passport['overall_rating']*100)}%")

    if passport["images"]:
        for img in passport["images"]:
            st.image(f"data:image/jpeg;base64,{img['file_base64']}")

    st.stop()

# ======================================================
# SELEZIONE TIPO PRODOTTO
# ======================================================
tipo = st.selectbox("Tipo prodotto", ["mobile", "lampada", "bicicletta"])
fields = [f["name"] for f in services.PRODUCT_FIELDS[tipo]["pdf"]]

tabs = st.tabs(["Upload & AI", "Validazione PDF", "Validazione Immagine", "Pubblica"])

# ======================================================
# TAB 1 — UPLOAD + AI
# ======================================================
with tabs[0]:
    uploaded_pdf = st.file_uploader("PDF prodotto", type=["pdf"])
    uploaded_images = st.file_uploader(
        "Immagini prodotto (più file)", 
        type=["jpg","png","jpeg"], 
        accept_multiple_files=True
    )

    if st.button("🔍 Analizza"):
        if not uploaded_pdf or not uploaded_images:
            st.warning("Carica PDF e almeno un'immagine")
        else:
            st.session_state.uploaded_pdf = uploaded_pdf
            st.session_state.uploaded_images = uploaded_images

            with st.spinner("Analisi in corso..."):

                # --- PDF ---
                pdf_text = services.extract_text_from_pdf(uploaded_pdf)
                st.session_state.pdf_data = services.gpt_extract_from_pdf(
                    pdf_text, client, tipo, fields
                )

                # --- IMAGE ---
                image_data = {}
                for img in uploaded_images:
                    image_data.update(services.gpt_analyze_image(img, client, tipo))
                st.session_state.image_data = image_data

            st.success("Analisi completata. Vai alle schede di validazione.")

# ======================================================
# TAB 2 — VALIDAZIONE PDF
# ======================================================
with tabs[1]:
    if st.session_state.pdf_data:
        st.subheader("📄 Validazione PDF")
        validated_pdf = {}
        for k, v in st.session_state.pdf_data.items():
            val = v["value"] if isinstance(v, dict) else v
            conf = v.get("confidence", 0)
            expl = v.get("explanation", "")
            validated_pdf[k] = st.text_input(
                f"{k} (conf: {conf}, {expl})",
                value="" if val is None else str(val)
            )
        st.session_state.validated_pdf = validated_pdf
    else:
        st.info("Esegui prima l’analisi PDF.")

# ======================================================
# TAB 3 — VALIDAZIONE IMMAGINE
# ======================================================
with tabs[2]:
    if st.session_state.image_data:
        st.subheader("👁️ Validazione Immagine")
        validated_image = {}
        for k, v in st.session_state.image_data.items():
            val = v["value"] if isinstance(v, dict) else v
            conf = v.get("confidence", 0)
            expl = v.get("explanation", "")
            validated_image[k] = st.text_input(
                f"{k} (conf: {conf}, {expl})",
                value="" if val is None else str(val)
            )
        st.session_state.validated_image = validated_image

        # Mostra le immagini caricate
        for idx, img in enumerate(st.session_state.uploaded_images):
            st.image(img, caption=f"Immagine prodotto {idx+1}", use_column_width=True)
    else:
        st.info("Esegui prima l’analisi immagini.")

# ======================================================
# TAB 4 — PUBBLICA
# ======================================================
with tabs[3]:
    if st.session_state.validated_pdf and st.session_state.validated_image:
        if st.button("🚀 Pubblica DPP"):

            pid = f"{tipo.upper()}-{uuid.uuid4().hex[:6]}"
            passport = services.initialize_passport(pid, tipo, fields)

            # --- Merge PDF + Image ---
            services.merge_data(passport, st.session_state.validated_pdf, st.session_state.validated_image)

            # --- Aggiungi immagini ---
            for img in st.session_state.uploaded_images:
                services.add_product_image(passport, img)

            # --- Salvataggio file + Access DB ---
            services.save_passport_to_file(passport)
            services.save_passport_to_access(passport)

            # --- QR pubblico ---
            public_url = f"{st.secrets['APP_URL']}?passport_id={pid}"
            qr_buf = services.generate_qr_from_url(public_url)

            st.success("🇪🇺 Digital Product Passport pubblicato ✅")

            # --- ESPR & Reliability ---
            services.render_espr_compliance(passport)
            st.progress(passport["overall_rating"])
            st.metric("Data Reliability", f"{int(passport['overall_rating']*100)}%")

            # --- PDF evidenziato ---
            if st.button("📄 Scarica PDF evidenziato"):
                terms = list(st.session_state.validated_pdf.values()) + list(st.session_state.validated_image.values())
                highlighted_pdf = services.highlight_pdf_terms(st.session_state.uploaded_pdf, terms)
                st.download_button("Download PDF evidenziato", highlighted_pdf, file_name="highlighted.pdf")

            st.image(qr_buf)
            st.code(public_url)
    else:
        st.info("Completa validazione PDF e immagini prima di pubblicare.")
