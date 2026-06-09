"""
Vues du parcours participant.

Flux :
  index  -> consentement + création du Participant (jeton en session)
  tache  -> tire un enregistrement, affiche la vidéo + le formulaire de questions
  soumettre (POST) -> enregistre les réponses, propose Continuer / Arrêter
  media_protege -> sert vidéo/VTT uniquement au participant qui a un jugement
                   en cours sur ce clip (X-Accel-Redirect en prod, direct en dev)
  fin    -> page de remerciement

L'accès protégé aux fichiers : voir media_protege(). En production, Django
ne sert pas la vidéo lui-même ; il renvoie un en-tête X-Accel-Redirect que
Nginx intercepte pour servir le fichier efficacement. En développement
(DEBUG=True, pas de Nginx), Django sert le fichier directement.
"""
import mimetypes
import os
import secrets

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.http import FileResponse, HttpResponse, Http404, HttpResponseForbidden
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import (
    Question, Groupe, Media, Enregistrement, Participant, Jugement,
    Reponse, ReponseProfil, CodeAcces,
)
from .selection import tirer_enregistrement


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
      - collectif : chaque accès crée un NOUVEAU participant (lien à partager) ;
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


def acces(request):
    """
    Barrière d'entrée : le participant saisit un code d'accès (individuel ou
    collectif). Voir aussi acces_lien() pour un lien cliquable sans saisie.
    """
    if request.session.get("acces_ok") and _participant_courant(request):
        return redirect("index")
    if request.method == "POST":
        saisi = request.POST.get("code", "").strip()
        code = CodeAcces.objects.filter(code=saisi, actif=True).first() if saisi else None
        if code is None:
            return render(request, "etude/acces.html", {"erreur": "Code d'accès incorrect."})
        _demarrer_session(request, code)
        return redirect("index")
    return render(request, "etude/acces.html")


def acces_lien(request, code):
    """
    Lien d'accès cliquable : /acces/<code>/. Évite la saisie manuelle. Sert
    aussi bien de lien collectif (à diffuser) que de lien personnel pour un
    code individuel. Si une session est déjà ouverte, on la reprend.
    """
    if request.session.get("acces_ok") and _participant_courant(request):
        return redirect("index")
    code_obj = CodeAcces.objects.filter(code=code, actif=True).first()
    if code_obj is None:
        return render(request, "etude/acces.html",
                      {"erreur": "Lien d'accès invalide ou expiré."})
    _demarrer_session(request, code_obj)
    return redirect("index")


def index(request):
    # Le consentement n'est accessible qu'après le code d'accès (qui a déjà
    # créé/restauré le Participant). On enregistre ici son consentement.
    participant = _participant_courant(request)
    if not request.session.get("acces_ok") or not participant:
        return redirect("acces")
    if request.method == "POST":
        if not participant.consentement:
            participant.consentement = True
            participant.save(update_fields=["consentement"])
        return redirect("profil")
    return render(request, "etude/index.html")


def _questions_profil():
    """Questions de portée profil, actives, dans l'ordre (groupe puis ordre)."""
    return list(
        Question.objects.filter(active=True, portee=Question.PROFIL)
        .order_by("groupe__ordre", "ordre", "id")
    )


