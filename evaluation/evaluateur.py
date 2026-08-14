"""
Moteur d'évaluation article par article.

Enchaînement, pour chaque article du référentiel :

  1. APPLICABILITÉ  — l'article concerne-t-il l'organisme ? Sinon : hors périmètre.
  2. RETRIEVAL      — sélection des passages pertinents du document.
  3. EXTRACTION     — le modèle cherche une preuve pour chaque élément attendu.
  4. VÉRIFICATION   — le code contrôle que chaque citation existe littéralement.
  5. VERDICT        — conforme UNIQUEMENT si tous les éléments bloquants sont
                      prouvés ET vérifiés. Par défaut : manquement.
  6. DÉROGATION     — si manquement et que l'article admet des dérogations,
                      passe obligatoire avant de figer le verdict.

Le modèle ne rend jamais le verdict. Il fournit des faits ; le code conclut.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from evaluation.prompts import (
    SYSTEME,
    prompt_applicabilite,
    prompt_derogation,
    prompt_extraction,
)
from evaluation.schemas import (
    DerogationRetenue,
    Preuve,
    RapportAudit,
    Verdict,
    VerdictArticle,
)
from evaluation.verificateur import LONGUEUR_MINIMALE_EXCLUSION, verifier_citation
from rag.chunking import Passage, decouper
from referentiel.articles import REFERENTIEL, ArticleRGPD

logger = logging.getLogger(__name__)

# Signature attendue du client LLM : (systeme, utilisateur) -> texte brut
ClientLLM = Callable[[str, str], str]
# Signature attendue du retriever : (requete, passages, k) -> passages classés
Retriever = Callable[[str, Sequence[Passage], int], list[Passage]]

SEUIL_REVUE_HUMAINE = 0.70

# Articles dont l'applicabilité relève d'une appréciation juridique sur laquelle
# des praticiens qualifiés divergent : « activités de base », « grande échelle »,
# « effet significatif ». Le moteur produit un verdict motivé mais ne prétend
# jamais trancher seul. C'est une limite assumée, pas un défaut à corriger.
ARTICLES_REVUE_SYSTEMATIQUE = frozenset({"37", "35", "22"})
K_PASSAGES = 5


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

def extraire_json(brut: str) -> dict:
    """Extrait un objet JSON d'une réponse de modèle, tolérant aux enrobages."""
    if not brut:
        raise ValueError("réponse vide du modèle")
    texte = brut.strip()
    texte = re.sub(r"^```(?:json)?\s*", "", texte)
    texte = re.sub(r"\s*```$", "", texte)
    try:
        return json.loads(texte)
    except json.JSONDecodeError:
        pass
    debut, fin = texte.find("{"), texte.rfind("}")
    if debut != -1 and fin > debut:
        return json.loads(texte[debut : fin + 1])
    raise ValueError(f"aucun JSON exploitable dans : {brut[:200]!r}")


def retriever_lexical(requete: str, passages: Sequence[Passage], k: int) -> list[Passage]:
    """
    Retriever de repli, sans dépendance : recouvrement lexical pondéré.

    À remplacer par le retriever pgvector en production ; la signature est
    identique, ce qui permet de comparer les deux sur le même harnais.
    """
    from evaluation.verificateur import normaliser

    termes = [t for t in normaliser(requete).split() if len(t) > 3]
    if not termes:
        return list(passages[:k])

    scores: list[tuple[float, int, Passage]] = []
    for i, p in enumerate(passages):
        corps = normaliser(p.texte + " " + p.section)
        score = sum(corps.count(t) for t in termes) / (1 + len(corps) / 800)
        scores.append((score, -i, p))

    scores.sort(key=lambda x: (x[0], x[1]), reverse=True)
    retenus = [p for s, _, p in scores if s > 0][:k]
    # Toujours renvoyer quelque chose : un article sans passage pertinent doit
    # être évalué (et conclure au manquement), pas escamoté.
    return retenus or list(passages[:k])


def _assembler(passages: Sequence[Passage]) -> str:
    return "\n\n".join(f"[{p.identifiant} · {p.section}]\n{p.texte.strip()}" for p in passages)


# ---------------------------------------------------------------------------
# Évaluateur
# ---------------------------------------------------------------------------

