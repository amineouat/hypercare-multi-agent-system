"""Classification réelle d'un ticket par le LLM.

Remplace le nœud factice `classify`. Le LLM lit le ticket et renvoie une
sortie structurée : thème, périmètre, équipe et besoin de données.
Les exemples donnés au LLM viennent de la table KB_QA, jamais de
EVAL_TICKETS.
"""
from typing import Literal

from pydantic import BaseModel, Field

from ..trace import entry

KB_TABLE = "PROJECT_DB.PUBLIC.KB_QA"

# Noms : colonne Theme du fichier de questions-réponses.
# Descriptions : déduites des questions de KB_QA de chaque thème. À faire valider.
THEMES = {
    "Pricing": "création et mise à jour des pricelines et des tarifs dans AQUA Spot, "
               "erreur de l'outil sur une priceline, tarif absent sur SpotOn",
    "Routing": "offre absente sur SpotOn à cause du service ou du routing, i-Route, Routing Finder",
    "Charges Management": "charges et surcharges (BAF09, EFS, CAR, FRT...) : montant, "
                          "structure incluse ou additionnelle, charge manquante",
    "Setup / Configuration": "paramétrage : ports, marchandises, FMC, pré et post-acheminement, équipements",
    "Booking / Operations": "création d'un devis (QSPOT), réservation impossible, freighting d'un booking",
    "Change Request": "demande d'évolution de l'outil, question sur une prochaine version",
    "PG Admin": "TTB d'un pricing group : paire de ports absente, TTB manquant ou non récupéré",
    "DDSM": "free time, detention, demurrage",
    "VAS": "codes et services VAS",
}

# Noms : colonne Team du fichier de questions-réponses.
# Descriptions : guide Hypercare quand il en parle, sinon déduites des
# questions de KB_QA traitées par chaque équipe. À faire valider.
TEAMS = {
    "AQUA support": "questions fonctionnelles sur l'utilisation d'AQUA Spot : pricelines, routing, pricing group",
    "Pricing": "gestion des prix et des charges, tariff book, paires de ports d'une pricelist",
    "IT Support": "incident technique : erreur, blocage, lenteur, comportement anormal de l'outil",
    "Cargo Flow": "routing absent ou incorrect dans les instructions de routing",
    "DDSM": "allocation, offre affichée Sold Out",
    "AQUA Contract": "toute demande qui relève d'AQUA Contract",
    "Web Support": "problème technique sur le site SpotOn",
    "E-commerce": "paramétrage de l'affichage en ligne : recherche SpotOn, XBO, offres non affichées",
    "Product Team": "demande d'évolution du produit",
    "Hypercare": "devis ou réservation bloqués sans cause identifiée",
    "Intermodal": "free time, demurrage, detention",
}


class Classification(BaseModel):
    """Classement d'un ticket de support AQUA Spot / SpotOn."""
    theme: Literal[
        "Pricing", "Routing", "Charges Management", "Setup / Configuration",
        "Booking / Operations", "Change Request", "PG Admin", "DDSM", "VAS",
    ] = Field(description="Thème principal du ticket")
    in_scope: bool = Field(
        description="True si la demande concerne AQUA Spot ou SpotOn, "
                    "False si elle relève d'AQUA Contract ou d'un autre outil")
    team: Literal[
        "AQUA support", "Pricing", "IT Support", "Cargo Flow", "DDSM", "AQUA Contract",
        "Web Support", "E-commerce", "Product Team", "Hypercare", "Intermodal",
    ] = Field(description="Équipe à qui transmettre le ticket en cas d'escalade")
    needs_data: bool = Field(
        description="True si consulter les données du cas (ligne de prix, devis, réservation) "
                    "peut aider à répondre. False si la documentation suffit")
    price_case: bool = Field(
        description="True si le ticket demande d'expliquer ou de vérifier un prix, un tarif, "
                    "un montant ou une charge affichés. False dans tous les autres cas")


