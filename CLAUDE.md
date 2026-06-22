# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Langue

Le projet est intégralement en **français** : code, commentaires, docstrings, noms de modèles/champs, libellés et messages de commit. Conserver le français pour tout nouveau code et toute communication dans le dépôt.

## Commandes

```bash
source .venv/bin/activate          # venv déjà présent à la racine
python manage.py migrate
python manage.py runserver          # http://127.0.0.1:8000/ (participant), /admin/, /editeur/
python manage.py createsuperuser    # accès à /admin et /editeur (staff)

python manage.py test               # toute la suite (etude/tests.py)
python manage.py test etude.tests.NomDeClasse                 # une classe
python manage.py test etude.tests.NomDeClasse.test_methode    # un seul test

python seed.py                      # données de démo (codes `demo` / `ouvert`) — à NE PAS lancer sur une vraie collecte
python manage.py sauvegarde         # archive .zip horodatée (base + médias) dans sauvegardes/
```

Pas de linter ni de formateur configuré. Dépendances dans `requirements.txt` (Django, gunicorn, markdown).

## Architecture

Application Django mono-app (`etude/`), réglages dans `config/`. Outil de questionnaire **neutre et paramétrable** : aucun texte d'étude n'est codé en dur (tout vient du modèle `Configuration`, singleton chargé via `Configuration.charger()` et exposé à tous les templates par le context processor `etude.context.configuration`).

### Concept central : le GROUPE comme unité de tirage

L'unité du questionnaire n'est pas la question mais le **Groupe** :
- **Groupe `profil`** : posé **une seule fois** au début, réponses stockées sur le participant (`ReponseProfil`).
- **Groupe `standard`** : fait partie du **pool de tirage**. La boucle (`selection.tirer_groupe`) tire un groupe non encore abordé — aléatoire pondéré (poids `1/(1+nb_evaluations)` pour équilibrer la couverture) ou ordre fixe selon `Configuration.ordre_groupes_aleatoire` — jusqu'à épuisement ou `max_groupes`. Entre chaque groupe : page « Continuer / Arrêter ».
- Un groupe se découpe en **écrans** via le drapeau `saut_de_page` d'une question (la pagination est gérée côté client ; tout le groupe est posté d'un coup à `soumettre`).

### Modèle de données (etude/models.py)

`Groupe → Question → Choix` ; `Question → SousQuestion` (lignes d'une matrice). Les réponses utilisent un **schéma clé-valeur** : `Reponse` (une par `Passage`×question, ou par sous-question pour une matrice ; valeurs multiples jointes par `|`). **Conséquence clé** : ajouter une question = nouvelle colonne à l'export, **sans migration**. `Passage` = un participant a abordé un groupe (`fin` non nul = terminé), `unique_together(participant, groupe)`.

Types de question (`Question.TYPE_CHOICES`) : `echelle`, `choix`, `cartes`, `matrice`, `dragdrop`, `texte`, `longtext`. Toute logique sensible au type est centralisée dans les helpers de `views.py` : `_collecter` (lecture du POST), `_valider` (intégrité — on n'enregistre jamais une valeur hors bornes/hors liste), `_persister`, `_preparer` (mélange stable des options par participant). Étendre un type = toucher ces quatre helpers + `exports._colonnes`.

### Séparation construction / agencement

- **Construire** une question (type, média, options, échelle) → **admin Django** (`admin.py`, formulaire + inlines) OU le formulaire intégré `editeur.question_form`.
- **Agencer** (ordre, déplacer entre groupes, saut de page, réglages de groupe) → **éditeur visuel** `/editeur/` (`editeur.py`, staff only), glisser-déposer via API JSON en `fetch()` (`api_groupe`, `api_question`, `api_reordonner`, etc.). L'éditeur expose aussi médias, paramètres, résultats/exports et **aperçu** du questionnaire.

### Parcours participant (views.py)

`acces` (code individuel ou lien collectif `/acces/<code>/`) → `index` (consentement) → `profil` → `tache` (tire/reprend un groupe) → `soumettre` → `continuer` → … → `fin`. Identité par `jeton` anonyme en session ; code d'accès **jamais exporté** (la correspondance code→personne reste hors outil). Mode **aperçu** (`session["apercu"]`) : participant temporaire supprimé en fin de parcours.

### Sécurité

- **Médias protégés** : `media_question` vérifie que le participant a un passage **en cours** sur le groupe concerné, puis sert le fichier. Bascule automatique `_servir` : `X-Accel-Redirect` (Nginx) en production / `FileResponse` en dev (`settings.DEBUG`). `MEDIA_ROOT` n'est **jamais** exposé directement.
- **Anti-flood des accès** : deux niveaux via cache Django (`_trop_de_tentatives`) — par session navigateur (`ACCES_MAX_SESSION`, principal, n'affecte pas les autres participants d'une même IP/NAT) et par IP (`ACCES_MAX_IP`, garde-fou). Un succès réinitialise les compteurs. **En multi-workers, utiliser un cache partagé** (Redis/Memcached).
- Réglages production via variables d'env (`config/settings.py`) : `DJANGO_DEBUG`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`. Hors DEBUG, cookies sécurisés + `CSRF_TRUSTED_ORIGINS` dérivés des hôtes autorisés.

### Export (exports.py)

`csv_passages` : une ligne par passage, format large repivoté (matrice dépliée en une colonne par sous-question), colonnes profil recopiées sur chaque ligne du participant. `csv_participants` : une ligne par participant. Réutilisé par l'admin (action) et la page Résultats de l'éditeur.

## Déploiement

Fichiers prêts dans `deploy/` (`nginx.conf`, `gunicorn.conf.py`, `etude.service` systemd, `deployer.sh`, `.env.example`, checklist `deploy/README.md`). SQLite par défaut (migrer vers PostgreSQL en cas de forte charge concurrente). Nginx doit autoriser les gros uploads (`client_max_body_size`) et exposer un `location /media-protege/ { internal; }` pour le X-Accel-Redirect.
