"""Agent de recherche documentaire réel."""

from ..trace import entry
from ..tools.retrieval import search_docs, verify_passages


def make_doc_search(session, llm, mode="strict"):
    """
    Construit le nœud doc_search avec accès à Snowflake et au LLM.

    mode : "strict" ou "souple", voir verify_passages dans tools/retrieval.py.
    En mode strict, seuls les passages validés un par un sont transmis à la
    rédaction. En mode souple, tous les passages retrouvés le sont.
    """

    def doc_search(state: dict) -> dict:

        question = state["ticket"].get("description", "").strip()

        # 1. Recherche documentaire
        result = search_docs(
            session=session,
            question=question,
            top_k=5,
        )

        passages = result["passages"]

        # 2. Vérification LLM uniquement si le seuil est atteint
        verification = {
            "relevant": False,
            "source_ids": [],
            "reason": "Aucun passage ne dépasse le seuil de similarité."
        }

        if result["reliable"] and passages:
            verification = verify_passages(
                llm=llm,
                question=question,
                passages=passages,
                threshold=result["threshold"],
                mode=mode,
            )

        # 3. Fiabilité finale
        reliable = (
            result["reliable"]
            and verification["relevant"]
        )

        # 4. Adaptation au format attendu par State
        #    "verified" : le passage a été validé par la vérification. Seuls
        #    ces passages sont transmis à la rédaction de la réponse.
        if not reliable:
            verified_ids = set()
        elif mode == "strict":
            verified_ids = set(verification["source_ids"])
        else:
            verified_ids = {p["source_id"] for p in passages}
        docs = [
            {
                "source": p["title"],
                "source_id": p["source_id"],
                "source_type": p["source_type"],
                "extrait": p["content"],
                "score": p["score"],
                "application": p["application"],
                "doc_date": p["doc_date"],
                "version": p["version"],
                "verified": p["source_id"] in verified_ids,
            }
            for p in passages
        ]

        consulted = [
            f"{d['source']} (score {d['score']:.4f})"
            + (" - validé" if d["verified"] else "")
            for d in docs
        ]

        return {
            "docs": docs,
            "docs_reliable": reliable,

            "trace": [
                entry(
                    "doc_search",
                    "agent documentaire",
                    tools=[
                        f"search_docs ({result['mode']})",
                        f"vérification LLM ({mode})"
                        if result["reliable"]
                        else "filtre de similarité"
                    ],
                    consulted=consulted,
                    result=(
                        f"{len(docs)} passage(s) retrouvé(s), "
                        f"seuil atteint = {result['reliable']}, "
                        f"validation LLM = {verification['relevant']} "
                        f"({len(verified_ids)} passage(s) validé(s)), "
                        f"source fiable = {reliable}"
                    )
                )
            ]
        }

    return doc_search