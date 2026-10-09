"""Recherche documentaire : documents du stage et fiches de la FAQ.

Trois modes :
- "dense"  : similarité entre l'embedding de la question et ceux des passages
             (principe d'origine de utils.retrieve_chunks) ;
- "bm25"   : recherche par mots-clés ;
- "hybrid" : fusion des deux classements.

Le résultat suit le contrat de docs/contrats_outils.md.
"""
import re
from pydantic import BaseModel, Field

EMBEDDING_MODEL = "snowflake-arctic-embed-m-v1.5"
TABLE = "PROJECT_DB.PUBLIC.BASE_CONNAISSANCE_RAG"

# Préfixe recommandé par la fiche du modèle arctic-embed pour les questions
# (jamais pour les passages). Mesuré sur nos données : sans préfixe, 35 vraies
# questions sur 60 dépassaient le meilleur score hors sujet ; avec, 59 sur 60.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

# Score de similarité minimal du meilleur passage. En dessous, on considère que
# la base n'a rien de proche. Mesuré avec le préfixe : phrases hors sujet toutes
# sous 0,38 ; trois quarts des vraies questions au-dessus de 0,49.
RELIABILITY_THRESHOLD = 0.45

SEARCH_MODE = "dense"     # mode par défaut, à changer après mesure
FUSION_DEPTH = 50         # nombre de passages pris dans chaque classement
RRF_K = 60                # constante usuelle de la fusion par rangs

STOPWORDS = {
    "a", "an", "the", "to", "of", "in", "on", "for", "is", "are", "be", "and", "or",
    "i", "we", "you", "it", "my", "our", "this", "that", "with", "not", "do", "does",
    "can", "how", "why", "what", "hi", "hello", "team", "please", "question", "answer",
}

_CORPUS = {}        # table -> liste des passages (chargée une fois)
_BM25 = {}          # table -> index BM25
_DENSE_CACHE = {}   # (table, question préfixée) -> scores de similarité


def _tokens(text: str) -> list[str]:
    """Découpe en mots simples, en gardant les codes comme baf09 ou qspot7432636."""
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS]


def _load_corpus(session, refresh: bool = False) -> list[dict]:
    if refresh or TABLE not in _CORPUS:
        rows = session.sql(
            f"SELECT FILE_NAME, SOURCE_TYPE, CONTENT FROM {TABLE} WHERE EMBEDDINGS IS NOT NULL"
        ).collect()
        _CORPUS[TABLE] = [
            {"source_id": r["FILE_NAME"], "source_type": r["SOURCE_TYPE"], "content": r["CONTENT"]}
            for r in rows
        ]
        _BM25.pop(TABLE, None)
        _DENSE_CACHE.clear()
    return _CORPUS[TABLE]


def _bm25_index(corpus: list[dict]):
    if TABLE not in _BM25:
        try:
            from rank_bm25 import BM25Okapi
        except ImportError as e:
            raise ImportError("Installe le paquet rank_bm25 : !pip install rank_bm25") from e
        _BM25[TABLE] = BM25Okapi([_tokens(p["content"]) for p in corpus])
    return _BM25[TABLE]


def _dense_scores(session, question: str, query_prefix: str) -> dict:
    """Similarité de la question avec tous les passages : une seule requête."""
    key = (TABLE, query_prefix + question)
    if key not in _DENSE_CACHE:
        rows = session.sql(f"""
            SELECT
                FILE_NAME,
                VECTOR_COSINE_SIMILARITY(EMBEDDINGS, AI_EMBED('{EMBEDDING_MODEL}', ?)) AS SCORE
            FROM {TABLE}
            WHERE EMBEDDINGS IS NOT NULL
        """, params=[query_prefix + question]).collect()
        _DENSE_CACHE[key] = {r["FILE_NAME"]: float(r["SCORE"]) for r in rows}
    return _DENSE_CACHE[key]


def _ranking(scores: dict, allowed: set) -> list[str]:
    """Identifiants autorisés, du meilleur score au moins bon. Les scores nuls sont écartés."""
    items = [(sid, s) for sid, s in scores.items() if sid in allowed and s > 0]
    return [sid for sid, _ in sorted(items, key=lambda x: (-x[1], x[0]))]


