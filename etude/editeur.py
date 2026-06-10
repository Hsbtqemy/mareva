"""
Éditeur visuel du questionnaire (réservé au staff) — AGENCEMENT uniquement.

La construction d'une question (type, média, options, échelle...) se fait dans
le formulaire d'admin Django. L'éditeur sert à :
  - voir l'ensemble du questionnaire d'un coup ;
  - glisser-déposer groupes et questions (ordre, déplacement entre groupes) ;
  - régler les paramètres de groupe (titre, consigne, portée, tirage, actif) ;
  - basculer le « saut de page » (bouton Suivant) d'une question.

API JSON appelée en fetch() :
  api_groupe / api_groupe_supprimer / api_question (toggles) /
  api_question_supprimer / api_reordonner.
"""
from __future__ import annotations

import json
import os

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.files.storage import FileSystemStorage
from django.db import transaction
from django.db.models import ProtectedError
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.text import get_valid_filename, slugify
from django.views.decorators.http import require_POST

from .forms import (
    QuestionForm, MediaForm, MediaUploadForm, ConfigurationForm,
    ChoixFormSet, SousQuestionFormSet,
)
from . import exports
from .models import (
    Groupe, Question, Choix, SousQuestion, Media, Participant, Passage,
    Reponse, ReponseProfil, Configuration,
)


def _serialiser_question(q):
    return {
        "id": q.id,
        "code": q.code,
        "libelle": q.libelle,
        "type": q.get_type_display(),
        "media": q.media.code if q.media_id else None,
        "saut_de_page": q.saut_de_page,
        "active": q.active,
        "groupe_id": q.groupe_id,
    }


def _donnees():
    questions = list(
        Question.objects.select_related("groupe", "media").order_by("ordre", "id")
    )
    groupes = list(Groupe.objects.order_by("ordre", "id"))
    return {
        "groupes": [
            {
                "id": g.id,
                "titre": g.titre,
                "consigne": g.consigne,
                "portee": g.portee,
                "inclure_tirage": g.inclure_tirage,
                "active": g.active,
                "media_id": g.media_id,
                "questions": [_serialiser_question(q) for q in questions if q.groupe_id == g.id],
            }
            for g in groupes
        ],
        "sans_groupe": [_serialiser_question(q) for q in questions if q.groupe_id is None],
        "medias": [{"id": m.id, "code": m.code, "type": m.type_media} for m in Media.objects.all()],
    }


@staff_member_required
def editeur(request):
    return render(request, "etude/editeur.html", {"data": _donnees()})


def _corps_json(request):
    try:
        return json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return {}


@staff_member_required
@require_POST
def api_groupe(request):
    d = _corps_json(request)
    gid = d.get("id")
    if gid:
        groupe = get_object_or_404(Groupe, pk=gid)
    else:
        dernier = Groupe.objects.order_by("-ordre").first()
        groupe = Groupe(ordre=(dernier.ordre + 1) if dernier else 0)

    if "titre" in d:
        groupe.titre = d["titre"]
    if "consigne" in d:
        groupe.consigne = d["consigne"]
    if "portee" in d and d["portee"] in (Groupe.PROFIL, Groupe.STANDARD):
        groupe.portee = d["portee"]
    if "media_id" in d:
        groupe.media_id = d["media_id"] or None
    for champ in ("inclure_tirage", "active"):
        if champ in d:
            setattr(groupe, champ, bool(d[champ]))
    groupe.save()
    return JsonResponse({"id": groupe.id})


@staff_member_required
@require_POST
def api_groupe_supprimer(request, gid):
    groupe = get_object_or_404(Groupe, pk=gid)
    # Les questions du groupe repassent « sans groupe » (FK SET_NULL).
    groupe.delete()
    return JsonResponse({"ok": True})


@staff_member_required
@require_POST
def api_question(request):
    """Bascules légères depuis l'éditeur : saut_de_page, active."""
    d = _corps_json(request)
    question = get_object_or_404(Question, pk=d.get("id"))
    for champ in ("saut_de_page", "active"):
        if champ in d:
            setattr(question, champ, bool(d[champ]))
    question.save(update_fields=["saut_de_page", "active"])
    return JsonResponse({"id": question.id})


