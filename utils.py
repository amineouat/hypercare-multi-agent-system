from snowflake.snowpark.context import get_active_session

session = get_active_session()

EMBEDDING_MODEL = "snowflake-arctic-embed-m-v1.5"
TABLE_NAME = "PROJECT_DB.PUBLIC.BASE_CONNAISSANCE_RAG"


# Retrieval

def embed_question(question: str, embedding_model: str = EMBEDDING_MODEL):
    """
    Génère l'embedding d'une question utilisateur avec Snowflake AI_EMBED.
    """
    query = f"""
    SELECT AI_EMBED('{EMBEDDING_MODEL}', ?) AS embedding
    """

    result = session.sql(
        query,
        params=[question]
    ).collect()

    return result[0]["EMBEDDING"]


def retrieve_chunks(question: str, top_k: int = 5):

    query = f"""
    SELECT
        file_name,
        content,
        VECTOR_COSINE_SIMILARITY(
            embeddings,
            AI_EMBED(
                '{EMBEDDING_MODEL}',
                ?
            )
        ) AS similarity

    FROM PROJECT_DB.PUBLIC.BASE_CONNAISSANCE_RAG

    WHERE embeddings IS NOT NULL

    ORDER BY similarity DESC

    LIMIT {int(top_k)}
    """

    return session.sql(
        query,
        params=[question]
    ).collect()


def display_retrieval_results(results):
    """
    Affiche les résultats du retrieval.
    """
    for i, row in enumerate(results, start=1):
        print(f"\n{'=' * 60}")
        print(f"Résultat {i}")
        print(f"{'=' * 60}")
        print(f"Similarité : {row['SIMILARITY']:.4f}")
        print(f"Fichier    : {row['FILE_NAME']}")
        print("\nContenu :")
        print(row["CONTENT"])


def format_results_for_rag(results):
    """
    Formate les résultats pour pouvoir les injecter
    ensuite dans le contexte du RAG.
    """
    return [
        {
            "file_name": row["FILE_NAME"],
            "content": row["CONTENT"],
            "similarity": row["SIMILARITY"],
        }
        for row in results
    ]


def display_rag_context(results):
    """
    Affiche proprement les résultats du retrieval
    tels qu'ils seront utilisés comme contexte RAG.
    """

    print("\n" + "=" * 70)
    print("CONTEXTE RAG")
    print("=" * 70)

    for i, row in enumerate(results, start=1):

        print(f"\n[Source {i}]")
        print(f"Fichier    : {row['FILE_NAME']}")
        print(f"Similarité : {row['SIMILARITY']:.4f}")
        print("-" * 70)
        print(row["CONTENT"])
        print("-" * 70)