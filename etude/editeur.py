"""
Éditeur visuel du questionnaire (réservé au staff).

La page `editeur()` rend l'interface ; les autres vues sont des points d'API
JSON appelés en fetch() par le front :
  - api_groupe              : créer / modifier un groupe
  - api_groupe_supprimer    : supprimer un groupe (ses questions repassent « sans groupe »)
  - api_question            : créer / modifier une question (+ ses choix)
  - api_question_supprimer  : supprimer une question (refusé si des réponses existent)
  - api_reordonner          : enregistrer l'ordre (drag & drop) des groupes et questions

Toutes les écritures passent par l'admin Django pour l'authentification
(staff_member_required) et sont protégées CSRF.
"""
from __future__ import annotations

import json

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import ProtectedError
from django.http import JsonResponse, Http404
from django.shortcuts import render, get_object_or_404
from django.views.decorators.http import require_POST

from .models import Groupe, Question, Choix, Media, Reponse


def _serialiser_question(q):
    return {
        "id": q.id,
        "code": q.code,
        "libelle": q.libelle,
        "aide": q.aide,
        "type": q.type,
        "portee": q.portee,
        "obligatoire": q.obligatoire,
        "active": q.active,
        "ordre": q.ordre,
        "groupe_id": q.groupe_id,
        "min_val": q.min_val,
        "max_val": q.max_val,
        "label_min": q.label_min,
        "label_max": q.label_max,
        "choix_multiple": q.choix_multiple,
        "media_id": q.media_id,
        "choix": [
            {"id": c.id, "valeur": c.valeur, "libelle": c.libelle, "ordre": c.ordre}
            for c in q.choix.all()
        ],
    }


def _donnees():
    """Structure complète du questionnaire pour l'initialisation du front."""
    questions = list(
        Question.objects.select_related("groupe")
        .prefetch_related("choix")
        .order_by("ordre", "id")
    )
    groupes = list(Groupe.objects.order_by("ordre", "id"))
    return {
        "groupes": [
            {
                "id": g.id,
                "titre": g.titre,
                "consigne": g.consigne,
                "nouvelle_page": g.nouvelle_page,
                "active": g.active,
                "questions": [_serialiser_question(q) for q in questions if q.groupe_id == g.id],
            }
            for g in groupes
        ],
        "sans_groupe": [_serialiser_question(q) for q in questions if q.groupe_id is None],
        "medias": [
            {"id": m.id, "code": m.code, "type": m.type_media} for m in Media.objects.all()
        ],
        "types_question": [
            {"valeur": Question.ECHELLE, "libelle": "Échelle"},
            {"valeur": Question.CHOIX, "libelle": "Choix"},
            {"valeur": Question.TEXTE, "libelle": "Texte"},
        ],
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
        # Nouveau groupe : placé en fin de liste.
        dernier = Groupe.objects.order_by("-ordre").first()
        groupe = Groupe(ordre=(dernier.ordre + 1) if dernier else 0)

    groupe.titre = d.get("titre", groupe.titre)
    groupe.consigne = d.get("consigne", groupe.consigne)
    if "nouvelle_page" in d:
        groupe.nouvelle_page = bool(d["nouvelle_page"])
    if "active" in d:
        groupe.active = bool(d["active"])
    groupe.save()
    return JsonResponse({"id": groupe.id})


@staff_member_required
@require_POST
def api_groupe_supprimer(request, gid):
    groupe = get_object_or_404(Groupe, pk=gid)
    # Les questions du groupe repassent « sans groupe » (FK SET_NULL).
    groupe.delete()
    return JsonResponse({"ok": True})


def _synchroniser_choix(question, choix_payload):
    """Met à jour les Choix d'une question à partir du payload (création/màj/suppression)."""
    if choix_payload is None:
        return
    vus = set()
    for i, c in enumerate(choix_payload):
        cid = c.get("id")
        valeur = (c.get("valeur") or "").strip()
        libelle = (c.get("libelle") or "").strip()
        if not (valeur or libelle):
            continue
        if cid:
            obj = Choix.objects.filter(pk=cid, question=question).first()
            if not obj:
                continue
        else:
            obj = Choix(question=question)
        obj.valeur = valeur or libelle
        obj.libelle = libelle or valeur
        obj.ordre = i
        obj.save()
        vus.add(obj.id)
    # Supprime les choix retirés côté éditeur.
    question.choix.exclude(id__in=vus).delete()


@staff_member_required
@require_POST
def api_question(request):
    d = _corps_json(request)
    qid = d.get("id")
    if qid:
        question = get_object_or_404(Question, pk=qid)
    else:
        groupe_id = d.get("groupe_id")
        dernier = Question.objects.filter(groupe_id=groupe_id).order_by("-ordre").first()
        question = Question(
            groupe_id=groupe_id,
            ordre=(dernier.ordre + 1) if dernier else 0,
            code=d.get("code") or _code_libre(),
            libelle=d.get("libelle") or "Nouvelle question",
        )

    if "groupe_id" in d:
        question.groupe_id = d["groupe_id"]
    for champ in ("code", "libelle", "aide", "type", "portee", "label_min", "label_max"):
        if champ in d and d[champ] is not None:
            setattr(question, champ, d[champ])
    for champ in ("obligatoire", "active", "choix_multiple"):
        if champ in d:
            setattr(question, champ, bool(d[champ]))
    for champ in ("min_val", "max_val"):
        if champ in d:
            val = d[champ]
            if val in (None, ""):
                setattr(question, champ, None)
            else:
                try:
                    setattr(question, champ, int(val))
                except (TypeError, ValueError):
                    return JsonResponse({"erreur": f"« {champ} » doit être un entier."}, status=400)
    if "media_id" in d:
        question.media_id = d["media_id"] or None

    try:
        question.save()
    except Exception as exc:  # ex. code non unique
        return JsonResponse({"erreur": f"Enregistrement impossible : {exc}"}, status=400)

    _synchroniser_choix(question, d.get("choix"))
    return JsonResponse({"id": question.id})


@staff_member_required
@require_POST
def api_question_supprimer(request, qid):
    question = get_object_or_404(Question, pk=qid)
    if Reponse.objects.filter(question=question).exists():
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


@staff_member_required
@require_POST
def api_reordonner(request):
    """
    Enregistre l'ordre issu du drag & drop.
    Payload : {
      "groupes": [{"id": gid, "questions": [qid, ...]}, ...],
      "sans_groupe": [qid, ...]
    }
    """
    d = _corps_json(request)
    for i, g in enumerate(d.get("groupes", [])):
        Groupe.objects.filter(pk=g["id"]).update(ordre=i)
        for j, qid in enumerate(g.get("questions", [])):
            Question.objects.filter(pk=qid).update(groupe_id=g["id"], ordre=j)
    for j, qid in enumerate(d.get("sans_groupe", [])):
        Question.objects.filter(pk=qid).update(groupe_id=None, ordre=j)
    return JsonResponse({"ok": True})


def _code_libre():
    """Génère un code de question unique du type q_1, q_2..."""
    i = Question.objects.count() + 1
    while Question.objects.filter(code=f"q_{i}").exists():
        i += 1
    return f"q_{i}"
