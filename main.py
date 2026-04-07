import streamlit as st
import uuid
import os
import base64
import pandas as pd
from io import BytesIO
from PIL import Image
from openai import OpenAI

# funzioni custom
from functions import services


# ======================================================
# CONFIG STREAMLIT
# ======================================================
st.set_page_config(
    page_title="Nuvia Digital Product Passport",
    page_icon="functions/favicon.jpeg",
    layout="centered"
)

# ======================================================
# HEADER / LOGO
# ======================================================
try:
    st.image("functions/logo_nuvia.jpeg", width=220)
except Exception:
    pass

st.title("🇪🇺 Digital Product Passport")

# ======================================================
# OPENAI CLIENT
# ======================================================
client = OpenAI(api_key=st.secrets["OPEN_AI_KEY"])

# ======================================================
# SESSION STATE INIT
# ======================================================
DEFAULT_STATE = {
    "uploaded_pdf_bytes": None,
    "uploaded_images_bytes": None,
    "uploaded_cert_bytes": None,
    "uploaded_cert_names": None,
    "pdf_data": None,
    "image_data": None,
    "cert_data": None,
    "validated_pdf": None,
    "validated_image": None,
    "validated_cert": None,
}
for k, v in DEFAULT_STATE.items():
    st.session_state.setdefault(k, v)

# ======================================================
# PUBLIC VIEW (?passport_id=...)
# ======================================================
passport_id = st.query_params.get("passport_id")
if passport_id:
    passport = services.load_passport_from_file(passport_id)
    if not passport:
        st.error("Passport non trovato")
        st.stop()

    st.subheader("📌 Metadata principali")
    st.markdown(
        f"""
**ID:** {passport.get("id")}  
**Tipo:** {passport.get("product_type")}  
**Versione:** {passport.get("version")}  
**Issuer:** {(passport.get("issuer") or {}).get("legal_name")}  
**Lifecycle:** {(passport.get("lifecycle") or {}).get("status", "—")}  
**Hash (integrità):** `{(passport.get("digital_signature") or {}).get("hash","")[:16]}…`
"""
    )

    if passport.get("physical_binding"):
        pb = passport["physical_binding"]
        st.subheader("🔗 Legame fisico‑digitale")
        st.write(f"Carrier: {pb.get('carrier')}")
        st.write(f"Location: {pb.get('location')}")
        st.write(f"URL: {pb.get('public_url')}")
        st.write(f"Tamper risk: {pb.get('tamper_risk')}")

    st.divider()
    services.render_espr_compliance(passport)
    st.stop()

# ======================================================
# SELEZIONE TIPO PRODOTTO
# ======================================================
tipo = st.selectbox("Tipo prodotto", ["mobile", "lampada", "bicicletta"])
fields = list(services.PRODUCT_FIELDS.get(tipo, {}).get("pdf", []))

tabs = st.tabs(["📤 Upload & Analisi", "📝 Validazione", "🚀 Pubblica", "📚 Archivio"])

# ======================================================
# TAB 1 — UPLOAD & AI
# ======================================================
with tabs[0]:
    pdf_file = st.file_uploader("PDF prodotto", type=["pdf"])
    image_files = st.file_uploader("Immagini prodotto", type=["jpg", "png"], accept_multiple_files=True)
    cert_files = st.file_uploader("Certificati", type=["pdf", "jpg", "png"], accept_multiple_files=True)

    if st.button("Analizza"):
        if not pdf_file or not image_files:
            st.warning("Carica PDF e almeno un'immagine")
            st.stop()

        st.session_state.uploaded_pdf_bytes = pdf_file.read()
        st.session_state.uploaded_images_bytes = [i.read() for i in image_files]

        st.session_state.uploaded_cert_bytes = [c.read() for c in (cert_files or [])]
        st.session_state.uploaded_cert_names = [
            getattr(c, "name", f"cert_{i+1}") for i, c in enumerate(cert_files or [])
        ]

        with st.spinner("Analisi in corso..."):
            pdf_text = services.extract_text_from_pdf(BytesIO(st.session_state.uploaded_pdf_bytes))
            st.session_state.pdf_data = services.gpt_extract_from_pdf(pdf_text, client, tipo, fields)

            img_data = {}
            for b in st.session_state.uploaded_images_bytes:
                img_data.update(services.gpt_analyze_image(BytesIO(b), client, tipo))
            st.session_state.image_data = img_data

            cert_list = []
            for b in st.session_state.uploaded_cert_bytes:
                cert_list.append(services.gpt_extract_cert_info(BytesIO(b), client))
            st.session_state.cert_data = cert_list

        st.success("Analisi completata ✅")

# ======================================================
# TAB 2 — VALIDAZIONE
# ======================================================
with tabs[1]:
    if st.session_state.pdf_data and st.session_state.image_data:
        st.subheader("Validazione PDF")
        st.session_state.validated_pdf = {
            k: {
                "value": st.text_input(f"PDF · {k}", v.get("value", ""), help=v.get("explanation", "")),
                "confidence": v.get("confidence", 0),
                "explanation": v.get("explanation", "")
            }
            for k, v in st.session_state.pdf_data.items()
        }

        st.subheader("Validazione Immagini")
        st.session_state.validated_image = {
            k: {
                "value": st.text_input(f"IMG · {k}", v.get("value", ""), help=v.get("explanation", "")),
                "confidence": v.get("confidence", 0),
                "explanation": v.get("explanation", "")
            }
            for k, v in st.session_state.image_data.items()
        }

        st.success("Validazione pronta ✅")
    else:
        st.info("Esegui prima l’analisi")

