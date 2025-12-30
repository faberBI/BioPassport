import pdfplumber
import json
import base64
import qrcode
import os
from io import BytesIO
from openai import OpenAI
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# ======================================================
# CAMPi PER TIPO PRODOTTO
# ======================================================
PRODUCT_FIELDS = {
    "mobile": {
        "pdf": ["nome_prodotto","produttore","materiali","dimensioni","anno_produzione",
                "certificazioni","codice_prodotto","lotto_produzione","luogo_produzione",
                "istruzioni_manutenzione","istruzioni_smaltimento"],
        "image": ["tipo_mobile","materiali_visibili","colore","condizioni"]
    },
    "lampada": {
        "pdf": ["nome_prodotto","produttore","materiale","wattaggio","anno_produzione"],
        "image": ["colore","stile","forma"]
    },
    "bicicletta": {
        "pdf": ["nome_prodotto","produttore","modello","anno_produzione","tipo_freni", "tipo_telaio", "tipo_ruote", "tipo_cambio" ],
        "image": ["colore_telaio","tipo_sella","condizioni"]
    }
}

def get_required_fields(tipo_prodotto: str):
    return PRODUCT_FIELDS.get(tipo_prodotto, {}).get("pdf", [])

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
def gpt_extract_from_pdf(text: str, client: OpenAI, tipo_prodotto="mobile") -> dict:
    campi = PRODUCT_FIELDS.get(tipo_prodotto, {}).get("pdf", [])
    prompt = f"""
Estrai informazioni tecniche di un {tipo_prodotto} dal testo seguente.
Se un dato NON è presente usa null.
Non inventare.

Restituisci SOLO JSON con campi: {', '.join(campi)}

TESTO:
{text}
"""
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    return json.loads(response.choices[0].message.content)

def gpt_analyze_image(image_b64: str, client: OpenAI, tipo_prodotto="mobile") -> dict:
    campi = PRODUCT_FIELDS.get(tipo_prodotto, {}).get("image", [])
    prompt = f"""
Analizza l'immagine di un {tipo_prodotto}.
Restituisci SOLO JSON con campi: {', '.join(campi)}
Usa solo informazioni deducibili visivamente.
"""
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": f"data:image/jpeg;base64,{image_b64}"}
            ]
        }],
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
# QR OFFLINE
# ======================================================
def generate_qr_from_json(passaporto: dict) -> BytesIO:
    json_str = json.dumps(passaporto)
    b64_str = base64.b64encode(json_str.encode()).decode()

    qr = qrcode.QRCode(version=10, box_size=8, border=4)
    qr.add_data(b64_str)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

# ======================================================
# PDF EXPORT
# ======================================================
def export_passport_pdf(passaporto: dict) -> BytesIO:
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    text = c.beginText(40, 800)

    text.textLine(f"PASSAPORTO DIGITALE DEL {passaporto.get('tipo_prodotto', 'PRODOTTO').upper()}")
    text.textLine(f"ID: {passaporto['id']}")
    text.textLine("")

    for section, values in passaporto.items():
        if isinstance(values, dict):
            text.textLine(section.upper())
            for k, v in values.items():
                text.textLine(f"- {k}: {v}")
            text.textLine("")

    c.drawText(text)
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer

# ======================================================
# RENDER VALIDATION FORM
# ======================================================
def render_validation_form(data: dict, title="Validazione", tipo_prodotto="mobile", columns_per_row=1):
    st.subheader(title)
    validated_data = {}
    cols = st.columns(columns_per_row)
    i = 0
    for key, value in data.items():
        col = cols[i % columns_per_row]
        if isinstance(value, str):
            validated_data[key] = col.text_input(key, value)
        elif isinstance(value, list):
            validated_data[key] = col.text_area(key, ", ".join(value))
        else:
            validated_data[key] = col.text_input(key, str(value))
        i += 1
    return validated_data
