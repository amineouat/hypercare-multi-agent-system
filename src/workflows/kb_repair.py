import uuid
import json
from pydantic import BaseModel, Field


class KBRepairSuggestion(BaseModel):
    problem_description: str = Field(
        description="Description courte de la lacune documentaire."
    )
    suggested_content: str = Field(
        description="Proposition de contenu à ajouter à la base de connaissances."
    )

def generate_kb_suggestion(llm, state: dict) -> dict | None:

    if not state.get("kb_gap", False):
        return None

    ticket = state.get("ticket", {})
    question = ticket.get("description", "")

    docs = state.get("docs", [])

    docs_text = "\n\n".join(
        f"Source: {d.get('source')}\n"
        f"Extrait: {d.get('extrait')}"
        for d in docs
    )

    prompt = f"""
Tu aides à maintenir une base de connaissances Hypercare AQUA / SpotOn.

Une lacune documentaire a été détectée.

Question utilisateur :
{question}

Documents consultés :
{docs_text if docs_text else "Aucun document fiable."}

Règles :
- Ne pas inventer de règle métier.
- Ne pas inventer de valeur, prix, date ou comportement.
- Si les sources disponibles ne permettent pas de connaître la réponse,
  proposer uniquement une fiche indiquant ce qui doit être documenté.
- La proposition doit être concise et exploitable par un expert humain.
- Le contenu sera validé manuellement avant publication.
"""

    verifier = llm.with_structured_output(KBRepairSuggestion)

    result = verifier.invoke(prompt)

    return result.model_dump()



def create_kb_proposal(session, llm, state: dict) -> dict | None:
    """
    Crée une proposition de réparation de la base de connaissances
    lorsqu'une lacune documentaire a été détectée.

    La proposition est générée par le LLM puis enregistrée avec
    le statut 'pending' pour validation humaine.
    """

    # Pas de lacune détectée -> rien à proposer
    if not state.get("kb_gap", False):
        return None

    ticket = state.get("ticket", {})
    docs = state.get("docs", [])

    ticket_id = ticket.get("ticket_id")
    question = ticket.get("description", "")

    # Génération du contenu proposé
    suggestion = generate_kb_suggestion(
        llm=llm,
        state=state
    )

    if suggestion is None:
        return None

    proposal_id = str(uuid.uuid4())

    problem_type = "missing_knowledge"

    problem_description = suggestion["problem_description"]
    suggested_content = suggestion["suggested_content"]

    # On conserve la liste des sources consultées
    sources = [
        {
            "source": d.get("source"),
            "source_id": d.get("source_id"),
            "score": d.get("score"),
        }
        for d in docs
    ]

    session.sql(
        """
        INSERT INTO PROJECT_DB.PUBLIC.KB_PROPOSALS (
            PROPOSAL_ID,
            TICKET_ID,
            QUESTION,
            PROBLEM_TYPE,
            PROBLEM_DESCRIPTION,
            SOURCES,
            SUGGESTED_CONTENT,
            STATUS
        )
        SELECT
            ?,
            ?,
            ?,
            ?,
            ?,
            PARSE_JSON(?),
            ?,
            'pending'
        """,
        params=[
            proposal_id,
            ticket_id,
            question,
            problem_type,
            problem_description,
            json.dumps(sources),
            suggested_content,
        ],
    ).collect()

    return {
        "proposal_id": proposal_id,
        "status": "pending",
        "problem_type": problem_type,
        "problem_description": problem_description,
        "suggested_content": suggested_content,
    }


def approve_proposal(session, proposal_id: str, reviewer: str, comment: str = ""):
    session.sql("""
        UPDATE PROJECT_DB.PUBLIC.KB_PROPOSALS
        SET
            STATUS = 'approved',
            REVIEWED_AT = CURRENT_TIMESTAMP(),
            REVIEWED_BY = ?,
            REVIEW_COMMENT = ?
        WHERE PROPOSAL_ID = ?
          AND STATUS = 'pending'
    """, params=[
        reviewer,
        comment,
        proposal_id
    ]).collect()


def reject_proposal(session, proposal_id: str, reviewer: str, comment: str = ""):
    session.sql("""
        UPDATE PROJECT_DB.PUBLIC.KB_PROPOSALS
        SET
            STATUS = 'rejected',
            REVIEWED_AT = CURRENT_TIMESTAMP(),
            REVIEWED_BY = ?,
            REVIEW_COMMENT = ?
        WHERE PROPOSAL_ID = ?
          AND STATUS = 'pending'
    """, params=[
        reviewer,
        comment,
        proposal_id
    ]).collect()


