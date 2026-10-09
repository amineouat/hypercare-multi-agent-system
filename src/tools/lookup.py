"""Fonctions de lookup pour les tables de support : QUOTES, BOOKINGS,
REF_CAR_CHARGES, REF_GOL_SERVICES."""

DB = "PROJECT_DB.PUBLIC"


def find_quote(session, quote_id: str) -> dict | None:
    """Retrouve un devis par son QUOTE_ID. Renvoie None si introuvable."""
    if not quote_id:
        return None
    rows = session.sql(
        f"SELECT * FROM {DB}.QUOTES WHERE QUOTE_ID = ?", params=[quote_id]
    ).collect()
    if not rows:
        return None
    r = rows[0]
    return {
        "quote_id": r["QUOTE_ID"],
        "detail_uid": r["DETAIL_UID"],
        "pol_code": r["POL_CODE"],
        "pod_code": r["POD_CODE"],
        "container_type": r["CONTAINER_TYPE"],
        "container_size": r["CONTAINER_SIZE"],
        "quote_date": str(r["QUOTE_DATE"]),
        "base_freight": _to_num(r["BASE_FREIGHT"]),
        "baf09_amount": _to_num(r["BAF09_AMOUNT"]),
        "total": _to_num(r["TOTAL"]),
        "case_type": r["CASE_TYPE"],
        "note": r["NOTE"],
    }


def find_booking(session, booking_id: str = None, quote_id: str = None) -> dict | None:
    """Retrouve une réservation par BOOKING_ID ou QUOTE_ID."""
    if booking_id:
        rows = session.sql(
            f"SELECT * FROM {DB}.BOOKINGS WHERE BOOKING_ID = ?", params=[booking_id]
        ).collect()
    elif quote_id:
        rows = session.sql(
            f"SELECT * FROM {DB}.BOOKINGS WHERE QUOTE_ID = ?", params=[quote_id]
        ).collect()
    else:
        return None
    if not rows:
        return None
    r = rows[0]
    return {
        "booking_id": r["BOOKING_ID"],
        "quote_id": r["QUOTE_ID"],
        "booking_date": str(r["BOOKING_DATE"]),
        "container_count": int(r["CONTAINER_COUNT"]),
        "status": r["STATUS"],
        "customer_ref": r["CUSTOMER_REF"],
        "note": r["NOTE"],
    }


def find_charge_desc(session, charge_code: str) -> str | None:
    """Renvoie la description longue d'un code charge (REF_CAR_CHARGES)."""
    if not charge_code:
        return None
    rows = session.sql(
        f"SELECT LONG_DESC FROM {DB}.REF_CAR_CHARGES WHERE CHARGE_CODE = ?",
        params=[charge_code],
    ).collect()
    return rows[0]["LONG_DESC"] if rows else None


def find_services_for_route(session, pol: str, pod: str) -> list[dict]:
    """Cherche les services maritimes (REF_GOL_SERVICES) dont le nom de ligne
    contient les codes POL ou POD. Heuristique simple car la table n'a pas
    de colonnes POL/POD explicites."""
    if not pol or not pod:
        return []
    rows = session.sql(f"""
        SELECT DISTINCT LINE_CODE, LINE_NAME, SERVICE_CODE, SERVICE_NAME
        FROM {DB}.REF_GOL_SERVICES
        WHERE LINE_NAME ILIKE ? OR LINE_NAME ILIKE ?
        LIMIT 20
    """, params=[f"%{pol}%", f"%{pod}%"]).collect()
    return [
        {
            "line_code": r["LINE_CODE"],
            "line_name": r["LINE_NAME"],
            "service_code": r["SERVICE_CODE"],
            "service_name": r["SERVICE_NAME"],
        }
        for r in rows
    ]


def _to_num(val):
    if val is None or str(val).lower() in ("nan", "none", "null", ""):
        return None
    try:
        f = float(val)
        return int(f) if f == int(f) else f
    except (ValueError, TypeError):
        return None
