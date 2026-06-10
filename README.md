# Outil d'étude — squelette Django

Outil **neutre** de questionnaire. L'unité est le **groupe de questions** : on
propose au participant des groupes non encore répondus, tant qu'il souhaite
continuer. Chaque question porte son propre média audio/vidéo. Le nom de l'étude
et tous les textes sont **paramétrables** dans l'admin.

## Modèle

```text
Groupe (profil ou standard)         ← unité tirée par la boucle
  └── Question (type, média, options, saut de page)
        └── Choix (si type = choix)
Configuration  ← textes + paramètres de déroulé (singleton)
```

- **Groupe profil** : posé **une seule fois** au début (âge, genre…), stocké sur
  le participant (`ReponseProfil`).
- **Groupe standard** : fait partie du **pool de tirage**. On tire un groupe non
  encore répondu (aléatoire pondéré ou ordre fixe), le participant y répond, puis
  **Continuer / Arrêter**, jusqu'à épuisement (ou `max_groupes`).
- Un groupe peut être découpé en plusieurs **écrans** : cocher `saut de page`
  sur une question fait apparaître un bouton **« Suivant »** avant elle.

## Ce qui est inclus

- **Identité & déroulé paramétrables** : `Configuration` (nom, accueil,
  consentement, intro profil, remerciement, **ordre aléatoire des groupes**,
  **nombre max de groupes**) — éditable dans l'admin, rien n'est codé en dur.
- **Modèles** : `Groupe`, `Question`, `Choix`, `Media`, `Participant`,
  `Passage` (participant × groupe), `Reponse`, `ReponseProfil`, `CodeAcces`,
  `Configuration` (réponses en schéma clé-valeur → questions ajoutables sans migration).
- **Construction des questions** : formulaire d'admin Django (type, média,
  options, échelle). L'**éditeur visuel** ne sert qu'à **agencer**.
- **Éditeur visuel** (`/editeur/`, staff) : vue d'ensemble, **glisser-déposer**
  des groupes et des questions, réglages de groupe (titre, consigne, portée,
  inclure au tirage, actif) et bascule « saut de page » par question. Lien
  « Modifier » → formulaire d'admin. Sans dépendance externe.
- **Accès participant** : **code individuel** (un code = un participant, reprise
  de session) ou **lien collectif** `/acces/<code>/` (chaque visiteur = un
  participant). Codes gérés dans l'admin, jamais exportés.
- **Tirage** : `selection.py`. Aléatoire pondéré (poids = 1/(1+nb_evaluations),
  couverture équilibrée) ou ordre fixe, excluant les groupes déjà faits.
- **Média par question** : audio ou vidéo (`Media`), servi protégé uniquement au
  participant ayant un passage en cours sur le groupe de la question.
- **Export CSV** : une ligne par `Passage`, colonnes profil (recopiées) puis une
  colonne par question.

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

`python seed.py` crée un groupe profil + deux groupes standard (dont un sur deux
écrans) et les codes `demo` / `ouvert`. À supprimer avant une vraie collecte.

## Construire et agencer le questionnaire

**Construire une question** : dans **/admin → Questions** (formulaire complet :
code, libellé, type, média, options/échelle, groupe). Le code sert d'en-tête de
colonne à l'export. Décocher « active » la retire sans perdre les réponses.

