import os
import json
import base64
from io import BytesIO
import pdfplumber
import qrcode
import streamlit as st
from openai import OpenAI

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
        "image": ["colore", "condizioni"]
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
        "image": ["colore", "stile", "condizioni"]
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
        "image": ["colore_telaio", "condizioni"]
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
    """Converte immagine in base64 per invio o salvataggio."""
    return base64.b64encode(image_file.getvalue()).decode()

# ======================================================
# GPT EXTRACTION
# ======================================================
def gpt_extract_from_pdf(text, client: OpenAI, tipo: str):
    """Estrae dati dal PDF tramite GPT e ritorna dict con tutti i campi definiti."""
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

    # Pulizia JSON robusta
    import re
    match = re.search(r"\{.*\}", resp_text, re.DOTALL)
    resp_text_clean = match.group(0) if match else resp_text
    resp_text_clean = resp_text_clean.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")

    try:
        data_gpt = json.loads(resp_text_clean)
    except json.JSONDecodeError:
        st.error("GPT non ha restituito JSON valido. Mostro la risposta grezza:")
        st.code(resp_text)
        data_gpt = {}

    # Popola tutti i campi definiti
    data_finale = {}
    for campo in campi:
        val = data_gpt.get(campo, None)
        data_finale[campo] = "" if val is None else val

    return data_finale

def gpt_analyze_image(image_file, client: OpenAI, tipo: str):
    """Analizza immagine e ritorna dict con campi stimati."""
    campi = PRODUCT_FIELDS[tipo]["image"]
    prompt = f"""
Hai a disposizione un prodotto di tipo '{tipo}' rappresentato da un'immagine codificata in Base64.
Restituisci SOLO un JSON con i seguenti campi: {', '.join(campi)}.
Se un campo non è chiaro, usa null.
NON inventare nulla.
Esempio di output:
{{{', '.join([f'"{c}": "valore"' for c in campi])}}}
"""
    image_b64 = image_to_base64(image_file)
    r = client.chat.completions.create(
        model="gpt-4.1",
        messages=[{"role": "user", "content": prompt + f"\nBase64: {image_b64}"}],
        temperature=0
    )

    result_text = r.choices[0].message.content.strip()
    try:
        data = json.loads(result_text)
    except json.JSONDecodeError:
        data = {campo: "" for campo in campi}
    # Convert None -> ""
    for k in campi:
        if k not in data or data[k] is None:
            data[k] = ""
    return data

# ======================================================
# FIELD MAPPING
# ======================================================
def map_gpt_fields(pdf_or_image_data: dict, tipo: str, source: str = "pdf") -> dict:
    """Mappa i campi GPT a quelli previsti dal form per precompilare."""
    mapped = {}
    campi = PRODUCT_FIELDS[tipo][source]
    for campo in campi:
        if campo in pdf_or_image_data:
            mapped[campo] = pdf_or_image_data.get(campo)
        else:
            alt_map = {
                "produttore": pdf_or_image_data.get("nome_produttore"),
                "nome_produttore": pdf_or_image_data.get("produttore"),
                "indirizzo_produttore": pdf_or_image_data.get("indirizzo_produttore"),
                "composizione_materiali_dettagliata": pdf_or_image_data.get("materiale_dettagliato"),
                "impronta_carbonio": pdf_or_image_data.get("carbon_footprint"),
                "consumo_energia": pdf_or_image_data.get("energy_use"),
                "documenti_conformita": pdf_or_image_data.get("compliance_documents"),
                "istruzioni_uso": pdf_or_image_data.get("usage_instructions"),
                "istruzioni_fine_vita": pdf_or_image_data.get("end_of_life_instructions"),
                "numero_serie": pdf_or_image_data.get("serial_number"),
                "gtin": pdf_or_image_data.get("gtin"),
            }
            mapped[campo] = alt_map.get(campo, "")
    # Converti eventuali None in stringa vuota
    for k in mapped:
        if mapped[k] is None:
            mapped[k] = ""
    return mapped

# ======================================================
# VALIDATION FORM
# ======================================================
def render_validation_form(data: dict, title: str = "", prefix: str = "") -> dict:
    """Renderizza form di validazione in Streamlit, popola i campi."""
    st.subheader(title)
    validated = {}
    for k, v in data.items():
        field_key = f"{prefix}_{k}" if prefix else k
        default_value = "" if v is None else str(v)
        validated_value = st.text_input(f"{k.replace('_',' ').capitalize()}:", value=default_value, key=field_key)
        validated[k] = validated_value.strip() if validated_value else ""
    return validated

# ======================================================
# PASSPORT STORAGE
# ======================================================
def save_passport_to_file(passport: dict):
    os.makedirs(PASSPORT_DIR, exist_ok=True)
    path = os.path.join(PASSPORT_DIR, f"{passport['id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(passport, f, indent=2, ensure_ascii=False)

def load_passport_from_file(passport_id: str):
    path = os.path.join(PASSPORT_DIR, f"{passport_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# ======================================================
# QR CODE
# ======================================================
def generate_qr_from_url(url: str) -> BytesIO:
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
