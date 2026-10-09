"""Agent d'investigation des données (nœud réel).

Interroge toutes les sources de données disponibles :
- QUOTES : devis lié au ticket (montants, detail_uid)
- BOOKINGS : réservation liée (statut, client)
- PRICELINES_BAF09 : lignes de prix (extraction principale)
- PRICELINES_BAF09_UPDATE : seconde photo (détection de changements)
- REF_CAR_CHARGES : description lisible des codes de charges
- REF_GOL_SERVICES : services maritimes liés à la route
"""

from ..trace import entry
from ..tools.pricelines import find_pricelines
from ..tools.lookup import find_quote, find_booking, find_charge_desc, find_services_for_route

BAF09_TABLE = "PROJECT_DB.PUBLIC.PRICELINES_BAF09"
BAF09_UPDATE_TABLE = "PROJECT_DB.PUBLIC.PRICELINES_BAF09_UPDATE"


def make_data_investigation(session):
    """Construit le nœud data_investigation avec accès à Snowflake."""

    def data_investigation(state: dict) -> dict:
        ticket = state.get("ticket", {})
        pol = ticket.get("pol", "").strip().upper()
        pod = ticket.get("pod", "").strip().upper()
        # find_pricelines attend "AAAA-MM-JJ" : on retire l'heure éventuelle.
        # Quand le ticket cite un devis, les lignes se cherchent à la date du
        # devis (reference_date), pas à celle du ticket.
        on_date = (state.get("reference_date") or ticket.get("time_of_issue")
                   or ticket.get("received_at") or "")[:10] or None
        container_type = ticket.get("container_type") or None
        line_reference = ticket.get("line_reference") or None
        quote_id = ticket.get("quote_id") or None
        booking_id = ticket.get("booking_id") or None

        tools_used = []
        consulted = []

        # 1. Devis et réservation
        quote = find_quote(session, quote_id) if quote_id else None
        booking = None
        if booking_id:
            booking = find_booking(session, booking_id=booking_id)
        elif quote_id:
            booking = find_booking(session, quote_id=quote_id)

        if quote:
            tools_used.append("find_quote")
            consulted.append(
                f"devis {quote['quote_id']} : "
                f"BAF09={quote['baf09_amount']}, total={quote['total']}, "
                f"detail_uid={quote['detail_uid']}"
            )
        if booking:
            tools_used.append("find_booking")
            consulted.append(
                f"réservation {booking['booking_id']} : "
                f"statut={booking['status']}, client={booking['customer_ref']}"
            )

        # 2. Lignes de prix BAF09
        if not pol or not pod or not on_date:
            return {
                "data": {
                    "lines": [], "nb_candidates": 0,
                    "evidence": False, "finding": "",
                    "quote": quote, "booking": booking,
                    "baf09_update": None, "services": [], "charge_desc": None,
                },
                "trace": [entry(
                    "data_investigation", "agent données",
                    tools=tools_used or ["aucun"],
                    consulted=consulted,
                    result="recherche de lignes impossible : POL, POD ou date manquant(e)",
                )],
            }

        priceline_args = dict(
            session=session, pol=pol, pod=pod, on_date=on_date,
            container_type=container_type, line_reference=line_reference,
        )

        baf09 = find_pricelines(**priceline_args, table=BAF09_TABLE)
        tools_used.append("find_pricelines (BAF09)")
        for l in baf09["lines"]:
            consulted.append(
                f"BAF09 ligne {l['line_sequence']} / detail_uid {l['detail_uid']} "
                f"({l['charge_origin']}, {l['rate_structure']})"
            )

        # 3. Seconde photo (BAF09_UPDATE) — comparaison
        baf09_upd = find_pricelines(**priceline_args, table=BAF09_UPDATE_TABLE)
        tools_used.append("find_pricelines (BAF09_UPDATE)")
        update_changes = _detect_changes(baf09["lines"], baf09_upd["lines"])
        if update_changes:
            consulted.append(f"changements dans BAF09_UPDATE : {update_changes}")

        # 4. Services maritimes
        services = find_services_for_route(session, pol, pod)
        if services:
            tools_used.append("find_services_for_route")
            consulted.append(
                f"{len(services)} service(s) sur la route : "
                + ", ".join(s["service_code"] for s in services[:5])
            )

        # 5. Description de la charge BAF09
        charge_desc = find_charge_desc(session, "BAF09")
        if charge_desc:
            tools_used.append("find_charge_desc")

        # Résultat consolidé
        data = {
            **baf09,
            "quote": quote,
            "booking": booking,
            "baf09_update": {
                "lines": baf09_upd["lines"],
                "nb_candidates": baf09_upd["nb_candidates"],
                "changes": update_changes,
            },
            "services": services,
            "charge_desc": charge_desc,
        }

        # Enrichir le finding avec le contexte du devis
        if quote and baf09["finding"]:
            data["finding"] += (
                f" Le devis {quote['quote_id']} indique un BAF09 de "
                f"{quote['baf09_amount']} sur un total de {quote['total']}."
            )

        return {
            "data": data,
            "trace": [entry(
                "data_investigation", "agent données",
                tools=tools_used,
                consulted=consulted,
                result=(
                    f"{baf09['nb_candidates']} ligne(s) candidate(s), "
                    f"preuve = {baf09['evidence']}"
                    + (f", changements UPDATE = {bool(update_changes)}" if baf09_upd["lines"] else "")
                    + (f", devis = {quote['quote_id']}" if quote else "")
                ),
            )],
        }

    return data_investigation


def _detect_changes(lines_v1: list, lines_v2: list) -> str:
    """Compare les lignes entre BAF09 et BAF09_UPDATE par detail_uid + charge_origin.
    Renvoie une description des différences, ou chaîne vide si identiques."""
    # UPDATE ne couvre pas cette route ou cette date : rien à comparer.
    if not lines_v2:
        return ""
    key = lambda l: (l["detail_uid"], l["charge_origin"])
    v1_map = {key(l): l for l in lines_v1}
    v2_map = {key(l): l for l in lines_v2}

    diffs = []
    rate_keys = ("rate_20ST", "rate_40ST", "rate_40HC", "rate_45HC", "rate_structure")

    for k, l2 in v2_map.items():
        if k not in v1_map:
            diffs.append(f"nouvelle ligne {l2['line_sequence']} ({l2['charge_origin']}) dans UPDATE")
            continue
        l1 = v1_map[k]
        for rk in rate_keys:
            if l1.get(rk) != l2.get(rk):
                diffs.append(
                    f"ligne {l1['line_sequence']} ({l1['charge_origin']}) : "
                    f"{rk} {l1.get(rk)} → {l2.get(rk)}"
                )

    for k in v1_map:
        if k not in v2_map:
            l1 = v1_map[k]
            diffs.append(f"ligne {l1['line_sequence']} ({l1['charge_origin']}) absente de UPDATE")

    return " | ".join(diffs)
