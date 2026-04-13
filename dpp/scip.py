SVHC_LIST = [
    "Piombo",
    "Cromo VI",
    "Mercurio",
    "Cadmio"
]

def map_svhc_to_echa(substance):
    if substance in SVHC_LIST:
        return f"https://echa.europa.eu/substance-information/-/substanceinfo/{substance}"
    return None

def generate_scip_block(passport):
    pdf = passport.get("sections", {}).get("PDF", {})
    substances = pdf.get("Sostanze preoccupanti", {}).get("value", "")
    if not substances:
        return {}

    return {
        "scip:substances": [
            {
                "name": s.strip(),
                "echa_uri": map_svhc_to_echa(s.strip())
            }
            for s in substances.split(",")
        ]
    }
