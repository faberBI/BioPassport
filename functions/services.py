import pdfplumber
import json
import base64
import qrcode
import os
from io import BytesIO
from openai import OpenAI
import streamlit as st
import re

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
            "nome_produttore",             # ex manufacturer_name
            "indirizzo_produttore",        # ex manufacturer_address
            "gtin",                        # codice a barre internazionale
            "numero_serie",                # ex serial_number
            "composizione_materiali_dettagliata", # ex material_composition_detailed
            "impronta_carbonio",           # ex carbon_footprint
            "consumo_energia",             # ex energy_use
            "documenti_conformita",        # ex compliance_documents
            "istruzioni_uso",              # ex usage_instructions
            "istruzioni_fine_vita"         # ex end_of_life_instructions
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
            "nome_produttore",
            "indirizzo_produttore",
            "gtin",
            "numero_serie",
            "composizione_materiali_dettagliata",
            "impronta_carbonio",
            "consumo_energia",
            "documenti_conformita",
            "istruzioni_uso",
            "istruzioni_fine_vita"
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
            "nome_produttore",
            "indirizzo_produttore",
            "gtin",
            "numero_serie",
            "composizione_materiali_dettagliata",
            "impronta_carbonio",
            "consumo_energia",
            "documenti_conformita",
            "istruzioni_uso",
            "istruzioni_fine_vita"
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
import re

def gpt_extract_from_pdf(text, client: OpenAI, tipo):
    campi = PRODUCT_FIELDS[tipo]["pdf"]
    prompt = f"""
Estrai i dati tecnici del prodotto di tipo '{tipo}' dal seguente testo PDF.
Se un dato non è presente nel PDF, restituisci null.
NON inventare.
Restituisci SOLO un JSON con i campi: {', '.join(campi)}.

TESTO:
{text}
"""
    r = client.chat.completions.create(
        model="gpt-4.1",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    resp_text = r.choices[0].message.content.strip()

    # Pulisce solo spazi e newline iniziali/finali
    resp_text_clean = resp_text.strip()

    try:
        data_gpt = json.loads(resp_text_clean)
    except json.JSONDecodeError:
        st.error("GPT non ha restituito JSON valido. Mostro la risposta grezza:")
        st.code(resp_text)
        data_gpt = {}

    # Popola tutti i campi definiti in PRODUCT_FIELDS
    data_finale = {}
    for campo in campi:
        # Se il campo esiste nel JSON di GPT lo prendi, altrimenti None
        data_finale[campo] = data_gpt.get(campo, None)

    return data_finale




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

def render_validation_form(data, title="", prefix=""):
    """
    Crea form Streamlit per validare manualmente i dati estratti.
    Non salva direttamente in session_state.
    prefix: stringa opzionale per distinguere chiavi PDF/immagine
    """
    st.subheader(title)
    validated = {}
    for k, v in data.items():
        key = f"{prefix}_{k}" if prefix else k
        validated[k] = st.text_input(k, "" if v is None else str(v), key=key)
    return validated


