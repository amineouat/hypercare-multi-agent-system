"""Préparation du dossier d'escalade (nœud réel).

Le LLM rédige le dossier, mais tous les faits lui sont fournis par du code :
références du ticket, documents consultés, lignes de prix consultées, raison
de l'escalade et ce qui manque. Le contexte dit explicitement ce qui a été
cherché et ce qui ne l'a pas été, pour que le dossier n'affirme jamais qu'une
recherche a échoué alors qu'elle n'a pas eu lieu.
"""
from ..trace import entry
from .summaries import describe_lines, describe_refs


SYSTEM_PROMPT = """\
Tu prépares un dossier d'escalade pour un ticket de support de
l'équipe Hypercare (applications AQUA Spot et SpotOn).

Le dossier est destiné à une équipe spécialisée qui prendra le relais.

Structure du dossier :
1. Résumé du problème (une ou deux phrases), avec les références du ticket.
2. Ce qui a été vérifié : documents consultés, données interrogées.
3. Raison de l'escalade et ce qui manque pour répondre.
4. Lacune documentaire : seulement si le contexte indique
   « LACUNE DOCUMENTAIRE : oui ». Sinon, n'écris pas cette section.

Règles :
- N'utilise QUE les éléments fournis. N'invente aucune explication.
- Si le contexte dit qu'une recherche n'a pas été effectuée, écris qu'elle
  n'a pas été effectuée. Ne dis jamais qu'elle n'a rien donné.
- Reprends les lignes de prix consultées telles qu'elles sont décrites.
- Cite les documents par leur titre et les données par « données BAF09 ».
- Sois factuel et structuré : l'équipe destinataire doit pouvoir
  reprendre le dossier sans relire le ticket.
- Rédige en anglais si le ticket est en anglais, en français sinon.
"""

# Ce qui manque pour répondre, selon la règle de décision appliquée.
MISSING_BY_RULE = {
    "hors_perimetre": "Le traitement par l'équipe compétente : la demande ne relève pas du support Hypercare.",
    "pas_de_preuve": "Une explication de l'écart de prix : les lignes de prix consultées ne montrent "
                     "aucune modification manuelle qui l'expliquerait.",
    "aucune_ligne_trouvee": "La ligne de prix concernée : aucune ne correspond à cette route à cette date "
                            "dans l'extraction BAF09.",
    "pas_de_source_fiable": "Une source documentaire qui réponde à la question.",
}


def _build_context(state: dict) -> str:
    """Rassemble tout le contexte pour le dossier d'escalade."""
    parts = []
    team = state.get("team") or "support Hypercare"
    rule = state.get("decision_rule", "")

    parts.append(f"ÉQUIPE DESTINATAIRE : {team}")
    parts.append(f"RÉFÉRENCES DU TICKET : {describe_refs(state)}")
    parts.append(f"RAISON DE L'ESCALADE : {state.get('decision_reason', '')} (règle : {rule})")
    parts.append(f"CE QUI MANQUE : {MISSING_BY_RULE.get(rule, 'Un élément vérifiable permettant de répondre.')}")

    # Documentation : distinguer « non cherché », « rien trouvé » et « trouvé »
    if "docs" not in state:
        parts.append("\nRECHERCHE DOCUMENTAIRE : non effectuée pour ce ticket.")
    elif not state["docs"]:
        parts.append("\nRECHERCHE DOCUMENTAIRE : effectuée, aucun passage retrouvé.")
    else:
        reliable = state.get("docs_reliable", False)
        parts.append("\nRECHERCHE DOCUMENTAIRE : effectuée. "
                     + ("Au moins un passage répond au problème." if reliable
                        else "Passages proches retrouvés, mais aucun ne répond au problème."))
        for d in state["docs"]:
            source = d.get("source") or d.get("source_id", "?")
            tag = " [vérifié]" if d.get("verified") else ""
            parts.append(f"  - {source} (score {d.get('score', 0):.2f}){tag}")
            if d.get("verified") and d.get("extrait"):
                parts.append(f"    {d['extrait']}")

    # Données : distinguer « non consultées », « aucune ligne » et « lignes consultées »
    if "data" not in state:
        parts.append("\nDONNÉES : non consultées pour ce ticket.")
    else:
        data = state.get("data") or {}
        lines = data.get("lines") or []
        if not lines:
            parts.append("\nDONNÉES BAF09 : consultées, aucune ligne de prix pour cette route à cette date.")
        else:
            parts.append(f"\nDONNÉES BAF09 : {data.get('nb_candidates', 0)} ligne(s) de prix consultée(s).")
            parts += [f"  - {text}" for text in describe_lines(lines)]
            if data.get("finding"):
                parts.append(f"  Constat : {data['finding']}")
            elif not data.get("evidence", False):
                parts.append("  Constat : aucune modification manuelle sur ces lignes.")

        quote = data.get("quote")
        if quote:
            parts.append(f"DEVIS : {quote['quote_id']} — BAF09 = {quote['baf09_amount']}, total = {quote['total']}")
        booking = data.get("booking")
        if booking:
            parts.append(f"RÉSERVATION : {booking['booking_id']} — statut = {booking['status']}")

    parts.append("\nLACUNE DOCUMENTAIRE : " + ("oui" if state.get("kb_gap") else "non"))
    return "\n".join(parts)


def make_escalate(llm):
    """Fabrique le nœud escalate à partir d'un LLM."""

    def escalate(state: dict) -> dict:
        ticket = state.get("ticket", {})
        description = ticket.get("description", "")
        team = state.get("team") or "support Hypercare"
        context = _build_context(state)

        user_msg = (
            f"Ticket : {description}\n\n"
            f"Contexte collecté :\n{context}\n\n"
            f"Prépare le dossier d'escalade pour l'équipe {team}."
        )

        response = llm.invoke([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ])
        text = response.content.strip()

        sources = [d.get("source") or d.get("source_id", "?") for d in (state.get("docs") or [])]
        data = state.get("data") or {}
        if data.get("lines"):
            sources.append(f"données BAF09 ({data.get('nb_candidates', 0)} ligne(s))")

        return {
            "answer": text,
            "trace": [entry(
                "escalate", "agent résolution",
                tools=["préparation du dossier LLM"],
                consulted=sources,
                decision=f"escalade vers {team}",
                result=f"dossier transmis à {team}"
                       + (" — lacune documentaire signalée" if state.get("kb_gap") else ""),
            )],
        }

    return escalate
