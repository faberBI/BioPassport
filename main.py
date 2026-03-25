import streamlit as st
import uuid
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
keys = ["pdf_data","image_data","validated_pdf","validated_image","images"]
for k in keys:
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
# PRODUCT TYPE
# ======================================================
tipo = st.selectbox("Tipo prodotto", ["mobile","lampada","bicicletta"])

# fields dinamici
fields = [f["name"] for f in services.PRODUCT_FIELDS[tipo]["pdf"]]

tabs = st.tabs(["Upload","Validazione","Pubblica"])

# ======================================================
# TAB 1 — UPLOAD + AI
# ======================================================
with tabs[0]:

    pdf = st.file_uploader("PDF", type=["pdf"])
    images = st.file_uploader("Immagini", type=["jpg","png"], accept_multiple_files=True)

    if st.button("Analizza"):

        if not pdf or not images:
            st.warning("Carica PDF e immagini")
        else:
            with st.spinner("Analisi..."):

                # PDF (chunked + confidence)
                text = services.extract_text_from_pdf(pdf)
                st.session_state.pdf_data = services.gpt_extract_from_pdf(
                    text, client, tipo, fields
                )

                # IMAGE (enhanced)
                img_data = {}
                for img in images:
                    res = services.gpt_analyze_image(img, client, tipo)
                    img_data.update(res)

                st.session_state.image_data = img_data
                st.session_state.images = images

            st.success("Analisi completata")

# ======================================================
# TAB 2 — VALIDAZIONE
# ======================================================
with tabs[1]:

    if st.session_state.pdf_data:

        st.subheader("PDF")

        validated_pdf = {}
        for k,v in st.session_state.pdf_data.items():
            val = v["value"] if isinstance(v,dict) else v
            validated_pdf[k] = st.text_input(k, val)

        st.session_state.validated_pdf = validated_pdf

        st.subheader("Immagine")

        validated_img = {}
        for k,v in (st.session_state.image_data or {}).items():
            val = v["value"] if isinstance(v,dict) else v
            validated_img[k] = st.text_input(k, val)

        st.session_state.validated_image = validated_img

    else:
        st.info("Esegui prima analisi")

# ======================================================
# TAB 3 — PUBBLICA
# ======================================================
with tabs[2]:

    if st.session_state.validated_pdf and st.session_state.validated_image:

        if st.button("Pubblica"):

            pid = f"{tipo.upper()}-{uuid.uuid4().hex[:6]}"

            passport = services.initialize_passport(pid, tipo, fields)

            # merge intelligente
            services.merge_data(
                passport,
                st.session_state.validated_pdf,
                st.session_state.validated_image
            )

            # salva immagini
            for img in st.session_state.images:
                services.add_product_image(passport, img)

            services.save_passport_to_file(passport)

            url = f"{st.secrets['APP_URL']}?passport_id={pid}"
            qr = services.generate_qr_from_url(url)

            st.success("DPP pubblicato")

            st.subheader("ESPR")
            st.write(passport["overall_espr"])

            st.subheader("Reliability")
            st.progress(passport["overall_rating"])

            st.image(qr)
            st.code(url)

    else:
        st.info("Completa validazione")
