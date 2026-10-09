"""Résolution des références du ticket (nœud de l'orchestrateur).

Quand un ticket cite un devis ou une réservation, le devis donne déjà la
route, le type de conteneur, la date et la ligne de prix concernée. Ce nœud
va les chercher et complète les champs VIDES du ticket. Il ne remplace
jamais une valeur donnée par l'auteur du ticket.

Deux conséquences pour la suite du graphe :
- un cas de prix n'est plus bloqué pour « route manquante » si le devis la donne ;
- un ticket rattaché à un devis spot existant est dans le périmètre, quoi
  qu'en pense la classification.
"""
from datetime import datetime

from ..tools.lookup import find_booking, find_quote
from ..trace import entry

PRICELINES_TABLE = "PROJECT_DB.PUBLIC.PRICELINES_BAF09"


def _clean(value) -> str:
    """Texte d'une valeur, ou chaîne vide si elle est absente (None, NaN, "null"...)."""
    text = "" if value is None else str(value).strip()
    return "" if text.lower() in ("", "none", "nan", "null") else text


def _date_text(value) -> str:
    """Renvoie la date au format AAAA-MM-JJ, ou une chaîne vide si elle est illisible."""
    text = _clean(value)[:10]
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return ""
    return text


def _line_reference(session, detail_uid) -> str:
    """Référence de ligne (LINE_SEQUENCE) correspondant à un detail_uid."""
    if detail_uid is None:
        return ""
    rows = session.sql(
        f"SELECT DISTINCT LINE_SEQUENCE FROM {PRICELINES_TABLE} WHERE DETAIL_UID = ?",
        params=[int(detail_uid)],
    ).collect()
    return str(rows[0]["LINE_SEQUENCE"]) if rows else ""


def make_resolve_refs(session):
    """Fabrique le nœud resolve_refs avec accès à Snowflake."""

    def resolve_refs(state: dict) -> dict:
        ticket = dict(state.get("ticket", {}))
        quote_id = _clean(ticket.get("quote_id"))
        booking_id = _clean(ticket.get("booking_id"))

        if not quote_id and not booking_id:
            return {
                "quote_found": False,
                "trace": [entry("resolve_refs", "orchestrateur",
                                result="aucune référence de devis ou de réservation dans le ticket")],
            }

        tools, consulted = [], []

        # Une réservation mène à son devis.
        if not quote_id and booking_id:
            booking = find_booking(session, booking_id=booking_id)
            tools.append("find_booking")
            if booking:
                quote_id = _clean(booking["quote_id"])
                consulted.append(f"réservation {booking_id} -> devis {quote_id}")

        quote = find_quote(session, quote_id) if quote_id else None
        tools.append("find_quote")
        if not quote:
            return {
                "quote_found": False,
                "trace": [entry("resolve_refs", "orchestrateur", tools=tools, consulted=consulted,
                                result=f"référence introuvable : devis {quote_id or '?'}")],
            }
        consulted.append(f"devis {quote['quote_id']} (detail_uid {quote['detail_uid']})")

        # On complète seulement les champs vides.
        quote_type = _clean(quote["container_type"])
        filled = []
        for field, value in (("pol", _clean(quote["pol_code"])), ("pod", _clean(quote["pod_code"])),
                             ("container_type", quote_type)):
            if not _clean(ticket.get(field)) and value:
                ticket[field] = value
                filled.append(field)

        # La ligne de prix du devis n'est retenue que si le devis précise le type
        # de conteneur. Un devis sans type est incomplet : on ne s'y fie pas pour
        # désigner la ligne, et la recherche se fera par route.
        if quote_type and not _clean(ticket.get("line_reference")):
            line = _line_reference(session, quote["detail_uid"])
            if line:
                tools.append("ligne du devis")
                ticket["line_reference"] = line
                filled.append("line_reference")

        missing = [f for f in state.get("missing_fields", []) if not _clean(ticket.get(f))]
        reference_date = _date_text(quote["quote_date"])

        result = "champs repris du devis : " + (", ".join(filled) if filled else "aucun")
        if reference_date:
            result += f" ; date de référence = {reference_date} (date du devis)"

        update = {
            "ticket": ticket,
            "missing_fields": missing,
            "quote_found": True,
            "trace": [entry("resolve_refs", "orchestrateur", tools=tools, consulted=consulted, result=result)],
        }
        if reference_date:
            update["reference_date"] = reference_date
        return update

    return resolve_refs


def resolve_refs_noop(state: dict) -> dict:
    """Version sans base de données, pour le mode factice : ne change rien."""
    return {
        "quote_found": False,
        "trace": [entry("resolve_refs", "orchestrateur", result="non exécuté (mode factice)")],
    }
