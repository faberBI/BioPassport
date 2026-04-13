from .utils import canonical_json, compute_hash, utc_now

JSONLD_CONTEXT = {
    "@context": {
        "dpp": "https://data.europa.eu/dpp/",
        "schema": "https://schema.org/",
        "gs1": "https://gs1.org/voc/",
        "eprel": "https://eprel.ec.europa.eu/voc/",
        "scip": "https://echa.europa.eu/scip/",
        "Product": "schema:Product",
        "Organization": "schema:Organization",
        "Material": "dpp:Material",
        "Certificate": "dpp:Certificate",
        "Component": "dpp:Component",
        "hasMaterial": "dpp:hasMaterial",
        "hasCertificate": "dpp:hasCertificate",
        "madeIn": "dpp:madeIn",
        "hasEndOfLife": "dpp:hasEndOfLife",
        "hasRepairInfo": "dpp:hasRepairInfo"
    }
}

def map_passport_to_jsonld(passport):
    pdf = passport.get("sections", {}).get("PDF", {})
    images = passport.get("sections", {}).get("Images", {})
    certs = passport.get("certificates", [])

    return {
        "@context": JSONLD_CONTEXT["@context"],
        "@type": "dpp:DigitalProductPassport",
        "dpp:id": passport.get("id"),
        "dpp:version": passport.get("version"),
        "dpp:createdAt": passport.get("created_at"),
        "dpp:lastUpdatedAt": passport.get("last_updated_at"),

        "Product": {
            "@type": "schema:Product",
            "schema:name": pdf.get("Nome prodotto", {}).get("value"),
            "schema:model": pdf.get("Numero di modello", {}).get("value"),
            "schema:manufacturer": {
                "@type": "schema:Organization",
                "schema:name": pdf.get("Produttore", {}).get("value")
            },
            "dpp:madeIn": pdf.get("Luogo di Produzione", {}).get("value"),
            "dpp:materials": pdf.get("Materiali/componenti utilizzati", {}).get("value"),
            "dpp:hazardousSubstances": pdf.get("Sostanze preoccupanti", {}).get("value"),
            "dpp:recycledContent": pdf.get("Percentuale di contenuto riciclato", {}).get("value"),
            "dpp:durability": pdf.get("Durabilità", {}).get("value"),
            "dpp:repairability": pdf.get("Istruzioni di riparazione", {}).get("value"),
            "dpp:endOfLife": pdf.get("Indicazioni di smaltimento", {}).get("value")
        },

        "dpp:certificates": [
            {
                "@type": "dpp:Certificate",
                "dpp:issuer": c.get("ente_emittente", {}).get("value"),
                "dpp:number": c.get("numero_certificato", {}).get("value"),
                "dpp:standard": c.get("norma_riferimento", {}).get("value")
            }
            for c in certs
        ]
    }

def generate_jsonld(passport):
    graph = map_passport_to_jsonld(passport)
    graph["dpp:hash"] = compute_hash(graph)
    return graph
