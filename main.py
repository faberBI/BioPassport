import streamlit as st
import pdfplumber
import json
import uuid
import qrcode
from PIL import Image
import openai
from io import BytesIO

# =====================
# CONFIG
# =====================
st.set_page_config(page_title="Passaporto del Mobile", layout="centered")

openai.api_key = "INSERISCI_LA_TUA_API_KEY"

# =====================
# FUNZIONI
# =====================

def extract_text_from_pdf(pdf_file):
    text = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text


def gpt_extract_from_pdf(text):
    prompt = f"""
Estrai le informazioni di un mobile dal testo seguente.
Restituisci SOLO un JSON con questi campi:
- nome_prodotto
- produttore
- materiali
- dimensioni
- anno_produzione
- certificazioni

TESTO:
{text}
"""

    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    content = response.choices[0].message.content
    return json.loads(content)


def gpt_analyze_image(image):
    prompt = """
Analizza l'immagine di un mobile e restituisci SOLO un JSON con:
- tipo_mobile
- materiali_visibili
- colore
- condizioni
- data di realizzazione
- paese di provenienza dei materiali
- 
"""

    response = openai.ChatCompletion.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": image}
                ],
            }
        ],
        temperature=0
    )

    content = response.choices[0].message.content
    return json.loads(content)


def generate_qr(url):
    qr = qrcode.make(url)
    buf = BytesIO()
    qr.save(buf)
    buf.seek(0)
    return buf


# =====================
# UI
# =====================

st.title("🪑 Passaporto Digitale del Mobile")

pdf_file = st.file_uploader("Carica PDF con le informazioni", type=["pdf"])
image_file = st.file_uploader("Carica foto del mobile", type=["jpg", "png", "jpeg"])

if st.button("🔍 Analizza con AI") and pdf_file and image_file:

    st.info("Analisi in corso...")

    # PDF
    pdf_text = extract_text_from_pdf(pdf_file)
    pdf_data = gpt_extract_from_pdf(pdf_text)

    # Immagine
    image = Image.open(image_file)
    st.image(image, caption="Foto caricata", use_column_width=True)

    image_data = gpt_analyze_image("data:image/jpeg;base64")  # placeholder

    # ID univoco
    mobile_id = str(uuid.uuid4())[:8]

    passaporto = {
        "id": mobile_id,
        "dati_pdf": pdf_data,
        "dati_visivi": image_data
    }

    st.success("Passaporto generato!")
    st.subheader("📄 Passaporto del Mobile (modificabile)")

    passaporto = st.json(passaporto)

    # URL fittizio
    url_passaporto = f"https://tuo-app.streamlit.app/passaporto/{mobile_id}"

    qr_buf = generate_qr(url_passaporto)

    st.subheader("🔗 QR Code")
    st.image(qr_buf)
    st.download_button("⬇️ Scarica QR Code", qr_buf, "qrcode.png", "image/png")
