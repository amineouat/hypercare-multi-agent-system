"""Résumés factuels, construits par du code, des éléments déjà réunis.

Ils servent à la demande de précision et au dossier d'escalade. Rien n'y est
interprété : on décrit ce que contiennent le ticket et les lignes de prix.
"""

TYPE_LABELS = {"ST": "dry", "RF": "reefer"}
RATE_LABELS = (("rate_20ST", "20ST"), ("rate_40ST", "40ST"), ("rate_40HC", "40HC"), ("rate_45HC", "45HC"))


def _text(value) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text.lower() in ("", "none", "nan", "null") else text


def describe_refs(state: dict) -> str:
    """Références connues du ticket : devis, réservation, route, type, ligne, date."""
    ticket = state.get("ticket") or {}
    parts = []
    for label, field in (("ticket", "ticket_id"), ("devis", "quote_id"), ("réservation", "booking_id"),
                         ("pricelist", "pricelist_number"), ("ligne", "line_reference")):
        value = _text(ticket.get(field))
        if value:
            parts.append(f"{label} {value}")
    pol, pod = _text(ticket.get("pol")), _text(ticket.get("pod"))
    if pol and pod:
        parts.append(f"route {pol} -> {pod}")
    ctype = _text(ticket.get("container_type"))
    if ctype:
        parts.append(f"conteneur {TYPE_LABELS.get(ctype, ctype)}")
    date = _text(state.get("reference_date")) or _text(ticket.get("time_of_issue"))[:10]
    if date:
        parts.append(f"date {date}")
    return ", ".join(parts) if parts else "aucune référence fournie"


def describe_lines(lines: list, limit: int = 8) -> list[str]:
    """Une phrase par version de ligne de prix (origine, structure, montants, validité)."""
    out = []
    for l in (lines or [])[:limit]:
        ctype = _text(l.get("pricelist_line_type"))
        rates = [f"{label}={l[field]}" for field, label in RATE_LABELS if l.get(field) is not None]
        text = (f"ligne {l.get('line_sequence')} (detail_uid {l.get('detail_uid')}"
                + (f", {TYPE_LABELS.get(ctype, ctype)}" if ctype else "") + ") : "
                + f"origine {l.get('charge_origin')}, structure {l.get('rate_structure')}, "
                + ("montants " + ", ".join(rates) if rates else "aucun montant"))
        if l.get("valid_from") and l.get("valid_to"):
            text += f", valide du {l['valid_from']} au {l['valid_to']}"
        out.append(text)
    extra = len(lines or []) - limit
    if extra > 0:
        out.append(f"... et {extra} autre(s) version(s) non listée(s)")
    return out
