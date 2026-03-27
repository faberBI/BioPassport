import os
import json
import base64
import fitz  # PyMuPDF
import pdfplumber
import unicodedata
from difflib import get_close_matches
from io import BytesIO
from PIL import Image
import pandas as pd
import qrcode
from openai import OpenAI
import hashlib
from datetime import datetime
from cryptography.fernet import Fernet
from openpyxl import load_workbook

# ======================================================
# CONFIG
# ======================================================
PASSPORT_DIR = "passports"
EXCEL_FILE = os.path.join(PASSPORT_DIR, "passport_archive.xlsx")
LOG_FILE = os.path.join(PASSPORT_DIR, "passport_log.jsonl")

TRUSTED_ISSUERS = [
    "Chambersign","InfoCert","Aruba PEC","GlobalSign EU","D-Trust"
]

PRODUCT_FIELDS = {
    "mobile": {
        "pdf": [
            {"name":"Nome prodotto", "required": True},
            {"name":"Numero di modello", "required": True},
            {"name":"Produttore", "required": True},
            {"name":"Materiali", "required": True},
            {"name":"Certificazione di sicurezza", "required": True},
            {"name":"Certificazione di sostenibilita", "required": True},
            {"name":"Materiali/componenti utilizzati", "required": True},
            {"name":"% di contenuto riciclato", "required": True},
            {"name":"Sostanze preoccupanti", "required": True},
            {"name":"Conformità tecnica", "required": True},
            {"name":"Prezzo in euro", "required": False},
            {"name":"Luogo di Produzione", "required": False},
            {"name":"Data di produzione", "required": False},
            {"name":"Dimensioni", "required": False},
            {"name":"Peso", "required": False},
            {"name":"Energia consumata", "required": False}
        ],
        "image": [
            {"name":"Colore", "required": True},
            {"name":"Condizioni", "required": True}
        ]
    }
}

ECOLABEL_FIELDS = [
    "descrizione_prodotto",
    "svhc_limitati",
    "clp_conformita",
    "legno_certificato",
    "plastica_conforme",
    "metallo_conforme",
    "rivestimenti_ok",
    "formaldeide_bassa",
    "voc_bassi",
    "facilmente_smortabile",
    "produzione_basso_impatto",
    "info_consumatore_ok"
]

# ======================================================
# NORMALIZATION / MATCHING
# ======================================================
def normalize(text):
    text = text.lower().strip()
    text = unicodedata.normalize("NFKD", text).encode("ascii","ignore").decode()
    return text.replace(" ","_")

def match_field(input_key, field_names):
    norm_input = normalize(input_key)
    norm_fields = {normalize(f): f for f in field_names}
    if norm_input in norm_fields:
        return norm_fields[norm_input]
    matches = get_close_matches(norm_input, norm_fields.keys(), n=1, cutoff=0.8)
    if matches:
        return norm_fields[matches[0]]
    return None

# ======================================================
# PDF / IMAGE UTILITIES
# ======================================================
def split_text(text, max_chars=3000, overlap=300):
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunks.append(text[start:end])
        start += max_chars - overlap
    return chunks

def extract_text_from_pdf(pdf_file):
    text = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() + "\n"
    return text

def image_to_base64(image: Image.Image) -> str:
    if image.mode in ("RGBA", "P"):
        image = image.convert("RGB")
    buf = BytesIO()
    image.save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode()

def resize_image_for_vision(image_file, max_size=512):
    img = Image.open(image_file).convert("RGB")
    img.thumbnail((max_size, max_size))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    buf.seek(0)
    buf.name = "image.jpg"
    return buf

# ======================================================
# CONFIDENCE
# ======================================================
def compute_confidence(values):
    if not values:
        return 0.0
    most_common = max(set(values), key=values.count)
    return values.count(most_common)/len(values)

# ======================================================
# CRITTOGRAFIA DATI SENSIBILI
# ======================================================
def generate_key():
    return Fernet.generate_key()

def encrypt_sensitive_data(data: str, key: bytes) -> str:
    f = Fernet(key)
    return f.encrypt(data.encode()).decode()

def decrypt_sensitive_data(data: str, key: bytes) -> str:
    f = Fernet(key)
    return f.decrypt(data.encode()).decode()

