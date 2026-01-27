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
        "pdf": [
            "nome_prodotto",
            "produttore",
            "materiali",
            "dimensioni",
            "anno_produzione",
            "manufacturer_name",        # nuovo
            "manufacturer_address",     # nuovo
            "gtin",                     # nuovo
            "serial_number",            # nuovo
            "material_composition_detailed", # nuovo
            "carbon_footprint",         # nuovo
            "energy_use",               # nuovo
            "compliance_documents",     # nuovo
            "usage_instructions",       # nuovo
            "end_of_life_instructions"  # nuovo
        ],
        "image": [
            "colore",
            "condizioni"
        ]
    },
    "lampada": {
        "pdf": [
            "nome_prodotto",
            "produttore",
            "materiale",
            "wattaggio",
            "manufacturer_name",
            "manufacturer_address",
            "gtin",
            "serial_number",
            "material_composition_detailed",
            "carbon_footprint",
            "energy_use",
            "compliance_documents",
            "usage_instructions",
            "end_of_life_instructions"
        ],
        "image": [
            "colore",
            "stile",
            "condizioni"
        ]
    },
    "bicicletta": {
        "pdf": [
            "nome_prodotto",
            "produttore",
            "modello",
            "anno_produzione",
            "manufacturer_name",
            "manufacturer_address",
            "gtin",
            "serial_number",
            "material_composition_detailed",
            "carbon_footprint",
            "energy_use",
            "compliance_documents",
            "usage_instructions",
            "end_of_life_instructions"
        ],
        "image": [
            "colore_telaio",
            "condizioni"
        ]
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
    """Estrae dati tecnici obbligatori dal PDF tramite GPT."""
    campi = PRODUCT_FIELDS[tipo]["pdf"]
    prompt = f"""
Estrai tutti i dati tecnici obbligatori di un {tipo} secondo la normativa UE per Digital Product Passport.
Se un dato non è presente, usa null.
NON inventare valori.
Restituisci SOLO un JSON con le chiavi: {', '.join(campi)}.

TESTO PDF:
{text}
"""
    r = client.chat.completions.create(
        model="gpt-4.1",
        messages=[{"role":"user","content":prompt}],
        temperature=0
    )
    resp_text = r.choices[0].message.content.strip()
    try:
        data = json.loads(resp_text)
    except json.JSONDecodeError:
        data = {k: None for k in campi}  # default se JSON non valido
    return data


def gpt_analyze_image(image_b64, client: OpenAI, tipo):
    """
    Analizza un'immagine prodotto e restituisce JSON con i campi stimati.
    image_b64: stringa Base64 dell'immagine
    client: oggetto OpenAI
    tipo: tipo prodotto ('mobile', 'lampada', 'bicicletta')
    
    Restituisce un dizionario Python con:
        - colore
        - condizioni
    """
    # Campi che vogliamo dall'immagine
    campi = ["colore", "condizioni"]

    prompt = f"""
Hai a disposizione un prodotto di tipo '{tipo}' rappresentato da un'immagine codificata in Base64.
Non puoi vedere l'immagine direttamente, considera solo la Base64 come riferimento.
Restituisci SOLO un JSON con i seguenti campi: {', '.join(campi)}.
- 'colore': descrivi il colore dominante del prodotto.
- 'condizioni': descrivi se il prodotto è nuovo, usato, danneggiato, ecc.
Se un campo non è chiaro, usa null.
NON inventare nulla, restituisci solo JSON valido.
Esempio di output:
{{"colore": "bianco", "condizioni": "nuovo"}}
"""

    r = client.chat.completions.create(
        model="gpt-4.1",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    result_text = r.choices[0].message.content.strip()

    try:
        data = json.loads(result_text)
    except json.JSONDecodeError:
        # se GPT non restituisce JSON valido, ritorna campi a null
        data = {campo: None for campo in campi}
    return data


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

# ======================================================
# CONVERTER
# ======================================================

def image_to_base64(image_file):
    """
    Converte un file immagine caricato da Streamlit in stringa Base64.
    image_file: st.file_uploader (UploadedFile)
    """
    return base64.b64encode(image_file.getvalue()).decode()

def render_validation_form(data, title):
    st.subheader(title)
    validated = {}
    for k, v in data.items():
        label = k
        if k in ["manufacturer_name","gtin","serial_number"]:  # esempio campi obbligatori
            label += " *"  # aggiungi asterisco
        validated[k] = st.text_input(label, "" if v is None else str(v))
    return validated

