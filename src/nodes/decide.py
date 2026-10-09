"""Décision : répondre, demander une précision ou escalader.

Nœud réel, à base de règles explicites. Deux régimes :
- cas de prix : une preuve dans les données est obligatoire, sinon on
  demande une précision ou on escalade (consigne de l'énoncé) ;
- autres cas : une source documentaire fiable suffit pour répondre.
"""
from ..trace import entry

# Sans ces champs, la recherche de lignes de prix est impossible.
BLOCKING_FOR_DATA = ("pol", "pod")

# Un écart de prix sans preuve part à l'équipe Pricing (énoncé, section 4).
PRICING_TEAM = "Pricing"

RATE_FIELDS = ("rate_20ST", "rate_40ST", "rate_40HC", "rate_45HC")


def blocking_fields(state: dict) -> list[str]:
    missing = state.get("missing_fields", [])
    return [f for f in BLOCKING_FOR_DATA if f in missing]


def in_scope(state: dict) -> bool:
    """Périmètre retenu pour la décision.

    Un ticket rattaché à un devis spot existant est dans le périmètre : c'est
    un fait vérifié dans les données, qui l'emporte sur l'avis du LLM.
    """
    return bool(state.get("in_scope", True)) or bool(state.get("quote_found", False))


def distinct_candidates(data: dict) -> int:
    """Nombre de lignes de prix réellement différentes parmi les candidates.

    Deux lignes comptent pour une seule si elles ont le même type de conteneur
    et exactement les mêmes versions (origine, structure, montants) : choisir
    l'une ou l'autre ne changerait pas la conclusion. Mesuré sur BAF09 : une
    route avec son type donne plusieurs lignes dans 39 % des cas, mais elles
    ne diffèrent que dans 4 à 7 % des cas.
    """
    lines = data.get("lines") or []
    if not lines:
        return int(data.get("nb_candidates", 0) or 0)
    by_line = {}
    for l in lines:
        version = (l.get("charge_origin"), l.get("rate_structure")) + tuple(l.get(f) for f in RATE_FIELDS)
        by_line.setdefault((l.get("detail_uid"), l.get("pricelist_line_type")), []).append(version)
    groups = {(key[1], tuple(sorted(versions, key=str))) for key, versions in by_line.items()}
    return len(groups)


def decide(state: dict) -> dict:
    data = state.get("data") or {}
    missing = state.get("missing_fields", [])
    blocking = blocking_fields(state)
    price_case = state.get("price_case", False)
    docs_ok = state.get("docs_reliable", False)
    evidence = data.get("evidence", False)
    nb_lines = int(data.get("nb_candidates", 0) or 0)
    nb_distinct = distinct_candidates(data)
    data_searched = "data" in state
    team = state.get("team") or "support Hypercare"
    scope_ok = in_scope(state)
    kb_gap = False

    # Si le devis confirme le périmètre contre l'avis du LLM, l'équipe que le LLM
    # avait choisie (celle du hors périmètre) n'est plus la bonne.
    scope_confirmed_by_quote = scope_ok and not state.get("in_scope", True)
    if scope_confirmed_by_quote:
        team = PRICING_TEAM if price_case else "support Hypercare"

    if not scope_ok:
        decision, rule = "escalader", "hors_perimetre"
        reason = f"Demande hors périmètre, à transmettre à l'équipe {team}."
    elif "description" in missing:
        decision, rule = "preciser", "description_manquante"
        reason = "Le ticket ne décrit pas le problème."
    # --- Cas de prix : une preuve dans les données est obligatoire ---
    elif price_case and blocking:
        decision, rule = "preciser", "champs_manquants"
        reason = "Champs indispensables absents : " + ", ".join(blocking) + "."
    elif price_case and nb_distinct > 1:
        decision, rule = "preciser", "plusieurs_lignes_candidates"
        reason = f"{nb_distinct} lignes de prix différentes correspondent au ticket."
    elif price_case and data_searched and nb_lines == 0:
        decision, rule = "escalader", "aucune_ligne_trouvee"
        reason = "Aucune ligne de prix ne correspond à cette route à cette date."
        team = PRICING_TEAM
    elif price_case and not evidence:
        decision, rule = "escalader", "pas_de_preuve"
        reason = "Les données consultées n'expliquent pas le prix."
        team = PRICING_TEAM
    # --- Autres cas : une source documentaire fiable ou une preuve suffit ---
    elif not price_case and not docs_ok and not evidence:
        decision, rule = "escalader", "pas_de_source_fiable"
        reason = "Aucune source documentaire fiable ne répond à la question."
        kb_gap = True
    else:
        decision, rule = "repondre", "reponse_etayee"
        reason = "La réponse s'appuie sur des éléments vérifiables."

    # Les faits sur lesquels la règle s'est appuyée, pour la trace.
    facts = [f"dans le périmètre = {scope_ok}"
             + (" (confirmé par le devis)" if scope_confirmed_by_quote else ""),
             f"cas de prix = {price_case}"]
    if blocking:
        facts.append("champs bloquants manquants : " + ", ".join(blocking))
    if data_searched:
        facts.append(f"lignes candidates = {nb_lines}, dont différentes = {nb_distinct}")
        facts.append(f"preuve dans les données = {evidence}")
    else:
        facts.append("données non consultées")
    if "docs_reliable" in state:
        facts.append(f"source documentaire fiable = {docs_ok}")
    else:
        facts.append("documentation non consultée")

    return {
        "decision": decision,
        "decision_rule": rule,
        "decision_reason": reason,
        "kb_gap": kb_gap,
        "team": team,
        "trace": [entry(
            "decide", "orchestrateur",
            consulted=facts,
            decision=f"{decision} (règle : {rule})",
            result=reason,
        )],
    }
