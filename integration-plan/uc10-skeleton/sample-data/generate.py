#!/usr/bin/env python3
"""
generate.py — Synthetic Requirements Generator for UC10 Demo

Generates fictional requirements for three demo programmes via OCI Generative
AI. Output is a JSON file consumed by load_sample_data.sql.

CRITICAL:
  - The output JSON has a "header" object marked
    "synthetic": true, "not_representative": true.
  - Programme names, customer countries, dates are all FICTIONAL.
  - This script must NEVER be pointed at real classified data.

Usage:
  python3 generate.py --output synthetic.json --programs 3 --requirements-per-program 80

Environment:
  OCI_GENAI_ENDPOINT   — OCI Generative AI inference endpoint (EU region)
  OCI_GENAI_MODEL_CHAT — typically cohere.command-r-plus-v2
  OCI_COMPARTMENT_OCID — compartment for the model call
  OCI_CONFIG_FILE      — path to ~/.oci/config (default ~/.oci/config)
"""

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone

# OCI SDK is optional — this script falls back to a deterministic
# synthetic generator if the SDK isn't available, so the demo can still run
# from a clean checkout without OCI credentials configured.
try:
    import oci
    from oci.generative_ai_inference import GenerativeAiInferenceClient
    from oci.generative_ai_inference.models import (
        ChatDetails, CohereChatRequest, OnDemandServingMode,
    )
    OCI_AVAILABLE = True
except ImportError:
    OCI_AVAILABLE = False


# ---------------------------------------------------------------------------
# Programme catalogue — FICTIONAL, used purely for demo
# ---------------------------------------------------------------------------
PROGRAMS = [
    {
        "program_id": "BOXER-MOD",
        "name":       "Boxer-Modernisierung",
        "domain":     "armoured wheeled vehicle (8x8)",
        "categories": ["functional", "performance", "safety", "interface", "environmental"],
        "customer_country": "DEU",
        "start_year": 2022,
        "status":     "ACTIVE",
        "security_class": "VS-NfD",
    },
    {
        "program_id": "SPZ-NEXTGEN",
        "name":       "Schützenpanzer NextGen",
        "domain":     "infantry fighting vehicle",
        "categories": ["functional", "performance", "safety", "interface", "regulatory"],
        "customer_country": "DEU",
        "start_year": 2024,
        "status":     "BIDDING",
        "security_class": "VS-NfD",
    },
    {
        "program_id": "MARINE-SENS",
        "name":       "Marine-Sensor-Plattform",
        "domain":     "naval surveillance and sensor system",
        "categories": ["functional", "performance", "interface", "environmental"],
        "customer_country": "DEU",
        "start_year": 2023,
        "status":     "ACTIVE",
        "security_class": "VS-NfD",
    },
]

PROMPT_TEMPLATE = """Generate {n} fictional but plausible engineering
requirements for a defence programme.

Programme name:    {name}
Programme domain:  {domain}
Customer country:  {customer_country}
Categories to mix: {categories}

REQUIREMENTS for the output:
- Mix of SHALL (60%), SHOULD (30%), MAY (10%)
- ID format: {id_prefix}-REQ-NNNN (zero-padded)
- Language: German
- Each requirement maximum 250 characters
- Cover all listed categories
- Realistic defence vocabulary (NATO STANAG, environmental tests,
  AQAP-2110-style wording, sensor specs, interface protocols)
- DO NOT reference any real existing programme, vehicle, or vendor

CRITICAL: Mark the output as synthetic — these are not real requirements.

Return JSON only, no markdown fences, no commentary:
{{
  "requirements": [
    {{
      "req_id": "...",
      "req_type": "SHALL|SHOULD|MAY",
      "category": "functional|performance|safety|interface|environmental|regulatory",
      "req_text": "..."
    }}
  ]
}}
"""


