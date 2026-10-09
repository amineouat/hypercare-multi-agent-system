# Hypercare AQUA / SpotOn — Assistant multi-agents

Prototype d'aide au support **Hypercare** pour les applications de tarification **AQUA** et **SpotOn**. À partir d'un ticket, le système recherche des informations documentaires et opérationnelles, puis propose une **réponse**, une **demande de précision** ou une **escalade**.

**Technologies :** Python, LangGraph, Snowflake / Snowpark, Snowflake Cortex (embeddings), LLM et RAG.

## Structure du projet

```text
.
├── src/
│   ├── graph.py                  # Orchestration LangGraph et routage
│   ├── state.py                  # État partagé entre les agents
│   ├── trace.py                  # Traçabilité des étapes
│   ├── llm.py                    # Configuration du LLM
│   ├── nodes/                    # Agents et nœuds du graphe
│   ├── tools/                    # Recherche documentaire et requêtes métier
│   ├── workflows/                # Détection de tickets similaires, réparation KB
│   └── evaluation.py             # Évaluation du système
├── notebooks/
│   ├── 12_demonstration.ipynb    # Démonstration à ouvrir en priorité
│   ├── 09_workflow_automatique.ipynb
│   ├── 10_kb_repair.ipynb
│   ├── 11_evaluation.ipynb
│   └── ...                       # Préparation des données et développement
├── tests/
│   ├── scenarios.json            # Scénarios de test
│   └── check_data_investigation.py
├── docs/
│   └── contrats_outils.md        # Interfaces des outils
└── utils.py
```

## Principaux agents

| Nœud (`src/nodes/`) | Rôle |
|---|---|
| `intake` | Lit le ticket et identifie les champs manquants. |
| `resolve_refs` | Recherche les références de devis/réservation et complète le contexte. |
| `classify` | Classe le problème, identifie l'équipe et les recherches nécessaires. |
| `doc_search` | Recherche dans la base documentaire RAG et fait vérifier les passages par le LLM. |
| `data_investigation` | Interroge les données Snowflake : lignes de prix, devis, réservations et références métier. |
| `decide` | Applique des règles explicites pour choisir l'issue, sans laisser la décision au LLM. |
| `answer` / `clarify` / `escalate` | Rédige la réponse étayée, la demande de précision ou le dossier d'escalade. |

**Parcours type :** `intake → resolve_refs → classify → doc_search → data_investigation → decide → answer / clarify / escalate`. Des raccourcis évitent certaines recherches lorsqu'elles ne sont pas nécessaires. Chaque étape alimente une **trace observable**.

## Deux fonctionnalités complémentaires

- **Workflow automatique** — `src/workflows/similar_tickets.py` : rapproche les tickets par similarité sémantique et signale les groupes susceptibles de révéler un incident collectif. Démonstration : `notebooks/09_workflow_automatique.ipynb`.
- **Réparation de la base de connaissances** — `src/workflows/kb_repair.py` : détecte une lacune documentaire, génère une proposition, demande une validation humaine, puis permet sa publication et son *rollback*. Démonstration : `notebooks/10_kb_repair.ipynb`.

## Parcours conseillé 

1. **`notebooks/12_demonstration.ipynb`** : quatre situations principales, décisions et traces détaillées.
2. **`src/graph.py`** : architecture et enchaînement des agents.
3. **`src/nodes/`** et **`src/tools/`** : logique des agents et accès aux sources.
4. **`notebooks/09_workflow_automatique.ipynb`**, **`10_kb_repair.ipynb`** et **`11_evaluation.ipynb`** : extensions et évaluation.
