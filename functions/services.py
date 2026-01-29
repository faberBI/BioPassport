import pdfplumber
import json
import base64
import qrcode
import os
from io import BytesIO
from openai import OpenAI
import streamlit as st
from PIL import Image
from datetime import datetime

# ======================================================
# CONFIG
# ======================================================
PASSPORT_DIR = "passports"

PRODUCT_FIELDS = {
    "mobile": {
        "pdf": [
            {"name":"Nome prodotto", "required": True},
            {"name":"Numero di modello", "required": True},
            {"name":"Produttore", "required": True},
            {"name":"Materiali", "required": True},
            {"name":"Dimensioni", "required": False},
            {"name":"Lotto di produzione", "required": False},
            {"name":"Anno di produzione", "required": False},
            {"name":"Certificazione di sicurezza", "required": True},
            {"name":"Certificazione di sostenibilita", "required": True},
            {"name":"Descrizione prodotto", "required": False},
            {"name":"Luogo di produzione", "required": False},
            {"name":"Manutenzione e cura", "required": False},
            {"name":"Materiali/componenti utilizzati", "required": True},
            {"name":"Specie legnosa", "required": False},
            {"name":"% di contenuto riciclato", "required": True},
            {"name":"Sostanze preoccupanti", "required": True},
            {"name":"Finitura superficiale", "required": False},
            {"name":"Marchio", "required": False},
            {"name":"Garanzia", "required": False},
            {"name":"Certificazioni materiale", "required": False},
            {"name":"Impronta carbonio GWP", "required": False},
            {"name":"Prezzo", "required": False},
            {"name":"Identificativo operatore", "required": False},
            {"name":"Conformità tecnica", "required": True},
            {"name":"Gestione fine vita (codice CER)", "required": True}
        ],
        "image": [
            {"name":"Colore", "required": True},
            {"name":"Condizioni", "required": True}
        ]
    },
    "lampada": {
        "pdf": [
            {"name":"nome_prodotto", "required": True},
            {"name":"produttore", "required": True},
            {"name":"materiale", "required": True},
            {"name":"wattaggio", "required": True}
        ],
        "image": [
            {"name":"tipologia_prodotto", "required": True},
            {"name":"colore", "required": True},
            {"name":"stile", "required": False}
        ]
    },
    "bicicletta": {
        "pdf": [
            {"name":"nome_prodotto", "required": True},
            {"name":"produttore", "required": True},
            {"name":"modello", "required": True},
            {"name":"anno_produzione", "required": False}
        ],
        "image": [
            {"name":"colore_telaio", "required": True},
            {"name":"condizioni", "required": True}
        ]
    }
}


# ======================================================
# PDF / IMAGE UTILITIES
# ======================================================
def extract_text_from_pdf(pdf_file):
    text = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text

def image_to_base64(image_file):
    if hasattr(image_file, "getvalue"):
        return base64.b64encode(image_file.getvalue()).decode()
    else:
        buf = BytesIO()
        image_file.save(buf, format="JPEG")
        buf.seek(0)
        return base64.b64encode(buf.read()).decode()

def resize_image_for_vision(image_file, max_size=512):
    img = Image.open(image_file).convert("RGB")
    img.thumbnail((max_size, max_size))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    buf.seek(0)
    buf.name = "image.jpg"
    return buf

# ======================================================
# GPT EXTRACTION
# ======================================================
def gpt_extract_from_pdf(text, client: OpenAI, tipo):
    campi = [c["name"] for c in PRODUCT_FIELDS[tipo]["pdf"]]
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
        if resp_text.startswith("```"):
            resp_text = "\n".join(resp_text.split("\n")[1:-1]).strip()
        data = json.loads(resp_text)
        for c in campi:
            if c not in data:
                data[c] = None
        return data
    except Exception as e:
        st.error(f"Errore GPT PDF: {e}")
        return {c: None for c in campi}

def gpt_analyze_image(image_file, client: OpenAI, tipo):
    campi = ["colore", "condizioni"]
    prompt = f"""
Analizza immagine del prodotto {tipo}.
Restituisci JSON con campi colore e condizioni.
Se non determinabile usa null.
"""
    def safe_json_parse(text):
        if text.startswith("```"):
            text = "\n".join([l for l in text.splitlines() if not l.strip().startswith("```")])
        first, last = text.find("{"), text.rfind("}")
        return json.loads(text[first:last+1])
    try:
        file_id = upload_image_to_openai(image_file, client)
        resp = client.responses.create(
            model="gpt-4o",
            input=[{"role":"user","content":[{"type":"input_text","text":prompt},{"type":"input_image","file_id":file_id}]}]
        )
        data_raw = safe_json_parse(resp.output_text.strip())
        data = {}
        mapping = {"colore":"Colore","condizioni":"Condizioni"}
        for k,v in mapping.items():
            val = data_raw.get(k,None)
            data[v] = val if val not in [None,"null",""] else "non rilevato"
        return data
    except Exception as e:
        st.error(f"Errore GPT Image: {e}")
        return {v:"non rilevato" for v in mapping.values()}

def upload_image_to_openai(image_file, client):
    resized = resize_image_for_vision(image_file)
    uploaded = client.files.create(file=resized, purpose="vision")
    return uploaded.id

