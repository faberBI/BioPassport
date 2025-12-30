import streamlit as st
import uuid
from datetime import datetime
from openai import OpenAI, error as openai_error
from functions import services
from auth.user_login import check_login, create_user

# ======================================================
# CONFIG
# ======================================================
st.set_page_config(page_title="Passaporto Digitale del Prodotto", layout="wide")

# ======================================================
# SESSION STATE
# ======================================================
for key in [
    "logged_in", "username", "pdf_data", "image_data",
    "validated_pdf", "validated_image", "tipo_prodotto", "logs"
]:
    if key not in st.session_state:
        st.session_state[key] = False if key == "logged_in" else None

if st.session_state.logs is None:
    st.session_state.logs = []

# ======================================================
# OPENAI CLIENT
# ======================================================
client = OpenAI(api_key=st.secrets["OPEN_AI_KEY"])

# ======================================================
# LOGIN / REGISTRAZIONE
# ======================================================
if not st.session_state.logged_in:
    st.title("🔒 Accesso al sistema")

    tab_login, tab_signup = st.tabs(["Accedi", "Crea account"])

    # --- Tab Login ---
    with tab_login:
        username_login = st.text_input("Username", key="login_user")
        password_login = st.text_input("Password", type="password", key="login_pass")
        if st.button("Accedi", key="btn_login"):
            try:
                if check_login(username_login, password_login):
                    st.session_state.logged_in = True
                    st.session_state.username = username_login
                    st.success(f"Benvenuto {username_login}!")
                    st.experimental_rerun()
                else:
                    st.error("Username o password errati")
            except Exception as e:
                st.error("Errore login!")
                st.session_state.logs.append(f"LOGIN ERROR: {e}")

    # --- Tab Registrazione ---
    with tab_signup:
        username_signup = st.text_input("Nuovo Username", key="signup_user")
        password_signup = st.text_input("Nuova Password", type="password", key="signup_pass")
        if st.button("Crea account", key="btn_signup"):
            try:
                if create_user(username_signup, password_signup):
                    st.success("Account creato con successo! Ora puoi accedere nella tab 'Accedi'.")
                else:
                    st.error("Username già esistente")
            except Exception as e:
                st.error("Errore creazione account!")
                st.session_state.logs.append(f"SIGNUP ERROR: {e}")

