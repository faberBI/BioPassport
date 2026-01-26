import streamlit as st
import uuid
from datetime import datetime
from openai import OpenAI
from functions import services
from auth.user_login import check_login, create_user

# ======================================================
# CONFIG
# ======================================================
st.set_page_config(
    page_title="Digital Product Passport (EU)",
    layout="wide"
)

# ======================================================
# SESSION STATE
# ======================================================
for key in [
    "logged_in",
    "username",
    "pdf_data",
    "image_data",
    "validated_pdf",
    "validated_image",
    "tipo_prodotto",
    "error_log"
]:
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

    with tab_login:
        username_login = st.text_input("Username", key="login_user")
        password_login = st.text_input("Password", type="password", key="login_pass")

        if st.button("Accedi"):
            if check_login(username_login, password_login):
                st.session_state.logged_in = True
                st.session_state.username = username_login
                st.rerun()
            else:
                st.error("Username o password errati")

    with tab_signup:
        username_signup = st.text_input("Nuovo Username", key="signup_user")
        password_signup = st.text_input("Nuova Password", type="password", key="signup_pass")

        if st.button("Crea account"):
            if create_user(username_signup, password_signup):
                st.success("Account creato. Ora puoi accedere.")
            else:
                st.error("Username già esistente")

# ======================================================
# MAIN APP
# ======================================================
else:
    # ---------------- Sidebar ----------------
    st.sidebar.success(f"Connesso come: {st.session_state.username}")

    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.rerun()

    st.sidebar.info(
        "📞 +39 0123 456789\n\n"
        "✉️ info@azienda.it"
    )

    # ---------------- Header ----------------
    st.title("🪑 Digital Product Passport (EU)")

    tipo_prodotto = st.selectbox(
        "Seleziona il tipo di prodotto",
        ["mobile", "lampada", "bicicletta"]
    )
    st.session_state.tipo_prodotto = tipo_prodotto

    tabs = st.tabs([
        "📤 Upload & Analisi",
        "📝 Validazione Dati (PDF)",
        "👁️ Validazione Dati (Immagine)",
        "🔗 Digital Product Passport"
    ])

    # ======================================================
    # TAB 1 — Upload & Analisi
    # ======================================================
    with tabs[0]:
        with st.form("upload_form"):
            pdf_file = st.file_uploader(
                "Carica PDF del prodotto",
                type=["pdf"]
            )
            image_file = st.file_uploader(
                "Carica immagine del prodotto",
                type=["jpg", "jpeg", "png"]
            )

            submitted = st.form_submit_button("🔍 Analizza")

            if submitted:
                st.session_state.error_log = []

                if not pdf_file or not image_file:
                    st.warning("Carica sia il PDF che l'immagine.")
                else:
                    with st.spinner("Analisi in corso…"):
                        try:
                            pdf_text = services.extract_text_from_pdf(pdf_file)
                            st.session_state.pdf_data = services.gpt_extract_from_pdf(
                                pdf_text, client, tipo_prodotto
                            )
                        except Exception as e:
                            st.session_state.pdf_data = {}
                            st.session_state.error_log.append(str(e))

                        try:
                            image_b64 = services.image_to_base64(image_file)
                            st.session_state.image_data = services.gpt_analyze_image(
                                image_b64, client, tipo_prodotto
                            )
                        except Exception as e:
                            st.session_state.image_data = {}
                            st.session_state.error_log.append(str(e))

                    st.success("Analisi completata")

    # ======================================================
    # TAB 2 — Validazione PDF
    # ======================================================
    with tabs[1]:
        if st.session_state.pdf_data:
            st.session_state.validated_pdf = services.render_validation_form(
                st.session_state.pdf_data,
                title="✔ Dati certificati (PDF)"
            )
        else:
            st.info("Completa prima l’analisi del PDF")

    # ======================================================
    # TAB 3 — Validazione Immagine
    # ======================================================
    with tabs[2]:
        if st.session_state.image_data:
            st.session_state.validated_image = services.render_validation_form(
                st.session_state.image_data,
                title="👁️ Dati stimati da immagine"
            )
        else:
            st.info("Completa prima l’analisi dell’immagine")

    # ======================================================
    # TAB 4 — DIGITAL PRODUCT PASSPORT (EU)
    # ======================================================
    with tabs[3]:
        if st.session_state.validated_pdf and st.session_state.validated_image:
            with st.form("create_passport_form"):
                submitted_pass = st.form_submit_button("🚀 Pubblica Digital Product Passport")

                if submitted_pass:
                    required = services.get_required_fields(tipo_prodotto)
                    missing = [
                        f for f in required
                        if not st.session_state.validated_pdf.get(f)
                    ]

                    if missing:
                        st.warning(
                            f"Campi obbligatori mancanti: {', '.join(missing)}"
                        )
                    else:
                        product_id = f"{tipo_prodotto.upper()}-{uuid.uuid4().hex[:8]}"

                        passport_data = {
                            "id": product_id,
                            "product_type": tipo_prodotto,
                            "created_at": datetime.utcnow().isoformat(),
                            "data_source_pdf": st.session_state.validated_pdf,
                            "data_source_image": st.session_state.validated_image,
                            "dpp_version": "EU-DPP-1.0"
                        }

                        services.save_passport_to_file(passport_data)

                        public_url = services.build_passport_url(product_id)
                        qr_buf = services.generate_qr_from_url(public_url)

                        st.success("Digital Product Passport pubblicato")

                        st.subheader("🔗 Accesso pubblico")
                        st.image(qr_buf)
                        st.code(public_url)

        else:
            st.info("Completa prima la validazione dei dati")

    # ======================================================
    # ERROR LOG
    # ======================================================
    if st.session_state.error_log:
        st.subheader("🛑 Errori")
        for err in st.session_state.error_log:
            st.text(err)
