"""Évaluation du prototype (étape 11).

Fait passer des tickets réels dans le graphe et mesure ce que demande
l'énoncé : réponses correctes, pertinence des escalades, qualité des sources
citées, et erreurs, avec une attention particulière aux explications de prix.

Chaque ticket vient du fichier de questions-réponses : il a une question, une
réponse de référence et un statut (« Resolved » ou « Out of Scope »).
"""
import json
import re
import time
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

# Décision attendue selon le statut réel du ticket.
EXPECTED_BY_STATUS = {"Resolved": "repondre", "Out of Scope": "escalader"}


def to_graph_ticket(row) -> dict:
    """Un ticket réel n'a que du texte : pas de devis, pas de champ de route."""
    return {
        "ticket_id": row["ID"],
        "received_at": "", "time_of_issue": "", "email": "",
        "description": str(row["QUESTION"]),
        "pricelist_number": "", "pricing_group": "",
        "pol": "", "pod": "", "container_type": "", "line_reference": "",
        "quote_id": "", "booking_id": "",
    }


# ---------------------------------------------------------------- juge

class Judgement(BaseModel):
    """Comparaison de la réponse du système à la réponse de référence."""
    verdict: Literal["correct", "partiel", "incorrect"] = Field(
        description="correct : la solution de la référence est donnée comme réponse principale. "
                    "partiel : elle figure parmi d'autres pistes, ou n'est donnée qu'en partie. "
                    "incorrect : elle est absente ou contredite.")
    reason: str = Field(description="Justification en une phrase.")


JUDGE_PROMPT = """\
Tu évalues un système de support. On te donne un ticket, la réponse de
référence écrite par un expert, et la réponse produite par le système.

Repère d'abord la solution de la référence : la cause identifiée et l'action
recommandée. Puis cherche-la dans la réponse du système.

- correct : la réponse du système donne cette solution comme réponse
  principale. La formulation peut différer, et des précisions exactes en plus
  ne changent pas ce verdict.
- partiel : la solution de la référence figure dans la réponse, mais noyée
  parmi d'autres pistes sans être désignée comme la bonne, ou seulement en
  partie. Rien ne la contredit.
- incorrect : la solution de la référence est absente de la réponse, ou la
  réponse la contredit.

Ne juge pas le style. N'utilise aucune connaissance extérieure : la référence
fait foi.
"""


def judge_answer(llm, question: str, reference: str, answer: str) -> dict:
    result = llm.with_structured_output(Judgement).invoke([
        {"role": "system", "content": JUDGE_PROMPT},
        {"role": "user", "content": f"TICKET :\n{question}\n\nRÉPONSE DE RÉFÉRENCE :\n{reference}\n\n"
                                    f"RÉPONSE DU SYSTÈME :\n{answer}"},
    ])
    return {"verdict": result.verdict, "reason": result.reason}


# ------------------------------------------------------------- sources

def check_citations(answer: str, docs: list) -> dict:
    """Vérifie que les sources citées entre crochets ont bien été retrouvées.

    Les mentions de données ([données : ...]) ne sont pas des documents et
    sont ignorées.
    """
    known = set()
    for d in docs or []:
        for key in ("source", "source_id"):
            if d.get(key):
                known.add(str(d[key]).strip().lower())
    cited = []
    for raw in re.findall(r"\[([^\[\]]{2,120})\]", answer or ""):
        name = raw.strip().strip("*").strip()
        if name.lower().startswith(("données", "donnees", "data")):
            continue
        cited.append(name)
    unknown = [c for c in cited if c.lower() not in known]
    return {"nb_cited": len(cited), "nb_unknown": len(unknown), "unknown": unknown}


# ------------------------------------------------------------ exécution

