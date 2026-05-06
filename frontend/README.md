# Interface web

Page unique, sans dependance ni etape de build. Elle consomme l'API FastAPI du
backend et couvre le parcours complet : ouverture de session, creation d'une
campagne, versement des pieces, analyse, lecture des constats, production du
rapport.

## Demarrage

Deux terminaux.

**Terminal 1 — l'API**

    cd backend
    uvicorn app.main:app --reload --port 8000

**Terminal 2 — l'interface**

    cd frontend
    python -m http.server 5173

Puis ouvrir http://localhost:5173

## Pourquoi le port 5173

Le backend n'accepte que les origines listees dans `CORS_ORIGINS`, dont la
valeur par defaut est `http://localhost:5173`. Servir la page sur ce port evite
toute configuration supplementaire.

Ouvrir `index.html` par double-clic ne fonctionnera pas : le navigateur emet
alors l'origine `null`, que le backend rejette. Il faut passer par un serveur
local, d'ou la commande ci-dessus.

Pour un autre port, ajouter l'origine correspondante a `CORS_ORIGINS` dans
`backend/.env`.

## Prerequis

Le referentiel doit avoir ete ingere, sans quoi l'analyse echoue avec un message
explicite :

    cd backend
    python -m app.ingestion.cli --only rgpd

## Adresse de l'API

Determinee automatiquement : `http://localhost:8000` lorsque la page est servie
sur le port 5173, l'origine courante sinon. Pour une autre adresse, modifier la
constante `API` en tete du script.
