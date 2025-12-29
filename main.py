import streamlit as st
import uuid
from datetime import datetime
from openai import OpenAI
from functions import services
from auth import check_login, create_user
import os

# ======================================================
# CONFIG
# ======================================================
st.set_page_config(page_title="Passaporto Digitale del Mobile", layout="wide")

# ======================================================
# SESSION STATE
# ======================================================
for key in ["logged_in", "username", "pdf_data", "image_data", "validated_pdf", "validated_image"]:
    if key not in st.session_state:
        st.session_state[key] = False if key == "logged_in" else None

# ======================================================
# OPENAI CLIENT
# ======================================================
client = OpenAI(api_key=st.secrets["OPEN_AI_KEY"])

# ======================================================
# LOGIN / REGISTRAZIONE
# ======================================================
if not st.session_state.logged_in:
    st.title("🔒 Login / Registrazione")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Accedi"):
            if check_login(username, password):
                st.session_state.logged_in = True
                st.session_state.username = username
                st.success(f"Benvenuto {username}!")
                st.experimental_rerun()
            else:
                st.error("Username o password errati")
    with col2:
        if st.button("Crea account"):
            if create_user(username, password):
                st.success("Account creato con successo!")
            else:
                st.error("Username già esistente")

else:
    # Sidebar info e logout
    st.sidebar.success(f"Connesso come: {st.session_state.username}")
    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.experimental_rerun()

    st.sidebar.info("""
📞 Numero telefono: +39 0123 456789  
✉️ Email aziendale: info@azienda.it
""")

    # ======================================================
    # MAIN APP
    # ======================================================
    st.title("🪑 Passaporto Digitale del Mobile")

    tabs = st.tabs(["📤 Upload & Analisi", "📝 Validazione PDF", "👁️ Validazione Immagine", "📄 PDF & QR"])

    # --- Tab 1: Upload & Analisi ---
    with tabs[0]:
        with st.form("upload_form"):
            pdf_file = st.file_uploader("Carica PDF del mobile", type=["pdf"])
            image_file = st.file_uploader("Carica foto del mobile", type=["jpg", "png", "jpeg"])
            submitted = st.form_submit_button("🔍 Analizza con AI")

            if submitted:
                if not pdf_file or not image_file:
                    st.warning("Carica sia il PDF che l'immagine.")
                else:
                    with st.spinner("Analisi in corso..."):
                        try:
                            pdf_text = services.extract_text_from_pdf(pdf_file)
                            st.session_state.pdf_data = services.gpt_extract_from_pdf(pdf_text, client)
                        except Exception as e:
                            st.error(f"Errore estrazione PDF: {e}")
                            st.session_state.pdf_data = {}

                        try:
                            image_b64 = services.image_to_base64(image_file)
                            st.session_state.image_data = services.gpt_analyze_image(image_b64, client)
                        except Exception as e:
                            st.error(f"Errore analisi immagine: {e}")
                            st.session_state.image_data = {}
                    st.success("Analisi completata!")

    # --- Tab 2: Validazione PDF ---
    with tabs[1]:
        if st.session_state.pdf_data:
            st.session_state.validated_pdf = services.render_validation_form(
                st.session_state.pdf_data, title="✔ Dati Certificati (PDF)"
            )
        else:
            st.info("Analizza prima il PDF nella tab Upload & Analisi")

    # --- Tab 3: Validazione Immagine ---
    with tabs[2]:
        if st.session_state.image_data:
            st.session_state.validated_image = services.render_validation_form(
                st.session_state.image_data, title="👁️ Dati Visivi Stimati"
            )
        else:
            st.info("Analizza prima l'immagine nella tab Upload & Analisi")

    # --- Tab 4: PDF + QR Download ---
    with tabs[3]:
        if st.session_state.validated_pdf and st.session_state.validated_image:
            with st.form("create_passport_form"):
                submitted_pass = st.form_submit_button("💾 Crea Passaporto")

                if submitted_pass:
                    # Controllo campi obbligatori
                    required_fields = ["nome_prodotto", "produttore"]
                    missing = [f for f in required_fields if not st.session_state.validated_pdf.get(f)]
                    if missing:
                        st.warning(f"Compila i campi obbligatori: {', '.join(missing)}")
                    else:
                        mobile_id = f"MOB-{str(uuid.uuid4())[:8]}"
                        passaporto = {
                            "id": mobile_id,
                            "metadata": {
                                "creato_il": datetime.now().isoformat(),
                                "versione": "1.0"
                            },
                            "dati_certificati_pdf": st.session_state.validated_pdf,
                            "dati_visivi_stimati": st.session_state.validated_image
                        }

                        # Salvataggio JSON
                        path = services.save_passport_to_file(passaporto)
                        st.success(f"Passaporto salvato: {path}")
                        st.json(passaporto)

                        # Preview PDF + download
                        pdf_buf = services.export_passport_pdf(passaporto)
                        st.download_button("📄 Scarica Passaporto PDF", pdf_buf, "passaporto.pdf", "application/pdf")

                        # QR code
                        url = f"https://tuo-app.streamlit.app/passaporto/{mobile_id}"
                        qr_buf = services.generate_qr(url)
                        st.subheader("🔗 QR Code / NFC")
                        st.image(qr_buf)
                        st.caption("Usa lo stesso URL per NFC")
                        st.download_button("⬇️ Scarica QR", qr_buf, "qrcode.png", "image/png")
        else:
            st.info("Completa prima la validazione PDF e immagine")