# ======================================================
# GPT FUNCTIONS
# ======================================================
def gpt_extract_cert_info(cert_file, client: OpenAI):
    text = extract_text_from_pdf(cert_file) if cert_file else None
    prompt = f"""
Analizza il certificato allegato.
Estrai le seguenti informazioni:
- tipo_certificato
- numero_certificato
- ente_emittente
- data_emissione
- data_scadenza
- riferimenti_LCA/EPD
Rispondi solo con JSON valido. Usa null se il campo non è disponibile.
Testo certificato: {text if text else 'Non disponibile, usare GPT Vision'}
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[{"role":"user","content":prompt}],
            temperature=0
        )
        resp_text = response.choices[0].message.content
        if resp_text.startswith("```"):
            resp_text = "\n".join(resp_text.splitlines()[1:-1])
        return json.loads(resp_text)
    except Exception as e:
        return {k: None for k in ["tipo_certificato","numero_certificato","ente_emittente","data_emissione","data_scadenza","riferimenti"]}

def gpt_extract_from_pdf(text, client: OpenAI, tipo, fields):
    chunks = split_text(text)
    results = []
    for chunk in chunks:
        prompt = f"""
Estrai dati tecnici del prodotto ({tipo}).
Rispondi SOLO con JSON valido. Usa null se non presente.
Campi: {json.dumps(fields)}
Testo: {chunk}
"""
        try:
            r = client.chat.completions.create(
                model="gpt-4.1",
                messages=[{"role":"user","content":prompt}],
                temperature=0
            )
            resp_text = r.choices[0].message.content
            if resp_text.startswith("```"):
                resp_text = "\n".join(resp_text.splitlines()[1:-1])
            results.append(json.loads(resp_text))
        except Exception:
            continue
    final = {}
    for campo in fields:
        values = [r.get(campo) for r in results if r.get(campo)]
        final[campo] = {
            "value": values[0] if values else None,
            "confidence": compute_confidence(values),
            "explanation": "Dato estratto da PDF" if values else "Dato non trovato nel PDF"
        }
    return final

def gpt_analyze_image(image_file, client: OpenAI, tipo):
    campi = ["colore","condizioni","materiale_probabile","categoria_visiva","segni_usura"]
    prompt = f"""