def profil(request):
    """
    Questions de profil (âge, genre...), posées UNE seule fois après le
    consentement. Si elles sont déjà toutes répondues (ou s'il n'y en a pas),
    on passe directement à l'évaluation des extraits.
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

    return render(request, "etude/profil.html", {"blocs": _blocs_actifs(Question.PROFIL)})


@require_POST
def soumettre_profil(request):
    participant = _participant_courant(request)
    if not participant or not participant.consentement:
        return redirect("index")

    questions = _questions_profil()
    valeurs = {}
    for q in questions:
        if q.type == Question.CHOIX and q.choix_multiple:
            valeur = "|".join(request.POST.getlist(f"q_{q.id}"))
        else:
            valeur = request.POST.get(f"q_{q.id}", "").strip()
        if q.obligatoire and not valeur:
            return render(request, "etude/profil.html", {
                "blocs": _blocs_actifs(Question.PROFIL),
                "erreur": "Merci de répondre à toutes les questions obligatoires.",
            })
        valeurs[q] = valeur

    with transaction.atomic():
        for q, valeur in valeurs.items():
            ReponseProfil.objects.update_or_create(
                participant=participant, question=q, defaults={"valeur": valeur},
            )
    return redirect("tache")


def _blocs_actifs(portee=Question.EXTRAIT):
    """
    Construit les blocs du questionnaire pour une portée donnée : une liste
    ordonnée de {groupe, questions}. Les questions sans groupe (legacy) forment
    un bloc de tête. Les groupes actifs suivent, dans l'ordre, avec leurs
    questions de cette portée.
    """
    questions = list(
        Question.objects.filter(active=True, portee=portee)
        .select_related("groupe", "media")
        .prefetch_related("choix")
    )
    blocs = []
    sans_groupe = [q for q in questions if q.groupe_id is None]
    if sans_groupe:
        blocs.append({"groupe": None, "questions": sans_groupe})
    for g in Groupe.objects.filter(active=True).order_by("ordre", "id"):
        qs = [q for q in questions if q.groupe_id == g.id]
        if qs:
            blocs.append({"groupe": g, "questions": qs})
    return blocs


def _construire_pages():
    """
    Découpe les blocs en pages : un groupe marqué `nouvelle_page` commence une
    nouvelle page ; sinon il suit le précédent sur la même page. Retourne une
    liste de pages, chaque page étant une liste de blocs.
    """
    pages = []
    for bloc in _blocs_actifs(Question.EXTRAIT):
        g = bloc["groupe"]
        if pages and g is not None and g.nouvelle_page:
            pages.append([bloc])
        elif not pages:
            pages.append([bloc])
        else:
            pages[-1].append(bloc)
    return pages


def _page_courante(request, pages):
    page = request.session.get("page", 0)
    if not pages:
        return 0
    return max(0, min(page, len(pages) - 1))


def _contexte_tache(jugement, pages, page, **extra):
    ctx = {
        "jugement": jugement,
        "enregistrement": jugement.enregistrement,
        "blocs": pages[page] if pages else [],
        "page": page,
        "total_pages": len(pages),
        "derniere_page": page >= len(pages) - 1,
        # Le clip sujet (tiré) n'est montré qu'en première page.
        "afficher_clip": page == 0,
    }
    ctx.update(extra)
    return ctx


def tache(request):
    participant = _participant_courant(request)
    if not participant:
        return redirect("index")

    # Reprend un jugement déjà ouvert (clip affiché mais non terminé),
    # sinon en crée un nouveau par tirage pondéré (remet la pagination à zéro).
    jugement = participant.jugements.filter(fin__isnull=True).first()
    if not jugement:
        enr = tirer_enregistrement(participant)
        if enr is None:
            return redirect("fin")  # banque épuisée pour ce participant
        jugement = Jugement.objects.create(participant=participant, enregistrement=enr)
        request.session["page"] = 0

    pages = _construire_pages()
    page = _page_courante(request, pages)
    return render(request, "etude/tache.html", _contexte_tache(jugement, pages, page))


@require_POST
def soumettre(request):
    participant = _participant_courant(request)
    if not participant:
        return redirect("index")

    jugement = participant.jugements.filter(fin__isnull=True).first()
    if not jugement:
        return redirect("tache")

    pages = _construire_pages()
    page = _page_courante(request, pages)
    questions_page = [q for bloc in (pages[page] if pages else []) for q in bloc["questions"]]

    # On valide les questions de la PAGE courante avant d'écrire quoi que ce
    # soit : pas d'enregistrement partiel si une obligatoire manque.
    valeurs = {}
    for q in questions_page:
        if q.type == Question.CHOIX and q.choix_multiple:
            valeur = "|".join(request.POST.getlist(f"q_{q.id}"))
        else:
            valeur = request.POST.get(f"q_{q.id}", "").strip()
        if q.obligatoire and not valeur:
            return render(request, "etude/tache.html", _contexte_tache(
                jugement, pages, page,
                erreur="Merci de répondre à toutes les questions obligatoires.",
            ))
        valeurs[q] = valeur

    with transaction.atomic():
        for q, valeur in valeurs.items():
            Reponse.objects.update_or_create(
                jugement=jugement, question=q, defaults={"valeur": valeur},
            )
        # Page intermédiaire : on passe à la suivante sans clôturer.
        if page < len(pages) - 1:
            request.session["page"] = page + 1
            return redirect("tache")

        # Dernière page : clôture du jugement + incrément du compteur (F()).
        jugement.fin = timezone.now()
        jugement.save(update_fields=["fin"])
        Enregistrement.objects.filter(pk=jugement.enregistrement_id).update(
            nb_evaluations=F("nb_evaluations") + 1
        )

    request.session["page"] = 0
    reste = tirer_enregistrement(participant) is not None
    return render(request, "etude/continuer.html", {"reste": reste})


def fin(request):
    return render(request, "etude/fin.html")


def _type_contenu(kind, rel):
    """Content-Type d'un fichier média : VTT explicite, sinon deviné par extension."""
    if kind == "vtt":
        return "text/vtt"
    return mimetypes.guess_type(rel)[0] or "application/octet-stream"


