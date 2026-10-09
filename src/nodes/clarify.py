"""Demande de précision au client (nœud réel).

Le LLM rédige un message expliquant pourquoi l'information manquante
est nécessaire et ce que le client doit fournir. Il s'appuie sur la
règle de décision et le contexte déjà collecté.
"""
from ..trace import entry
from .summaries import describe_lines, describe_refs


SYSTEM_PROMPT = """\
Tu rédiges une demande de précision pour un ticket de support de
l'équipe Hypercare (applications AQUA Spot et SpotOn).

Règles :
- Explique brièvement pourquoi tu ne peux pas encore répondre.
- Indique clairement ce que le client doit fournir.
- Ne demande pas une information qui figure déjà dans les références connues.
- Si des lignes de prix sont listées, présente-les pour aider à choisir.
- Si des éléments ont déjà été trouvés (documents ou données), mentionne
  ce qui a été vérifié pour montrer que le travail a commencé.
- Sois concis et professionnel.
- Réponds en anglais si le ticket est en anglais, en français sinon.
"""

FIELD_LABELS = {
    "pol": "port de chargement (POL)",
    "pod": "port de déchargement (POD)",
    "container_type": "type de conteneur (dry / reefer)",
    "line_reference": "référence de la ligne de prix",
    "description": "description du problème",
    "pricelist_number": "numéro de pricelist",
}


def make_clarify(llm):
    """Fabrique le nœud clarify à partir d'un LLM."""

    def clarify(state: dict) -> dict:
        ticket = state.get("ticket", {})
        description = ticket.get("description", "")
        rule = state.get("decision_rule", "")
        reason = state.get("decision_reason", "")
        data = state.get("data") or {}

        # Ce qu'il faut demander selon la règle
        if rule == "plusieurs_lignes_candidates":
            found = describe_lines(data.get("lines") or [], limit=6)
            ask = (
                f"{reason} Pour identifier la bonne, merci d'indiquer le type de "
                f"conteneur (dry ou reefer) ou la référence de ligne."
            )
            if found:
                ask += "\nLignes trouvées :\n" + "\n".join(f"- {t}" for t in found)
        elif rule == "champs_manquants":
            missing = state.get("missing_fields", [])
            blocking = [f for f in ("pol", "pod") if f in missing]
            labels = [FIELD_LABELS.get(f, f) for f in blocking]
            ask = "Champs indispensables manquants : " + ", ".join(labels) + "."
        elif rule == "description_manquante":
            ask = "Le ticket ne contient pas de description du problème."
        else:
            ask = reason

        # Contexte déjà collecté
        context_parts = []
        docs = state.get("docs") or []
        if docs:
            context_parts.append(
                f"{len(docs)} passage(s) documentaire(s) trouvé(s), "
                f"mais insuffisant(s) sans cette précision."
            )
        finding = data.get("finding", "")
        if finding:
            context_parts.append(f"Constat partiel dans les données : {finding}")

        context = "\n".join(context_parts) if context_parts else "Aucun élément collecté pour le moment."

        user_msg = (
            f"Ticket : {description}\n\n"
            f"Références déjà connues : {describe_refs(state)}\n\n"
            f"Raison de la demande : {ask}\n\n"
            f"Éléments déjà collectés :\n{context}\n\n"
            f"Rédige la demande de précision."
        )

        response = llm.invoke([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ])
        text = response.content.strip()

        return {
            "answer": text,
            "trace": [entry(
                "clarify", "agent résolution",
                tools=["rédaction LLM"],
                decision=f"précision demandée (règle : {rule})",
                result=f"demande envoyée — {reason}",
            )],
        }

    return clarify
