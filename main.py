import streamlit as st
import uuid
from datetime import datetime
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
# STILE GLOBALE + LOGO
# ======================================================
logo = Image.open("functions/logo_nuvia.jpeg")
logo_base64 = services.image_to_base64(logo)

st.markdown(f"""
<style>
body, div, span, input, button {{
    font-family: 'Nunito Sans', sans-serif;
    background-color: #f5f1ed;
    color: #3a2607;
}}
h1, h2, h3, h4, h5, h6 {{ color: #3a2607; }}
.stButton>button {{
    background-color: #25ce6c;
    color: white;
    border-radius: 8px;
    border: none;
}}
.required-field {{
    font-weight: bold;
    color: #d9534f;
}}
</style>
<div style="display:flex; align-items:center; gap:15px; margin-bottom:20px;">
    <img src="data:image/jpeg;base64,{logo_base64}" width="450">
    <h1 style="margin:0;"></h1>
</div>
""", unsafe_allow_html=True)

client = OpenAI(api_key=st.secrets["OPEN_AI_KEY"])

# ======================================================
# INIZIALIZZA SESSION STATE
# ======================================================
for key in ["uploaded_pdf_file", "uploaded_image_files",
            "pdf_data", "image_data",
            "validated_pdf", "validated_image"]:
    if key not in st.session_state:
        st.session_state[key] = None

