from snowflake.cortex import embed_text_768
from datetime import datetime, timezone
import numpy as np
import json
import uuid

MODEL = "snowflake-arctic-embed-m-v1.5"


def cosine_similarity(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)

    norm = np.linalg.norm(a) * np.linalg.norm(b)

    if norm == 0:
        return 0.0

    return float(np.dot(a, b) / norm)


def find_similar_tickets(
    tickets: list[dict],
    reference_ticket: dict,
    threshold: float = 0.80
) -> list[dict]:

    reference_date = reference_ticket["received_at"][:10]
    reference_id = reference_ticket["ticket_id"]
    reference_description = reference_ticket["description"]

    reference_embedding = embed_text_768(
        MODEL,
        reference_description
    )

    similar = []

    for ticket in tickets:

        # Exclure le ticket lui-même
        if ticket["ticket_id"] == reference_id:
            continue

        # Uniquement les tickets du même jour
        if ticket["received_at"][:10] != reference_date:
            continue

        description = ticket.get("description", "")

        if not description.strip():
            continue

        embedding = embed_text_768(MODEL, description)

        score = cosine_similarity(
            reference_embedding,
            embedding
        )

        if score >= threshold:
            similar.append({
                "ticket_id": ticket["ticket_id"], # permet d'exploiter les champs normalisés ou classifiés du ticket lorsqu'ils existent
                "description": description,
                "similarity": round(score, 4),
                "pol": ticket.get("pol"),
                "pod": ticket.get("pod"),
                "theme": ticket.get("theme")
            })

    return sorted(
        similar,
        key=lambda x: x["similarity"],
        reverse=True
    )

def group_similar_tickets(
    reference_ticket: dict,
    similar_tickets: list[dict],
    min_similarity: float = 0.85,
    same_route: bool = True
) -> dict:
    """
    Regroupe les tickets proches d'un ticket de référence.

    Conditions :
    - similarité >= min_similarity ;
    - même route si same_route=True et si la route
      est connue dans les deux tickets.

    Le groupe indique une suspicion d'incident commun,
    pas une cause métier confirmée.
    """

    grouped = []

    for ticket in similar_tickets:

        if ticket["similarity"] < min_similarity:
            continue

        if same_route:
            ref_pol = reference_ticket.get("pol")
            ref_pod = reference_ticket.get("pod")

            other_pol = ticket.get("pol")
            other_pod = ticket.get("pod")

            if (
                ref_pol and ref_pod
                and other_pol and other_pod
            ):
                if (
                    ref_pol.strip().upper() != other_pol.strip().upper()
                    or ref_pod.strip().upper() != other_pod.strip().upper()
                ):
                    continue

        grouped.append(ticket)

    return {
        "reference_ticket_id": reference_ticket["ticket_id"],
        "count": len(grouped),
        "tickets": grouped,
        "possible_common_incident": len(grouped) >= 1
    }
    

def detect_similar_ticket_alert(
    tickets: list[dict],
    reference_ticket: dict,
    similarity_threshold: float = 0.85,
    min_tickets: int = 3
) -> dict:
    """
    Détecte automatiquement un groupe de tickets similaires
    et produit une alerte si le seuil est atteint.

    min_tickets inclut le ticket de référence.
    """

    # 1. Recherche sémantique
    similar = find_similar_tickets(
        tickets=tickets,
        reference_ticket=reference_ticket,
        threshold=similarity_threshold
    )

    # 2. Regroupement métier
    group = group_similar_tickets(
        reference_ticket=reference_ticket,
        similar_tickets=similar,
        min_similarity=similarity_threshold,
        same_route=True
    )

    # Ajouter le ticket de référence au nombre total
    total_tickets = group["count"] + 1

    # 3. Vérifier la règle de déclenchement
    triggered = total_tickets >= min_tickets

    ticket_ids = [
        reference_ticket["ticket_id"]
    ] + [
        ticket["ticket_id"]
        for ticket in group["tickets"]
    ]

    # 4. Construire l'alerte
    return {
        "triggered": triggered,
        "alert_type": "similar_tickets" if triggered else None,
        "created_at": (
            datetime.now(timezone.utc).isoformat()
            if triggered else None
        ),
        "reference_ticket_id": reference_ticket["ticket_id"],
        "ticket_ids": ticket_ids,
        "total_tickets": total_tickets,
        "threshold": min_tickets,
        "ticket_date": reference_ticket["received_at"][:10],
        "similarity_threshold": similarity_threshold,
        "message": (
            f"Alerte Hypercare : {total_tickets} tickets "
            f"potentiellement liés détectés le "
            f"{reference_ticket['received_at'][:10]}."
            if triggered
            else "Nombre de tickets insuffisant pour déclencher une alerte."
        )
    }


