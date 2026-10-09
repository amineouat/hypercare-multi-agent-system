"""Recherche de lignes de prix dans PRICELINES_BAF09 / BAF09_UPDATE."""

from datetime import date, datetime


def find_pricelines(session, pol: str, pod: str, on_date,
                    container_type: str | None = None,
                    line_reference: str | None = None,
                    table: str = "PROJECT_DB.PUBLIC.PRICELINES_BAF09") -> dict:
    """Cherche les lignes de prix valides pour une route et une date.

    Voir docs/contrats_outils.md pour le format complet.
    """
    if isinstance(on_date, str):
        # Accepte "YYYY-MM-DD" éventuellement suivi d'une heure ("YYYY-MM-DD HH:MM", ISO "T...")
        on_date = datetime.strptime(on_date.strip()[:10], "%Y-%m-%d").date()
    elif isinstance(on_date, datetime):
        on_date = on_date.date()

    epoch_ns = int(datetime(on_date.year, on_date.month, on_date.day).timestamp()) * 1_000_000_000

    conditions = [
        f"POL_CODE = '{pol}'",
        f"POD_CODE = '{pod}'",
        f"VALID_FROM <= {epoch_ns}",
        f"VALID_TO   >= {epoch_ns}",
    ]
    if container_type:
        conditions.append(f"PRICELIST_LINE_TYPE = '{container_type}'")
    if line_reference:
        conditions.append(f"LINE_SEQUENCE = '{line_reference}'")

    where = " AND ".join(conditions)

    sql = f"""
    SELECT DETAIL_UID, LINE_SEQUENCE, PRICELIST_NAME, PRICING_GROUP_NAME,
           POL_CODE, POD_CODE, PRICELIST_LINE_TYPE, COMMODITY_CODE,
           TO_TIMESTAMP_NTZ(VALID_FROM, 9)::VARCHAR  AS VALID_FROM,
           TO_TIMESTAMP_NTZ(VALID_TO,   9)::VARCHAR  AS VALID_TO,
           CHARGE_ORIGIN, RATE_STRUCTURE,
           RATE_20ST, RATE_40ST, RATE_40HC, RATE_45HC,
           APPLICABLE, FIXED,
           TO_TIMESTAMP_NTZ(LAST_MODIFICATION_DATE, 9)::VARCHAR AS LAST_MODIFICATION_DATE
    FROM {table}
    WHERE {where}
    ORDER BY DETAIL_UID, CHARGE_ORIGIN
    """

    rows = session.sql(sql).collect()

    if not rows:
        return {"lines": [], "nb_candidates": 0, "evidence": False, "finding": ""}

    lines = []
    for r in rows:
        lines.append({
            "detail_uid":             r["DETAIL_UID"],
            "line_sequence":          r["LINE_SEQUENCE"],
            "pricelist_name":         r["PRICELIST_NAME"],
            "pricing_group_name":     r["PRICING_GROUP_NAME"],
            "pol_code":               r["POL_CODE"],
            "pod_code":               r["POD_CODE"],
            "pricelist_line_type":    r["PRICELIST_LINE_TYPE"],
            "commodity_code":         r["COMMODITY_CODE"],
            "valid_from":             r["VALID_FROM"][:10] if r["VALID_FROM"] else None,
            "valid_to":               r["VALID_TO"][:10] if r["VALID_TO"] else None,
            "charge_origin":          r["CHARGE_ORIGIN"],
            "rate_structure":         r["RATE_STRUCTURE"],
            "rate_20ST":              _to_num(r["RATE_20ST"]),
            "rate_40ST":              _to_num(r["RATE_40ST"]),
            "rate_40HC":              _to_num(r["RATE_40HC"]),
            "rate_45HC":              _to_num(r["RATE_45HC"]),
            "applicable":             r["APPLICABLE"],
            "fixed":                  r["FIXED"],
            "last_modification_date": r["LAST_MODIFICATION_DATE"],
        })

    detail_uids = {l["detail_uid"] for l in lines}
    nb_candidates = len(detail_uids)

    evidence, finding = _detect_evidence(lines, detail_uids)

    return {
        "lines": lines,
        "nb_candidates": nb_candidates,
        "evidence": evidence,
        "finding": finding,
    }


def _to_num(val):
    if val is None or str(val).lower() in ("nan", "none", "null", ""):
        return None
    try:
        f = float(val)
        return int(f) if f == int(f) else f
    except (ValueError, TypeError):
        return None


def _detect_evidence(lines: list, detail_uids: set) -> tuple[bool, str]:
    """Détecte si un detail_uid a une version système ET une version Manual
    avec structure ou montant différents."""
    findings = []
    for uid in sorted(detail_uids):
        uid_lines = [l for l in lines if l["detail_uid"] == uid]
        origins = {l["charge_origin"] for l in uid_lines}
        system_origins = origins & {"CTB", "CTM"}
        if not system_origins or "Manual" not in origins:
            continue

        sys_line = next(l for l in uid_lines if l["charge_origin"] in system_origins)
        man_line = next(l for l in uid_lines if l["charge_origin"] == "Manual")

        diffs = []
        if sys_line["rate_structure"] != man_line["rate_structure"]:
            diffs.append(f"structure {sys_line['rate_structure']} → {man_line['rate_structure']}")
        for rate_key in ("rate_20ST", "rate_40ST", "rate_40HC", "rate_45HC"):
            sv, mv = sys_line[rate_key], man_line[rate_key]
            if sv != mv:
                diffs.append(f"{rate_key} {sv} → {mv}")

        if diffs:
            seq = sys_line["line_sequence"]
            findings.append(
                f"La ligne {seq} (detail_uid {uid}) existe en version "
                f"{sys_line['charge_origin']} et en version Manual : "
                + ", ".join(diffs) + "."
            )

    if findings:
        return True, " ".join(findings)
    return False, ""