def run_ticket(graph, llm, row) -> dict:
    """Passe un ticket dans le graphe et renvoie une ligne de résultat."""
    t0 = time.time()
    state = graph.invoke({"ticket": to_graph_ticket(row), "trace": []})
    decision = state["decision"]
    status = row["STATUS"]
    docs = state.get("docs") or []
    data = state.get("data") or {}

    verdict, verdict_reason = "", ""
    if decision == "repondre" and status == "Resolved":
        judged = judge_answer(llm, str(row["QUESTION"]), str(row["ANSWER"]), state.get("answer", ""))
        verdict, verdict_reason = judged["verdict"], judged["reason"]

    citations = check_citations(state.get("answer", ""), docs) if decision == "repondre" else \
        {"nb_cited": 0, "nb_unknown": 0, "unknown": []}

    return {
        "ID": row["ID"],
        "STATUS": status,
        "THEME": row["THEME"],
        "FREQUENCY": row["FREQUENCY"],
        "EXPECTED_DECISION": EXPECTED_BY_STATUS.get(status, ""),
        "DECISION": decision,
        "RULE": state["decision_rule"],
        "IN_SCOPE": bool(state.get("in_scope", True)),
        "PRICE_CASE": bool(state.get("price_case", False)),
        "DOCS_RELIABLE": bool(state.get("docs_reliable", False)),
        "DATA_SEARCHED": "data" in state,
        "EVIDENCE": bool(data.get("evidence", False)),
        "KB_GAP": bool(state.get("kb_gap", False)),
        "TEAM": state.get("team") or "",
        "VERDICT": verdict,
        "VERDICT_REASON": verdict_reason,
        "NB_SOURCES_CITED": citations["nb_cited"],
        "NB_SOURCES_UNKNOWN": citations["nb_unknown"],
        "SOURCES_UNKNOWN": " | ".join(citations["unknown"]),
        "SOURCES_FOUND": " | ".join(str(d.get("source")) for d in docs),
        "PATH": " > ".join(e["noeud"] for e in state["trace"]),
        "SECONDS": round(time.time() - t0, 1),
        "QUESTION": str(row["QUESTION"]),
        "REFERENCE": str(row["ANSWER"]),
        "ANSWER": state.get("answer", ""),
        "TRACE_JSON": json.dumps(state["trace"], ensure_ascii=False),
    }


def error_row(row, error: Exception) -> dict:
    """Ligne de résultat pour un ticket que le graphe n'a pas pu traiter.

    Le ticket reste dans le total : une erreur technique n'est ni une réponse
    ni une escalade, c'est un ticket non traité.
    """
    status = row["STATUS"]
    return {
        "ID": row["ID"], "STATUS": status, "THEME": row["THEME"], "FREQUENCY": row["FREQUENCY"],
        "EXPECTED_DECISION": EXPECTED_BY_STATUS.get(status, ""),
        "DECISION": "erreur", "RULE": type(error).__name__,
        "IN_SCOPE": True, "PRICE_CASE": False, "DOCS_RELIABLE": False, "DATA_SEARCHED": False,
        "EVIDENCE": False, "KB_GAP": False, "TEAM": "",
        "VERDICT": "", "VERDICT_REASON": "",
        "NB_SOURCES_CITED": 0, "NB_SOURCES_UNKNOWN": 0, "SOURCES_UNKNOWN": "", "SOURCES_FOUND": "",
        "PATH": "", "SECONDS": 0.0,
        "QUESTION": str(row["QUESTION"]), "REFERENCE": str(row["ANSWER"]),
        "ANSWER": f"ERREUR : {str(error)[:300]}", "TRACE_JSON": "[]",
    }


def load_done(session, table: str) -> pd.DataFrame:
    """Résultats déjà enregistrés, pour reprendre une exécution interrompue."""
    try:
        return session.table(table).to_pandas()
    except Exception:
        return pd.DataFrame()


