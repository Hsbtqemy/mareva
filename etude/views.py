"""
Vues du parcours participant.

Flux :
  acces   -> code d'accès (individuel ou lien collectif)
  index   -> consentement
  profil  -> questions de profil (groupes « profil »), posées une seule fois
  tache   -> tire un GROUPE non encore abordé, affiche ses questions (paginé par
             saut_de_page), bouton Suivant / Continuer
  soumettre (POST) -> enregistre la page, page suivante ou clôture du groupe,
             puis propose Continuer / Arrêter
  fin     -> remerciement
  media_question -> sert le média d'une question, uniquement au participant qui a
             un passage EN COURS sur le groupe de cette question.

Média : X-Accel-Redirect en production (Nginx sert le fichier), FileResponse en
développement. Bascule automatique selon settings.DEBUG.
"""
import mimetypes
import os
import random
import secrets

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import F
from django.http import FileResponse, HttpResponse, Http404, HttpResponseForbidden
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import (
    Question, Groupe, Media, Participant, Passage,
    Reponse, ReponseProfil, CodeAcces, Configuration,
)
from .selection import tirer_groupe


def _participant_courant(request):
    jeton = request.session.get("jeton")
    if not jeton:
        return None
    return Participant.objects.filter(jeton=jeton).first()


def _nouveau_participant(request):
    return Participant.objects.create(
        jeton=secrets.token_urlsafe(32),
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
    )


def _demarrer_session(request, code):
    """
    Ouvre la session participant à partir d'un CodeAcces valide.
      - collectif : chaque accès crée un NOUVEAU participant ;
      - individuel : crée et lie un participant à la première utilisation,
        puis le restaure aux utilisations suivantes (reprise possible).
    """
    if code.collectif:
        participant = _nouveau_participant(request)
    else:
        participant = code.participant
        if participant is None:
            participant = _nouveau_participant(request)
            code.participant = participant
            code.save(update_fields=["participant"])
    request.session["jeton"] = participant.jeton
    request.session["acces_ok"] = True
    return participant


# --- Limitation des tentatives d'accès (anti brute-force des codes) ---
MAX_TENTATIVES_ACCES = 10
FENETRE_ACCES = 600  # secondes (10 min) ; le blocage expire après ce délai
MSG_TROP_TENTATIVES = "Trop de tentatives. Veuillez réessayer dans quelques minutes."


