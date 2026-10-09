# Contrats des outils

Proposition à valider en équipe. Statut : brouillon.

## À quoi sert ce document

L'orchestrateur appelle deux outils : la recherche documentaire et la recherche de lignes de prix. Ce document fixe, pour chacun, ce qu'il reçoit et ce qu'il renvoie. Tant que ce format est respecté, chacun peut modifier son code sans casser celui des autres.

Les deux outils suivent trois règles communes :

- Ils renvoient un dictionnaire Python simple (textes, nombres, booléens, listes).
- Quand ils ne trouvent rien, ils renvoient un résultat vide, jamais une erreur.
- Ils ne lisent jamais la table `EVAL_TICKETS`.

## Outil 1 : recherche documentaire

Fichier : `src/tools/retrieval.py`

```python
search_docs(session, question, top_k=5, application=None, as_of=None) -> dict
```

### Entrées

| Paramètre | Type | Rôle |
|---|---|---|
| `session` | session Snowflake | connexion active |
| `question` | texte | la description du ticket |
| `top_k` | entier | nombre maximal de passages |
| `application` | texte ou vide | filtre facultatif : `AQUA Spot` ou `SpotOn` |
| `as_of` | date ou vide | filtre facultatif : ne garder que les documents valables à cette date |

### Sortie

```python
{
    "passages": [
        {
            "source_id": "KB-SPT-012",        # identifiant unique de la source
            "source_type": "faq",             # "faq" ou "document"
            "title": "KB-SPT-012",            # nom lisible, à citer dans la réponse
            "content": "If the EFS/BAF09 amount is wrong...",
            "score": 0.83,                    # similarité, entre 0 et 1
            "application": "AQUA Spot",       # ou None si inconnu
            "doc_date": None,                 # date du document, ou None
            "version": None,                  # ex. "V12", ou None
        },
    ],
    "reliable": True,       # au moins un passage atteint le seuil
    "threshold": 0.0,       # seuil utilisé (voir plus bas)
}
```

Les passages sont triés du meilleur score au moins bon. Si rien n'est trouvé : `passages` est une liste vide et `reliable` vaut `False`.

### Ce que la recherche doit couvrir

- Les documents du stage `FILES` : PDF, PPTX, DOCX, images, transcriptions des vidéos.
- Les 493 fiches de la table `KB_QA`, à raison d'une fiche par passage, avec `source_id` égal à l'identifiant de la fiche.

Les fichiers Excel ne passent pas par cette recherche (voir « Tables partagées »).

### Le seuil de fiabilité

`reliable` décide si l'orchestrateur peut répondre ou doit escalader. Le seuil ne doit donc pas être choisi au hasard. Proposition : le régler sur `KB_QA`, en regardant à partir de quel score le premier passage retrouvé est le bon. La valeur retenue et la méthode sont à noter ici.

### Écart avec l'existant

| Aujourd'hui (`utils.retrieve_chunks`) | Attendu |
|---|---|
| Renvoie `FILE_NAME`, `CONTENT`, `SIMILARITY` | Renvoie le dictionnaire ci-dessus |
| Renvoie toujours `top_k` passages | Indique en plus `reliable` |
| Ne cherche que dans `BASE_CONNAISSANCE_RAG` | Cherche aussi dans `KB_QA` |
| Aucune métadonnée | `application`, `doc_date`, `version` quand ils sont connus |
| Fichiers Excel découpés et tronqués | Fichiers Excel exclus |
| `utils.py` à la racine | Fonction dans `src/tools/retrieval.py` |

### Tests d'acceptation

1. Une question présente dans `KB_QA` renvoie sa propre fiche en premier passage.
2. Une phrase sans rapport avec le projet renvoie `reliable = False`.
3. Aucun passage ne provient d'un fichier Excel.
4. Aucun `source_id` n'appartient à `EVAL_TICKETS`.

## Outil 2 : recherche de lignes de prix

Fichier : `src/tools/pricelines.py`

```python
find_pricelines(session, pol, pod, on_date,
                container_type=None, line_reference=None) -> dict
```

### Entrées

| Paramètre | Type | Rôle |
|---|---|---|
| `pol`, `pod` | texte | ports de chargement et de déchargement, ex. `MXVER`, `ESSCT` |
| `on_date` | date | la ligne doit être valide ce jour-là |
| `container_type` | texte ou vide | `ST` (dry) ou `RF` (reefer) |
| `line_reference` | texte ou vide | référence de ligne, ex. `2378-134` |