# ---------------------------------------------------------------------------
# Deterministic fallback generator (no OCI SDK / no internet)
# ---------------------------------------------------------------------------
FALLBACK_TEMPLATES = {
    "functional": [
        "Das System SHALL eine 360-Grad-Rundumsicht über Multi-Spektral-Sensoren bereitstellen.",
        "Das System SHALL Bedrohungen aus mindestens 4000 m Entfernung erkennen und klassifizieren.",
        "Das System SHOULD Daten von mindestens 12 vernetzten Plattformen gleichzeitig fusionieren.",
        "Das System SHALL eine Reaktionszeit von 200 ms zwischen Detektion und Warnung einhalten.",
        "Das System MAY zusätzlich passive Sensorik zur Detektion ohne Eigenstrahlung anbieten.",
    ],
    "performance": [
        "Das System SHALL Inferenzlatenzen unter 50 ms bei 95-Perzentil-Last einhalten.",
        "Das System SHALL Datenraten von mindestens 10 Gbit/s über Fast-Ethernet-Schnittstelle bereitstellen.",
        "Das System SHOULD eine Verfügbarkeit von 99,5 Prozent im Einsatzbetrieb erreichen.",
        "Das System SHALL bei Vollast nicht mehr als 750 W elektrische Leistung aufnehmen.",
    ],
    "safety": [
        "Das System SHALL bei Ausfall der Primärsensorik in einen sicheren Zustand übergehen.",
        "Das System SHALL alle sicherheitskritischen Funktionen durch redundante Pfade absichern.",
        "Das System SHOULD AQAP-2110-konforme Audit-Trails für alle Modusänderungen führen.",
        "Das System SHALL bei Erkennung eines Selbsttest-Fehlers innerhalb von 100 ms eine Warnung ausgeben.",
    ],
    "interface": [
        "Das System SHALL die NATO STANAG 4586 Schnittstelle für unbemannte Plattformen unterstützen.",
        "Das System SHALL Daten über CAN-Bus (ISO 11898) und MIL-STD-1553 austauschen können.",
        "Das System SHOULD eine REST-API für Konfiguration und Telemetrie über TLS 1.3 bereitstellen.",
        "Das System MAY zusätzlich Ethernet-AVB für Echtzeit-Audio/Video unterstützen.",
    ],
    "environmental": [
        "Das System SHALL Betrieb im Temperaturbereich -32 °C bis +55 °C nach MIL-STD-810 sicherstellen.",
        "Das System SHALL Vibrationsfestigkeit nach MIL-STD-810 Methode 514.7 nachweisen.",
        "Das System SHOULD IP67-Schutzklasse für Außeneinheiten erreichen.",
    ],
    "regulatory": [
        "Das System SHALL die Anforderungen der ITAR-Kategorie XI Absatz a einhalten.",
        "Das System SHALL DSGVO-konforme Datenverarbeitung für alle personenbezogenen Telemetriedaten gewährleisten.",
        "Das System SHOULD BSI C5 Type II Audit-Anforderungen erfüllen.",
    ],
}


def fallback_generate(program: dict, n: int) -> list[dict]:
    """Deterministic generator used when OCI SDK is not available."""
    import random
    rng = random.Random(program["program_id"])  # deterministic per program
    requirements = []
    id_prefix = program["program_id"].replace("-", "")[:8]
    type_distribution = ["SHALL"] * 6 + ["SHOULD"] * 3 + ["MAY"] * 1
    for i in range(1, n + 1):
        category = rng.choice(program["categories"])
        templates = FALLBACK_TEMPLATES.get(category, FALLBACK_TEMPLATES["functional"])
        text = rng.choice(templates)
        # Insert a unique tag so requirements aren't textually identical
        # across programmes (better demo for vector similarity)
        text = text.replace("Das System", f"Das {program['domain']}-System").replace(
            "The system", f"The {program['domain']} system"
        )
        requirements.append({
            "req_id":    f"{id_prefix}-REQ-{i:04d}",
            "req_type":  rng.choice(type_distribution),
            "category":  category,
            "req_text":  text,
        })
    return requirements


