"""Lecture du ticket : repère les champs du formulaire qui ne sont pas remplis.

Nœud réel (pas de LLM). L'extraction de références depuis le texte libre
(numéro de devis, type de conteneur...) sera ajoutée à l'étape 7.
"""
from ..trace import entry

FORM_FIELDS = (
    "pricelist_number", "pricing_group", "email", "time_of_issue",
    "description", "pol", "pod", "line_reference",
    "container_type", "quote_id", "booking_id",
)


def intake(state: dict) -> dict:
    ticket = state.get("ticket", {})
    missing = [f for f in FORM_FIELDS if not str(ticket.get(f) or "").strip()]
    result = "tous les champs sont remplis" if not missing else "champs vides : " + ", ".join(missing)
    return {
        "missing_fields": missing,
        "trace": [entry(
            "intake", "orchestrateur",
            consulted=[f"ticket {ticket.get('ticket_id', '?')}"],
            result=result,
        )],
    }