# ======================================================
# ROUTING QR → PAGINA PUBBLICA
# ======================================================
passport_id = st.query_params.get("passport_id")
if passport_id:
    passport = services.load_passport_from_file(passport_id)
    if not passport:
        st.error("Digital Product Passport not found")
        st.stop()

    st.markdown("""
        <style>
        [data-testid="stSidebar"] {display:none;}
        header {visibility:hidden;}
        footer {visibility:hidden;}
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

    # Mostra le sezioni e campi con colore
    for section_name, section in passport["sections"].items():
        st.subheader(f"{section_name}")
        for field_name, field in section["fields"].items():
            required = field.get("required", False)
            label = f"{field_name} {'(obbligatorio)' if required else '(opzionale)'}"
            color = field.get("color","")
            st.write(f"**{label}**: {field['value']} {color}")
    
    # Mostra immagini multiple
    if "images" in passport and passport["images"]:
        for img in passport["images"]:
            st.image(
                f"data:image/jpeg;base64,{img['file_base64']}",
                caption=f"{img.get('caption','Immagine')} - {img.get('annotation','')}",
                use_column_width=True
            )

    # Overall reliability
    st.subheader("📊 Overall Reliability")
    st.progress(passport.get("overall_rating",0.0))
    st.metric("Overall Reliability Score", f"{int(passport.get('overall_rating',0.0)*100)}%")

    st.caption("Public read-only Digital Product Passport. Generated via AI extraction and human validation.")
    st.stop()

# ======================================================
# SELEZIONE TIPO PRODOTTO
# ======================================================
tipo_prodotto = st.selectbox(
    "Seleziona tipo prodotto",
    ["mobile","lampada","bicicletta"]
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
        image_files = st.file_uploader(
            "Immagini prodotto (puoi caricare più immagini)", 
            type=["jpg","png","jpeg"], 
            accept_multiple_files=True
        )

        submitted = st.form_submit_button("🔍 Analizza")

        if submitted:
            if not pdf_file or not image_files:
                st.warning("Carica PDF e almeno un'immagine")
            else:
                st.session_state.uploaded_pdf_file = pdf_file
                st.session_state.uploaded_image_files = image_files

                with st.spinner("Analisi in corso ⏳…"):
                    # PDF
                    try:
                        pdf_text = services.extract_text_from_pdf(pdf_file)
                        st.session_state.pdf_data = services.gpt_extract_from_pdf(pdf_text, client, tipo_prodotto)
                    except Exception:
                        st.warning("GPT PDF fallito, userà dati vuoti")
                        st.session_state.pdf_data = {c: None for c in services.PRODUCT_FIELDS[tipo_prodotto]["pdf"]}

                    # Immagini multiple
                    st.session_state.image_data = {}
                    for idx, img_file in enumerate(image_files):
                        try:
                            image_data = services.gpt_analyze_image(img_file, client, tipo_prodotto)
                            st.session_state.image_data.update(image_data)
                        except Exception:
                            st.warning(f"GPT Image fallita per immagine {img_file.name}")
                            st.session_state.image_data.update({c: "non rilevato" for c in services.PRODUCT_FIELDS[tipo_prodotto]["image"]})

                st.success("Analisi completata")
                st.info("I dati sono stati estratti e popolati automaticamente nei form di validazione.")

# ======================================================
# TAB 2 — VALIDAZIONE PDF
# ======================================================
with tabs[1]:
    if st.session_state.pdf_data:
        with st.form("validate_pdf_form"):
            validated_pdf = services.render_validation_form(
                st.session_state.pdf_data,
                title="✔ Dati certificati (PDF)"
            )
            submitted_pdf = st.form_submit_button("Salva validazione PDF")
            if submitted_pdf:
                st.session_state.validated_pdf = validated_pdf
                st.success("Validazione PDF salvata ✅")
    else:
        st.info("Esegui prima l’analisi")

# ======================================================
# TAB 3 — VALIDAZIONE IMMAGINE
# ======================================================
with tabs[2]:
    if st.session_state.image_data:
        with st.form("validate_image_form"):
            validated_image = services.render_validation_form(
                st.session_state.image_data,
                title="👁️ Dati estratti da immagine"
            )
            submitted_img = st.form_submit_button("Salva validazione Immagine")
            if submitted_img:
                st.session_state.validated_image = validated_image
                st.success("Validazione immagine salvata ✅")
        # Mostra tutte le immagini caricate
        if st.session_state.uploaded_image_files:
            for idx, img in enumerate(st.session_state.uploaded_image_files):
                st.image(img, caption=f"Foto prodotto {idx+1}", use_column_width=True)
    else:
        st.info("Esegui prima l’analisi")

# ======================================================
# TAB 4 — PUBBLICAZIONE DPP
# ======================================================
with tabs[3]:
    if st.session_state.validated_pdf and st.session_state.validated_image:

        if st.button("🚀 Pubblica Digital Product Passport"):

            product_id = f"{tipo_prodotto.upper()}-{uuid.uuid4().hex[:8]}"

            # 1️⃣ Inizializza passport con sezione vuota e campi required
            passport_data = services.initialize_passport(product_id, tipo_prodotto)

            # 2️⃣ Funzione helper per mappare dati validati nel passport
            def merge_validated_data(passport, validated_pdf, validated_image):
                merged_data = {**validated_pdf, **validated_image}

                for section_name, section in passport["sections"].items():
                    for field_name, field in section["fields"].items():
                        # Trova la chiave valida nel form (case-insensitive)
                        val = None
                        for k, v in merged_data.items():
                            if k.strip().lower() == field_name.strip().lower():
                                val = v
                                break

                        if val is not None:
                            if not isinstance(val, dict):
                                val = {
                                    "value": val,
                                    "confidence": 1.0,
                                    "field_type": field.get("field_type", "technical"),
                                    "eu_weight": 1.0,
                                    "required": field.get("required", False)
                                }
                            else:
                                # preserva required se non presente
                                val["required"] = val.get("required", field.get("required", False))
                            field.update(val)
                            # aggiorna rating e colore
                            rating = services.compute_field_rating(field)
                            field["rating"] = rating
                            field["color"] = services.score_to_color(rating)

            # 3️⃣ Merge PDF + Image nel passport
            merge_validated_data(passport_data, st.session_state.validated_pdf, st.session_state.validated_image)

            # 4️⃣ Aggiungi tutte le immagini caricate
            for idx, img_file in enumerate(st.session_state.uploaded_image_files):
                services.add_product_image(passport_data, img_file, caption=f"Immagine {idx+1}")

            # 5️⃣ Calcola rating complessivo considerando campi obbligatori
            services.compute_overall_rating(passport_data)

            # 6️⃣ Salva passport
            services.save_passport_to_file(passport_data)

            # 7️⃣ Genera QR code + URL pubblico
            public_url = f"{st.secrets['APP_URL']}?passport_id={product_id}"
            qr_buf = services.generate_qr_from_url(public_url)

            # 8️⃣ UI Feedback
            st.success("🇪🇺 Digital Product Passport pubblicato ✅")
            st.subheader("📊 Overall Reliability")
            st.progress(passport_data["overall_rating"])
            st.metric("Overall Reliability Score", f"{int(passport_data['overall_rating']*100)}%")
            st.subheader("🔗 Accesso pubblico")
            st.image(qr_buf)
            st.code(public_url)

    else:
        st.info("Completa validazione PDF e immagine")

