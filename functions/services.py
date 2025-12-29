import pdfplumber
import json
import base64
import qrcode
import os
from io import BytesIO
from openai import OpenAI
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ======================================================
# PDF
# ======================================================

def extract_text_from_pdf(pdf_file) -> str:
    text = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text


# ======================================================
# IMAGE
# ======================================================

def image_to_base64(image_file) -> str:
    return base64.b64encode(image_file.getvalue()).decode("utf-8")


# ======================================================
# GPT
# ======================================================

def gpt_extract_from_pdf(text: str) -> dict:
    prompt = f"""
Estrai informazioni tecniche di un mobile dal testo seguente.
Se un dato NON è presente usa null.
Non inventare.

Restituisci SOLO JSON con:
- nome_prodotto
- produttore
- materiali
- dimensioni
- anno_produzione
- certificazioni
- codice_prodotto
- lotto_produzione
- luogo_produzione
- istruzioni_manutenzione
- istruzioni_smaltimento

TESTO:
{text}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    return json.loads(response.choices[0].message.content)


def gpt_analyze_image(image_b64: str) -> dict:
    prompt = """
Analizza l'immagine di un mobile.
Restituisci SOLO JSON con:
- tipo_mobile
- materiali_visibili
- colore
- condizioni

Usa solo informazioni deducibili visivamente.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_b64}"
                        }
                    }
                ],
            }
        ],
        temperature=0
    )

    return json.loads(response.choices[0].message.content)


# ======================================================
# STORAGE
# ======================================================

def save_passport_to_file(passaporto: dict) -> str:
    os.makedirs("passaporti", exist_ok=True)
    path = f"passaporti/{passaporto['id']}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(passaporto, f, indent=2, ensure_ascii=False)
    return path


# ======================================================
# QR
# ======================================================

def generate_qr(url: str) -> BytesIO:
    qr = qrcode.make(url)
    buf = BytesIO()
    qr.save(buf)
    buf.seek(0)
    return buf


# ======================================================
# PDF EXPORT
# ======================================================

def export_passport_pdf(passaporto: dict) -> BytesIO:
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    text = c.beginText(40, 800)

    text.textLine("PASSAPORTO DIGITALE DEL MOBILE")
    text.textLine("")
    text.textLine(f"ID: {passaporto['id']}")
    text.textLine("")

    for section, values in passaporto.items():
        if isinstance(values, dict):
            text.textLine(section.upper())
            for k,
