import streamlit as st
import uuid
from datetime import datetime
from functions.services import (
    extract_text_from_pdf,
    image_to_base64,
    gpt_extract_from_pdf,
    gpt_analyze_image,
    save_passport_to_file,
    export_passport_pdf,
    generate_qr
)
from openai import OpenAI

# ==============================
# CONFIG
# ==============================
st.set_page_config(page_title="Passaporto Digitale del Mobile", layout="wide")

# ==============================
# CLIENT OPENAI
# ==============================
client = OpenAI(api_key=st.secrets["OPEN_AI_KEY"])

# ==============================
# SESSION STATE
# ==============================
for key in ["pdf_data", "image_data", "validated_pdf", "validated_image"]:
    if key not in st.session_state:
        st.session_state[key] = None

# ==============================
# FUNZIONI DI SUPPORTO
# ==============================

def analyze_files(pdf_file, image_file):
    """Estrazione GPT con gestione errori"""
    try:
        pdf_text = extract_text_from_pdf(pdf_file)
        pdf_data = gpt_extract_from_pdf(pdf_text, client)
        st.session_state.pdf_data = pdf_data
    except Exception as e:
        st.error(f"Errore estrazione PDF: {e}")
        st.session_state.pdf_data = {}

    try:
        image_b64 = image_to_base64(image_file)
        image_data = gpt_analyze_image(image_b64, client)
        st.session_state.image_data = image_data
    except Exception as e:
        st.error(f"Errore analisi immagine: {e}")
        st.session_state.image_data = {}

def render_validation_form(data_dict, title="Validazione", columns_per_row=2):
    """Mostra form con validazione user-friendly e checkbox"""
    st.subheader(title)
    validated = {}
    keys = list(data_dict.keys())
    for i in range(0, len(keys), columns_per_row):
        cols = st.columns(columns_per_row)
        for j, key in enumerate(keys[i:i+columns_per_row]):
            value = data_dict[key]
            if isinstance(value, list) or len(str(value)) > 40:
                val = cols[j].text_area(key, value=", ".join(value) if isinstance(value, list) else str(value))
            else:
                val = cols[j].text_input(key, str(value) if value else "")
            confirm = cols[j].checkbox(f"Conferma {key}", value=True)
            if confirm:
                validated[key] = val.split(",") if isinstance(value, list) else val
    return validated

# ==============================
# MAIN
# ==============================
def main():
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
                        analyze_files(pdf_file, image_file)
                    st.success("Analisi completata!")

    # --- Tab 2: Validazione PDF ---
    with tabs[1]:
        if st.session_state.pdf_data:
            st.session_state.validated_pdf = render_validation_form(
                st.session_state.pdf_data, title="✔ Dati Certificati (PDF)"
            )
        else:
            st.info("Analizza prima il PDF nella tab Upload & Analisi")

    # --- Tab 3: Validazione Immagine ---
    with tabs[2]:
        if st.session_state.image_data:
            st.session_state.validated_image = render_validation_form(
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
                        path = save_passport_to_file(passaporto)
                        st.success(f"Passaporto salvato: {path}")
                        st.json(passaporto)

                        # Preview PDF + download
                        pdf_buf = export_passport_pdf(passaporto)
                        st.download_button("📄 Scarica Passaporto PDF", pdf_buf, "passaporto.pdf", "application/pdf")

                        # QR code
                        url = f"https://tuo-app.streamlit.app/passaporto/{mobile_id}"
                        qr_buf = generate_qr(url)
                        st.subheader("🔗 QR Code / NFC")
                        st.image(qr_buf)
                        st.caption("Usa lo stesso URL per NFC")
                        st.download_button("⬇️ Scarica QR", qr_buf, "qrcode.png", "image/png")
        else:
            st.info("Completa prima la validazione PDF e immagine")

if __name__ == "__main__":
    main()
