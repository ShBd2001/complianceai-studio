import json

d = json.load(open("rapport_validation.json", encoding="utf-8"))
cibles = {"37", "44-49", "22"}

for doc in d["documents"]:
    for v in doc["verdicts"]:
        if v["article"] in cibles:
            print(f"--- {doc['document']}  art. {v['article']}  → {v['verdict']}")
            print(f"    justification : {v['justification'][:200]}")
            print(f"    confiance     : {v['confiance']}  revue : {v['revue_humaine_requise']}")
            if v.get("motif_revue"):
                print(f"    motif revue   : {v['motif_revue']}")
            print(f"    passages      : {v['passages_consultes']}")
            print()