def load_examples(session, per_group: int = 4, table: str = KB_TABLE) -> list[dict]:
    """Prend quelques exemples par (thème, statut) dans KB_QA, toujours les mêmes."""
    rows = session.sql(f"""
        SELECT ID, QUESTION, THEME, STATUS, TEAM_NAME
        FROM {table}
        QUALIFY ROW_NUMBER() OVER (PARTITION BY THEME, STATUS ORDER BY ID) <= {int(per_group)}
        ORDER BY THEME, STATUS, ID
    """).collect()
    return [
        {"id": r["ID"], "question": r["QUESTION"], "theme": r["THEME"],
         "in_scope": r["STATUS"] != "Out of Scope", "team": r["TEAM_NAME"]}
        for r in rows
    ]


def build_prompt(examples: list[dict]) -> str:
    lines = [
        "Tu classes des tickets de support pour l'équipe Hypercare d'une compagnie maritime.",
        "Deux applications sont concernées : AQUA Spot (préparation des prix par les Pricers)",
        "et SpotOn (vente en ligne : offre, devis, réservation).",
        "",
        "Thèmes :",
    ]
    lines += [f"- {name} : {desc}" for name, desc in THEMES.items()]
    lines += [
        "Quand une offre ou un tarif est absent pour un corridor : choisis Routing si le ticket",
        "évoque un service, un routing ou i-Route, sinon Pricing.",
        "",
        "Périmètre : tout ce qui touche aux offres spot est dans le périmètre, y compris les",
        "outils liés (i-Route, Routing Finder, XBO, LARA). Une demande est hors périmètre",
        "seulement si elle relève d'AQUA Contract : contrats, tarifs contractuels, facturation.",
        "",
        "Équipes :",
    ]
    lines += [f"- {name} : {role}" for name, role in TEAMS.items()]
    lines += [
        "",
        "Besoin de données : vrai si consulter les données du cas (ligne de prix, devis,",
        "réservation) peut aider à répondre. Faux si la question porte sur une manipulation,",
        "une règle ou un comportement général de l'outil, même quand une route est citée.",
        "",
        "Cas de prix : vrai seulement si le ticket demande d'expliquer ou de vérifier un prix,",
        "un tarif, un montant ou une charge affichés (écart avec ce qui était attendu, montant",
        "jugé faux). C'est vrai même si le ticket ne donne aucune référence. Faux pour une",
        "offre absente, une erreur de l'outil, une manipulation ou une question générale.",
        "",
        "Exemples déjà classés :",
    ]
    for ex in examples:
        scope = "dans le périmètre" if ex["in_scope"] else "hors périmètre"
        team = f" | équipe : {ex['team']}" if ex["team"] in TEAMS else ""
        lines.append(f"- « {ex['question'][:300]} » -> thème : {ex['theme']} | {scope}{team}")
    return "\n".join(lines)


def format_ticket(ticket: dict) -> str:
    """Seule la description est envoyée au LLM.

    Les autres champs du formulaire (route, pricelist...) sont toujours remplis,
    même pour une question générale : les montrer pousse le LLM à croire que
    tout ticket porte sur un cas précis.
    """
    return f"Description du ticket : {ticket.get('description', '')}"


def make_classify(llm, examples: list[dict], model_name: str = "LLM"):
    """Fabrique le nœud classify à partir d'un LLM et d'exemples."""
    structured_llm = llm.with_structured_output(Classification)
    system_prompt = build_prompt(examples)

    def classify(state: dict) -> dict:
        ticket = state.get("ticket", {})
        result = structured_llm.invoke([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": format_ticket(ticket)},
        ])
        # un cas de prix exige toujours une vérification dans les données
        needs = ["docs", "data"] if (result.needs_data or result.price_case) else ["docs"]
        return {
            "theme": result.theme,
            "in_scope": result.in_scope,
            "team": result.team,
            "needs": needs,
            "price_case": result.price_case,
            "trace": [entry(
                "classify", "orchestrateur",
                tools=[f"{model_name} (sortie structurée)"],
                consulted=[f"{len(examples)} exemples de KB_QA"],
                decision=f"thème = {result.theme}, dans le périmètre = {result.in_scope}, "
                         f"cas de prix = {result.price_case}",
                result=f"équipe : {result.team} ; besoins : " + ", ".join(needs),
            )],
        }

    return classify
