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

    # ESPR Compliance
    st.subheader("🇪🇺 ESPR Compliance per sezione")
    for section_name, section in passport["sections"].items():
        st.write(f"{section.get('espr_compliance','MISSING')} → {section_name}")

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

tipo_prodotto = st.selectbox("Seleziona tipo prodotto", ["mobile","lampada","bicicletta"])

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
            created_at = datetime.utcnow().isoformat()

            # --------------------------------------------------
            # UNIONE E NORMALIZZAZIONE CAMPI
            # --------------------------------------------------
            merged_data = {**st.session_state.validated_image, **st.session_state.validated_pdf}
            sections = {}
            overall_scores = []

            # Usa i campi definiti nel services
            pdf_fields = services.PRODUCT_FIELDS[tipo_prodotto]["pdf"]
            image_fields = services.PRODUCT_FIELDS[tipo_prodotto]["image"]

            # PDF
            pdf_section_fields = {}
            for f in pdf_fields:
                val = merged_data.get(f)
                field = {
                    "value": val,
                    "confidence": 1.0 if val else 0.0,
                    "field_type": "technical",
                    "source": "PDF"
                }
                rating = compute_field_rating(field)
                color = score_to_color(rating)
                field.update({"rating": rating, "color": color})
                pdf_section_fields[f] = field
                overall_scores.append(rating)

            pdf_espr = compute_espr_compliance(pdf_section_fields, pdf_fields)
            sections["PDF"] = {"fields": pdf_section_fields, "espr_compliance": pdf_espr}

            # IMAGE
            image_section_fields = {}
            for f in image_fields:
                val = merged_data.get(f)
                field = {
                    "value": val,
                    "confidence": 1.0 if val else 0.0,
                    "field_type": "visual",
                    "source": "IMAGE"
                }
                rating = compute_field_rating(field)
                color = score_to_color(rating)
                field.update({"rating": rating, "color": color})
                image_section_fields[f] = field
                overall_scores.append(rating)

            image_espr = compute_espr_compliance(image_section_fields, image_fields)
            sections["IMAGE"] = {"fields": image_section_fields, "espr_compliance": image_espr}

            # --------------------------------------------------
            # OVERALL RATING
            # --------------------------------------------------
            overall_rating = round(sum(overall_scores)/len(overall_scores),2) if overall_scores else 0.0

            # --------------------------------------------------
            # BUILD PASSPORT
            # --------------------------------------------------
            passport_data = {
                "id": product_id,
                "product_type": tipo_prodotto,
                "metadata": {"created_at": created_at, "version":"EU-DPP-1.0"},
                "sections": sections,
                "overall_rating": overall_rating
            }

            # Salva immagine base64
            if st.session_state.uploaded_image_file:
                passport_data["product_image_base64"] = services.image_to_base64(st.session_state.uploaded_image_file)

            services.save_passport_to_file(passport_data)

            # URL + QR
            public_url = f"{st.secrets['APP_URL']}?passport_id={product_id}"
            qr_buf = services.generate_qr_from_url(public_url)

            # --------------------------------------------------
            # UI FEEDBACK
            # --------------------------------------------------
            st.success("🇪🇺 Digital Product Passport pubblicato con successo")
            st.subheader("📊 Overall Reliability")
            st.progress(overall_rating)
            st.metric("Overall Reliability Score", f"{int(overall_rating*100)}%")

            st.subheader("🇪🇺 ESPR Compliance Summary")
            for sec_name, sec in sections.items():
                st.write(f"{sec.get('espr_compliance','MISSING')} → {sec_name}")

            st.subheader("🔗 Accesso pubblico")
            st.image(qr_buf)
            st.code(public_url)

    else:
        st.info("Completa validazione PDF e immagine")
