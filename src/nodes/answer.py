"""Rédaction de la réponse au ticket (nœud réel).

Le LLM rédige une réponse en s'appuyant uniquement sur les éléments
fournis (documents et données) et cite ses sources. Il ne doit rien
inventer.
"""
from ..trace import entry


SYSTEM_PROMPT = """\
Tu rédiges la réponse à un ticket de support pour l'équipe Hypercare
d'une compagnie maritime (applications AQUA Spot et SpotOn).

Règles strictes :
- N'utilise QUE les éléments fournis (passages documentaires et constats
  issus des données). N'invente aucune information.
- Cite chaque source utilisée entre crochets : [nom du document] ou
  [données : constat].
- Si un constat dans les données explique le problème (par exemple une
  modification manuelle d'une charge), c'est la cause : commence par cette
  explication et ne propose aucune autre cause possible. Les passages ne
  servent alors qu'à expliquer ce constat.
- Sinon, réponds à partir des passages documentaires fournis.
- Si les passages décrivent plusieurs causes possibles et que le ticket ne
  permet pas de trancher, présente-les comme des vérifications à faire,
  dans l'ordre, sans affirmer laquelle s'applique.
- Ne donne pas de devise si elle ne figure pas dans les éléments fournis.
- Sois concis, factuel et professionnel. Pas de formule de politesse
  inutile.
- Réponds en anglais si le ticket est en anglais, en français sinon.
"""


def _usable_docs(state: dict) -> list:
    """Passages transmis à la rédaction : seulement ceux que la vérification a validés.

    Les passages retrouvés mais non validés traitent souvent un problème voisin :
    les transmettre fait apparaître dans la réponse des causes qui ne concernent
    pas le ticket.
    """
    docs = state.get("docs") or []
    if any("verified" in d for d in docs):
        return [d for d in docs if d.get("verified")]
    return docs


def _build_context(state: dict) -> str:
    """Rassemble les éléments disponibles pour le LLM."""
    parts = []

    # Documents : seulement les passages validés par la vérification
    docs = _usable_docs(state)
    if docs:
        parts.append("PASSAGES DOCUMENTAIRES :")
        for i, d in enumerate(docs, 1):
            source = d.get("source") or d.get("source_id", "?")
            score = d.get("score", 0)
            extrait = d.get("extrait", "")
            parts.append(f"  [{i}] {source} (score {score:.2f})")
            if extrait:
                parts.append(f"      {extrait}")

    # Données
    data = state.get("data") or {}
    finding = data.get("finding", "")
    if finding:
        parts.append(f"\nCONSTAT DANS LES DONNÉES :\n  {finding}")

    quote = data.get("quote")
    if quote:
        parts.append(
            f"\nDEVIS : {quote['quote_id']} — BAF09 = {quote['baf09_amount']}, "
            f"total = {quote['total']}, detail_uid = {quote['detail_uid']}"
        )

    booking = data.get("booking")
    if booking:
        parts.append(
            f"\nRÉSERVATION : {booking['booking_id']} — "
            f"statut = {booking['status']}, client = {booking['customer_ref']}"
        )

    update = data.get("baf09_update") or {}
    changes = update.get("changes", "")
    if changes:
        parts.append(f"\nCHANGEMENTS ENTRE EXTRACTIONS : {changes}")

    charge_desc = data.get("charge_desc")
    if charge_desc:
        parts.append(f"\nDESCRIPTION DE LA CHARGE : {charge_desc}")

    if not parts:
        parts.append("Aucune source disponible.")

    return "\n".join(parts)


def make_answer(llm):
    """Fabrique le nœud answer à partir d'un LLM."""

    def answer(state: dict) -> dict:
        ticket = state.get("ticket", {})
        description = ticket.get("description", "")
        context = _build_context(state)

        user_msg = (
            f"Ticket : {description}\n\n"
            f"Éléments disponibles :\n{context}\n\n"
            f"Rédige la réponse."
        )

        response = llm.invoke([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ])
        text = response.content.strip()

        sources = [d.get("source") or d.get("source_id", "?") for d in _usable_docs(state)]
        data = state.get("data") or {}
        if data.get("finding"):
            sources.append("données opérationnelles")

        return {
            "answer": text,
            "trace": [entry(
                "answer", "agent résolution",
                tools=["rédaction LLM"],
                consulted=sources,
                result="réponse rédigée avec ses sources",
            )],
        }

    return answer
