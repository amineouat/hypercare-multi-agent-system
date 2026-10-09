"""Nœuds FACTICES de l'étape 5.

Ils ne cherchent rien et n'appellent aucun LLM : ils renvoient les réponses
préparées dans state["fixtures"] (voir tests/scenarios.json). Ils servent à
tester le routage, les règles de décision et la trace.

À l'étape 7, chaque fonction est remplacée par un vrai nœud dans son propre
fichier (classify.py, doc_search.py...), puis l'import est changé dans
graph.py. L'étape 7 est finie quand ce fichier n'est plus importé.
"""
from ..trace import entry


def _fx(state: dict, key: str) -> dict:
    return (state.get("fixtures") or {}).get(key, {})


def classify(state: dict) -> dict:
    fx = _fx(state, "classify")
    theme = fx.get("theme", "Inconnu")
    in_scope = fx.get("in_scope", True)
    needs = fx.get("needs", ["docs"])
    return {
        "theme": theme,
        "in_scope": in_scope,
        "team": fx.get("team", ""),
        "needs": needs,
        "price_case": fx.get("price_case", False),
        "trace": [entry(
            "classify", "orchestrateur",
            tools=["classification (factice)"],
            decision=f"thème = {theme}, dans le périmètre = {in_scope}",
            result="besoins : " + ", ".join(needs),
        )],
    }


def doc_search(state: dict) -> dict:
    fx = _fx(state, "doc_search")
    docs = fx.get("docs", [])
    reliable = fx.get("reliable", False)
    return {
        "docs": docs,
        "docs_reliable": reliable,
        "trace": [entry(
            "doc_search", "agent documentaire",
            tools=["recherche documentaire (factice)"],
            consulted=[f"{d['source']} (score {d['score']})" for d in docs],
            result=f"{len(docs)} passage(s), source fiable = {reliable}",
        )],
    }


def data_investigation(state: dict) -> dict:
    fx = _fx(state, "data_investigation")
    data = {
        "lines": fx.get("lines", []),
        "nb_candidates": fx.get("nb_candidates", 0),
        "evidence": fx.get("evidence", False),
        "finding": fx.get("finding", ""),
    }
    consulted = [
        f"ligne {l['line_sequence']} / detail_uid {l['detail_uid']} "
        f"({l['charge_origin']}, {l['rate_structure']})"
        for l in data["lines"]
    ]
    return {
        "data": data,
        "trace": [entry(
            "data_investigation", "agent données",
            tools=["recherche de lignes de prix (factice)"],
            consulted=consulted,
            result=f"{data['nb_candidates']} ligne(s) candidate(s), preuve = {data['evidence']}",
        )],
    }


def _sources(state: dict) -> str:
    return ", ".join(d["source"] for d in state.get("docs", [])) or "aucune"


def answer(state: dict) -> dict:
    finding = (state.get("data") or {}).get("finding", "")
    text = "[RÉPONSE FACTICE] "
    if finding:
        text += f"Constat dans les données : {finding} "
    text += f"Sources documentaires : {_sources(state)}."
    return {
        "answer": text,
        "trace": [entry("answer", "agent résolution",
                        tools=["rédaction (factice)"], result="réponse rédigée avec ses sources")],
    }


def clarify(state: dict) -> dict:
    rule = state.get("decision_rule", "")
    if rule == "plusieurs_lignes_candidates":
        ask = "le type de conteneur (dry ou reefer) ou la référence de ligne"
    elif rule == "champs_manquants":
        ask = "le port de chargement et le port de déchargement"
    else:
        ask = "une description détaillée du problème"
    text = (f"[DEMANDE DE PRÉCISION FACTICE] {state.get('decision_reason', '')} "
            f"Merci d'indiquer {ask}.")
    return {
        "answer": text,
        "trace": [entry("clarify", "agent résolution",
                        tools=["rédaction (factice)"], result="demande de précision envoyée")],
    }


def escalate(state: dict) -> dict:
    data = state.get("data") or {}
    team = state.get("team") or "support Hypercare"
    lines = [
        "[ESCALADE FACTICE]",
        f"Destinataire : {team}",
        f"Motif : {state.get('decision_reason', '')}",
        f"Documents consultés : {_sources(state)}",
        f"Données consultées : {data.get('finding') or 'aucune'}",
        "Ce qui manque : une explication étayée par les données ou la documentation.",
    ]
    if state.get("kb_gap"):
        lines.append("Lacune documentaire signalée pour la base de connaissances.")
    return {
        "answer": "\n".join(lines),
        "trace": [entry("escalate", "agent résolution",
                        tools=["préparation du dossier (factice)"],
                        result=f"dossier transmis à {team}")],
    }