def run_all(session, graph, llm, tickets: pd.DataFrame, table: str, before_ticket=None) -> pd.DataFrame:
    """Passe tous les tickets, en enregistrant chaque résultat dès qu'il est obtenu.

    Si l'exécution est interrompue, la relancer reprend là où elle s'était
    arrêtée : les tickets déjà dans la table ne sont pas refaits.
    before_ticket : fonction appelée avec l'identifiant avant chaque ticket.
    """
    done = load_done(session, table)
    done_ids = set(done["ID"]) if len(done) else set()
    todo = tickets[~tickets["ID"].isin(done_ids)]
    print(f"{len(done_ids)} ticket(s) déjà traité(s), {len(todo)} à traiter")

    database, schema, name = table.split(".")
    t0 = time.time()
    for i, (_, row) in enumerate(todo.iterrows(), start=1):
        print(f"[{i}/{len(todo)}] {row['ID']} ...", end=" ", flush=True)
        if before_ticket:
            before_ticket(row["ID"])
        try:
            result = run_ticket(graph, llm, row)
        except Exception as e:
            result = error_row(row, e)
        session.write_pandas(pd.DataFrame([result]), name, database=database, schema=schema,
                             auto_create_table=True, overwrite=False)
        if result["DECISION"] == "erreur":
            print(f"ERREUR {result['RULE']} : {result['ANSWER'][9:100]}")
            continue
        print(f"{result['DECISION']} ({result['RULE']})"
              + (f", jugé {result['VERDICT']}" if result["VERDICT"] else "")
              + f" en {result['SECONDS']:.0f} s")
    print(f"\nTerminé en {time.time() - t0:.0f} s")
    return load_done(session, table)


# --------------------------------------------------------------- mesures

def summarize(res: pd.DataFrame) -> dict:
    """Calcule les mesures demandées par l'énoncé. Renvoie des tableaux prêts à afficher."""
    n = len(res)
    resolved = res[res["STATUS"] == "Resolved"]
    out_scope = res[res["STATUS"] == "Out of Scope"]
    answered = res[res["DECISION"] == "repondre"]
    escalated = res[res["DECISION"] == "escalader"]
    answered_res = resolved[resolved["DECISION"] == "repondre"]

    def pct(a, b):
        return f"{a} / {b}" + (f" ({100 * a / b:.0f} %)" if b else "")

    correct = int((answered_res["VERDICT"] == "correct").sum())
    partial = int((answered_res["VERDICT"] == "partiel").sum())
    wrong = int((answered_res["VERDICT"] == "incorrect").sum())
    recurring = resolved[resolved["FREQUENCY"].isin(["High", "Medium"])]
    recurring_ok = int(((recurring["DECISION"] == "repondre") & (recurring["VERDICT"] == "correct")).sum())

    main = pd.DataFrame([
        ("Tickets évalués", str(n)),
        ("dont Resolved / Out of Scope", f"{len(resolved)} / {len(out_scope)}"),
        ("Tickets en erreur technique", str(int((res["DECISION"] == "erreur").sum()))),
        ("— Tickets Resolved —", ""),
        ("Réponse donnée", pct(len(answered_res), len(resolved))),
        ("  jugée correcte", pct(correct, len(resolved))),
        ("  jugée partielle", pct(partial, len(resolved))),
        ("  jugée incorrecte", pct(wrong, len(resolved))),
        ("Précision demandée", pct(int((resolved["DECISION"] == "preciser").sum()), len(resolved))),
        ("Escaladé", pct(int((resolved["DECISION"] == "escalader").sum()), len(resolved))),
        ("Questions récurrentes résolues correctement", pct(recurring_ok, len(recurring))),
        ("— Tickets Out of Scope —", ""),
        ("Escaladé (attendu)", pct(int((out_scope["DECISION"] == "escalader").sum()), len(out_scope))),
        ("  dont reconnu hors périmètre", pct(int((out_scope["RULE"] == "hors_perimetre").sum()), len(out_scope))),
        ("Réponse donnée à tort", pct(int((out_scope["DECISION"] == "repondre").sum()), len(out_scope))),
        ("— Escalades —", ""),
        ("Escalades au total", str(len(escalated))),
        ("  portant sur un ticket Out of Scope", pct(int((escalated["STATUS"] == "Out of Scope").sum()), len(escalated))),
        ("  portant sur un ticket Resolved", pct(int((escalated["STATUS"] == "Resolved").sum()), len(escalated))),
        ("— Sources citées —", ""),
        ("Réponses citant au moins une source", pct(int((answered["NB_SOURCES_CITED"] > 0).sum()), len(answered))),
        ("Réponses citant une source non retrouvée", pct(int((answered["NB_SOURCES_UNKNOWN"] > 0).sum()), len(answered))),
        ("— Cas de prix —", ""),
        ("Tickets classés cas de prix", str(int(res["PRICE_CASE"].sum()))),
        ("  ayant reçu une réponse", str(int((res["PRICE_CASE"] & (res["DECISION"] == "repondre")).sum()))),
        ("  réponse jugée incorrecte", str(int((res["PRICE_CASE"] & (res["VERDICT"] == "incorrect")).sum()))),
    ], columns=["mesure", "valeur"])

    by_rule = res.groupby(["DECISION", "RULE", "STATUS"]).size().unstack(fill_value=0)
    by_theme = resolved.assign(
        correct=(resolved["DECISION"] == "repondre") & (resolved["VERDICT"] == "correct")
    ).groupby("THEME")["correct"].agg(["sum", "count"]).rename(columns={"sum": "résolus correctement", "count": "tickets"})
    return {"main": main, "by_rule": by_rule, "by_theme": by_theme}


