import streamlit as st
import uuid
from datetime import datetime
from services import (
    extract_text_from_pdf,
    image_to_base64,
    gpt_extract_from_pdf,
    gpt_analyze_image,
    save_passport_to_file,
    export_passport_pdf,
    generate_qr
)

# ======================================================
# CONFIG
# ======================================================

st.set_page_config(
    page_title="Passaporto Digitale del Mobile",
    layout="centered"
)

# ======================================================
# MAIN
# ======================================================

def main():

    st.title("🪑 Passaporto Digitale del Mobile")

    pdf_file = st.file_uploader("Carica PDF del mobile", type=["pdf"])
    image_file = st.file_uploader("Carica foto del mobile", type=["jpg", "png", "jpeg"])

    if st.button("🔍 Analizza con AI"):

        if not pdf_file or not image_file:
            st.warning("Carica PDF e immagine.")
            return

        with st.spinner("Analisi in corso..."):

            pdf_text = extract_text_from_pdf(pdf_file)
            pdf_data = gpt_extract_from_pdf(pdf_text)

            image_b64 = image_to_base64(image_file)
            image_data = gpt_analyze_image(image_b64)

        st.success("Analisi completata")

        # =========================
        # VALIDAZIONE PDF
        # =========================
        st.subheader("✔ Dati certificati (da PDF)")

        validated_pdf = {}
        for key, value in pdf_data.items():
            validated_pdf[key] = st.text_input(key, str(value) if value else "")

        # =========================
        # VALIDAZIONE IMAGE
        # =========================
        st.subheader("👁️ Dati visivi stimati")

        validated_image = {}
        for key, value in image_data.items():
            validated_image[key] = st.text_input(key, str(value) if value else "")

        # =========================
        # CREAZIONE PASSAPORTO
        # =========================
        if st.button("💾 Crea Passaporto"):

            mobile_id = f"MOB-{str(uuid.uuid4())[:8]}"

            passaporto = {
                "id": mobile_id,
                "metadata": {
                    "creato_il": datetime.now().isoformat(),
                    "versione": "1.0"
                },
                "dati_certificati_pdf": validated_pdf,
                "dati_visivi_stimati": validated_image
            }

            path = save_passport_to_file(passaporto)

            st.success(f"Passaporto salvato: {path}")
            st.json(passaporto)

            # =========================
            # EXPORT PDF
            # =========================
            pdf_buf = export_passport_pdf(passaporto)
            st.download_button(
                "📄 Scarica Passaporto PDF",
                pdf_buf,
                "passaporto.pdf",
                "application/pdf"
            )

            # =========================
            # QR
            # =========================
            url = f"https://tuo-app.streamlit.app/passaporto/{mobile_id}"
            qr_buf = generate_qr(url)

            st.subheader("🔗 QR Code / NFC")
            st.image(qr_buf)
            st.caption("Usa lo stesso URL per NFC")

            st.download_button(
                "⬇️ Scarica QR",
                qr_buf,
                "qrcode.png",
                "image/png"
            )


if __name__ == "__main__":
    main()
