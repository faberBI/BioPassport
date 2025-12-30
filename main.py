import streamlit as st
import uuid
from datetime import datetime
from openai import OpenAI
from functions import services
from auth.user_login import check_login, create_user

# ======================================================
# CONFIG
# ======================================================
st.set_page_config(page_title="Passaporto Digitale del Prodotto", layout="wide")

# ======================================================
# SESSION STATE
# ======================================================
for key in ["logged_in","username","pdf_data","image_data","validated_pdf","validated_image","tipo_prodotto"]:
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
    st.title("🔒 Accesso al sistema")
    tab_login, tab_signup = st.tabs(["Accedi", "Crea account"])

    # --- LOGIN ---
    with tab_login:
        username_login = st.text_input("Username", key="login_user")
        password_login = st.text_input("Password", type="password", key="login_pass")
        if st.button("Accedi", key="btn_login"):
            if check_login(username_login, password_login):
                st.session_state.logged_in = True
                st.session_state.username = username_login
                st.success(f"Benvenuto {username_login}!")
                st.experimental_rerun()
            else:
                st.error("Username o password errati")

    # --- CREAZIONE ACCOUNT ---
    with tab_signup:
        username_signup = st.text_input("Nuovo Username", key="signup_user")
        password_signup = st.text_input("Nuova Password", type="password", key="signup_pass")
        if st.button("Crea account", key="btn_signup"):
            if create_user(username_signup, password_signup):
                st.success("Account creato con successo! Ora puoi accedere nella tab 'Accedi'.")
            else:
                st.error("Username già esistente")

# ======================================================
# MAIN APP
# ======================================================
else:
    st.sidebar.success(f"Connesso come: {st.session_state.username}")
    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.experimental_rerun()

    st.sidebar.info("📞 Numero telefono: +39 0123 456789\n✉️ Email aziendale: info@azienda.it")

    st.title("🪑 Passaporto Digitale del Prodotto")
    tipo_prodotto = st.selectbox("Seleziona il tipo di prodotto", ["mobile","lampada","bicicletta"])
    st.session_state.tipo_prodotto = tipo_prodotto

    tabs = st.tabs(["📤 Upload & Analisi","📝 Validazione PDF","👁️ Validazione Immagine","📄 PDF & QR"])

    # --- Upload & Analisi ---
    with tabs[0]:
        with st.form("upload_form"):
            pdf_file = st.file_uploader("Carica PDF", type=["pdf"])
            image_file = st.file_uploader("Carica immagine", type=["jpg","png","jpeg"])
            submitted = st.form_submit_button("🔍 Analizza con AI")
            if submitted:
                if not pdf_file or not image_file:
                    st.warning("Carica sia PDF che immagine")
                else:
                    st.session_state.pdf_data = services.gpt_extract_from_pdf(pdf_file, client, tipo_prodotto)
                    st.session_state.image_data = services.gpt_analyze_image(image_file, client, tipo_prodotto)
                    st.success("Analisi completata!")

    # --- Validazione PDF ---
    with tabs[1]:
        if st.session_state.pdf_data:
            st.session_state.validated_pdf = services.render_validation_form(
                st.session_state.pdf_data,
                title=f"✔ Dati Certificati (PDF) - {tipo_prodotto}",
                columns_per_row=2
            )
        else:
            st.info("Analizza prima il PDF nella tab Upload & Analisi")

    # --- Validazione Immagine ---
    with tabs[2]:
        if st.session_state.image_data:
            st.session_state.validated_image = services.render_validation_form(
                st.session_state.image_data,
                title=f"👁️ Dati Visivi Stimati - {tipo_prodotto}",
                columns_per_row=2
            )
        else:
            st.info("Analizza prima l'immagine nella tab Upload & Analisi")

    # --- PDF + QR Download ---
    with tabs[3]:
        if st.session_state.validated_pdf and st.session_state.validated_image:
            if st.button("💾 Crea Passaporto"):
                product_id = f"{tipo_prodotto.upper()}-{str(uuid.uuid4())[:8]}"
                passport_data = {
                    "id": product_id,
                    "tipo_prodotto": tipo_prodotto,
                    "metadata": {"creato_il": datetime.now().isoformat(), "versione":"1.0"},
                    "dati_certificati_pdf": st.session_state.validated_pdf,
                    "dati_visivi_stimati": st.session_state.validated_image
                }
                path = services.save_passport_to_file(passport_data)
                st.success(f"Passaporto salvato: {path}")
                st.json(passport_data)
                pdf_buf = services.export_passport_pdf(passport_data)
                st.download_button("📄 Scarica PDF", pdf_buf, "passaporto.pdf", "application/pdf")
                qr_buf = services.generate_qr_from_json(passport_data)
                st.image(qr_buf)
                st.download_button("⬇️ Scarica QR", qr_buf, "qrcode.png", "image/png")
        else:
            st.info("Completa prima la validazione PDF e immagine")