def rejudge(llm, res: pd.DataFrame) -> pd.DataFrame:
    """Rejuge les réponses déjà enregistrées, sans repasser les tickets dans le graphe.

    Sert à appliquer la même grille de jugement à deux exécutions à comparer.
    """
    out = res.copy()
    mask = (out["DECISION"] == "repondre") & (out["STATUS"] == "Resolved")
    for idx in out[mask].index:
        judged = judge_answer(llm, out.at[idx, "QUESTION"], out.at[idx, "REFERENCE"], out.at[idx, "ANSWER"])
        out.at[idx, "VERDICT"] = judged["verdict"]
        out.at[idx, "VERDICT_REASON"] = judged["reason"]
    print(f"{int(mask.sum())} réponse(s) rejugée(s)")
    return out


def compare(runs: dict) -> pd.DataFrame:
    """Met côte à côte les mesures de plusieurs exécutions : {"avant": res1, "après": res2}."""
    table = None
    for name, res in runs.items():
        main = summarize(res)["main"]
        if table is None:
            table = main[["mesure"]].copy()
        table[name] = table["mesure"].map(dict(zip(main["mesure"], main["valeur"])))
    return table


PARAPHRASE_PROMPT = (
    "Rewrite this support ticket as another user would write it: same problem, different wording "
    "and sentence structure. Keep codes, port names and reference numbers unchanged. "
    "Reply with the rewritten ticket only, in English.\n\nTicket: "
)


def paraphrase_tickets(session, llm, tickets: pd.DataFrame, table: str) -> pd.DataFrame:
    """Prépare des questions récurrentes : la même question, posée avec d'autres mots.

    Les reformulations sont enregistrées dans une table la première fois, puis
    relues telles quelles, pour que la mesure soit reproductible. La question
    d'origine est gardée dans ORIGINAL_QUESTION.
    """
    saved = load_done(session, table)
    if len(saved):
        print(f"{len(saved)} reformulation(s) relue(s) dans {table}")
        return saved
    rows = []
    for _, row in tickets.iterrows():
        try:
            text = llm.invoke(PARAPHRASE_PROMPT + str(row["QUESTION"])).content.strip()
        except Exception as e:
            print(f"{row['ID']} : reformulation impossible ({type(e).__name__}), ticket écarté")
            continue
        new = row.to_dict()
        new["ORIGINAL_QUESTION"] = str(row["QUESTION"])
        new["QUESTION"] = text
        rows.append(new)
    out = pd.DataFrame(rows)
    database, schema, name = table.split(".")
    session.write_pandas(out, name, database=database, schema=schema, auto_create_table=True, overwrite=True)
    print(f"{len(out)} reformulation(s) enregistrée(s) dans {table}")
    return out