@staff_member_required
@require_POST
def api_question_supprimer(request, qid):
    question = get_object_or_404(Question, pk=qid)
    if (Reponse.objects.filter(question=question).exists()
            or ReponseProfil.objects.filter(question=question).exists()):
        return JsonResponse(
            {"erreur": "Des réponses existent déjà pour cette question : "
                       "décochez « active » plutôt que de la supprimer."},
            status=400,
        )
    try:
        question.delete()
    except ProtectedError:
        return JsonResponse({"erreur": "Suppression impossible (réponses liées)."}, status=400)
    return JsonResponse({"ok": True})


def _code_libre(model, base):
    """Code de slug unique pour `model`, dérivé de `base`, respectant max_length."""
    maxlen = model._meta.get_field("code").max_length
    base = (slugify(base) or "x")[:maxlen]
    code, i = base, 2
    while model.objects.filter(code=code).exists():
        suffixe = f"-{i}"
        code = base[:maxlen - len(suffixe)] + suffixe
        i += 1
    return code


def _dupliquer_question(q, groupe=None):
    """Copie une question (champs + choix + sous-questions) en fin du groupe cible."""
    groupe = groupe if groupe is not None else q.groupe
    dernier = Question.objects.filter(groupe=groupe).order_by("-ordre").first()
    copie = Question.objects.create(
        groupe=groupe, code=_code_libre(Question, f"{q.code}-copie"),
        libelle=q.libelle, type=q.type, aide=q.aide, media=q.media,
        min_val=q.min_val, max_val=q.max_val, label_min=q.label_min, label_max=q.label_max,
        choix_multiple=q.choix_multiple, melanger=q.melanger, longueur=q.longueur,
        obligatoire=q.obligatoire, saut_de_page=q.saut_de_page, active=q.active,
        ordre=(dernier.ordre + 1) if dernier else 0,
    )
    for c in q.choix.all():
        Choix.objects.create(question=copie, valeur=c.valeur, libelle=c.libelle,
                             description=c.description, ordre=c.ordre)
    for sq in q.sous_questions.all():
        SousQuestion.objects.create(question=copie, code=_code_libre(SousQuestion, f"{sq.code}-copie"),
                                    libelle=sq.libelle, ordre=sq.ordre)
    return copie


@staff_member_required
@require_POST
def api_question_dupliquer(request, qid):
    q = get_object_or_404(Question, pk=qid)
    with transaction.atomic():
        _dupliquer_question(q)
    return JsonResponse({"ok": True})


@staff_member_required
@require_POST
def api_groupe_dupliquer(request, gid):
    g = get_object_or_404(Groupe, pk=gid)
    with transaction.atomic():
        dernier = Groupe.objects.order_by("-ordre").first()
        copie = Groupe.objects.create(
            titre=(g.titre + " (copie)") if g.titre else "",
            consigne=g.consigne, media=g.media, portee=g.portee,
            inclure_tirage=g.inclure_tirage, active=g.active,
            ordre=(dernier.ordre + 1) if dernier else 0,
        )
        for q in g.questions.order_by("ordre", "id"):
            _dupliquer_question(q, groupe=copie)
    return JsonResponse({"id": copie.id})


@staff_member_required
@require_POST
def api_reordonner(request):
    """
    Enregistre l'ordre issu du drag & drop.
    Payload : {"groupes": [{"id", "questions": [qid,...]}, ...], "sans_groupe": [qid,...]}
    """
    d = _corps_json(request)
    for i, g in enumerate(d.get("groupes", [])):
        Groupe.objects.filter(pk=g["id"]).update(ordre=i)
        for j, qid in enumerate(g.get("questions", [])):
            Question.objects.filter(pk=qid).update(groupe_id=g["id"], ordre=j)
    for j, qid in enumerate(d.get("sans_groupe", [])):
        Question.objects.filter(pk=qid).update(groupe_id=None, ordre=j)
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Construction dans l'interface du site (plus de passage par /admin).
# ---------------------------------------------------------------------------
@staff_member_required
def question_form(request, qid=None):
    """Création / édition d'une question (champs + choix + sous-questions)."""
    instance = get_object_or_404(Question, pk=qid) if qid else None

    if request.method == "POST":
        form = QuestionForm(request.POST, instance=instance)
        choix = ChoixFormSet(request.POST, instance=instance, prefix="choix")
        sousq = SousQuestionFormSet(request.POST, instance=instance, prefix="sousq")
        if form.is_valid():
            question = form.save(commit=False)
            if instance is None:
                dernier = Question.objects.filter(groupe=question.groupe).order_by("-ordre").first()
                question.ordre = (dernier.ordre + 1) if dernier else 0
            # On rattache les formsets à l'instance (créée ou existante).
            choix = ChoixFormSet(request.POST, instance=question, prefix="choix")
            sousq = SousQuestionFormSet(request.POST, instance=question, prefix="sousq")
            if choix.is_valid() and sousq.is_valid():
                question.save()
                choix.instance = question
                sousq.instance = question
                choix.save()
                sousq.save()
                messages.success(request, "Question enregistrée.")
                return redirect("editeur")
    else:
        groupe_id = request.GET.get("groupe")
        form = QuestionForm(instance=instance, initial=({"groupe": groupe_id} if groupe_id else None))
        choix = ChoixFormSet(instance=instance, prefix="choix")
        sousq = SousQuestionFormSet(instance=instance, prefix="sousq")

    return render(request, "etude/editeur_question.html", {
        "form": form, "choix": choix, "sousq": sousq, "question": instance,
    })