def publish_proposal(session, proposal_id: str) -> dict:
    """
    Publie une proposition approuvée dans BASE_CONNAISSANCE_RAG.

    Pour le moment, on traite le cas missing_knowledge :
    création d'une nouvelle fiche FAQ.

    L'opération est enregistrée dans KB_VERSIONS afin de permettre
    un rollback.
    """

    rows = session.sql("""
        SELECT
            PROPOSAL_ID,
            PROBLEM_TYPE,
            SUGGESTED_CONTENT,
            STATUS
        FROM PROJECT_DB.PUBLIC.KB_PROPOSALS
        WHERE PROPOSAL_ID = ?
    """, params=[proposal_id]).collect()

    if not rows:
        raise ValueError("Proposition introuvable.")

    row = rows[0]

    status = row["STATUS"]
    problem_type = row["PROBLEM_TYPE"]
    content = row["SUGGESTED_CONTENT"]

    if status != "approved":
        raise ValueError(
            f"La proposition doit être 'approved' avant publication "
            f"(statut actuel : {status})."
        )

    if problem_type != "missing_knowledge":
        raise ValueError(
            "Cette première version ne publie que les lacunes "
            "de type missing_knowledge."
        )

    if not content or not content.strip():
        raise ValueError("Le contenu à publier est vide.")

    source_id = f"KB-AUTO-{uuid.uuid4()}"
    version_id = str(uuid.uuid4())

    try:
        session.sql("BEGIN").collect()

        # 1. Nouvelle fiche dans le RAG.
        # EMBEDDINGS est généré automatiquement par le DEFAULT
        # défini sur BASE_CONNAISSANCE_RAG.
        session.sql("""
            INSERT INTO PROJECT_DB.PUBLIC.BASE_CONNAISSANCE_RAG (
                CONTENT,
                FILE_NAME,
                SOURCE_TYPE
            )
            VALUES (?, ?, 'faq')
        """, params=[
            content,
            source_id
        ]).collect()

        # 2. Enregistrer l'opération pour rollback.
        # OLD_CONTENT = NULL car il s'agit d'une création.
        session.sql("""
            INSERT INTO PROJECT_DB.PUBLIC.KB_VERSIONS (
                VERSION_ID,
                PROPOSAL_ID,
                SOURCE_ID,
                SOURCE_TYPE,
                OLD_CONTENT,
                NEW_CONTENT,
                ACTION
            )
            VALUES (?, ?, ?, 'faq', NULL, ?, 'insert')
        """, params=[
            version_id,
            proposal_id,
            source_id,
            content
        ]).collect()

        # 3. Marquer la proposition comme publiée.
        session.sql("""
            UPDATE PROJECT_DB.PUBLIC.KB_PROPOSALS
            SET
                STATUS = 'published',
                PUBLISHED_SOURCE_ID = ?,
                PUBLISHED_AT = CURRENT_TIMESTAMP()
            WHERE PROPOSAL_ID = ?
        """, params=[
            source_id,
            proposal_id
        ]).collect()

        session.sql("COMMIT").collect()

    except Exception:
        session.sql("ROLLBACK").collect()
        raise

    return {
        "proposal_id": proposal_id,
        "source_id": source_id,
        "version_id": version_id,
        "status": "published",
    }


def rollback_proposal(session, proposal_id: str) -> dict:
    """
    Annule la publication correspondant à une proposition.

    Pour ACTION='insert', la fiche créée est supprimée du RAG.
    """

    proposals = session.sql("""
        SELECT
            STATUS,
            PUBLISHED_SOURCE_ID
        FROM PROJECT_DB.PUBLIC.KB_PROPOSALS
        WHERE PROPOSAL_ID = ?
    """, params=[proposal_id]).collect()

    if not proposals:
        raise ValueError("Proposition introuvable.")

    proposal = proposals[0]

    if proposal["STATUS"] != "published":
        raise ValueError(
            "Seule une proposition publiée peut être annulée."
        )

    versions = session.sql("""
        SELECT
            VERSION_ID,
            SOURCE_ID,
            SOURCE_TYPE,
            OLD_CONTENT,
            NEW_CONTENT,
            ACTION
        FROM PROJECT_DB.PUBLIC.KB_VERSIONS
        WHERE PROPOSAL_ID = ?
        ORDER BY CREATED_AT DESC
        LIMIT 1
    """, params=[proposal_id]).collect()

    if not versions:
        raise ValueError("Aucune version disponible pour le rollback.")

    version = versions[0]

    try:
        session.sql("BEGIN").collect()

        if version["ACTION"] == "insert":

            session.sql("""
                DELETE FROM PROJECT_DB.PUBLIC.BASE_CONNAISSANCE_RAG
                WHERE FILE_NAME = ?
            """, params=[
                version["SOURCE_ID"]
            ]).collect()

        elif version["ACTION"] == "update":

            session.sql("""
                UPDATE PROJECT_DB.PUBLIC.BASE_CONNAISSANCE_RAG
                SET CONTENT = ?
                WHERE FILE_NAME = ?
            """, params=[
                version["OLD_CONTENT"],
                version["SOURCE_ID"]
            ]).collect()

        else:
            raise ValueError(
                f"Action de version inconnue : {version['ACTION']}"
            )

        session.sql("""
            UPDATE PROJECT_DB.PUBLIC.KB_PROPOSALS
            SET STATUS = 'rolled_back'
            WHERE PROPOSAL_ID = ?
        """, params=[proposal_id]).collect()

        session.sql("COMMIT").collect()

    except Exception:
        session.sql("ROLLBACK").collect()
        raise

    return {
        "proposal_id": proposal_id,
        "source_id": version["SOURCE_ID"],
        "status": "rolled_back",
    }