### Sortie

```python
{
    "lines": [
        {
            "detail_uid": 360146852,
            "line_sequence": "2378-134",
            "pricelist_name": "11577-SPOT-EUROPE_LATAM/...",
            "pricing_group_name": "MIA-ATLANTIC COAST TO EUROPE-ALL",
            "pol_code": "MXVER", "pod_code": "ESSCT",
            "pricelist_line_type": "ST", "commodity_code": "FAK",
            "valid_from": "2026-04-01", "valid_to": "2026-05-15",
            "charge_origin": "CTB",            # CTB, CTM ou Manual
            "rate_structure": "INCLUDED",      # INCLUDED ou ADDITIONAL
            "rate_20ST": None, "rate_40ST": None,
            "rate_40HC": None, "rate_45HC": None,
            "applicable": "Y", "fixed": "N",
            "last_modification_date": "2026-03-11 21:17:53",
        },
    ],
    "nb_candidates": 1,
    "evidence": True,
    "finding": "La ligne 2378-134 existe en deux versions : ...",
}
```

### Définitions

- **`nb_candidates`** : nombre de lignes de prix distinctes, c'est-à-dire de `detail_uid` différents. Une ligne qui existe en version système et en version manuelle compte pour une seule candidate.
- **`evidence`** : vrai seulement si les données contiennent un fait vérifiable qui explique le cas. Une seule règle pour l'instant : le même `detail_uid` existe en version système (`CTB` ou `CTM`) et en version `Manual`, avec une structure ou un montant différents. Cette valeur est calculée par du code, jamais devinée par un LLM.
- **`finding`** : une phrase factuelle construite par du code à partir des lignes trouvées. Elle décrit, elle n'interprète pas.

Si rien n'est trouvé : `lines` vide, `nb_candidates = 0`, `evidence = False`.

### Table source

`PROJECT_DB.PUBLIC.PRICELINES_BAF09`, chargée depuis `stage_1/Extraction BAF09.xlsx` :

- 459 lignes en double exact à supprimer ;
- clé : `(detail_uid, charge_origin)`, car `detail_uid` seul n'est pas unique ;
- `last_modification_date` à convertir en horodatage.

### Tests d'acceptation

Ces trois cas existent dans l'extraction BAF09.

| Appel | Résultat attendu |
|---|---|
| `MXVER`, `ESSCT`, 2026-04-10, `ST` | 1 candidate (`detail_uid` 360146852), 2 versions, `evidence = True` |
| `BDCGP`, `MAAGA`, 2026-03-18, `ST` | 1 candidate (`detail_uid` 359468845), 1 version, `evidence = False` |
| `AEJEA`, `AUADL`, 2026-03-20, sans type | 2 candidates (lignes `24804-2` en ST et `24333-4` en RF) |

Un quatrième test : une route inexistante renvoie le résultat vide, sans erreur.

## Tables partagées

| Table | Contenu | Qui la lit |
|---|---|---|
| `KB_QA` | 493 fiches utilisables | recherche documentaire, exemples de classification |
| `EVAL_TICKETS` | 100 fiches réservées | évaluation finale uniquement |
| `BASE_CONNAISSANCE_RAG` | passages des documents | recherche documentaire |
| `PRICELINES_BAF09` | lignes de prix | recherche de lignes de prix |
| `REF_CAR_CHARGES`, `REF_GOL_SERVICES` | référentiels | à charger en tables, pas en passages |

## Ce que l'orchestrateur fait de ces résultats

| Résultat | Champ de l'état | Utilisé par |
|---|---|---|
| `passages` | `docs` | rédaction de la réponse et de l'escalade |
| `reliable` | `docs_reliable` | règles de décision |
| `lines`, `nb_candidates`, `evidence`, `finding` | `data` | règles de décision et rédaction |

## Points à trancher

1. Qui écrit `find_pricelines` et charge `PRICELINES_BAF09` ?
2. Pour indexer `KB_QA`, on encode la question seule ou la question avec sa réponse ?
3. Quelle valeur pour le seuil de fiabilité, et sur quelle mesure ?
4. Comment renseigner `application`, `doc_date` et `version` pour chaque document ?
5. Questions pour le prof : que signifient `CTB` et `CTM`, et laquelle des deux versions d'une ligne s'applique ?
