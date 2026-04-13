def build_ontology_graph():
    return {
        "@context": {
            "dpp": "https://data.europa.eu/dpp/",
            "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#"
        },
        "@graph": [
            {"@id": "dpp:Product", "@type": "rdfs:Class"},
            {"@id": "dpp:Material", "@type": "rdfs:Class"},
            {"@id": "dpp:Certificate", "@type": "rdfs:Class"},
            {"@id": "dpp:Component", "@type": "rdfs:Class"},
            {"@id": "dpp:hasMaterial", "@type": "rdf:Property"},
            {"@id": "dpp:hasCertificate", "@type": "rdf:Property"},
            {"@id": "dpp:madeIn", "@type": "rdf:Property"},
            {"@id": "dpp:hasEndOfLife", "@type": "rdf:Property"},
            {"@id": "dpp:hasRepairInfo", "@type": "rdf:Property"}
        ]
    }
