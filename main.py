import streamlit as st
import uuid
from openai import OpenAI
from functions import services
from PIL import Image
import os
import pandas as pd

# ======================================================
# CONFIG STREAMLIT
# ======================================================
st.set_page_config(
    page_title="Nuvia Digital Product Passport",
    page_icon="functions/favicon.jpeg",
    layout="centered"
)

# ======================================================
# LOGO + STILE
# ======================================================
logo = Image.open("functions/logo_nuvia.jpeg")
logo_base64 = services.image_to_base64(logo)

st.markdown(f"""
<style>
body {{background-color:#f5f1ed; color:#3a2607; font-family:Nunito Sans;}}
.stButton>button {{background-color:#25ce6c; color:white; border-radius:8px;}}
.required-field {{font-weight:bold; color:#d9534f;}}
</style>
<img src="data:image/jpeg;base64,{logo_base64}" width="350">
""", unsafe_allow_html=True)

# ======================================================
# OPENAI CLIENT
# ======================================================
client = OpenAI(api_key=st.secrets["OPEN_AI_KEY"])

# ======================================================
# SESSION STATE
# ======================================================
keys = ["uploaded_pdf_file", "uploaded_image_files",
        "pdf_data", "image_data", "validated_pdf",
        "validated_image", "images"]
for k in keys:
    if k not in st.session_state:
        st.session_state[k] = None

# ======================================================
# PUBLIC VIEW (QR LINK)
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
            st.write(f"**{fname}**: {f['value']} {f['color']} (conf: {f.get('confidence',0)})")
            if f.get("explanation"):
                st.caption(f["explanation"])

    services.render_espr_compliance(passport)
    st.progress(passport["overall_rating"])
    st.metric("Reliability", f"{int(passport['overall_rating']*100)}%")

    if passport.get("images"):
        for img in passport["images"]:
            st.image(f"data:image/jpeg;base64,{img['file_base64']}")

    st.stop()

# ======================================================
# SELEZIONE TIPO PRODOTTO
# ======================================================
tipo = st.selectbox("Tipo prodotto", ["mobile","lampada","bicicletta"])
fields = [f["name"] for f in services.PRODUCT_FIELDS[tipo]["pdf"]]

tabs = st.tabs(["📤 Upload & Analisi", "📝 Validazione", "🔗 Pubblica", "📚 Archivio"])

# ======================================================
# TAB 1 — UPLOAD + AI
# ======================================================
with tabs[0]:
    pdf_file = st.file_uploader("PDF prodotto", type=["pdf"])
    image_files = st.file_uploader("Immagini prodotto", type=["jpg","png"], accept_multiple_files=True)

    if st.button("Analizza"):
        if not pdf_file or not image_files:
            st.warning("Carica PDF e almeno un'immagine")
        else:
            st.session_state.uploaded_pdf_file = pdf_file
            st.session_state.uploaded_image_files = image_files
            st.session_state.images = image_files

            with st.spinner("Analisi in corso..."):
                # PDF
                pdf_text = services.extract_text_from_pdf(pdf_file)
                st.session_state.pdf_data = services.gpt_extract_from_pdf(pdf_text, client, tipo, fields)

                # Immagini
                img_data = {}
                for img in image_files:
                    res = services.gpt_analyze_image(img, client, tipo)
                    img_data.update(res)
                st.session_state.image_data = img_data

            st.success("Analisi completata ✅")

    # Evidenzia PDF e visualizza in-app
    if st.session_state.pdf_data and pdf_file:
        if st.button("Evidenzia PDF"):
            highlighted_pdf_path = services.highlight_pdf_fields(
                pdf_file,
                st.session_state.pdf_data
            )
            st.success("PDF evidenziato pronto!")

            # Bottone per scaricare PDF
            with open(highlighted_pdf_path, "rb") as f:
                pdf_bytes = f.read()
            st.download_button("Scarica PDF evidenziato", pdf_bytes, file_name="highlighted.pdf", mime="application/pdf")

            # Visualizza PDF nell'app
            base64_pdf = services.file_to_base64(highlighted_pdf_path)
            pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="700" height="1000" type="application/pdf"></iframe>'
            st.components.v1.html(pdf_display, height=1000)

# ======================================================
# TAB 2 — VALIDAZIONE
# ======================================================
with tabs[1]:
    if st.session_state.pdf_data and st.session_state.image_data:
        st.subheader("Validazione dati PDF")
        validated_pdf = {}
        for k,v in st.session_state.pdf_data.items():
            val = v["value"]
            explanation = v.get("explanation","")
            conf = v.get("confidence",0)
            validated_pdf[k] = st.text_input(f"{k} (conf: {conf})", val, help=explanation)
        st.session_state.validated_pdf = validated_pdf

        st.subheader("Validazione dati Immagini")
        validated_img = {}
        for k,v in st.session_state.image_data.items():
            val = v["value"]
            explanation = v.get("explanation","")
            conf = v.get("confidence",0)
            validated_img[k] = st.text_input(f"{k} (conf: {conf})", val, help=explanation)
        st.session_state.validated_image = validated_img

        if st.button("Completa validazione"):
            st.success("Validazione completata ✅")
    else:
        st.info("Esegui prima l’analisi PDF e immagini")

# ======================================================
# TAB 3 — PUBBLICA
# ======================================================
with tabs[2]:
    if st.session_state.validated_pdf and st.session_state.validated_image:
        if st.button("Pubblica Digital Product Passport"):

            pid = f"{tipo.upper()}-{uuid.uuid4().hex[:6]}"
            passport = services.initialize_passport(pid, tipo, fields)

            # Merge dati PDF + immagini validati
            services.merge_data(passport, st.session_state.validated_pdf, st.session_state.validated_image)

            # Calcola ESPR e overall reliability aggiornati
            services.compute_overall(passport)

            # Salva immagini
            for img in st.session_state.images:
                services.add_product_image(passport, img)

            # Salva su file e Excel
            services.save_passport_to_file(passport)
            services.save_passport_to_excel_append(passport)

            # Genera QR pubblico
            url = f"https://biopassport-versione-modify1.streamlit.app/?passport_id={pid}"
            qr = services.generate_qr_from_url(url)

            st.success("DPP pubblicato ✅")
            st.subheader("ESPR")
            st.write(passport.get("overall_espr","MISSING"))
            st.subheader("Reliability")
            st.progress(passport.get("overall_rating",0))

            st.image(qr)
            st.code(url)
    else:
        st.info("Completa prima la validazione PDF e immagini")

# ======================================================
# TAB 4 — ARCHIVIO
# ======================================================
with tabs[3]:
    st.header("Archivio Passport")
    if os.path.exists(services.EXCEL_FILE):
        # Lista ID passport
        df_passport = pd.read_excel(services.EXCEL_FILE, sheet_name="passport")
        passport_ids = df_passport["id"].tolist()
        selected_id = st.selectbox("Seleziona Passport da visualizzare", passport_ids)

        if selected_id:
            st.subheader("Dati Generali")
            st.dataframe(df_passport[df_passport["id"]==selected_id])

            st.subheader("Fields")
            df_fields = pd.read_excel(services.EXCEL_FILE, sheet_name="fields")
            st.dataframe(df_fields[df_fields["passport_id"]==selected_id])

            st.subheader("Immagini")
            df_images = pd.read_excel(services.EXCEL_FILE, sheet_name="images")
            images = df_images[df_images["passport_id"]==selected_id]
            for idx, row in images.iterrows():
                st.image(f"data:image/jpeg;base64,{row['file_base64']}", caption=row.get("caption",""))
    else:
        st.info("Nessun dato archivio disponibile")