# ======================================================
# MAIN APP
# ======================================================
else:
    st.sidebar.success(f"Connesso come: {st.session_state.username}")
    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.experimental_rerun()

    st.sidebar.info("""
📞 Numero telefono: +39 0123 456789  
✉️ Email aziendale: info@azienda.it
""")

    st.title("🪑 Passaporto Digitale del Prodotto")

    tipo_prodotto = st.selectbox("Seleziona il tipo di prodotto", ["mobile", "lampada", "bicicletta"])
    st.session_state.tipo_prodotto = tipo_prodotto

    tabs = st.tabs(["📤 Upload & Analisi", "📝 Validazione PDF", "👁️ Validazione Immagine", "📄 PDF & QR", "⚠️ Log Errori"])

    # --- Tab 1: Upload & Analisi ---
    with tabs[0]:
        with st.form("upload_form"):
            pdf_file = st.file_uploader("Carica PDF del prodotto", type=["pdf"])
            image_file = st.file_uploader("Carica foto del prodotto", type=["jpg", "png", "jpeg"])
            submitted = st.form_submit_button("🔍 Analizza con AI")

            if submitted:
                if not pdf_file or not image_file:
                    st.warning("Carica sia il PDF che l'immagine.")
                else:
                    with st.spinner("Analisi in corso..."):
                        # Estrazione PDF
                        try:
                            pdf_text = services.extract_text_from_pdf(pdf_file)
                            try:
                                st.session_state.pdf_data = services.gpt_extract_from_pdf(
                                    pdf_text, client, tipo_prodotto
                                )
                            except openai_error.RateLimitError as e:
                                st.error("Errore: troppe richieste all'API OpenAI. Riprova tra qualche secondo.")
                                st.session_state.logs.append(f"RateLimitError PDF: {e}")
                                st.session_state.pdf_data = {}
                            except openai_error.OpenAIError as e:
                                st.error("Errore API OpenAI durante estrazione PDF")
                                st.session_state.logs.append(f"OpenAIError PDF: {e}")
                                st.session_state.pdf_data = {}
                        except Exception as e:
                            st.error(f"Errore estrazione PDF: {e}")
                            st.session_state.logs.append(f"PDF Extraction Error: {e}")
                            st.session_state.pdf_data = {}

                        # Analisi immagine
                        try:
                            image_b64 = services.image_to_base64(image_file)
                            try:
                                st.session_state.image_data = services.gpt_analyze_image(
                                    image_b64, client, tipo_prodotto
                                )
                            except openai_error.RateLimitError as e:
                                st.error("Errore: troppe richieste all'API OpenAI. Riprova tra qualche secondo.")
                                st.session_state.logs.append(f"RateLimitError Image: {e}")
                                st.session_state.image_data = {}
                            except openai_error.OpenAIError as e:
                                st.error("Errore API OpenAI durante analisi immagine")
                                st.session_state.logs.append(f"OpenAIError Image: {e}")
                                st.session_state.image_data = {}
                        except Exception as e:
                            st.error(f"Errore analisi immagine: {e}")
                            st.session_state.logs.append(f"Image Analysis Error: {e}")
                            st.session_state.image_data = {}

                    st.success("Analisi completata!")

    # --- Tab 2: Validazione PDF ---
    with tabs[1]:
        if st.session_state.pdf_data:
            st.session_state.validated_pdf = services.render_validation_form(
                st.session_state.pdf_data,
                title=f"✔ Dati Certificati (PDF) - {tipo_prodotto}"
            )
        else:
            st.info("Analizza prima il PDF nella tab Upload & Analisi")

    # --- Tab 3: Validazione Immagine ---
    with tabs[2]:
        if st.session_state.image_data:
            st.session_state.validated_image = services.render_validation_form(
                st.session_state.image_data,
                title=f"👁️ Dati Visivi Stimati - {tipo_prodotto}"
            )
        else:
            st.info("Analizza prima l'immagine nella tab Upload & Analisi")

    # --- Tab 4: PDF + QR Download ---
    with tabs[3]:
        if st.session_state.validated_pdf and st.session_state.validated_image:
            with st.form("create_passport_form"):
                submitted_pass = st.form_submit_button("💾 Crea Passaporto")
                if submitted_pass:
                    required_fields = services.get_required_fields(tipo_prodotto)
                    missing = [f for f in required_fields if not st.session_state.validated_pdf.get(f)]
                    if missing:
                        st.warning(f"Compila i campi obbligatori: {', '.join(missing)}")
                    else:
                        product_id = f"{tipo_prodotto.upper()}-{str(uuid.uuid4())[:8]}"
                        passport_data = {
                            "id": product_id,
                            "tipo_prodotto": tipo_prodotto,
                            "metadata": {
                                "creato_il": datetime.now().isoformat(),
                                "versione": "1.0"
                            },
                            "dati_certificati_pdf": st.session_state.validated_pdf,
                            "dati_visivi_stimati": st.session_state.validated_image
                        }
                        path = services.save_passport_to_file(passport_data)
                        st.success(f"Passaporto salvato: {path}")
                        st.json(passport_data)

                        pdf_buf = services.export_passport_pdf(passport_data)
                        st.download_button("📄 Scarica Passaporto PDF", pdf_buf, "passaporto.pdf", "application/pdf")

                        qr_buf = services.generate_qr_from_json(passport_data)
                        st.subheader("🔗 QR Code / NFC (funziona offline)")
                        st.image(qr_buf)
                        st.download_button("⬇️ Scarica QR", qr_buf, "qrcode.png", "image/png")
        else:
            st.info("Completa prima la validazione PDF e immagine")

    # --- Tab 5: Log Errori ---
    with tabs[4]:
        st.subheader("📋 Log degli errori")
        if st.session_state.logs:
            for log in st.session_state.logs:
                st.text(log)
        else:
            st.info("Nessun errore registrato")
