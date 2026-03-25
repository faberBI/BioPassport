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
keys = ["uploaded_pdf_file", "uploaded_image_files",
        "pdf_data", "image_data",
        "validated_pdf", "validated_image", "images"]
for k in keys:
    if k not in st.session_state:
        st.session_state[k] = None

# ======================================================
# PUBLIC VIEW (QR)
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
            label = f"{fname} ({f['color']})"
            st.text_input(label, value="" if f["value"] is None else str(f["value"]), disabled=True)
            if f.get("explanation"):
                st.caption(f"explanation: {f['explanation']} (conf: {f.get('confidence',0)})")

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
fields = [f["name"] for f in services.PRODUCT_FIELDS[tipo]["pdf"]]

tabs = st.tabs(["Upload & Analisi", "Validazione PDF", "Validazione Immagini", "Pubblica"])

# ======================================================
# TAB 1 — UPLOAD & ANALISI
# ======================================================
with tabs[0]:
    pdf = st.file_uploader("PDF prodotto", type=["pdf"])
    images = st.file_uploader("Immagini prodotto (puoi caricare più immagini)", type=["jpg","png","jpeg"], accept_multiple_files=True)

    if st.button("Analizza PDF e immagini"):
        if not pdf or not images:
            st.warning("Carica PDF e almeno un'immagine")
        else:
            st.session_state.uploaded_pdf_file = pdf
            st.session_state.uploaded_image_files = images
            st.session_state.images = images

            with st.spinner("Analisi in corso..."):
                # PDF
                text = services.extract_text_from_pdf(pdf)
                st.session_state.pdf_data = services.gpt_extract_from_pdf(text, client, tipo, fields)

                # Immagini
                image_data = {}
                for img_file in images:
                    res = services.gpt_analyze_image(img_file, client, tipo)
                    if not res:
                        st.warning(f"GPT Image non ha estratto dati per {img_file.name}")
                        # inserisce placeholder
                        for f in ["colore","condizioni","materiale_probabile","categoria_visiva","segni_usura"]:
                            res[f] = {"value": None, "confidence":0, "explanation":"Non rilevabile"}
                    image_data.update(res)
                st.session_state.image_data = image_data

            st.success("Analisi completata")

# ======================================================
# TAB 2 — VALIDAZIONE PDF
# ======================================================
with tabs[1]:
    if st.session_state.pdf_data:
        with st.form("validate_pdf_form"):
            validated_pdf = {}
            for k, v in st.session_state.pdf_data.items():
                val = v["value"] if isinstance(v, dict) else v
                conf = v.get("confidence",0)
                expl = v.get("explanation","")
                validated_pdf[k] = st.text_input(f"{k} (conf:{conf}, {expl})", value="" if val is None else str(val))
            submitted_pdf = st.form_submit_button("✅ Completa validazione PDF")
            if submitted_pdf:
                st.session_state.validated_pdf = validated_pdf
                st.success("Validazione PDF completata")
    else:
        st.info("Esegui prima l’analisi PDF")

# ======================================================
# TAB 3 — VALIDAZIONE IMMAGINI
# ======================================================
with tabs[2]:
    if st.session_state.image_data:
        with st.form("validate_image_form"):
            validated_image = {}
            for k, v in st.session_state.image_data.items():
                val = v["value"] if isinstance(v, dict) else v
                conf = v.get("confidence",0)
                expl = v.get("explanation","")
                validated_image[k] = st.text_input(f"{k} (conf:{conf}, {expl})", value="" if val is None else str(val))
            submitted_img = st.form_submit_button("✅ Completa validazione immagini")
            if submitted_img:
                st.session_state.validated_image = validated_image
                st.success("Validazione immagini completata")

        # Mostra anteprima immagini
        for idx, img in enumerate(st.session_state.uploaded_image_files):
            st.image(img, caption=f"Foto prodotto {idx+1}", use_column_width=True)
    else:
        st.info("Esegui prima l’analisi immagini")

# ======================================================
# TAB 4 — PUBBLICAZIONE
# ======================================================
with tabs[3]:
    if st.session_state.validated_pdf and st.session_state.validated_image:

        if st.button("🚀 Pubblica Digital Product Passport"):

            pid = f"{tipo.upper()}-{uuid.uuid4().hex[:6]}"
            passport = services.initialize_passport(pid, tipo, fields)

            # Merge PDF + Image validati
            services.merge_data(passport, st.session_state.validated_pdf, st.session_state.validated_image)

            # Salva immagini
            for img in st.session_state.images:
                services.add_product_image(passport, img)

            # Salva su file
            services.save_passport_to_file(passport)

            # Salva su Access
            try:
                services.save_passport_to_access(passport)
            except Exception as e:
                st.warning(f"Errore salvataggio DB Access: {e}")

            # QR + URL
            url = f"{st.secrets['APP_URL']}?passport_id={pid}"
            qr = services.generate_qr_from_url(url)

            st.success("🇪🇺 Digital Product Passport pubblicato")
            services.render_espr_compliance(passport)
            st.progress(passport["overall_rating"])
            st.metric("Reliability", f"{int(passport['overall_rating']*100)}%")
            st.image(qr)
            st.code(url)

    else:
        st.info("Completa validazione PDF e immagini prima di pubblicare")