# ======================================================
# VALIDATION FORM
# ======================================================
def render_validation_form(data, title: str):
    st.subheader(title)
    validated = {}
    def render_item(key, value, parent=""):
        full_key = f"{parent} > {key}" if parent else key
        if isinstance(value, dict):
            with st.expander(full_key, expanded=False):
                for k,v in value.items():
                    render_item(k,v,full_key)
        elif isinstance(value,list):
            validated[full_key] = st.text_area(full_key,", ".join(map(str,value)) if value else "non rilevato",height=50)
        else:
            validated[full_key] = st.text_input(full_key,"" if value is None else str(value))
    for k,v in data.items():
        render_item(k,v)
    return validated

# ======================================================
# PASSPORT STORAGE
# ======================================================
def save_passport_to_file(passport):
    os.makedirs(PASSPORT_DIR, exist_ok=True)
    path = os.path.join(PASSPORT_DIR, f"{passport['id']}.json")
    with open(path,"w",encoding="utf-8") as f:
        json.dump(passport,f,indent=2,ensure_ascii=False)

def load_passport_from_file(passport_id):
    path = os.path.join(PASSPORT_DIR, f"{passport_id}.json")
    if not os.path.exists(path):
        return None
    with open(path,"r",encoding="utf-8") as f:
        return json.load(f)

# ======================================================
# QR CODE
# ======================================================
def generate_qr_from_url(url: str):
    qr = qrcode.QRCode(version=1,error_correction=qrcode.constants.ERROR_CORRECT_H,box_size=10,border=4)
    qr.add_data(url)
    qr.make(fit=True)
    buf = BytesIO()
    img = qr.make_image(fill_color="black", back_color="white")
    img.save(buf)
    buf.seek(0)
    return buf

# ======================================================
# RATING / COMPLIANCE
# ======================================================
def compute_field_rating(field, type_weight_map=None):
    if type_weight_map is None:
        type_weight_map = {"technical":1.0,"declaration":0.6,"lca":0.5,"visual":0.4}
    val = field.get("value")
    if val is None or (isinstance(val,str) and val.strip()==""):
        return 0.0
    conf = field.get("confidence",0.0) or 0.0
    ftype = field.get("field_type","declaration")
    eu = field.get("eu_weight",1.0)
    w = type_weight_map.get(ftype,0.5)
    return round(conf*w*eu,2)

def score_to_color(score):
    if score>=0.7: return "🟢"
    elif score>=0.4: return "🟡"
    else: return "🔴"

def compute_section_rating(section):
    fields = section.get("fields",{})
    ratings = [compute_field_rating(f) for f in fields.values() if isinstance(f,dict)]
    return round(sum(ratings)/len(ratings),2) if ratings else 0.0

def compute_overall_rating(passport: dict):
    total_scores=[]
    for sec_name,section in passport.get("sections",{}).items():
        for f_name, field in section.get("fields",{}).items():
            r = compute_field_rating(field)
            field["rating"]=r
            field["color"]=score_to_color(r)
            total_scores.append(r)
    passport["overall_rating"]=sum(total_scores)/len(total_scores) if total_scores else 0.0

def compute_espr_compliance(section_fields):
    required = [f for f,v in section_fields.items() if isinstance(v,dict) and v.get("required",False)]
    ratings = [section_fields[f]["rating"] if f in section_fields else 0.0 for f in required]
    if not ratings: return "MISSING"
    n_ok=sum(1 for r in ratings if r>=0.5)
    pct_ok=n_ok/len(ratings)
    if pct_ok==1.0: return "OK"
    elif pct_ok>=0.5: return "PARTIAL"
    else: return "MISSING"

def score_to_judgment(score):
    if score>=0.9: return "🌟 Eccellente"
    elif score>=0.7: return "👍 Buono"
    elif score>=0.5: return "🟡 Sufficiente"
    elif score>=0.3: return "⚠️ Scarso"
    else: return "❌ Critico"

# ======================================================
# PASSPORT MANAGEMENT
# ======================================================
def initialize_passport(product_id: str, product_type: str) -> dict:
    passport = {
        "id": product_id,
        "product_type": product_type,
        "metadata": {"created_at":datetime.utcnow().isoformat(),"version":"EU-DPP-1.0"},
        "sections": {},
        "overall_rating":0.0,
        "images":[]
    }
    pdf_fields = PRODUCT_FIELDS.get(product_type,{}).get("pdf",[])
    image_fields = PRODUCT_FIELDS.get(product_type,{}).get("image",[])

    for f in pdf_fields:
        passport["sections"][f["name"]] = {
            "fields": {
                f["name"]: {
                    "value": None,
                    "confidence": 0.0,
                    "field_type": "technical",
                    "eu_weight": 1.0,
                    "rating": 0.0,
                    "color": "🔴",
                    "required": f.get("required",False)
                }
            }
        }
    for f in image_fields:
        passport["sections"][f["name"]] = {
            "fields": {
                f["name"]: {
                    "value": None,
                    "confidence":0.0,
                    "field_type":"visual",
                    "eu_weight":1.0,
                    "rating":0.0,
                    "color":"🔴",
                    "required":f.get("required",False)
                }
            }
        }
    return passport

def add_product_image(passport: dict, image_file, caption: str = "", annotation: str = ""):
    img_base64 = image_to_base64(image_file)
    passport["images"].append({"file_base64":img_base64,"caption":caption,"annotation":annotation})

def reset_session_state(keys=None):
    if keys is None:
        keys=["pdf_data","image_data","validated_pdf","validated_image","uploaded_image_file"]
    for k in keys:
        st.session_state[k]=None
