"""
Doc-Intelligence RAG synthesiser — wraps OCI Generative AI Inference
(Cohere Command R+ OnDemand) with a citation-aware prompt builder.

Auth + model selection mirror services/uc4-chat/app/llm.py:
  1) OKE Workload Identity signer (sovdefence-runtime SA)
  2) Resource Principal (Container Instances / Functions)
  3) Local ~/.oci/config (developer laptop)

The function `synthesise_rag_answer` is the only public entry point.
On any failure (auth, OCI 4xx/5xx, missing compartment OCID) it falls
back to the deterministic bullet-list answer the MVP shipped with —
the user always gets *some* response.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT_TEMPLATE = """\
Du bist der Dokumenten-Intelligenz-Assistent der Sovereign Defence Plattform.

Sprache (HART):
  - Antworte AUSSCHLIESSLICH auf Deutsch.

Aufgabe:
  - Beantworte die Frage des Operators ausschließlich auf Basis der unten
    angegebenen Dokument-Auszüge (numbered Citations [1], [2], …).
  - Zitiere präzise, indem du die Citation-Nummer in eckigen Klammern
    direkt hinter der Aussage einfügst, z. B. „Die Bandbreite beträgt
    100 Mbit/s [1]."
  - Wenn die Auszüge die Frage nicht beantworten, sage das deutlich:
    „Die vorliegenden Dokumente enthalten dazu keine direkte Aussage."
    Erfinde nichts, leite nicht aus Allgemeinwissen ab.

Klassifizierung:
  - Aktueller OLS-Cap der Sitzung: {ols_cap}.
  - Du siehst nur Auszüge bis zu diesem Cap. Markiere keine Inhalte als
    höher klassifiziert als der Cap.

Plattform-Disziplin (HART, nicht verhandelbar):
  - Diese Plattform ist ein Daten-, KI- und Compliance-Layer. Du gibst
    KEINE kinetischen Empfehlungen, KEINE C2-Anweisungen, KEINE
    Feuerleit-Hinweise.
"""


def _format_citations(hits: list[dict[str, Any]]) -> str:
    """Render the chunk corpus into a numbered citation block."""
    lines: list[str] = []
    for i, h in enumerate(hits):
        title = h.get("title") or "Dokument"
        chunk_idx = h.get("chunk_idx", 0)
        text = (h.get("text") or "").strip().replace("\n", " ")
        # Cap each excerpt at 1200 chars so the prompt stays bounded.
        if len(text) > 1200:
            text = text[:1200] + "…"
        lines.append(f"[{i + 1}] {title} (chunk {chunk_idx})\n{text}")
    return "\n\n".join(lines)


def _build_oci_client(region: str):  # type: ignore[no-untyped-def]
    """Three-tier auth fallback shared with uc4-chat."""
    import oci  # type: ignore
    from oci.generative_ai_inference import GenerativeAiInferenceClient

    signer = None
    last_exc: Exception | None = None
    try:
        signer = oci.auth.signers.get_oke_workload_identity_resource_principal_signer()
    except Exception as exc:
        last_exc = exc
    if signer is None:
        try:
            signer = oci.auth.signers.get_resource_principals_signer()
        except Exception as exc:
            last_exc = exc
    if signer is not None:
        return GenerativeAiInferenceClient(config={"region": region}, signer=signer)
    try:
        return GenerativeAiInferenceClient(config=oci.config.from_file())
    except Exception as cfg_exc:
        raise RuntimeError(
            "doc-intel: no OCI auth available — "
            f"workload-identity/resource-principal failed ({last_exc!r}); "
            f"~/.oci/config fallback failed ({cfg_exc!r})"
        ) from cfg_exc


def synthesise_rag_answer(
    *,
    question: str,
    hits: list[dict[str, Any]],
    ols_cap: str,
    fallback_text: str,
) -> str:
    """Generate a German RAG answer grounded in `hits`, or return
    `fallback_text` on any failure.

    `hits` is a list of dicts with keys: title, chunk_idx, text, doc_id.
    The function:
      1. Builds a system prompt with OLS cap + Plattform-Disziplin
      2. Constructs the user message: question + numbered citations
      3. Calls Cohere Command R+ OnDemand via OCI GenAI Inference
      4. Returns the generated text on success, fallback_text otherwise
    """
    if not hits:
        return fallback_text

    compartment_id = os.environ.get("OCI_COMPARTMENT_OCID")
    if not compartment_id:
        logger.warning("doc-intel rag: OCI_COMPARTMENT_OCID not set, returning fallback")
        return fallback_text

    region = os.environ.get("OCI_REGION", "eu-frankfurt-1")
    model_id = os.environ.get("CHAT_MODEL", "cohere.command-r-plus-08-2024")

    try:
        client = _build_oci_client(region)
    except Exception:
        logger.exception("doc-intel rag: OCI client build failed")
        return fallback_text

    try:
        from oci.generative_ai_inference.models import (
            ChatDetails,
            CohereChatRequest,
            OnDemandServingMode,
        )

        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(ols_cap=ols_cap)
        citations_block = _format_citations(hits)
        user_message = (
            f"Frage des Operators:\n{question}\n\n"
            f"Dokument-Auszüge (Citations):\n{citations_block}\n\n"
            "Antworte auf Deutsch unter Bezug auf die Citations."
        )

        chat_request = CohereChatRequest(
            message=user_message,
            chat_history=[{"role": "SYSTEM", "message": system_prompt}],
            max_tokens=900,
            temperature=0.2,
        )
        details = ChatDetails(
            compartment_id=compartment_id,
            serving_mode=OnDemandServingMode(model_id=model_id),
            chat_request=chat_request,
        )
        resp = client.chat(details)
        cohere_resp = getattr(resp.data, "chat_response", None) or resp.data
        text: Optional[str] = getattr(cohere_resp, "text", None)
        if text and text.strip():
            return text.strip()
        logger.warning("doc-intel rag: empty LLM response, returning fallback")
        return fallback_text
    except Exception:
        logger.exception("doc-intel rag: chat call failed model=%s", model_id)
        return fallback_text