Analizza immagine prodotto {tipo}.
Estrai i seguenti campi: colore, condizioni, materiale_probabile, categoria_visiva, segni_usura.
Rispondi con JSON valido.
Usa null se non determinabile.
"""
    def safe_json_parse(text):
        if text.startswith("```"):
            text = "\n".join([l for l in text.splitlines() if not l.strip().startswith("```")])
        first,last = text.find("{"), text.rfind("}")
        return json.loads(text[first:last+1])
    try:
        file_id = upload_image_to_openai(image_file, client)
        resp = client.responses.create(
            model="gpt-4o",
            input=[{"role":"user","content":[{"type":"input_text","text":prompt},{"type":"input_image","file_id":file_id}]}]
        )
        data_raw = safe_json_parse(resp.output_text.strip())
        result = {}
        for c in campi:
            val = data_raw.get(c, None)
            result[c.capitalize()] = {
                "value": val if val not in [None,"","null"] else "non rilevato",
                "confidence": 0.7 if val not in [None,"","null"] else 0.0,
                "explanation": "Dato estratto da immagine" if val not in [None,"","null"] else "Non rilevabile"
            }
        return result
    except Exception:
        return {c.capitalize():{"value":"non rilevato","confidence":0.0,"explanation":"Non rilevabile"} for c in campi}

def upload_image_to_openai(image_file, client: OpenAI):
    resized = resize_image_for_vision(image_file)
    uploaded = client.files.create(file=resized, purpose="vision")
    return uploaded.id

# ======================================================
# PASSPORT MANAGEMENT
# ======================================================
def initialize_passport(pid, tipo, fields):
    passport = {"id":pid,"product_type":tipo,"sections":{},"certificates":[],"images":[],"overall_rating":0,"sustainability_score":0,"validated_by_operator":False,"digital_signature":None}
    for field in fields:
        passport["sections"].setdefault("PDF",{})[field] = {"value":None,"confidence":0,"explanation":""}
    return passport

def merge_data(passport, pdf_data=None, image_data=None, cert_data=None):
    if pdf_data:
        passport["sections"]["PDF"].update(pdf_data)
    if image_data:
        passport["sections"]["Images"] = image_data
    if cert_data:
        passport["certificates"] = cert_data

def save_passport_to_file(passport: dict):
    os.makedirs(PASSPORT_DIR, exist_ok=True)
    path = os.path.join(PASSPORT_DIR,f"{passport['id']}.json")
    with open(path,"w") as f:
        json.dump(passport,f,indent=2)

def load_passport_from_file(pid):
    path = os.path.join(PASSPORT_DIR,f"{pid}.json")
    if not os.path.exists(path):
        return None
    with open(path,"r") as f:
        return json.load(f)

def log_passport_version(passport: dict):
    os.makedirs(PASSPORT_DIR, exist_ok=True)
    hash_data = hashlib.sha256(json.dumps(passport, sort_keys=True).encode()).hexdigest()
    log_entry = {
        "passport_id": passport["id"],
        "timestamp": datetime.utcnow().isoformat(),
        "hash": hash_data
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")

def save_passport_to_json(passport: dict):
    save_passport_to_file(passport)

# ======================================================
# QR CODE
# ======================================================
def generate_qr_from_url(url):
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

# ======================================================
# ECOLABEL
# ======================================================
def extract_ecolabel_fields_from_pdf(pdf_file, client: OpenAI):
    text = extract_text_from_pdf(pdf_file)
    extracted_data = gpt_extract_from_pdf(text, client, tipo="mobile", fields=ECOLABEL_FIELDS)
    mobile_data = {}
    for campo, info in extracted_data.items():
        val = info.get("value")
        if isinstance(val, bool):
            mobile_data[campo] = val
        elif isinstance(val, str):
            mobile_data[campo] = val.strip().lower() in ["sì","si","true","yes","conforme"]
        else:
            mobile_data[campo] = False
    return mobile_data

def merge_data_with_ecolabel(passport, pdf_file=None, image_data=None, cert_data=None, client=None):
    ecolabel_data = extract_ecolabel_fields_from_pdf(pdf_file, client) if pdf_file else {}
    if "sections" not in passport:
        passport["sections"] = {}
    passport["sections"]["Ecolabel_UE"] = ecolabel_data
    if pdf_file:
        pdf_text_data = gpt_extract_from_pdf(extract_text_from_pdf(pdf_file), client, "mobile", ECOLABEL_FIELDS)
        passport["sections"]["PDF"] = pdf_text_data
    if image_data:
        passport["sections"]["Images"] = image_data
    if cert_data:
        passport["certificates"] = cert_data

# ======================================================
# EXCEL
# ======================================================
def save_passport_to_excel_append(passport: dict):
    os.makedirs(PASSPORT_DIR, exist_ok=True)
    df_passport = pd.DataFrame([{
        "id": passport["id"],
        "product_type": passport.get("product_type"),
        "overall_rating": passport.get("overall_rating", 0),
        "sustainability_score": passport.get("sustainability_score", 0)
    }])
    fields_data = []
    for section_name, section in passport.get("sections", {}).items():
        for field_name, field_info in section.items():
            if isinstance(field_info, dict):
                fields_data.append({
                    "passport_id": passport["id"],
                    "section": section_name,
                    "field_name": field_name,
                    "value": field_info.get("value"),
                    "confidence": field_info.get("confidence",0)
                })
    df_fields = pd.DataFrame(fields_data)
    images_data = [{"passport_id": passport["id"], "file_base64": img.get("file_base64"), "caption": img.get("caption","")} for img in passport.get("images",[])]
    df_images = pd.DataFrame(images_data)

    if not os.path.exists(EXCEL_FILE):
        with pd.ExcelWriter(EXCEL_FILE, engine="openpyxl") as writer:
            df_passport.to_excel(writer, sheet_name="passport", index=False)
            df_fields.to_excel(writer, sheet_name="fields", index=False)
            df_images.to_excel(writer, sheet_name="images", index=False)
    else:
        with pd.ExcelWriter(EXCEL_FILE, engine="openpyxl", mode="a", if_sheet_exists="overlay") as writer:
            book = load_workbook(EXCEL_FILE)
            writer.book = book
            writer.sheets = {ws.title: ws for ws in book.worksheets}
            df_passport.to_excel(writer, sheet_name="passport", index=False, header=False, startrow=writer.sheets["passport"].max_row)
            df_fields.to_excel(writer, sheet_name="fields", index=False, header=False, startrow=writer.sheets["fields"].max_row)
            df_images.to_excel(writer, sheet_name="images", index=False, header=False, startrow=writer.sheets["images"].max_row)
            writer.save()
