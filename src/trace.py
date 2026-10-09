"""Trace observable : agent choisi, outils appelés, éléments consultés,
décision prise et résultat. Ce ne sont pas les pensées du modèle."""
from datetime import datetime, timezone


def entry(node, agent, tools=None, consulted=None, decision=None, result=None) -> dict:
    """Construit une entrée de trace. Un nœud la renvoie dans {"trace": [entry(...)]}."""
    return {
        "heure": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "noeud": node,
        "agent": agent,
        "outils": tools or [],
        "consultes": consulted or [],
        "decision": decision,
        "resultat": result,
    }


def show_trace(trace: list[dict]) -> None:
    """Affiche la trace étape par étape."""
    for i, e in enumerate(trace, start=1):
        print(f"\n[{i}] NŒUD : {e['noeud']}   (agent : {e['agent']})")
        if e["outils"]:
            print("    outils appelés :", ", ".join(e["outils"]))
        for c in e["consultes"]:
            print("    consulté       :", c)
        if e["decision"]:
            print("    décision       :", e["decision"])
        if e["resultat"]:
            print("    résultat       :", e["resultat"])


def trace_rows(ticket_id: str, trace: list[dict]) -> list[dict]:
    """Met la trace à plat, une ligne par étape (pour un DataFrame ou une table)."""
    return [
        {
            "ticket_id": ticket_id,
            "etape": i,
            "heure": e["heure"],
            "noeud": e["noeud"],
            "agent": e["agent"],
            "outils": ", ".join(e["outils"]),
            "consultes": " | ".join(e["consultes"]),
            "decision": e["decision"] or "",
            "resultat": e["resultat"] or "",
        }
        for i, e in enumerate(trace, start=1)
    ]
