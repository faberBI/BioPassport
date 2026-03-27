# COMPLETE ENTERPRISE PIPELINE (WITH SECURITY + COMPLIANCE)

import json
import base64
import unicodedata
import hashlib
from difflib import get_close_matches
from io import BytesIO
from datetime import datetime

import pdfplumber
from PIL import Image
from openai import OpenAI

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509 import load_pem_x509_certificate
from cryptography.hazmat.backends import default_backend

# ======================================================
# CONFIG
# ======================================================
SOURCE_PRIORITY = {
    "certificate": 1.0,
    "pdf": 0.8,
    "image": 0.6
}

# ======================================================
# NORMALIZATION
# ======================================================
def normalize(text):
    text = text.lower().strip()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return text.replace(" ", "_")


def match_field(input_key, field_names):
    norm_input = normalize(input_key)
    norm_fields = {normalize(f): f for f in field_names}

    if norm_input in norm_fields:
        return norm_fields[norm_input]

    matches = get_close_matches(norm_input, norm_fields.keys(), n=1, cutoff=0.7)
    return norm_fields[matches[0]] if matches else None

# ======================================================
# PDF
# ======================================================
def extract_text_from_pdf(pdf_file):
    text = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text

# ======================================================
# GPT SAFE PARSE
# ======================================================
def safe_json_parse(text):
    if text.startswith("```"):
        text = "\n".join(text.splitlines()[1:-1])
    first, last = text.find("{"), text.rfind("}")
    return json.loads(text[first:last + 1])

# ======================================================
# EXTRACTION
# ======================================================
def gpt_extract_from_pdf(text, client, fields):
    prompt = f"Extract fields {fields}. JSON only. Text: {text[:4000]}"

    r = client.chat.completions.create(
        model="gpt-4.1",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    data = safe_json_parse(r.choices[0].message.content)

    return {k: {"value": v, "confidence": 0.8 if v else 0, "source": "pdf"} for k, v in data.items()}


def gpt_analyze_image(image_file, client):
    img = Image.open(image_file).convert("RGB")
    buf = BytesIO()
    img.save(buf, format="JPEG")
    buf.seek(0)

    file = client.files.create(file=buf, purpose="vision")

    resp = client.responses.create(
        model="gpt-4o",
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Extract color, condition, material JSON"},
                {"type": "input_image", "file_id": file.id}
            ]
        }]
    )

    data = safe_json_parse(resp.output_text)

    return {k: {"value": v, "confidence": 0.6 if v else 0, "source": "image"} for k, v in data.items()}


def gpt_extract_cert(cert_file, client):
    text = extract_text_from_pdf(cert_file)

    prompt = f"Extract certificate info JSON: issuer, expiry, id. Text: {text[:3000]}"

    r = client.chat.completions.create(
        model="gpt-4.1",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    data = safe_json_parse(r.choices[0].message.content)

    return {k: {"value": v, "confidence": 0.9 if v else 0, "source": "certificate"} for k, v in data.items()}

# ======================================================
# TRUSTED CERTIFICATE VALIDATION
# ======================================================
def verify_certificate(cert_bytes, trusted_issuers):
    try:
        cert = load_pem_x509_certificate(cert_bytes, default_backend())
        issuer = cert.issuer.rfc4514_string()

        if issuer not in trusted_issuers:
            return False

        now = datetime.utcnow()
        if cert.not_valid_before > now or cert.not_valid_after < now:
            return False

        return True
    except Exception:
        return False

# ======================================================
# MERGE
# ======================================================
def merge_data(fields, *sources):
    for source in sources:
        for key, value in source.items():
            matched = match_field(key, fields.keys())
            if not matched:
                continue

            existing = fields[matched]

            new_score = value["confidence"] * SOURCE_PRIORITY[value["source"]]
            old_score = existing["confidence"] * SOURCE_PRIORITY.get(existing.get("source"), 0.5)

            if new_score > old_score:
                fields[matched] = value

    return fields

# ======================================================
# VALIDATION
# ======================================================
def validate_required(fields, required_fields):
    return [f for f in required_fields if not fields.get(f) or not fields[f].get("value")]


def validate_operator(operator):
    if not operator.get("name") or not operator.get("vat"):
        return False
    return True

# ======================================================
# SCORING
# ======================================================
def compute_scores(fields, required_fields):
    filled = [f for f in fields.values() if f.get("value")]
    reliability = sum(f["confidence"] for f in filled) / len(filled) if filled else 0

    required_filled = [f for f in required_fields if fields.get(f, {}).get("value")]
    espr = len(required_filled) / len(required_fields) if required_fields else 0

    return reliability, espr

# ======================================================
# SUSTAINABILITY
# ======================================================
def compute_sustainability(fields):
    score = 0
    count = 0

    for k, v in fields.items():
        if "riciclato" in k.lower() and v.get("value"):
            try:
                score += float(v["value"]) / 100
                count += 1
            except:
                pass

    return score / count if count else 0

# ======================================================
# SIGNATURE
# ======================================================
def generate_hash(passport):
    data = dict(passport)
    data.pop("signature", None)
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def sign_passport(passport, private_key_pem):
    private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)

    hash_value = generate_hash(passport)

    signature = private_key.sign(
        hash_value.encode(),
        padding.PKCS1v15(),
        hashes.SHA256()
    )

    passport["signature"] = {
        "hash": hash_value,
        "signature": signature.hex(),
        "timestamp": datetime.utcnow().isoformat()
    }

    return passport

# ======================================================
# VERSIONING
# ======================================================
def update_version(passport, changes):
    passport.setdefault("version", 1)
    passport["version"] += 1
    passport["updated_at"] = datetime.utcnow().isoformat()
    passport.setdefault("changes", []).append(changes)
    return passport

# ======================================================
# PIPELINE
# ======================================================
def process_passport(pdf_file, image_files, cert_files, fields, required_fields, client, private_key, operator, trusted_issuers):

    passport = {
        "id": f"PROD-{datetime.utcnow().timestamp()}",
        "created_at": datetime.utcnow().isoformat(),
        "fields": {f: {"value": None, "confidence": 0, "source": None} for f in fields},
        "operator": operator
    }

    # 1. VALIDATE OPERATOR
    if not validate_operator(operator):
        raise Exception("Invalid operator")

    # 2. PDF
    pdf_text = extract_text_from_pdf(pdf_file)
    pdf_data = gpt_extract_from_pdf(pdf_text, client, fields)

    # 3. IMAGES
    image_data = {}
    for img in image_files:
        image_data.update(gpt_analyze_image(img, client))

    # 4. CERTIFICATES
    cert_data = {}
    for cert in cert_files:
        if verify_certificate(cert.read(), trusted_issuers):
            cert.seek(0)
            cert_data.update(gpt_extract_cert(cert, client))

    # 5. MERGE
    passport["fields"] = merge_data(passport["fields"], pdf_data, image_data, cert_data)

    # 6. VALIDATION
    passport["missing_fields"] = validate_required(passport["fields"], required_fields)

    # 7. SCORING
    reliability, espr = compute_scores(passport["fields"], required_fields)
    passport["reliability"] = reliability
    passport["espr"] = espr

    # 8. SUSTAINABILITY
    passport["sustainability"] = compute_sustainability(passport["fields"])

    # 9. VERSION
    passport = update_version(passport, "initial creation")

    # 10. SIGN
    passport = sign_passport(passport, private_key)

    return passport