@dataclass
class Evaluateur:
    client: ClientLLM
    retriever: Retriever = retriever_lexical
    k_passages: int = K_PASSAGES
    corpus_reglementaire: dict[str, str] | None = None
    reessais: int = 2

    # -- appels modèle -----------------------------------------------------

    def _appeler(self, prompt: str, etape: str) -> dict:
        derniere: Exception | None = None
        for tentative in range(self.reessais + 1):
            try:
                return extraire_json(self.client(SYSTEME, prompt))
            except Exception as exc:  # noqa: BLE001 — on veut tout rattraper
                derniere = exc
                logger.warning(
                    "étape=%s tentative=%d/%d échec: %s",
                    etape, tentative + 1, self.reessais + 1, exc,
                )
        raise RuntimeError(f"étape {etape} : échec après réessais ({derniere})")

    # -- étapes ------------------------------------------------------------

    def _applicable(
        self, art: ArticleRGPD, extraits: str, document: str
    ) -> tuple[bool, str, list[str]]:
        diagnostics: list[str] = []
        try:
            reponse = self._appeler(
                prompt_applicabilite(art, extraits), f"applicabilite/{art.numero}"
            )
        except RuntimeError:
            # Défaut protecteur : en cas d'échec, l'article reste dans le périmètre.
            # Une exclusion abusive est bien plus grave qu'une évaluation superflue.
            return True, "applicabilité indéterminée — article maintenu dans le périmètre", diagnostics

        applicable = bool(reponse.get("applicable", True))
        justification = str(reponse.get("justification", ""))

        # Le modèle raisonne en deux temps ; les deux champs doivent concorder.
        # En cas de contradiction, la conclusion explicite l'emporte, et
        # l'incohérence est tracée.
        condition = reponse.get("condition_remplie")
        if condition is not None and bool(condition) != applicable:
            # Le modèle se contredit entre son constat et sa conclusion. Observé
            # sur l'art. 22 : « la décision est fondée exclusivement sur un
            # traitement automatisé » suivi de applicable=false. On retient
            # l'option protectrice : l'article reste dans le périmètre.
            diagnostics.append(
                f"applicabilité incohérente : condition_remplie={condition}, "
                f"applicable={applicable} — article maintenu dans le périmètre"
            )
            applicable = True

        if applicable:
            return True, justification, diagnostics

        # Exclure du périmètre exige une preuve, exactement comme déclarer conforme.
        # Le silence du document ne fait pas disparaître une obligation légale.
        if not art.exclusion_exige_preuve:
            return False, justification, diagnostics

        citation = reponse.get("citation") or None
        if not citation:
            diagnostics.append(
                "exclusion refusée : aucune citation ne prouve la non-applicabilité — "
                "article maintenu dans le périmètre"
            )
            return True, (
                "Exclusion demandée sans preuve textuelle. L'article est maintenu "
                "dans le périmètre : le silence d'un document ne dispense pas d'une "
                "obligation légale."
            ), diagnostics

        controle = verifier_citation(
            citation, document, longueur_minimale=LONGUEUR_MINIMALE_EXCLUSION
        )
        if not controle.valide:
            diagnostics.append(f"exclusion refusée : citation non vérifiée ({controle.motif})")
            return True, (
                "Exclusion demandée sur la base d'une citation introuvable dans le "
                "document. L'article est maintenu dans le périmètre."
            ), diagnostics

        return False, justification, diagnostics

    def _extraire_preuves(
        self, art: ArticleRGPD, extraits: str, document: str
    ) -> tuple[list[Preuve], list[str]]:
        contexte = (self.corpus_reglementaire or {}).get(art.numero, "")
        diagnostics: list[str] = []

        try:
            reponse = self._appeler(
                prompt_extraction(art, extraits, contexte), f"extraction/{art.numero}"
            )
        except RuntimeError as exc:
            diagnostics.append(f"extraction impossible : {exc}")
            return [
                Preuve(e.cle, e.intitule, None, False, bloquant=e.bloquant)
                for e in art.elements_attendus
            ], diagnostics

        par_cle = {
            str(item.get("cle", "")): item
            for item in reponse.get("elements", [])
            if isinstance(item, dict)
        }

        preuves: list[Preuve] = []
        for element in art.elements_attendus:
            item = par_cle.get(element.cle)
            if item is None:
                diagnostics.append(f"élément '{element.cle}' absent de la réponse du modèle")
                preuves.append(
                    Preuve(element.cle, element.intitule, None, False, bloquant=element.bloquant)
                )
                continue

            annonce = bool(item.get("satisfait", False))

            # Un élément peut être couvert par une phrase unique ou par plusieurs
            # passages éloignés du document : les deux formes sont acceptées.
            brutes = item.get("citations") or []
            if isinstance(brutes, str):
                brutes = [brutes]
            unique = item.get("citation")
            if unique and unique not in brutes:
                brutes = [unique, *brutes]
            citations = [c for c in brutes if isinstance(c, str) and c.strip()]

            preuve = Preuve(
                element=element.cle,
                intitule=element.intitule,
                citation=" […] ".join(citations) if citations else None,
                satisfait=annonce,
                bloquant=element.bloquant,
            )

            if annonce:
                if not citations:
                    preuve.satisfait = False
                    preuve.motif_rejet = "élément annoncé satisfait sans citation — rejeté"
                    diagnostics.append(f"{element.cle} : annoncé sans citation")
                else:
                    # Chaque citation est vérifiée séparément : une seule citation
                    # introuvable suffit à rejeter la preuve.
                    controles = [verifier_citation(c, document) for c in citations]
                    preuve.verifiee = all(c.valide for c in controles)
                    preuve.similarite = min(c.similarite for c in controles)
                    if not preuve.verifiee:
                        invalide = next(c for c in controles if not c.valide)
                        preuve.motif_rejet = invalide.motif
                        diagnostics.append(f"{element.cle} : {invalide.motif}")

            preuves.append(preuve)

        return preuves, diagnostics

    def _chercher_derogation(
        self, art: ArticleRGPD, extraits: str, document: str, manquants: list[str]
    ) -> tuple[DerogationRetenue | None, list[str]]:
        diagnostics: list[str] = []
        try:
            reponse = self._appeler(
                prompt_derogation(art, extraits, manquants), f"derogation/{art.numero}"
            )
        except RuntimeError as exc:
            diagnostics.append(f"passe dérogation impossible : {exc}")
            return None, diagnostics

        reference = reponse.get("reference") or None
        if not reference:
            return None, diagnostics

        connue = next((d for d in art.derogations if d.reference == reference), None)
        if connue is None:
            diagnostics.append(
                f"dérogation '{reference}' inconnue du référentiel — ignorée"
            )
            return None, diagnostics

        citation = reponse.get("citation") or None
        derogation = DerogationRetenue(
            reference=connue.reference,
            intitule=connue.intitule,
            citation=citation,
            justification=str(reponse.get("justification", "")),
        )

        if citation:
            controle = verifier_citation(
                citation, document, longueur_minimale=LONGUEUR_MINIMALE_EXCLUSION
            )
            derogation.verifiee = controle.valide
            if not controle.valide:
                diagnostics.append(
                    f"dérogation {reference} écartée : citation non vérifiée ({controle.motif})"
                )
                return None, diagnostics
        else:
            diagnostics.append(f"dérogation {reference} écartée : aucune citation fournie")
            return None, diagnostics

        return derogation, diagnostics

    # -- orchestration par article ----------------------------------------

    def evaluer_article(
        self, art: ArticleRGPD, passages: Sequence[Passage], document: str
    ) -> VerdictArticle:
        requete = f"{art.intitule} " + " ".join(
            i for e in art.elements_attendus for i in e.indices
        )
        k = max(self.k_passages, min(12, 3 + len(art.elements_attendus)))
        pertinents = self.retriever(requete, passages, k)

        # L'applicabilité s'apprécie sur d'autres passages que les éléments
        # probants : la condition parle de l'organisme, pas de ses procédures.
        # Interroger avec les mauvais passages produit des exclusions abusives.
        requete_condition = f"{art.intitule} {art.condition_applicabilite}"
        pertinents_condition = self.retriever(requete_condition, passages, self.k_passages)
        vus = {p.identifiant for p in pertinents}
        contexte_applicabilite = list(pertinents) + [
            p for p in pertinents_condition if p.identifiant not in vus
        ]

        extraits = _assembler(pertinents)
        extraits_applicabilite = _assembler(contexte_applicabilite)

        resultat = VerdictArticle(
            article=art.numero,
            intitule=art.intitule,
            criticite=art.criticite.value,
            verdict=Verdict.INDETERMINE,
            passages_consultes=[p.identifiant for p in pertinents],
        )

        # 1. applicabilité — l'exclusion exige une preuve vérifiée
        applicable, motif, diags_appl = self._applicable(art, extraits_applicabilite, document)
        resultat.diagnostics.extend(diags_appl)
        if not applicable:
            resultat.verdict = Verdict.HORS_PERIMETRE
            resultat.justification = motif or "condition d'applicabilité non remplie"
            resultat.confiance = 0.85
            return resultat

        # 2-4. extraction et vérification
        preuves, diagnostics = self._extraire_preuves(art, extraits, document)
        resultat.preuves = preuves
        # extend, pas d'affectation : les diagnostics d'applicabilité sont déjà là
        resultat.diagnostics.extend(diagnostics)

        bloquants = [p for p in preuves if p.bloquant]
        non_prouves = [p for p in bloquants if not p.retenue]

        # 5. verdict — par défaut manquement
        if not non_prouves and bloquants:
            resultat.verdict = Verdict.CONFORME
            resultat.justification = (
                f"{len(bloquants)}/{len(bloquants)} éléments probants établis "
                f"par citation vérifiée."
            )
        else:
            resultat.verdict = Verdict.MANQUEMENT
            libelles = [p.intitule for p in non_prouves]
            resultat.justification = (
                "Aucune preuve textuelle vérifiée pour : "
                + " ; ".join(libelles[:4])
                + ("…" if len(libelles) > 4 else "")
            )
            resultat.recommandations = [
                f"Documenter et rendre opposable : {p.intitule}" for p in non_prouves
            ]

            # 6. passe dérogation, obligatoire avant de figer le manquement
            if art.derogations_ex_ante:
                derogation, diags = self._chercher_derogation(
                    art, extraits, document, [p.intitule for p in non_prouves]
                )
                resultat.diagnostics.extend(diags)
                if derogation:
                    connue = next(
                        (d for d in art.derogations if d.reference == derogation.reference),
                        None,
                    )
                    effet = connue.effet if connue else "hors_perimetre"
                    resultat.derogation = derogation
                    resultat.recommandations = []
                    if effet == "conforme":
                        # La dérogation SATISFAIT l'obligation au lieu de l'écarter :
                        # l'article 9(2)(h) rend le traitement de données de santé
                        # licite, il ne fait pas sortir du champ de l'article 9.
                        resultat.verdict = Verdict.CONFORME
                        resultat.justification = (
                            f"Traitement licite au titre de l'article {derogation.reference} "
                            f"({derogation.intitule}) : {derogation.justification}"
                        )
                    else:
                        resultat.verdict = Verdict.HORS_PERIMETRE
                        resultat.justification = (
                            f"Dérogation {derogation.reference} retenue "
                            f"({derogation.intitule}) : {derogation.justification}"
                        )

        resultat.confiance = self._confiance(resultat, preuves)
        if art.numero in ARTICLES_REVUE_SYSTEMATIQUE:
            resultat.revue_humaine_requise = True
            resultat.motif_revue = (
                "qualification juridique appréciée au cas par cas — validation par un "
                "DPO requise quel que soit le verdict"
            )
            resultat.confiance = min(resultat.confiance, 0.6)
        if resultat.confiance < SEUIL_REVUE_HUMAINE:
            resultat.revue_humaine_requise = True
            resultat.motif_revue = "confiance insuffisante — validation par un DPO requise"
        elif resultat.diagnostics:
            resultat.revue_humaine_requise = True
            resultat.motif_revue = "anomalies détectées pendant l'extraction"

        return resultat

    @staticmethod
    def _confiance(resultat: VerdictArticle, preuves: list[Preuve]) -> float:
        base = 0.9
        rejetees = sum(1 for p in preuves if p.satisfait and not p.verifiee)
        if rejetees:
            base -= 0.2 * min(rejetees, 3)
        if resultat.diagnostics:
            base -= 0.1 * min(len(resultat.diagnostics), 3)
        non_bloquants_absents = sum(
            1 for p in preuves if not p.bloquant and not p.retenue
        )
        if resultat.verdict is Verdict.CONFORME and non_bloquants_absents:
            base -= 0.05 * non_bloquants_absents
        return max(0.0, min(1.0, base))

    # -- orchestration document -------------------------------------------

    def evaluer_document(
        self,
        texte: str,
        *,
        nom: str = "document",
        tenant_id: str = "inconnu",
        articles: Sequence[ArticleRGPD] | None = None,
    ) -> RapportAudit:
        from evaluation.scoring import calculer_score

        passages = decouper(texte)
        if not passages:
            raise ValueError("document vide : aucun passage exploitable")
        if len(passages) == 1:
            logger.warning(
                "%s : un seul passage produit (%d tokens). Vérifier le document "
                "ou les paramètres de découpage.", nom, passages[0].tokens,
            )

        cibles = list(articles or REFERENTIEL)
        verdicts = [self.evaluer_article(a, passages, texte) for a in cibles]

        rapport = RapportAudit(document=nom, tenant_id=tenant_id, verdicts=verdicts)
        rapport.score, rapport.detail_score = calculer_score(verdicts)
        rapport.metadonnees = {
            "passages": len(passages),
            "sections": len({p.section for p in passages}),
            "articles_evalues": len(cibles),
            "tokens_document": sum(p.tokens for p in passages),
        }
        return rapport
