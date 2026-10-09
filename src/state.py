"""État partagé du graphe : l'objet qui circule entre les nœuds.

Chaque nœud reçoit l'état complet et renvoie seulement les champs qu'il
modifie. Le champ `trace` est cumulatif : chaque nœud y ajoute une entrée.
"""
import operator
from typing import Annotated, Literal, TypedDict


class Ticket(TypedDict, total=False):
    """Champs du formulaire EUP (Hypercare Form AQUA)."""
    ticket_id: str
    received_at: str        # date de réception, format ISO
    email: str
    pricelist_number: str   # ex. "11577"
    pricing_group: str
    time_of_issue: str
    description: str
    pol: str                # port de chargement, ex. "MXVER"
    pod: str                # port de déchargement, ex. "ESSCT"
    container_type: str     # "ST" (dry) ou "RF" (reefer), peut être vide
    line_reference: str     # ex. "2378-134"
    quote_id: str           # ex. "QSPOT-A1", peut être vide
    booking_id: str         # ex. "BKG-001", peut être vide


Decision = Literal["repondre", "preciser", "escalader"]


class State(TypedDict, total=False):
    # Entrée
    ticket: Ticket
    fixtures: dict          # réponses des agents factices (étape 5 uniquement)

    # Lecture du ticket
    missing_fields: list[str]

    # Références du ticket (devis, réservation)
    quote_found: bool       # le devis cité existe dans la table QUOTES
    reference_date: str     # date du devis : sert à chercher les lignes de prix

    # Classification
    theme: str              # Pricing, Routing, Charges Management...
    in_scope: bool
    team: str               # équipe destinataire en cas d'escalade
    needs: list[str]        # "docs" et/ou "data"
    price_case: bool        # le ticket demande d'expliquer un prix ou une charge

    # Recherche documentaire
    docs: list[dict]        # passages : source, extrait, score
    docs_reliable: bool

    # Investigation des données
    data: dict              # lines, nb_candidates, evidence, finding

    # Décision
    decision: Decision
    decision_rule: str      # nom de la règle appliquée
    decision_reason: str
    kb_gap: bool            # lacune documentaire à signaler (partie E)

    # Sortie
    answer: str

    # Trace observable
    trace: Annotated[list[dict], operator.add]


TEST = "ok"  # utilisé par notebooks/00_verification.ipynb