def _servir(rel, content_type):
    """
    Sert un fichier média protégé.
      - PRODUCTION : délègue à Nginx via X-Accel-Redirect (ne bloque pas un worker).
      - DÉVELOPPEMENT : FileResponse direct.
    'rel' est un chemin relatif sous MEDIA_ROOT, défini en admin (pas par le participant).
    """
    if not settings.DEBUG:
        resp = HttpResponse()
        resp["Content-Type"] = content_type
        # 'rel' doit correspondre à une 'location' interne Nginx (voir README).
        resp["X-Accel-Redirect"] = f"/media-protege/{rel}"
        return resp

    chemin = os.path.join(settings.MEDIA_ROOT, rel)
    if not os.path.exists(chemin):
        raise Http404
    return FileResponse(open(chemin, "rb"), content_type=content_type)


def media_protege(request, kind, code):
    """
    Sert le clip sujet ('video') ou son sous-titre ('vtt'), uniquement si le
    participant a un jugement EN COURS sur ce clip.
    """
    participant = _participant_courant(request)
    if not participant:
        return HttpResponseForbidden("Accès réservé aux participants.")

    enr = Enregistrement.objects.filter(code=code, actif=True).first()
    if not enr:
        raise Http404

    autorise = participant.jugements.filter(
        enregistrement=enr, fin__isnull=True
    ).exists()
    if not autorise:
        return HttpResponseForbidden("Ce contenu n'est pas accessible.")

    rel = enr.fichier_video if kind == "video" else enr.fichier_vtt
    if not rel:
        raise Http404
    return _servir(rel, _type_contenu(kind, rel))


def media_question(request, code, kind):
    """
    Sert le média (audio/vidéo) ou le VTT d'une question, uniquement si le
    participant a un jugement EN COURS et que ce média est rattaché à une
    question active. Le type de contenu est deviné par l'extension (mp3, wav,
    mp4, webm...).
    """
    participant = _participant_courant(request)
    if not participant:
        return HttpResponseForbidden("Accès réservé aux participants.")

    if not participant.jugements.filter(fin__isnull=True).exists():
        return HttpResponseForbidden("Ce contenu n'est pas accessible.")

    media = Media.objects.filter(code=code).first()
    if not media:
        raise Http404
    # Le média doit être rattaché à au moins une question active du questionnaire.
    if not Question.objects.filter(active=True, media=media).exists():
        return HttpResponseForbidden("Ce contenu n'est pas accessible.")

    rel = media.vtt if kind == "vtt" else media.fichier
    if not rel:
        raise Http404
    return _servir(rel, _type_contenu(kind, rel))