def save_similar_ticket_alert(session, alert: dict) -> bool:
    """
    Enregistre une alerte si elle n'existe pas déjà.
    Retourne True si une nouvelle alerte est enregistrée.
    """

    if not alert["triggered"]:
        return False

    ticket_ids = sorted(set(alert["ticket_ids"]))
    ticket_date = alert["ticket_date"]

    # Identifiant déterministe pour un même groupe et une même date.
    import hashlib

    alert_key = hashlib.sha256(
        (ticket_date + "|" + "|".join(ticket_ids)).encode("utf-8")
    ).hexdigest()

    # Un MERGE permet d'éviter les insertions répétées
    # du même groupe de tickets.
    session.sql("""
        MERGE INTO PROJECT_DB.PUBLIC.SIMILAR_TICKET_ALERTS t
        USING (
            SELECT
                ? AS ALERT_ID,
                ? AS REFERENCE_TICKET_ID,
                TO_DATE(?) AS TICKET_DATE,
                PARSE_JSON(?) AS TICKET_IDS,
                ? AS TOTAL_TICKETS,
                ? AS SIMILARITY_THRESHOLD,
                ? AS MESSAGE
        ) s
        ON t.ALERT_ID = s.ALERT_ID
        WHEN NOT MATCHED THEN
            INSERT (
                ALERT_ID, REFERENCE_TICKET_ID, TICKET_DATE,
                TICKET_IDS, TOTAL_TICKETS,
                SIMILARITY_THRESHOLD, MESSAGE
            )
            VALUES (
                s.ALERT_ID, s.REFERENCE_TICKET_ID, s.TICKET_DATE,
                s.TICKET_IDS, s.TOTAL_TICKETS,
                s.SIMILARITY_THRESHOLD, s.MESSAGE
            )
    """, params=[
        alert_key,
        alert["reference_ticket_id"],
        ticket_date,
        json.dumps(ticket_ids),
        alert["total_tickets"],
        alert["similarity_threshold"],
        alert["message"]
    ]).collect()

    return True


def run_workflow_sp(sp_session):
    import uuid
    from similar_tickets import (
        detect_similar_ticket_alert,
        save_similar_ticket_alert
    )

    run_id = str(uuid.uuid4())
    tickets_analyzed = 0
    alerts_created = 0

    try:
        rows = sp_session.sql("""
            SELECT TICKET_ID, RECEIVED_AT, DESCRIPTION, POL, POD
            FROM PROJECT_DB.PUBLIC.WORKFLOW_TICKETS
            WHERE SUBSTR(RECEIVED_AT, 1, 10) =
                  TO_CHAR(CURRENT_DATE(), 'YYYY-MM-DD')
              AND DESCRIPTION IS NOT NULL
              AND TRIM(DESCRIPTION) <> ''
        """).collect()

        tickets = [
            {
                "ticket_id": row["TICKET_ID"],
                "received_at": row["RECEIVED_AT"],
                "description": row["DESCRIPTION"],
                "pol": row["POL"],
                "pod": row["POD"]
            }
            for row in rows
        ]

        tickets_analyzed = len(tickets)

        for ticket in tickets:
            alert = detect_similar_ticket_alert(
                tickets=tickets,
                reference_ticket=ticket,
                similarity_threshold=0.85,
                min_tickets=3
            )

            if not alert["triggered"]:
                continue

            # Un seul ticket de référence par groupe détecté.
            if ticket["ticket_id"] != min(alert["ticket_ids"]):
                continue

            if save_similar_ticket_alert(sp_session, alert):
                alerts_created += 1

        status = "success"
        details = "Analyse terminée."

    except Exception as exc:
        status = "failed"
        details = str(exc)[:2000]

    sp_session.sql("""
        INSERT INTO PROJECT_DB.PUBLIC.WORKFLOW_RUNS (
            RUN_ID, WORKFLOW_NAME, STATUS,
            TICKETS_ANALYZED, ALERTS_CREATED, DETAILS
        )
        VALUES (?, 'similar_tickets', ?, ?, ?, ?)
    """, params=[
        run_id,
        status,
        tickets_analyzed,
        alerts_created,
        details
    ]).collect()

    if status == "failed":
        raise RuntimeError(details)

    return (
        f"run_id={run_id}, "
        f"tickets={tickets_analyzed}, "
        f"new_alerts={alerts_created}"
    )