**Médias** (Éditeur → Médias) : **téléverser** un fichier vidéo/audio (jusqu'à
1 Go) — il est stocké sous `media/` sur le serveur et le Média est créé
automatiquement (type détecté par l'extension). Option avancée : référencer un
fichier déjà déposé (par SFTP) via son chemin relatif. Les fichiers sont servis
de façon protégée, jamais exposés publiquement.

> En production derrière Nginx, autoriser les gros envois :
> `client_max_body_size 1024m;` (sinon l'upload est refusé au-delà de ~1 Mo).

**Agencer** : dans **/editeur/** (lien en haut de l'admin), interface
glisser-déposer en lecture/agencement :

- **+ Groupe**, réordonner les groupes (poignée ⠿), régler chaque groupe :
  titre, consigne, **portée** (profil / standard), **inclure dans le tirage**,
  actif.
- Glisser les questions pour les **réordonner ou les déplacer** entre groupes
  (enregistré automatiquement). Cocher **« saut de page »** pour qu'une question
  commence un nouvel écran. « Modifier » ouvre son formulaire d'admin.
- **Paramètres** (lien en haut) → `Configuration` : ordre aléatoire des groupes,
  nombre max de groupes par participant.

**Codes d'accès** : **/admin → Codes d'accès**. Bouton **« Générer 20 codes »**,
ou ajout manuel (code vide → généré). Décocher « actif » révoque l'accès. Pour un
**lien collectif**, cocher « collectif » et diffuser le lien de la colonne
« Lien à partager ».

## Export des résultats

Admin → **Passages** → sélectionner → action **« Exporter en CSV »**.
Format large directement exploitable en R / pandas : `id_passage`,
`jeton_participant`, `consentement`, `code_groupe`, `debut`, `fin`, puis une
colonne par question **profil** (recopiée sur chaque ligne du participant), puis
une colonne par question. Toute question ajoutée devient automatiquement une
colonne — le schéma clé-valeur s'en charge.

## Déploiement (production)

> **Fichiers prêts à l'emploi dans [`deploy/`](deploy/)** : `nginx.conf`,
> `gunicorn.conf.py`, `etude.service` (systemd), `.env.example`, et une checklist
> pas-à-pas ([`deploy/README.md`](deploy/README.md)). Le résumé ci-dessous reprend les points clés.

1. `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY=...`, `DJANGO_ALLOWED_HOSTS=mondomaine.fr`
   en variables d'environnement.
2. Servir via gunicorn/uwsgi derrière **Nginx**, en **HTTPS**. En `DEBUG=False`,
   exposer les fichiers statiques de l'admin : `python manage.py collectstatic`
   puis servir `STATIC_ROOT` via Nginx (les médias, eux, restent protégés).
3. **Média protégé (X-Accel-Redirect)** — Django vérifie les droits puis délègue
   l'envoi du fichier à Nginx (médias de question, sous `MEDIA_ROOT`). Le dossier
   média n'est PAS exposé publiquement. Ajouter dans la config Nginx :

   ```nginx
   # Interne : seul Django peut y rediriger, pas le public.
   location /media-protege/ {
       internal;
       alias /chemin/absolu/vers/le-projet/media/;
   }
   ```

   En développement (`DEBUG=True`) il n'y a pas de Nginx : Django sert le
   fichier directement. Le basculement est automatique (voir `views.media_question`).

4. **Sauvegardes** : commande dédiée qui archive **base + médias** dans un
   `.zip` horodaté :

   ```bash
   python manage.py sauvegarde                 # → sauvegardes/sauvegarde_AAAAMMJJ_HHMMSS.zip
   python manage.py sauvegarde --sortie /backups
   ```

   À planifier régulièrement (cron / tâche planifiée). **Restauration** : arrêter
   le serveur, dézipper l'archive, puis remplacer `db.sqlite3` par
   `base/db.sqlite3` et le dossier `media/` par le `media/` de l'archive ;
   relancer `python manage.py migrate`. (Base non-SQLite : l'archive contient
   `base/dumpdata.json` → `python manage.py loaddata base/dumpdata.json`.)
   Migrer vers PostgreSQL si forte charge simultanée.
5. **Anti-flood des codes** : la tentative de code est limitée sur deux niveaux
   (cache Django) — **par navigateur** (`ACCES_MAX_SESSION`, défaut 8) et un
   garde-fou **par IP** (`ACCES_MAX_IP`, défaut 100, `0` pour désactiver), sur
   une fenêtre `ACCES_FENETRE` (défaut 600 s). Le niveau session évite de bloquer
   des participants **partageant une même IP** (réseau d'établissement, NAT) ;
   un accès réussi remet les compteurs à zéro. Codes = jetons à haute entropie →
   le brute-force est de toute façon irréaliste. Réglable par variables d'env.
   En multi-workers, utiliser un cache **partagé** (Redis/Memcached, ou
   `createcachetable` + cache base de données). Derrière un proxy, transmettre
   `X-Forwarded-For`.

## Pistes d'extension

- Mesurer le temps de visionnage (champs début/fin d'écoute côté JS).
- Pagination du groupe de profil (aujourd'hui sur un seul écran).
- `django-import-export` pour des boutons Export/Import enrichis dans l'admin.
