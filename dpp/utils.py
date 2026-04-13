import json
import hashlib
from datetime import datetime, timezone

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def canonical_json(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def compute_hash(obj):
    return hashlib.sha256(canonical_json(obj).encode()).hexdigest()