def _title(source_id: str, source_type: str) -> str:
    """Nom lisible : identifiant de fiche, ou nom du fichier sans dossier ni numéro de passage."""
    if source_type == "faq":
        return source_id
    return source_id.split("#")[0].split("/")[-1]


def search_docs(session, question, top_k=5, source_type=None, exclude_ids=None,
                threshold=RELIABILITY_THRESHOLD, query_prefix=QUERY_PREFIX,
                mode=SEARCH_MODE, refresh=False) -> dict:
    """Renvoie les passages les plus pertinents pour la question.

    source_type : "faq" ou "document" pour limiter la recherche, None pour tout.
    exclude_ids : identifiants à ignorer (sert aux mesures, pas en production).
    mode        : "dense", "bm25" ou "hybrid".
    refresh     : True pour recharger les passages après une modification de la table.
    """
    if mode not in ("dense", "bm25", "hybrid"):
        raise ValueError(f"Mode inconnu : {mode}")

    corpus = _load_corpus(session, refresh)
    by_id = {p["source_id"]: p for p in corpus}
    excluded = set(exclude_ids or [])
    allowed = {
        p["source_id"] for p in corpus
        if p["source_id"] not in excluded and (source_type is None or p["source_type"] == source_type)
    }

    # La similarité est toujours calculée : elle sert au seuil, quel que soit le mode.
    dense = _dense_scores(session, question, query_prefix)
    dense_rank = _ranking(dense, allowed)

    bm25_rank = []
    if mode in ("bm25", "hybrid"):
        scores = _bm25_index(corpus).get_scores(_tokens(question))
        bm25 = {p["source_id"]: float(s) for p, s in zip(corpus, scores)}
        bm25_rank = _ranking(bm25, allowed)

    if mode == "dense":
        ordered = dense_rank
    elif mode == "bm25":
        ordered = bm25_rank
    else:
        # Fusion par rangs : un passage bien classé dans les deux listes passe devant.
        fused = {}
        for ranking in (dense_rank[:FUSION_DEPTH], bm25_rank[:FUSION_DEPTH]):
            for rank, sid in enumerate(ranking, start=1):
                fused[sid] = fused.get(sid, 0.0) + 1.0 / (RRF_K + rank)
        ordered = [sid for sid, _ in sorted(fused.items(), key=lambda x: (-x[1], x[0]))]

    passages = [
        {
            "source_id": sid,
            "source_type": by_id[sid]["source_type"],
            "title": _title(sid, by_id[sid]["source_type"]),
            "content": by_id[sid]["content"],
            "score": round(dense.get(sid, 0.0), 4),   # similarité, quel que soit le mode
            "application": None,
            "doc_date": None,
            "version": None,
        }
        for sid in ordered[:int(top_k)]
    ]
    best_similarity = dense[dense_rank[0]] if dense_rank else 0.0
    reliable = threshold is not None and best_similarity >= threshold
    return {"passages": passages, "reliable": reliable, "threshold": threshold, "mode": mode}


# Vérification par le LLM (étape 7.2b)
#
# Deux modes, pour pouvoir mesurer le compromis entre réponses et escalades :
# - "strict" : le LLM se prononce passage par passage sur deux critères, et un
#   passage n'est retenu que s'il remplit les deux ;
# - "souple" : le LLM rend un seul avis global sur l'ensemble des passages
#   (première version de la vérification).
# Répétition sur 40 tickets à fiche cachée : en souple, 16 réponses dont 5
# jugées incorrectes ; en strict, 4 réponses dont 2 jugées incorrectes.

VERIFICATION_MODE = "strict"


class PassageCheck(BaseModel):
    source_id: str = Field(description="Identifiant du passage examiné.")
    same_problem: bool = Field(
        description="True si le passage traite la même situation que le ticket : "
                    "même symptôme ET même objet (même fonction, même outil, même charge). "
                    "False s'il porte sur une situation voisine ou seulement sur le même thème.")
    answers_question: bool = Field(
        description="True si le passage contient la cause ou l'action qui répond précisément "
                    "à ce que le ticket demande. False s'il ne donne que des généralités.")


