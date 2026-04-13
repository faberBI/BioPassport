from .eprel import validate_eprel
from .gs1 import validate_gs1
from .scip import generate_scip_block

ESSENTIAL_FIELDS = [
    "Nome prodotto",
    "Numero di modello",
    "Produttore",
    "Luogo di Produzione",
    "Materiali/componenti utilizzati",
    "Sostanze preoccupanti",
    "Indicazioni di smaltimento"
]

def validate_espr_compliance(passport):
    pdf = passport.get("sections", {}).get("PDF", {})

    missing = [f for f in ESSENTIAL_FIELDS if not pdf.get(f, {}).get("value")]
    eprel_missing = validate_eprel(passport)

    return {
        "is_compliant": len(missing) == 0 and len(eprel_missing) == 0,
        "missing_fields": missing,
        "missing_eprel": eprel_missing,
        "scip_block": generate_scip_block(passport)
    }
