import pdfplumber
import json
import base64
import qrcode
import os
from io import BytesIO
from openai import OpenAI
import streamlit as st

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

def extract_text_from_pdf(pdf_file):
    text = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text

def image_to_base64(image_file):
    return base64.b64encode(image_file.getvalue()).decode()

def gpt_extract_from_pdf(text, client: OpenAI, tipo):
    campi = PRODUCT_FIELDS[tipo]["pdf"]
    prompt = f"""
Estrai dati tecnici di un {tipo}.
Se un dato manca usa null.
NON inventare.
Restituisci SOLO JSON con: {', '.join(campi)}

TESTO:
{text}
"""
    r = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[{"role":"user","content":prompt}],
        temperature=0
    )
    return json.loads(r.choices[0].message.content)

def gpt_analyze_image(image_b64, client: OpenAI, tipo):
    campi = PRODUCT_FIELDS[tipo]["image"]
    prompt = f"""
Analizza l'immagine.
Restituisci SOLO JSON con: {', '.join(campi)}
"""
    r = client.chat.completions.create(
        model="gpt-5-mini",
        messages=[{
            "role":"user",
            "content":[
                {"type":"text","text":prompt},
                {"type":"image_url","image_url":f"data:image/jpeg;base64,{image_b64}"}
            ]
        }],
        temperature=0
    )
    return json.loads(r.choices[0].message.content)

def render_validation_form(data, title):
    st.subheader(title)
    validated = {}
    for k, v in data.items():
        validated[k] = st.text_input(k, "" if v is None else str(v))
    return validated

def save_passport_to_file(passport):
    os.makedirs(PASSPORT_DIR, exist_ok=True)
    path = os.path.join(PASSPORT_DIR, f"{passport['id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(passport, f, indent=2, ensure_ascii=False)

def load_passport_from_file(passport_id):
    path = os.path.join(PASSPORT_DIR, f"{passport_id}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def generate_qr_from_url(url):
    qr = qrcode.make(url)
    buf = BytesIO()
    qr.save(buf)
    buf.seek(0)
    return buf