class RelevanceVerification(BaseModel):
    checks: list[PassageCheck] = Field(description="Un avis par passage fourni.")
    reason: str = Field(description="Justification courte, fondée uniquement sur les passages.")


class GlobalVerification(BaseModel):
    relevant: bool = Field(
        description="True si au moins un passage répond réellement au problème posé.")
    source_ids: list[str] = Field(
        default_factory=list,
        description="Identifiants des passages réellement pertinents.")
    reason: str = Field(description="Justification courte fondée uniquement sur les passages.")


def _passages_text(candidates: list[dict]) -> str:
    return "\n\n".join(
        f"SOURCE_ID: {p['source_id']}\nTITLE: {p['title']}\nCONTENT:\n{p['content']}"
        for p in candidates
    )


def _verify_strict(llm, question: str, candidates: list[dict]) -> dict:
    prompt = f"""
Tu vérifies les résultats d'une recherche documentaire pour une équipe Hypercare.

TICKET :
{question}

PASSAGES RETROUVÉS :
{_passages_text(candidates)}

Pour CHAQUE passage, réponds à deux questions séparées.

1. same_problem : le passage traite-t-il la même situation que le ticket ?
   Il faut le même symptôme ET le même objet. Un passage sur une situation
   voisine, ou seulement sur le même thème, ne suffit pas. Quand le passage
   est une fiche « Question / Answer », compare la question de la fiche à
   celle du ticket : elles doivent décrire le même cas.

2. answers_question : le passage contient-il la cause ou l'action qui répond
   précisément à ce que le ticket demande ? Si le ticket pose une question
   précise (est-ce la bonne approche ? quelle est la nouvelle adresse ?
   pourquoi ce cas-là ?), le passage doit contenir cette réponse précise.

Règles :
- N'utilise aucune connaissance extérieure aux passages fournis.
- N'invente aucune règle métier.
- En cas de doute sur l'un des deux critères, réponds false.
- Donne un avis pour chaque SOURCE_ID fourni, sans en ajouter.
- reason : une justification courte.
"""
    result = llm.with_structured_output(RelevanceVerification).invoke(prompt)
    known = {p["source_id"] for p in candidates}
    source_ids = [c.source_id for c in result.checks
                  if c.same_problem and c.answers_question and c.source_id in known]
    return {"relevant": bool(source_ids), "source_ids": source_ids, "reason": result.reason}


def _verify_souple(llm, question: str, candidates: list[dict]) -> dict:
    prompt = f"""
Tu vérifies les résultats d'une recherche documentaire pour une équipe Hypercare.

QUESTION UTILISATEUR :
{question}

PASSAGES RETROUVÉS :
{_passages_text(candidates)}

Ta tâche est uniquement de déterminer si au moins un passage contient
une information qui répond réellement au problème posé.

Règles :
- Un passage qui parle seulement du même thème ou contient les mêmes mots
  n'est pas suffisant.
- N'utilise aucune connaissance extérieure aux passages fournis.
- N'invente aucune règle métier.
- En cas de doute, réponds relevant = false.
- source_ids doit contenir uniquement les identifiants des passages
  qui répondent réellement à la question.
- reason doit être une justification courte.
"""
    result = llm.with_structured_output(GlobalVerification).invoke(prompt)
    return result.model_dump()


def verify_passages(llm, question: str, passages: list[dict], threshold: float,
                    mode: str = VERIFICATION_MODE):
    """Vérifie qu'au moins un passage suffisamment similaire répond au problème du ticket.

    Renvoie {"relevant", "source_ids", "reason"}. Voir les deux modes plus haut.
    """
    if mode not in ("strict", "souple"):
        raise ValueError(f"Mode de vérification inconnu : {mode}")

    candidates = [p for p in passages if p["score"] >= threshold]
    if not candidates:
        return {
            "relevant": False,
            "source_ids": [],
            "reason": "Aucun passage ne dépasse le seuil de similarité."
        }
    if mode == "souple":
        return _verify_souple(llm, question, candidates)
    return _verify_strict(llm, question, candidates)
