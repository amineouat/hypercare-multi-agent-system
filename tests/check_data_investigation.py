"""Vérifie le nœud data_investigation réel sur les scénarios S2, S3 et S5."""
import os, sys, json, importlib

for p in (os.getcwd(), os.path.abspath(os.path.join(os.getcwd(), '..'))):
    if os.path.isdir(os.path.join(p, 'src')) and p not in sys.path:
        sys.path.insert(0, p)

import src.tools.pricelines, src.tools.lookup, src.nodes.data_investigation
for m in (src.tools.pricelines, src.tools.lookup, src.nodes.data_investigation):
    importlib.reload(m)
from src.nodes.data_investigation import make_data_investigation

from snowflake.snowpark.context import get_active_session
session = get_active_session()
node = make_data_investigation(session)

root = next(p for p in sys.path if os.path.isdir(os.path.join(p, 'src')))
with open(os.path.join(root, 'tests', 'scenarios.json')) as f:
    scenarios = {s['id']: s for s in json.load(f)['scenarios']}

# Valeurs attendues : contrat de find_pricelines (docs/contrats_outils.md)
expected = {
    'S2_prix_plusieurs_donnees':      {'nb_candidates': 1, 'evidence': True},
    'S3_cas_incertain':               {'nb_candidates': 1, 'evidence': False},
    'S5_plusieurs_lignes_candidates': {'nb_candidates': 2, 'evidence': False},
}

for sid, exp in expected.items():
    out = node({'ticket': scenarios[sid]['ticket']})
    data = out['data']
    ok = all(data[k] == v for k, v in exp.items())
    print(f"\n{'OK ' if ok else 'KO '} {sid}")
    print(f"  nb_candidates = {data['nb_candidates']} (attendu {exp['nb_candidates']})")
    print(f"  evidence      = {data['evidence']} (attendu {exp['evidence']})")
    print(f"  devis         = {data['quote']['quote_id'] if data['quote'] else None}")
    print(f"  réservation   = {data['booking']['booking_id'] if data['booking'] else None}")
    print(f"  lignes UPDATE = {data['baf09_update']['nb_candidates']}, changements : {data['baf09_update']['changes'] or 'aucun'}")
    print(f"  finding       : {data['finding'] or '(vide)'}")