# ======================================================
# TAB 3 — PUBBLICA
# ======================================================
with tabs[2]:
    if not (st.session_state.get("validated_pdf") and st.session_state.get("validated_image")):
        st.info("Completa prima la validazione")
        st.stop()

    ENABLE_QESEAL = False
    ENABLE_SES = True

    if st.button("🚀 Pubblica Digital Product Passport"):
        pid = f"{tipo.upper()}-{uuid.uuid4().hex[:6]}"
        passport = services.initialize_passport(pid, tipo, fields)

        url = f"{st.secrets['APP_URL']}?passport_id={pid}"
        services.set_physical_binding(
            passport,
            public_url=url,
            carrier="qr",
            location="product_label",
            tamper_risk="medium"
        )

        services.merge_data(
            passport,
            st.session_state.validated_pdf,
            st.session_state.validated_image,
            None
        )

        check = services.validate_espr_furniture(passport)
        if not check.get("is_compliant", False):
            st.error("❌ DPP NON conforme")
            st.stop()

        services.save_passport_to_file(passport)
        services.save_passport_to_excel_append(passport)
        st.session_state["published_passport"] = passport

        st.success("✅ DPP pubblicato")

        st.code(url)

        qr = services.generate_qr_from_url(url)
        st.image(qr, caption="Nuvia QR Code")

        qr.seek(0)
        st.download_button(
            label="⬇️ Scarica QR Code",
            data=qr,
            file_name=f"{passport['id']}_qrcode.png",
            mime="image/png"
        )

    if ENABLE_SES:
        st.divider()
        st.subheader("✍️ Firma elettronica semplice (OTP) – DEMO / TEST")

        pp = st.session_state.get("published_passport")
        if not pp:
            st.info("Pubblica prima il DPP per poter avviare la firma.")
            st.stop()

        st.session_state.setdefault("ses_name", "Mario")
        st.session_state.setdefault("ses_surname", "Rossi")
        st.session_state.setdefault("ses_email", "mario.rossi@test.it")
        st.session_state.setdefault("ses_mobile", "+39333111222")
        st.session_state.setdefault("ses_channel", "email")
        st.session_state.setdefault("ses_mode", "typed")

        with st.form("ses_form"):
            col1, col2 = st.columns(2)
            with col1:
                st.text_input("Nome firmatario", key="ses_name")
                st.text_input("Cognome firmatario", key="ses_surname")
                st.text_input("Email OTP", key="ses_email")
            with col2:
                st.text_input("Cellulare OTP", key="ses_mobile")
                st.selectbox("Canale OTP", ["email", "sms"], key="ses_channel")
                st.selectbox("Modalità firma", ["typed", "drawn"], key="ses_mode")

            submit_ses = st.form_submit_button("Invia richiesta firma SES")

        if submit_ses:
            services.sign_passport_pdf_ses_openapi(
                pp,
                signer_name=st.session_state["ses_name"],
                signer_surname=st.session_state["ses_surname"],
                signer_email=st.session_state["ses_email"],
                signer_mobile=st.session_state["ses_mobile"],
                otp_channel=st.session_state["ses_channel"],
                signature_mode=st.session_state["ses_mode"]
            )
            st.success("✅ Richiesta SES inviata")
# ======================================================
# TAB 4 — ARCHIVIO
# ======================================================
with tabs[3]:
    st.header("📚 Archivio Passport")

    if not os.path.exists(services.EXCEL_FILE):
        st.info("Nessun file Excel trovato")
        st.stop()

    try:
        df_passport = pd.read_excel(services.EXCEL_FILE, sheet_name="passport").rename(columns=str.strip)
        df_fields = pd.read_excel(services.EXCEL_FILE, sheet_name="fields").rename(columns=str.strip)
        df_images = pd.read_excel(services.EXCEL_FILE, sheet_name="images").rename(columns=str.strip)

        if df_passport.empty:
            st.info("Nessun passport disponibile")
            st.stop()

        df_passport["version"] = pd.to_numeric(df_passport["version"], errors="coerce")
        df_latest = (
            df_passport.sort_values(["id", "version"])
            .groupby("id", as_index=False)
            .tail(1)
        )

        st.subheader("📊 Elenco Passport (ultima versione)")
        st.dataframe(df_latest, use_container_width=True)

        selected_id = st.selectbox("Seleziona Passport", df_latest["id"])
        if not selected_id:
            st.stop()

        passport = services.load_passport_from_file(selected_id)
        if not passport:
            st.error("Passport JSON non trovato")
            st.stop()

        st.subheader("🧾 Dettaglio Passport")
        st.json({
            "id": passport.get("id"),
            "type": passport.get("product_type"),
            "version": passport.get("version"),
            "lifecycle": (passport.get("lifecycle") or {}).get("status"),
            "hash": (passport.get("digital_signature") or {}).get("hash"),
            "seal_id": (passport.get("qualified_seal") or {}).get("seal_id"),
            "seal_state": (passport.get("qualified_seal") or {}).get("state"),
            "evidences": len(passport.get("evidences", [])),
        })

        st.subheader("🧩 Campi (tutte le sezioni)")
        st.dataframe(df_fields[df_fields["passport_id"] == selected_id], use_container_width=True)

        st.subheader("🖼️ Immagini prodotto")
        imgs = df_images[df_images["passport_id"] == selected_id]
        if imgs.empty:
            st.info("Nessuna immagine associata")
        else:
            for _, row in imgs.iterrows():
                st.image(f"data:image/jpeg;base64,{row['file_base64']}", caption=row.get("caption", ""))

    except Exception as e:
        st.error(f"Errore archivio: {e}")
