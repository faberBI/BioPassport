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
</style>
<div style="display:flex; align-items:center; gap:15px; margin-bottom:20px;">
    <img src="data:image/jpeg;base64,{logo_base64}" width="450">
    <h1 style="margin:0;"></h1>
</div>
""", unsafe_allow_html=True)

client = OpenAI(api_key=st.secrets["OPEN_AI_KEY"])

# ======================================================
# FUNZIONI UTILI
# ======================================================
def compute_field_rating(field):
    """Calcola rating basato su confidence e tipo campo"""
    field_type_weight = {
        "technical": 1.0,
        "declaration": 0.6,
        "lca": 0.5,
        "visual": 0.8  # aumento peso visual per non farle MISSING
    }
    weight = field_type_weight.get(field.get("field_type","technical"),0.5)
    confidence = field.get("confidence",0.0) or 0.0
    return round(confidence * weight,2)

def score_to_color(score):
    """Converte rating in colore 🟢🟡🔴"""
    if score >= 0.8: return "🟢"
    elif score >= 0.5: return "🟡"
    else: return "🔴"

def compute_espr_compliance(fields, required_fields):
    """Calcola ESPR compliance OK/PARTIAL/MISSING basato su rating dei campi richiesti"""
    ratings = []
    for f in required_fields:
        r = fields.get(f,{}).get("rating",0.0)
        ratings.append(r)
    if all(r >= 0.8 for r in ratings):
        return "OK"
    elif any(r >= 0.5 for r in ratings):
        return "PARTIAL"
    else:
        return "MISSING"

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
            color = field.get("color","")
            st.write(f"**{field_name}**: {field['value']} {color}")

    # Overall reliability
    st.subheader("📊 Overall Reliability")
    st.progress(passport.get("overall_rating",0.0))
    st.metric("Overall Reliability Score", f"{int(passport.get('overall_rating',0.0)*100)}%")

    # Mostra immagine se presente
    if "product_image_base64" in passport:
        st.image(
            f"data:image/jpeg;base64,{passport['product_image_base64']}",
            caption="Foto prodotto",
            use_column_width=True
        )

    st.caption("Public read-only Digital Product Passport. Generated via AI extraction and human validation.")
    st.stop()

# ======================================================
# BACKOFFICE
# ======================================================
for k in ["pdf_data","image_data","validated_pdf","validated_image","uploaded_image_file"]:
    if k not in st.session_state:
        st.session_state[k] = None
st.markdown(
    """
    <style>
    /* Box bianco attorno al selectbox */
    .custom-selectbox {
        background-color: white;
        padding: 12px 20px;
        border-radius: 12px;
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
        display: inline-block;
        margin-bottom: 20px;
    }

    /* Target al label interno del selectbox */
    .custom-selectbox label {
        font-weight: bold;
    }

    /* Target alla select interna */
    .custom-selectbox div[role="combobox"] {
        background-color: white !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown('<div class="custom-selectbox">', unsafe_allow_html=True)

tipo_prodotto = st.selectbox(
    "Seleziona tipo prodotto",
    ["mobile","lampada","bicicletta"]
)

st.markdown('</div>', unsafe_allow_html=True)
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
                st.info("I dati sono stati estratti e popolati automaticamente nei form di validazione.")

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

            # --------------------------------------------------
            # Unisci PDF + IMAGE (PDF prioritario)
            # --------------------------------------------------
            merged_data = {**st.session_state.validated_image, **st.session_state.validated_pdf}

            # Tutti i campi obbligatori per il tipo prodotto
            required_fields = services.PRODUCT_FIELDS[tipo_prodotto]["pdf"] + services.PRODUCT_FIELDS[tipo_prodotto]["image"]

            sections = {}
            overall_scores = []

            for field_name in required_fields:
                if field_name in merged_data:
                    field_value = merged_data[field_name]

                    # Normalizza il campo se non è già un dict
                    if not isinstance(field_value, dict):
                        field = {
                            "value": field_value,
                            "confidence": 1.0,         # default se presente
                            "field_type": "technical", # default
                            "eu_weight": 1.0
                        }
                    else:
                        field = field_value

                    rating = services.compute_field_rating(field)
                    color = services.score_to_color(rating)

                    sections[field_name] = {
                        "fields": {
                            field_name: {
                                "value": field.get("value"),
                                "confidence": field.get("confidence", 0.0),
                                "field_type": field.get("field_type", "declaration"),
                                "eu_weight": field.get("eu_weight", 1.0),
                                "rating": rating,
                                "color": color
                            }
                        }
                    }

                else:
                    # Campo mancante → rating 0
                    rating = 0.0
                    color = services.score_to_color(rating)
                    sections[field_name] = {
                        "fields": {
                            field_name: {
                                "value": None,
                                "confidence": 0.0,
                                "field_type": "technical",
                                "eu_weight": 1.0,
                                "rating": rating,
                                "color": color
                            }
                        }
                    }

                overall_scores.append(rating)

            # --------------------------------------------------
            # Overall Reliability
            # --------------------------------------------------
            overall_rating = sum(overall_scores) / len(overall_scores) if overall_scores else 0.0

            # --------------------------------------------------
            # Costruzione passport
            # --------------------------------------------------
            passport_data = {
                "id": product_id,
                "product_type": tipo_prodotto,
                "metadata": {
                    "created_at": datetime.utcnow().isoformat(),
                    "version": "EU-DPP-1.0"
                },
                "sections": sections,
                "overall_rating": overall_rating
            }

            # Salva immagine Base64 se presente
            if st.session_state.uploaded_image_file:
                passport_data["product_image_base64"] = services.image_to_base64(st.session_state.uploaded_image_file)

            services.save_passport_to_file(passport_data)

            # --------------------------------------------------
            # QR + URL pubblico
            # --------------------------------------------------
            public_url = f"{st.secrets['APP_URL']}?passport_id={product_id}"
            qr_buf = services.generate_qr_from_url(public_url)

            # --------------------------------------------------
            # UI Feedback
            # --------------------------------------------------
            st.success("🇪🇺 Digital Product Passport pubblicato ✅")
            st.subheader("📊 Overall Reliability")
            st.progress(overall_rating)
            st.metric("Overall Reliability Score", f"{int(overall_rating*100)}%")
            st.subheader("🔗 Accesso pubblico")
            st.image(qr_buf)
            st.code(public_url)

    else:
        st.info("Completa validazione PDF e immagine")


