import pdfplumber
import json
import base64
import qrcode
import os
from io import BytesIO
from openai import OpenAI
import streamlit as st
from PIL import Image


# ======================================================
# CONFIG
# ======================================================
PASSPORT_DIR = "passports"

PRODUCT_FIELDS = {
    "mobile": {
        "pdf": ["nome_prodotto","produttore","materiali","dimensioni","anno_produzione"],
        "image": ["colore","condizioni"]
    },
    "lampada": {
        "pdf": ["nome_prodotto","produttore","materiale","wattaggio"],
        "image": ["colore","stile"]
    },
    "bicicletta": {
        "pdf": ["nome_prodotto","produttore","modello","anno_produzione"],
        "image": ["colore_telaio","condizioni"]
    }
}

# ======================================================
# PDF / IMAGE UTILITIES
# ======================================================
def extract_text_from_pdf(pdf_file):
    """Estrae tutto il testo da un PDF."""
    text = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text

def image_to_base64(image_file):
    """Converte immagine in base64 per invio a GPT."""
    return base64.b64encode(image_file.getvalue()).decode()

# ======================================================
# GPT EXTRACTION
# ======================================================
def gpt_extract_from_pdf(text, client: OpenAI, tipo):
    """Estrae dati tecnici dal PDF tramite GPT, in modo robusto."""
    campi = PRODUCT_FIELDS[tipo]["pdf"]
    prompt = f"""
Estrai dati tecnici di un {tipo}.
Se un dato manca usa null.
NON inventare.
Restituisci SOLO JSON con: {', '.join(campi)}

TESTO:
{text}
"""
    try:
        r = client.chat.completions.create(
            model="gpt-4.1",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )

        resp_text = r.choices[0].message.content.strip()

        # Rimuove eventuali blocchi ```json ... ```
        if resp_text.startswith("```"):
            resp_text = "\n".join(resp_text.split("\n")[1:-1]).strip()

        data = json.loads(resp_text)
        # Assicura che tutti i campi siano presenti
        for c in campi:
            if c not in data:
                data[c] = None

        return data

    except json.JSONDecodeError:
        st.error("GPT non ha restituito JSON valido. Ecco la risposta grezza:")
        st.code(resp_text)
        # Ritorna comunque un dizionario con tutti i campi a None
        return {c: None for c in campi}
    except Exception as e:
        st.error(f"Errore GPT: {e}")
        st.stop()


import json
import streamlit as st
from openai import OpenAI

def gpt_analyze_image(image_file, client, tipo):
    """
    Analizza un'immagine prodotto usando GPT-4o (vision reale)
    e restituisce JSON con: colore, condizioni
    """

    campi = PRODUCT_FIELDS[tipo]["image"]

    try:
        # --- 1️⃣ Apri immagine ---
        img = Image.open(image_file).convert("RGB")

        # --- 2️⃣ Ridimensiona (performance) ---
        img.thumbnail((512, 512))

        # --- 3️⃣ Salva in PNG valido ---
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        # --- 4️⃣ Encode Base64 (solo per API images) ---
        image_b64 = base64.b64encode(buf.read()).decode("utf-8")

        # --- 5️⃣ Prompt ultra-vincolato ---
        prompt = f"""
Analizza l'immagine di un prodotto di tipo "{tipo}".

Restituisci SOLO JSON valido con questi campi:
{', '.join(campi)}

Regole:
- colore: colore predominante
- condizioni: nuovo, usato, danneggiato, ecc.
- Se non determinabile usa null
- NON aggiungere testo
"""

        # --- 6️⃣ Chiamata GPT Vision ---
        response = client.responses.create(
            model="gpt-4o",
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {
                        "type": "input_image",
                        "image_base64": image_b64
                    }
                ]
            }],
            temperature=0
        )

        # --- 7️⃣ Estrai testo ---
        result_text = response.output_text

        # --- 8️⃣ Parse JSON robusto ---
        data = safe_json_parse(result_text)

        # --- 9️⃣ Allinea campi ---
        return {k: data.get(k) for k in campi}

    except json.JSONDecodeError:
        st.error("GPT non ha restituito JSON valido dall'immagine")
        st.code(result_text)
        return {k: None for k in campi}

    except Exception as e:
        st.error(f"Errore GPT Image: {e}")
        st.stop()


# ======================================================
# VALIDATION FORM
# ======================================================
def render_validation_form(data, title):
    """Crea form Streamlit per validare manualmente i dati estratti."""
    st.subheader(title)
    validated = {}
    for k, v in data.items():
        validated[k] = st.text_input(k, "" if v is None else str(v))
    return validated

# ======================================================
# PASSPORT STORAGE
# ======================================================
def save_passport_to_file(passport):
    """Salva passport JSON su disco."""
    os.makedirs(PASSPORT_DIR, exist_ok=True)
    path = os.path.join(PASSPORT_DIR, f"{passport['id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(passport, f, indent=2, ensure_ascii=False)

def load_passport_from_file(passport_id):
    """Carica passport JSON da disco."""
    path = os.path.join(PASSPORT_DIR, f"{passport_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# ======================================================
# QR CODE
# ======================================================
def generate_qr_from_url(url):
    """Genera QR code da un URL e ritorna BytesIO pronto per Streamlit."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4
    )
    qr.add_data(url)
    qr.make(fit=True)
    buf = BytesIO()
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(buf)
    buf.seek(0)
    return buf

def upload_image_to_openai(image_file, client):
    resized = resize_image_for_vision(image_file)

    uploaded = client.files.create(
        file=resized,
        purpose="vision"
    )
    return uploaded.id


from PIL import Image
from io import BytesIO

def resize_image_for_vision(image_file, max_size=512):
    img = Image.open(image_file).convert("RGB")
    img.thumbnail((max_size, max_size))

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    buf.seek(0)

    # risalva in formato jpg
    buf.name = "image.jpg"

    return buf

def safe_json_parse(text):
    text = text.strip()

    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        ).strip()

    return json.loads(text)


