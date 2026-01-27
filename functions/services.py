import pdfplumber
import json
import base64
import qrcode
import os
from io import BytesIO
from openai import OpenAI
import streamlit as st

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


def gpt_analyze_image(image_file_or_b64, client: OpenAI, tipo):
    """
    Analizza un'immagine prodotto e restituisce JSON con i campi stimati (solo colore e condizioni).
    
    image_file_or_b64: UploadedFile di Streamlit o stringa Base64
    client: oggetto OpenAI
    tipo: tipo prodotto ('mobile', 'lampada', 'bicicletta')
    """
    campi = PRODUCT_FIELDS[tipo]["image"]

    # Se riceve un UploadedFile, converte in Base64; altrimenti assume già Base64
    if hasattr(image_file_or_b64, "getvalue"):
        image_b64 = base64.b64encode(image_file_or_b64.getvalue()).decode()
    else:
        image_b64 = image_file_or_b64

    # Prompt chiaro e limitato ai campi richiesti, includendo la Base64 reale
    prompt = f"""
Hai un prodotto di tipo '{tipo}' rappresentato da un'immagine.
Ecco la Base64 dell'immagine: {image_b64}

Estrai SOLO queste informazioni in JSON: {', '.join(campi)}.
- colore: descrivi il colore predominante.
- condizioni: descrivi lo stato generale (nuovo, usato, danneggiato, ecc.)
Se non puoi determinare un campo, usa null.
NON inventare altre informazioni.
Esempio di output JSON:
{{"colore": "bianco", "condizioni": "nuovo"}}
"""

    try:
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )

        result_text = r.choices[0].message.content.strip()

        # Prova a parsare JSON
        data = json.loads(result_text)

        # Assicura che tutti i campi siano presenti
        for c in campi:
            if c not in data:
                data[c] = None

        return data

    except json.JSONDecodeError:
        st.error("Errore: GPT non ha restituito JSON valido dall'immagine")
        st.code(result_text)
        return {k: None for k in campi}

    except Exception as e:
        st.error(f"Errore GPT: {e}")
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
