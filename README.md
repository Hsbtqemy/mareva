# Outil d'étude — squelette Django

Outil **neutre** de questionnaire sur une banque d'extraits vidéo/audio
sous-titrés. Le nom de l'étude et tous les textes affichés sont **paramétrables**
(modèle `Configuration`, éditable dans l'admin) pour cadrer l'étude selon les
besoins. Tirage aléatoire pondéré, boucle « Continuer / Arrêter », questionnaire
composé dans un éditeur visuel, export CSV, fichiers média protégés.

## Ce qui est inclus

- **Identité paramétrable** : `Configuration` (nom de l'étude, titre d'accueil,
  texte de consentement, intro du profil, remerciement) — éditable dans l'admin,
  rien n'est codé en dur.
- **Modèles** : `Question`, `Choix`, `Groupe`, `Media`, `Enregistrement`,
  `Participant`, `Jugement`, `Reponse`, `ReponseProfil`
  (réponses en schéma clé-valeur → questions ajoutables sans migration).
- **Admin Django** : ajout/modification des questions et de la banque vidéo sans coder,
  consultation des jugements, et action **« Exporter en CSV »** qui repivote
  automatiquement en format large (une ligne par jugement, une colonne par question).
- **Accès participant** : deux modes, gérés dans l'admin, jamais exportés.
  - **Code individuel** (un code = un participant) : resaisir le même code
    (autre navigateur, plus tard) **reprend la même session**.
  - **Lien collectif** (case « collectif ») : un lien `/acces/<code>/` à
    diffuser largement ; **chaque visiteur** devient un nouveau participant.
  Page `/acces/` pour saisir un code, ou lien direct `/acces/<code>/` (sans
  saisie) qui marche pour les deux modes.
- **Accès chercheur** : connexion Django native sur `/admin/login/`, habillée
  à la palette de l'étude.
- **Éditeur visuel** (`/editeur/`, réservé au staff) : composer le questionnaire
  en **groupes** par glisser-déposer, gérer chaque question (type, options,
  média), et choisir la **mise en page** (case « nouvelle page » par groupe).
  Accessible depuis le lien en haut de l'admin. Sans dépendance externe.
- **Portée des questions** : chaque question est soit **« par extrait »**
  (rattachée à chaque jugement — les vraies évaluations), soit **« profil »**
  (âge, genre… posées **une seule fois** après le consentement, stockées sur le
  participant, pas sur un jugement). Réglable par question dans l'éditeur.
- **Groupes & média par question** : les questions se rangent en groupes
  (sections) ; chaque groupe peut commencer une nouvelle page ; chaque question
  peut porter son propre média **audio ou vidéo** (modèle `Media`, distinct du
  vivier de tirage). Le clip tiré reste le sujet principal, affiché en page 1.
- **Parcours participant** : consentement → clip + questions (en groupes,
  éventuellement sur plusieurs pages) → Continuer/Arrêter.
- **Tirage pondéré** : `selection.py`. Poids = 1/(1+nb_evaluations), exclut les clips
  déjà jugés par le participant → couverture équilibrée de la banque.
- **Média protégé** : la vidéo et les sous-titres ne sont accessibles qu'à un
  participant ayant un jugement en cours sur ce clip (voir « Déploiement »).

## Démarrage (développement)

```bash
pip install django
python manage.py migrate
python manage.py createsuperuser      # pour accéder à /admin
python manage.py runserver
```

Puis dans **/admin → Configuration de l'étude** : renseigner le nom de l'étude
et les textes affichés (accueil, consentement, remerciement). Tout est neutre
par défaut.

- Questionnaire : http://127.0.0.1:8000/
- Administration : http://127.0.0.1:8000/admin/

### Données de démonstration (optionnel)

`python seed.py` crée 3 questions (une de chaque type) et 3 clips d'exemple.
À supprimer avant une vraie collecte.

## Construire le questionnaire (éditeur visuel)

**/editeur/** (lien en haut de l'admin) : interface glisser-déposer pour
composer le questionnaire.

- **Groupes** : « + Groupe », réordonner par glisser-déposer, titre + consigne.
  Cocher « commence une nouvelle page » pour scinder le questionnaire en pages.
- **Questions** : « + Question » dans un groupe, glisser pour réordonner ou
  déplacer entre groupes. « Éditer » ouvre le détail (code, libellé, type,
  options de choix, échelle, média audio/vidéo, obligatoire/active).
- Les réordonnancements s'enregistrent automatiquement ; le reste via
  « Enregistrer ». Une question avec des réponses déjà collectées ne peut pas
  être supprimée (la désactiver à la place).
- Bouton « Aperçu participant » pour voir le rendu.

## Ajouter du contenu (sans coder)

Tout se fait dans **/admin** :

1. **Questions** : code (sert d'en-tête de colonne à l'export), libellé, type
   (échelle / choix / texte), bornes ou options, ordre, obligatoire, active.
   Décocher « active » retire une question sans perdre les réponses passées.
2. **Enregistrements** (clips sujets, vivier de tirage) : déposer les fichiers
   dans `media/videos/`, puis créer un enregistrement avec le chemin relatif
   (`videos/clip_042.mp4`) et son `.vtt`. Le compteur d'évaluations se met à
   jour seul.
2 bis. **Médias de question** (audio/vidéo attachés à une question) : déposer
   sous `media/` (ex. `media/medias/`), créer un **Média** (admin ou éditeur)
   avec son chemin relatif et son type (audio/vidéo), puis le sélectionner dans
   l'éditeur. Bibliothèque distincte des clips → jamais tirée comme sujet.
3. **Codes d'accès** : un code par participant invité. Bouton **« Générer 20
   codes »** sur la liste, ou ajout manuel (laisser le champ vide → code
   généré). Distribuer un code par personne. Décocher « actif » révoque l'accès.
   La colonne « participant » montre à qui chaque code a été lié.
   - **Lien à partager à tous** : créer un code, cocher **« collectif »**, et
     diffuser le lien affiché dans la colonne « Lien à partager »
     (`/acces/<code>/`). Chaque visiteur devient un participant distinct.

## Export des résultats

Admin → Jugements → sélectionner → action **« Exporter en CSV »**.
Format large directement exploitable en R / pandas : `id_jugement`,
`jeton_participant`, `consentement`, `code_enregistrement`, `categorie`,
`debut`, `fin`, puis une colonne par question **profil** (recopiée sur chaque
ligne du participant), puis une colonne par question **par extrait** (par
`code`). Toute question ajoutée devient automatiquement une colonne — aucun
réglage par question, le schéma clé-valeur s'en charge.

## Déploiement (production)

1. `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY=...`, `DJANGO_ALLOWED_HOSTS=mondomaine.fr`
   en variables d'environnement.
2. Servir via gunicorn/uwsgi derrière **Nginx**, en **HTTPS**. En `DEBUG=False`,
   exposer les fichiers statiques de l'admin : `python manage.py collectstatic`
   puis servir `STATIC_ROOT` via Nginx (les médias, eux, restent protégés).
3. **Média protégé (X-Accel-Redirect)** — Django vérifie les droits puis délègue
   l'envoi du fichier à Nginx, pour les clips sujets **comme** pour les médias
   de question (tous sous `MEDIA_ROOT`). Le dossier média n'est PAS exposé
   publiquement. Ajouter dans la config Nginx :

   ```nginx
   # Interne : seul Django peut y rediriger, pas le public.
   location /media-protege/ {
       internal;
       alias /chemin/absolu/vers/le-projet/media/;
   }
   ```

   En développement (`DEBUG=True`) il n'y a pas de Nginx : Django sert le
   fichier directement. Le basculement est automatique (voir `views.media_protege`).

4. **Sauvegardes** : `db.sqlite3` contient toutes les données — sauvegarder
   régulièrement. Migrer vers PostgreSQL si forte charge simultanée.

## Pistes d'extension

- Mesurer le temps de visionnage (champs début/fin d'écoute côté JS).
- Limiter le nombre de jugements par participant.
- `django-import-export` pour des boutons Export/Import enrichis dans l'admin.