# ---------------------------------------------------------------------------
# OCI GenAI generator (preferred path)
# ---------------------------------------------------------------------------
def oci_generate(program: dict, n: int) -> list[dict]:
    """Call OCI Generative AI to produce realistic synthetic requirements."""
    config = oci.config.from_file(
        file_location=os.path.expanduser(
            os.environ.get("OCI_CONFIG_FILE", "~/.oci/config")
        )
    )
    endpoint = os.environ["OCI_GENAI_ENDPOINT"]
    compartment = os.environ["OCI_COMPARTMENT_OCID"]
    model = os.environ.get("OCI_GENAI_MODEL_CHAT", "cohere.command-r-plus-v2")

    client = GenerativeAiInferenceClient(config=config, service_endpoint=endpoint)

    prompt = PROMPT_TEMPLATE.format(
        n=n,
        name=program["name"],
        domain=program["domain"],
        customer_country=program["customer_country"],
        categories=", ".join(program["categories"]),
        id_prefix=program["program_id"].replace("-", "")[:8],
    )

    chat_req = CohereChatRequest(
        message=prompt,
        max_tokens=4096,
        temperature=0.7,
        top_p=0.9,
    )
    details = ChatDetails(
        compartment_id=compartment,
        serving_mode=OnDemandServingMode(model_id=model),
        chat_request=chat_req,
    )
    response = client.chat(details)
    raw = response.data.chat_response.text.strip()

    # Strip optional markdown fence
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
    parsed = json.loads(raw)
    return parsed["requirements"]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output",                  default="synthetic.json")
    ap.add_argument("--programs",     type=int,  default=3)
    ap.add_argument("--requirements-per-program", type=int, default=80)
    ap.add_argument("--force-fallback", action="store_true",
                    help="Skip OCI SDK and use deterministic templates only")
    args = ap.parse_args()

    if args.programs > len(PROGRAMS):
        print(f"ERROR: only {len(PROGRAMS)} programmes defined", file=sys.stderr)
        return 2
    selected = PROGRAMS[: args.programs]

    use_oci = OCI_AVAILABLE and not args.force_fallback and "OCI_GENAI_ENDPOINT" in os.environ
    print(f"Generator mode: {'OCI GenAI' if use_oci else 'deterministic fallback'}")

    programs_out = []
    requirements_out = []
    for program in selected:
        print(f"  - {program['name']} ({args.requirements_per_program} requirements)...")
        if use_oci:
            try:
                reqs = oci_generate(program, args.requirements_per_program)
            except Exception as exc:
                print(f"    OCI call failed ({exc}), falling back to deterministic generator")
                reqs = fallback_generate(program, args.requirements_per_program)
        else:
            reqs = fallback_generate(program, args.requirements_per_program)

        # Stamp programme metadata onto each requirement
        for r in reqs:
            r["program_id"] = program["program_id"]
            r["status"] = "APPROVED"           # synthetic, but useful for demo views
            r["clearance_required"] = "RESTRICTED"
            r["releasable_to"] = "NATO"
        programs_out.append(program)
        requirements_out.extend(reqs)

    output = {
        "header": {
            "synthetic":           True,
            "not_representative":  True,
            "warning":             "These requirements are FICTIONAL, generated for demo purposes only.",
            "generator":           "uc10 generate.py",
            "generator_mode":      "oci-genai" if use_oci else "deterministic-fallback",
            "generated_at":        datetime.now(timezone.utc).isoformat(),
            "run_id":              str(uuid.uuid4()),
        },
        "programs":     programs_out,
        "requirements": requirements_out,
    }

    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(output, fh, ensure_ascii=False, indent=2)

    print(f"\nWrote {args.output}")
    print(f"  Programmes:   {len(programs_out)}")
    print(f"  Requirements: {len(requirements_out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
