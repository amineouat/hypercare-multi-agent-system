"""Construction du graphe LangGraph de traitement d'un ticket.

    intake -> resolve_refs -> classify -> doc_search -> data_investigation -> decide
                                                                                |
                                                          answer / clarify / escalate

Les raccourcis : un ticket hors périmètre, ou un cas de prix sans route,
va directement à decide sans lancer de recherche. La recherche de données
est sautée quand elle est inutile ou impossible (route absente).
"""
from langgraph.graph import END, START, StateGraph

from .nodes import factices
from .nodes.classify import load_examples, make_classify
from .nodes.decide import blocking_fields, decide, in_scope
from .nodes.intake import intake
from .nodes.answer import make_answer
from .nodes.clarify import make_clarify
from .nodes.escalate import make_escalate
from .nodes.data_investigation import make_data_investigation
from .nodes.doc_search import make_doc_search
from .nodes.resolve_refs import make_resolve_refs, resolve_refs_noop
from .state import State


def after_classify(state: State) -> str:
    if not in_scope(state):
        return "decide"
    if state.get("price_case", False) and blocking_fields(state):
        return "decide"
    return "doc_search"


def after_doc_search(state: State) -> str:
    if "data" in state.get("needs", []) and not blocking_fields(state):
        return "data_investigation"
    return "decide"


def after_decide(state: State) -> str:
    return state["decision"]


def build_graph(llm=None, session=None, checkpointer=None, verification="strict"):
    """Construit le graphe.

    Sans `llm` : tous les agents sont factices (tests de routage).
    Avec `llm` et `session` : tous les nœuds sont réels.
    verification : "strict" ou "souple", niveau d'exigence de la vérification
    des passages documentaires (voir tools/retrieval.py).
    """
    if llm is not None:
        model_name = getattr(llm, "model_name", "LLM")
    
        classify = make_classify(
            llm,
            load_examples(session),
            model_name
        )
    
        doc_search = make_doc_search(
            session=session,
            llm=llm,
            mode=verification,
        )

        data_investigation = make_data_investigation(session)
        resolve_refs = make_resolve_refs(session)
        answer = make_answer(llm)
        clarify = make_clarify(llm)
        escalate = make_escalate(llm)
    
    else:
        classify = factices.classify
        doc_search = factices.doc_search
        data_investigation = factices.data_investigation
        resolve_refs = resolve_refs_noop
        answer = factices.answer
        clarify = factices.clarify
        escalate = factices.escalate

    g = StateGraph(State)

    g.add_node("intake", intake)
    g.add_node("resolve_refs", resolve_refs)
    g.add_node("classify", classify)
    g.add_node("doc_search", doc_search)
    g.add_node("data_investigation", data_investigation)
    g.add_node("decide", decide)
    g.add_node("answer", answer)
    g.add_node("clarify", clarify)
    g.add_node("escalate", escalate)

    g.add_edge(START, "intake")
    g.add_edge("intake", "resolve_refs")
    g.add_edge("resolve_refs", "classify")
    g.add_conditional_edges("classify", after_classify,
                            {"doc_search": "doc_search", "decide": "decide"})
    g.add_conditional_edges("doc_search", after_doc_search,
                            {"data_investigation": "data_investigation", "decide": "decide"})
    g.add_edge("data_investigation", "decide")
    g.add_conditional_edges("decide", after_decide,
                            {"repondre": "answer", "preciser": "clarify", "escalader": "escalate"})
    for node in ("answer", "clarify", "escalate"):
        g.add_edge(node, END)

    return g.compile(checkpointer=checkpointer)
