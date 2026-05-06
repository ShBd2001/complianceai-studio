# Mentions produit

Textes à intégrer dans l'interface. Ce ne sont pas des formalités : ils
définissent ce que l'outil prétend faire, et ils te protègent autant qu'ils
protègent l'utilisateur.

## Bandeau permanent (en-tête du rapport)

> ComplianceAI Studio est un outil d'aide à l'auto-évaluation. Il analyse les
> documents que vous lui fournissez et signale les points qui appellent votre
> attention. **Il ne constitue pas un conseil juridique et ne vaut pas preuve de
> conformité au sens du RGPD.** Les conclusions doivent être validées par votre
> délégué à la protection des données ou par un conseil qualifié.

## Sous chaque verdict de conformité

> Ce verdict repose exclusivement sur le contenu du document analysé. Un
> document peut décrire une pratique qui n'est pas appliquée, ou omettre une
> pratique existante. Seul un audit sur pièces et sur site permet de conclure.

## Sous chaque verdict de manquement

> L'absence d'un élément dans le document ne signifie pas qu'il n'existe pas
> dans votre organisation. Ce constat porte sur la documentation fournie, et
> constitue une piste de vérification, non une conclusion.

## Sur les articles marqués « à réviser »

> Le moteur n'a pas atteint un niveau de confiance suffisant sur ce point.
> Une validation humaine est nécessaire avant toute décision.

## Ce qui doit être visible dans l'interface, pas seulement dans les CGU

1. **La citation source de chaque verdict.** Un verdict sans preuve affichable
   ne doit pas être rendu. C'est la différence entre un outil auditable et un
   oracle.
2. **La référence réglementaire exacte** : article et paragraphe, y compris la
   dérogation retenue le cas échéant.
3. **Le détail du score** : quel article a coûté combien de points. Un score
   global sans ventilation est ininterprétable.
4. **La date et la version du modèle** utilisées pour l'analyse. Un rapport
   produit il y a six mois avec un autre modèle n'est pas comparable.
5. **La politique de conservation** au moment du dépôt du document — voir
   `securite/retention.py::mention_utilisateur()`.

## Ce que l'outil ne doit jamais faire

- Afficher un pourcentage de conformité sans le mot « estimation ».
- Délivrer une attestation, un certificat ou un badge de conformité.
- Présenter un verdict indéterminé comme un résultat d'audit.
- Laisser entendre qu'un score élevé met à l'abri d'un contrôle de la CNIL.

## Position à tenir devant un jury

La bonne réponse à « votre outil est-il fiable ? » n'est pas un F1. C'est :
le moteur ne conclut jamais sans citation vérifiable, il refuse de conclure
quand il n'est pas sûr, il trace tout, et il est mesuré contre une vérité
terrain que je maintiens à la main. Les métriques viennent après, avec leur
intervalle de confiance.