_EXT_AUDIO = {".mp3", ".wav", ".ogg", ".oga", ".m4a", ".aac", ".flac"}


def _type_media(nom):
    return Media.AUDIO if os.path.splitext(nom)[1].lower() in _EXT_AUDIO else Media.VIDEO


def _code_unique(base):
    base = slugify(base)[:60] or "media"
    code, i = base, 2
    while Media.objects.filter(code=code).exists():
        code, i = f"{base}-{i}", i + 1
    return code


def _creer_media_depuis_upload(data):
    """Enregistre le(s) fichier(s) sous MEDIA_ROOT et crée le Média."""
    storage = FileSystemStorage()  # lit settings.MEDIA_ROOT à l'appel
    f = data["fichier"]
    type_media = _type_media(f.name)
    dossier = "videos" if type_media == Media.VIDEO else "audios"
    chemin = storage.save(f"{dossier}/{get_valid_filename(f.name)}", f).replace("\\", "/")

    vtt = ""
    if data.get("vtt"):
        vtt = storage.save(f"soustitres/{get_valid_filename(data['vtt'].name)}", data["vtt"]).replace("\\", "/")

    base = data.get("code") or os.path.splitext(os.path.basename(f.name))[0]
    Media.objects.create(
        code=_code_unique(base), titre=data.get("titre", ""),
        type_media=type_media, fichier=chemin, vtt=vtt,
    )


@staff_member_required
def medias(request):
    """Bibliothèque de médias : téléversement OU référence par chemin + liste."""
    upload = MediaUploadForm()
    form = MediaForm()
    if request.method == "POST":
        if "televerser" in request.POST:
            upload = MediaUploadForm(request.POST, request.FILES)
            if upload.is_valid():
                _creer_media_depuis_upload(upload.cleaned_data)
                messages.success(request, "Média téléversé.")
                return redirect("editeur_medias")
        else:
            form = MediaForm(request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, "Média ajouté.")
                return redirect("editeur_medias")
    return render(request, "etude/editeur_medias.html", {
        "upload": upload, "form": form, "medias": Media.objects.all(),
    })


@staff_member_required
@require_POST
def media_supprimer(request, mid):
    get_object_or_404(Media, pk=mid).delete()  # SET_NULL sur les références
    messages.success(request, "Média supprimé.")
    return redirect("editeur_medias")


@staff_member_required
def resultats(request):
    """Tableau de bord : compteurs + accès aux exports (réservé au staff)."""
    from django.db.models import Count, Q
    groupes = (
        Groupe.objects.order_by("ordre", "id")
        .annotate(nb_termines=Count("passages", filter=Q(passages__fin__isnull=False)))
    )
    return render(request, "etude/editeur_resultats.html", {
        "nb_participants": Participant.objects.count(),
        "nb_consentements": Participant.objects.filter(consentement=True).count(),
        "nb_passages": Passage.objects.filter(fin__isnull=False).count(),
        "groupes": groupes,
    })


@staff_member_required
def export_passages(request):
    return exports.csv_passages(Passage.objects.all())


@staff_member_required
def export_participants(request):
    return exports.csv_participants(Participant.objects.all())


@staff_member_required
def parametres(request):
    """Paramètres de l'étude (textes + déroulé)."""
    cfg = Configuration.charger()
    form = ConfigurationForm(request.POST or None, instance=cfg)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Paramètres enregistrés.")
        return redirect("editeur_parametres")
    return render(request, "etude/editeur_parametres.html", {"form": form})
