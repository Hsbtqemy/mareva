"""
Génération des exports CSV (réutilisée par l'admin et la page Résultats du site).

  - csv_passages : une ligne par passage (participant × groupe), format large
    repivoté ; matrice dépliée en une colonne par sous-question.
  - csv_participants : une ligne par participant (profil + nb de groupes faits).
"""
from __future__ import annotations

import csv

from django.http import HttpResponse

from .models import Question, Groupe


def _questions_triees():
    return list(
        Question.objects.select_related("groupe").prefetch_related("sous_questions")
        .order_by("groupe__ordre", "ordre", "id")
    )


def _colonnes(questions):
    """Une colonne par question, sauf matrice → une colonne par sous-question."""
    cols = []
    for q in questions:
        if q.type == Question.MATRICE:
            cols.extend(sq.code for sq in q.sous_questions.all())
        else:
            cols.append(q.code)
    return cols


def _par_code(reponses):
    """Réponses indexées par code de colonne (sous-question si matrice, sinon question)."""
    d = {}
    for r in reponses:
        sq = getattr(r, "sous_question", None)
        d[sq.code if sq else r.question.code] = r.valeur
    return d


def csv_passages(passages):
    toutes = _questions_triees()
    q_profil = [q for q in toutes if q.groupe and q.groupe.portee == Groupe.PROFIL]
    q_standard = [q for q in toutes if not (q.groupe and q.groupe.portee == Groupe.PROFIL)]
    cols_profil = _colonnes(q_profil)
    cols_standard = _colonnes(q_standard)

    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="passages.csv"'
    w = csv.writer(resp)
    w.writerow([
        "id_passage", "jeton_participant", "consentement", "code_groupe", "debut", "fin",
    ] + cols_profil + cols_standard)

    passages = passages.select_related("participant", "groupe").prefetch_related(
        "reponses__question", "reponses__sous_question",
        "participant__reponses_profil__question",
    )
    for p in passages:
        par_reponse = _par_code(p.reponses.all())
        par_profil = _par_code(p.participant.reponses_profil.all())
        w.writerow([
            p.id, p.participant.jeton, p.participant.consentement,
            p.groupe.titre or p.groupe_id,
            p.debut.isoformat(), p.fin.isoformat() if p.fin else "",
        ] + [par_profil.get(c, "") for c in cols_profil]
          + [par_reponse.get(c, "") for c in cols_standard])
    return resp


def csv_participants(participants):
    """Une ligne par participant : identité + réponses de profil + nb de groupes faits."""
    cols = [q.code for q in _questions_triees()
            if q.groupe and q.groupe.portee == Groupe.PROFIL]

    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="participants.csv"'
    w = csv.writer(resp)
    w.writerow(["jeton_participant", "consentement", "cree_le", "nb_groupes_repondus"] + cols)

    participants = participants.prefetch_related("reponses_profil__question", "passages")
    for pa in participants:
        prof = {r.question.code: r.valeur for r in pa.reponses_profil.all()}
        nb = sum(1 for pas in pa.passages.all() if pas.fin)
        w.writerow([
            pa.jeton, pa.consentement, pa.cree_le.isoformat(), nb,
        ] + [prof.get(c, "") for c in cols])
    return resp