def _ip_client(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    return xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", "?")


def _cle_acces(request):
    return f"acces_tentatives:{_ip_client(request)}"


def _trop_de_tentatives(request):
    return cache.get(_cle_acces(request), 0) >= MAX_TENTATIVES_ACCES


def _echec_acces(request):
    cle = _cle_acces(request)
    cache.set(cle, cache.get(cle, 0) + 1, FENETRE_ACCES)


def _reset_acces(request):
    cache.delete(_cle_acces(request))


def acces(request):
    """Barrière d'entrée : saisie d'un code d'accès (individuel ou collectif)."""
    if request.session.get("acces_ok") and _participant_courant(request):
        return redirect("index")
    if request.method == "POST":
        if _trop_de_tentatives(request):
            return render(request, "etude/acces.html", {"erreur": MSG_TROP_TENTATIVES})
        saisi = request.POST.get("code", "").strip()
        code = CodeAcces.objects.filter(code=saisi, actif=True).first() if saisi else None
        if code is None:
            _echec_acces(request)
            msg = MSG_TROP_TENTATIVES if _trop_de_tentatives(request) else "Code d'accès incorrect."
            return render(request, "etude/acces.html", {"erreur": msg})
        _reset_acces(request)
        _demarrer_session(request, code)
        return redirect("index")
    return render(request, "etude/acces.html")


def acces_lien(request, code):
    """Lien d'accès cliquable /acces/<code>/ : collectif ou personnel, sans saisie."""
    if request.session.get("acces_ok") and _participant_courant(request):
        return redirect("index")
    if _trop_de_tentatives(request):
        return render(request, "etude/acces.html", {"erreur": MSG_TROP_TENTATIVES})
    code_obj = CodeAcces.objects.filter(code=code, actif=True).first()
    if code_obj is None:
        _echec_acces(request)
        msg = MSG_TROP_TENTATIVES if _trop_de_tentatives(request) else "Lien d'accès invalide ou expiré."
        return render(request, "etude/acces.html", {"erreur": msg})
    _reset_acces(request)
    _demarrer_session(request, code_obj)
    return redirect("index")


def index(request):
    """Consentement (le Participant a déjà été créé/restauré à l'étape accès)."""
    participant = _participant_courant(request)
    if not request.session.get("acces_ok") or not participant:
        return redirect("acces")
    if request.method == "POST":
        if not participant.consentement:
            participant.consentement = True
            participant.save(update_fields=["consentement"])
        return redirect("profil")
    return render(request, "etude/index.html")


# ----------------------------------------------------------------------------
# Pagination : on découpe une liste ordonnée de questions en écrans. Un nouvel
# écran commence avant chaque question marquée `saut_de_page` (bouton Suivant).
# ----------------------------------------------------------------------------
def _questions_du_groupe(groupe):
    return list(
        groupe.questions.filter(active=True)
        .select_related("media").prefetch_related("choix", "sous_questions").order_by("ordre", "id")
    )


def _questions_profil():
    """Questions des groupes de profil, actives, dans l'ordre."""
    return list(
        Question.objects.filter(active=True, groupe__portee=Groupe.PROFIL)
        .select_related("groupe", "media").prefetch_related("choix", "sous_questions")
        .order_by("groupe__ordre", "ordre", "id")
    )


def _preparer(questions, graine):
    """
    Prépare les questions pour l'affichage : attache `choix_affiches` (mélangés
    si `melanger`, de façon stable pour un même participant) et
    `sous_questions_affichees`.
    """
    for q in questions:
        choix = list(q.choix.all())
        if q.melanger:
            random.Random(f"{graine}-{q.id}").shuffle(choix)
        q.choix_affiches = choix
        q.sous_questions_affichees = list(q.sous_questions.all()) if q.type == Question.MATRICE else []
    return questions


def _collecter(request, q):
    """Valeur(s) postée(s) pour une question, selon son type."""
    if q.type == Question.MATRICE:
        return {"matrice": {sq.id: request.POST.get(f"q_{q.id}_sq_{sq.id}", "").strip()
                            for sq in q.sous_questions.all()}}
    if q.type in (Question.CHOIX, Question.CARTES) and q.choix_multiple:
        return {"simple": "|".join(request.POST.getlist(f"q_{q.id}"))}
    return {"simple": request.POST.get(f"q_{q.id}", "").strip()}


OBLIGATOIRE_MSG = "Merci de répondre à toutes les questions obligatoires."


def _valider(q, data):
    """
    Retourne un message d'erreur si la réponse est manquante (obligatoire) OU
    invalide pour le type de question, sinon None. Garantit l'intégrité des
    données : on n'enregistre pas une valeur hors bornes / hors liste.
    """
    if "matrice" in data:
        valeurs_ok = {c.valeur for c in q.choix.all()}
        for v in data["matrice"].values():
            if not v:
                if q.obligatoire:
                    return OBLIGATOIRE_MSG
            elif v not in valeurs_ok:
                return "Réponse invalide dans la matrice."
        return None

    v = data["simple"]
    if not v:
        return OBLIGATOIRE_MSG if q.obligatoire else None

    if q.type == Question.ECHELLE:
        try:
            iv = int(v)
        except (TypeError, ValueError):
            return "Valeur d'échelle invalide."
        if q.min_val is None or q.max_val is None or not (q.min_val <= iv <= q.max_val):
            return "Valeur d'échelle hors bornes."
    elif q.type in (Question.CHOIX, Question.CARTES):
        valeurs_ok = {c.valeur for c in q.choix.all()}
        soumis = v.split("|") if q.choix_multiple else [v]
        if any(s not in valeurs_ok for s in soumis):
            return "Option de réponse invalide."
    elif q.type == Question.DRAGDROP:
        valeurs_ok = {c.valeur for c in q.choix.all()}
        soumis = [s for s in v.split("|") if s]
        if set(soumis) != valeurs_ok:
            return "Classement invalide."
    elif q.type in (Question.TEXTE, Question.LONGTEXT):
        if q.longueur and len(v) > q.longueur:
            return "Réponse trop longue."
    return None


def profil(request):
    """
    Questions de profil, posées UNE seule fois après le consentement. Si elles
    sont déjà répondues (ou s'il n'y en a pas), on passe directement à la boucle.
    """
    participant = _participant_courant(request)
    if not request.session.get("acces_ok") or not participant:
        return redirect("acces")
    if not participant.consentement:
        return redirect("index")

    questions = _questions_profil()
    deja = set(participant.reponses_profil.values_list("question_id", flat=True))
    if not questions or all(q.id in deja for q in questions):
        return redirect("tache")
    return render(request, "etude/profil.html", {"questions": _preparer(questions, participant.id)})


@require_POST
def soumettre_profil(request):
    participant = _participant_courant(request)
    if not participant or not participant.consentement:
        return redirect("index")

    questions = _questions_profil()
    valeurs = {}
    for q in questions:
        data = _collecter(request, q)
        erreur = _valider(q, data)
        if erreur:
            return render(request, "etude/profil.html", {
                "questions": _preparer(questions, participant.id),
                "erreur": erreur,
            })
        # Profil : types simples ; une éventuelle matrice est stockée jointe.
        valeurs[q] = data["simple"] if "simple" in data else "|".join(data["matrice"].values())

    with transaction.atomic():
        for q, valeur in valeurs.items():
            ReponseProfil.objects.update_or_create(
                participant=participant, question=q, defaults={"valeur": valeur},
            )
    return redirect("tache")


def _max_atteint(participant, config):
    return bool(config.max_groupes) and \
        participant.passages.filter(fin__isnull=False).count() >= config.max_groupes


def tache(request):
    participant = _participant_courant(request)
    if not participant:
        return redirect("index")

    # Reprend le groupe en cours, sinon en tire un nouveau.
    passage = participant.passages.filter(fin__isnull=True).first()
    if not passage:
        config = Configuration.charger()
        if _max_atteint(participant, config):
            return redirect("fin")
        groupe = tirer_groupe(participant)
        if groupe is None:
            return redirect("fin")  # plus de groupe disponible
        passage = Passage.objects.create(participant=participant, groupe=groupe)

    questions = _preparer(_questions_du_groupe(passage.groupe), passage.id)
    return render(request, "etude/tache.html", {"groupe": passage.groupe, "questions": questions})


def _persister(passage, q, data):
    if "matrice" in data:
        for sqid, val in data["matrice"].items():
            Reponse.objects.update_or_create(
                passage=passage, question=q, sous_question_id=sqid, defaults={"valeur": val},
            )
    else:
        Reponse.objects.update_or_create(
            passage=passage, question=q, sous_question=None, defaults={"valeur": data["simple"]},
        )


@require_POST
def soumettre(request):
    participant = _participant_courant(request)
    if not participant:
        return redirect("index")

    passage = participant.passages.filter(fin__isnull=True).first()
    if not passage:
        return redirect("tache")

    # Tout le groupe est posté d'un coup (les écrans sont gérés côté client).
    questions = _questions_du_groupe(passage.groupe)
    collecte = {}
    for q in questions:
        data = _collecter(request, q)
        erreur = _valider(q, data)
        if erreur:
            return render(request, "etude/tache.html", {
                "groupe": passage.groupe,
                "questions": _preparer(questions, passage.id),
                "erreur": erreur,
            })
        collecte[q] = data

    with transaction.atomic():
        for q, data in collecte.items():
            _persister(passage, q, data)
        passage.fin = timezone.now()
        passage.save(update_fields=["fin"])
        Groupe.objects.filter(pk=passage.groupe_id).update(nb_evaluations=F("nb_evaluations") + 1)

    config = Configuration.charger()
    reste = (not _max_atteint(participant, config)) and (tirer_groupe(participant) is not None)
    return render(request, "etude/continuer.html", {"reste": reste})


def fin(request):
    return render(request, "etude/fin.html")


def _type_contenu(kind, rel):
    if kind == "vtt":
        return "text/vtt"
    return mimetypes.guess_type(rel)[0] or "application/octet-stream"


def _servir(rel, content_type):
    """
    Sert un fichier média protégé : X-Accel-Redirect en production (Nginx),
    FileResponse en développement. 'rel' vient de l'admin, pas du participant.
    """
    if not settings.DEBUG:
        resp = HttpResponse()
        resp["Content-Type"] = content_type
        resp["X-Accel-Redirect"] = f"/media-protege/{rel}"
        return resp
    chemin = os.path.join(settings.MEDIA_ROOT, rel)
    if not os.path.exists(chemin):
        raise Http404
    return FileResponse(open(chemin, "rb"), content_type=content_type)


def media_question(request, code, kind):
    """
    Sert le média ('fichier') ou le VTT ('vtt') d'une question, uniquement si le
    participant a un passage EN COURS sur le groupe de cette question.
    """
    participant = _participant_courant(request)
    if not participant:
        return HttpResponseForbidden("Accès réservé aux participants.")

    passage = participant.passages.filter(fin__isnull=True).first()
    if not passage:
        return HttpResponseForbidden("Ce contenu n'est pas accessible.")

    media = Media.objects.filter(code=code).first()
    if not media:
        raise Http404
    # Autorisé si c'est la vidéo du groupe en cours, ou le média d'une de ses
    # questions actives.
    autorise = (passage.groupe.media_id == media.id) or \
        Question.objects.filter(active=True, media=media, groupe=passage.groupe).exists()
    if not autorise:
        return HttpResponseForbidden("Ce contenu n'est pas accessible.")

    rel = media.vtt if kind == "vtt" else media.fichier
    if not rel:
        raise Http404
    return _servir(rel, _type_contenu(kind, rel))
