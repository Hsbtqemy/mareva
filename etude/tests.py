"""
Tests bout-en-bout du nouveau modèle : la boucle tire des GROUPES.

Couverture : accès (codes/liens) → consentement → profil (une fois) → tirage
d'un groupe → pagination par saut_de_page → clôture du groupe + compteur +
réponses → média protégé → tirage suivant excluant les groupes faits →
épuisement → fin. Plus : sélection, max_groupes, export CSV, éditeur, config.

Sous test, DEBUG=False : media_question renvoie l'en-tête X-Accel-Redirect
(pas besoin de fichier réel sur disque).
"""
from __future__ import annotations

import csv
import io
import json
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .admin import PassageAdmin
from .models import (
    Choix, CodeAcces, Configuration, Groupe, Media,
    Participant, Passage, Question, Reponse, ReponseProfil, SousQuestion,
)
from .selection import tirer_groupe


def _groupe(titre="G", portee=Groupe.STANDARD, **kw):
    return Groupe.objects.create(titre=titre, portee=portee, **kw)


def _question(groupe, code, type=Question.TEXTE, **kw):
    return Question.objects.create(groupe=groupe, code=code, libelle=code, type=type, **kw)


class AccesTest(TestCase):
    def setUp(self):
        self.code = CodeAcces.objects.create(code="entree-1")

    def test_gate(self):
        r = self.client.post(reverse("acces"), {"code": "mauvais"})
        self.assertContains(r, "incorrect")
        self.assertEqual(Participant.objects.count(), 0)
        r = self.client.post(reverse("acces"), {"code": "entree-1"})
        self.assertRedirects(r, reverse("index"))
        self.code.refresh_from_db()
        self.assertEqual(self.client.session["jeton"], self.code.participant.jeton)

    def test_lien_individuel_restaure(self):
        self.client.get(reverse("acces_lien", args=["entree-1"]))
        self.code.refresh_from_db()
        autre = self.client.__class__()
        autre.get(reverse("acces_lien", args=["entree-1"]))
        self.assertEqual(autre.session["jeton"], self.code.participant.jeton)
        self.assertEqual(Participant.objects.count(), 1)

    def test_lien_collectif(self):
        col = CodeAcces.objects.create(code="ouvert", collectif=True)
        c1, c2 = self.client.__class__(), self.client.__class__()
        c1.get(reverse("acces_lien", args=["ouvert"]))
        c2.get(reverse("acces_lien", args=["ouvert"]))
        self.assertNotEqual(c1.session["jeton"], c2.session["jeton"])
        self.assertEqual(Participant.objects.count(), 2)
        col.refresh_from_db()
        self.assertIsNone(col.participant)

    def test_lien_invalide(self):
        r = self.client.get(reverse("acces_lien", args=["inconnu"]))
        self.assertContains(r, "invalide")


class ParcoursTest(TestCase):
    def setUp(self):
        CodeAcces.objects.create(code="e")
        self.g1 = _groupe("Groupe A", ordre=0)
        self.q1 = _question(self.g1, "a1", obligatoire=True)
        self.g2 = _groupe("Groupe B", ordre=1)
        self.q2 = _question(self.g2, "b1", obligatoire=True)

    def _entrer(self):
        self.client.post(reverse("acces"), {"code": "e"})
        self.client.post(reverse("index"))  # consentement → profil → tache

    def test_boucle_groupes(self):
        # Sans accès, le consentement renvoie à la barrière.
        self.assertRedirects(self.client.get(reverse("index")), reverse("acces"))

        self._entrer()
        # Pas de groupe profil → consentement mène directement à la tâche.
        participant = Participant.objects.get(jeton=self.client.session["jeton"])

        # 1er groupe tiré.
        r = self.client.get(reverse("tache"))
        self.assertEqual(r.status_code, 200)
        passage = participant.passages.get(fin__isnull=True)
        premier = passage.groupe
        question = premier.questions.first()

        # Soumission (groupe à une page) → clôture + compteur + réponse.
        r = self.client.post(reverse("soumettre"), {f"q_{question.id}": "ok"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Continuer")  # il reste un groupe
        passage.refresh_from_db(); premier.refresh_from_db()
        self.assertIsNotNone(passage.fin)
        self.assertEqual(premier.nb_evaluations, 1)
        self.assertEqual(passage.reponses.get(question=question).valeur, "ok")

        # 2e tirage : exclut le groupe déjà fait.
        r = self.client.get(reverse("tache"))
        nouveau = participant.passages.get(fin__isnull=True).groupe
        self.assertNotEqual(nouveau, premier)

        # On termine le second → plus de groupe → fin.
        q2 = nouveau.questions.first()
        self.client.post(reverse("soumettre"), {f"q_{q2.id}": "ok"})
        self.assertRedirects(self.client.get(reverse("tache")), reverse("fin"))

    def test_obligatoire_manquant(self):
        self._entrer()
        self.client.get(reverse("tache"))
        r = self.client.post(reverse("soumettre"), {})
        self.assertContains(r, "obligatoires")
        self.assertEqual(Reponse.objects.count(), 0)
        self.assertFalse(Passage.objects.filter(fin__isnull=False).exists())

    def test_groupe_sans_question_ne_casse_pas(self):
        """Un groupe sans question active se rend et se clôt sans erreur."""
        Question.objects.all().delete()  # g1/g2 deviennent vides
        self._entrer()
        r = self.client.get(reverse("tache"))
        self.assertEqual(r.status_code, 200)
        r = self.client.post(reverse("soumettre"), {})
        self.assertEqual(r.status_code, 200)  # groupe clôturé, page Continuer/Arrêter
        self.assertTrue(Passage.objects.filter(fin__isnull=False).exists())


class PaginationTest(TestCase):
    """Les écrans (saut_de_page) sont gérés côté client ; le groupe est posté en une fois."""

    def setUp(self):
        CodeAcces.objects.create(code="e")
        self.g = _groupe("G", ordre=0, inclure_tirage=True)
        self.qa = _question(self.g, "a", obligatoire=True, ordre=0)
        self.qb = _question(self.g, "b", obligatoire=True, ordre=1, saut_de_page=True)

    def test_marqueur_ecran_et_soumission_unique(self):
        self.client.post(reverse("acces"), {"code": "e"})
        self.client.post(reverse("index"))
        # La page rend les deux questions, avec un marqueur de saut d'écran sur qb.
        r = self.client.get(reverse("tache"))
        html = r.content.decode()
        self.assertIn(f'name="q_{self.qa.id}"', html)
        self.assertIn(f'name="q_{self.qb.id}"', html)
        self.assertIn('data-break="1"', html)
        # Tout le groupe posté d'un coup → clôture + deux réponses.
        r = self.client.post(reverse("soumettre"), {f"q_{self.qa.id}": "1", f"q_{self.qb.id}": "2"})
        self.assertEqual(r.status_code, 200)
        self.g.refresh_from_db()
        self.assertEqual(self.g.nb_evaluations, 1)
        passage = Passage.objects.get()
        self.assertEqual({r.question.code: r.valeur for r in passage.reponses.all()},
                         {"a": "1", "b": "2"})


class ChoixValeurTest(TestCase):
    def test_valeur_reprend_le_libelle_si_vide(self):
        g = _groupe("G")
        q = _question(g, "q", type=Question.CHOIX)
        c = Choix.objects.create(question=q, libelle="Manger")  # valeur laissée vide
        self.assertEqual(c.valeur, "Manger")
        c2 = Choix.objects.create(question=q, valeur="AO01", libelle="Socializer")
        self.assertEqual(c2.valeur, "AO01")  # valeur explicite conservée


class ValidationTest(TestCase):
    """Intégrité des données : valeurs hors bornes / hors liste refusées."""

    def setUp(self):
        CodeAcces.objects.create(code="e")
        self.g = _groupe("G", ordre=0)
        self.ech = _question(self.g, "ech", type=Question.ECHELLE, obligatoire=True, ordre=0,
                             min_val=1, max_val=5)
        self.ch = _question(self.g, "ch", type=Question.CHOIX, obligatoire=True, ordre=1)
        for v in ("a", "b"):
            Choix.objects.create(question=self.ch, valeur=v, libelle=v.upper())

    def _entrer_tache(self):
        self.client.post(reverse("acces"), {"code": "e"})
        self.client.post(reverse("index"))
        self.client.get(reverse("tache"))

    def _poste(self, **extra):
        data = {f"q_{self.ech.id}": "3", f"q_{self.ch.id}": "a"}
        data.update(extra)
        return self.client.post(reverse("soumettre"), data)

    def test_echelle_hors_bornes_refusee(self):
        self._entrer_tache()
        r = self._poste(**{f"q_{self.ech.id}": "9"})  # max 5
        self.assertContains(r, "hors bornes")
        self.assertEqual(Reponse.objects.count(), 0)

    def test_echelle_non_numerique_refusee(self):
        self._entrer_tache()
        r = self._poste(**{f"q_{self.ech.id}": "abc"})
        self.assertContains(r, "invalide")
        self.assertEqual(Reponse.objects.count(), 0)

    def test_choix_hors_liste_refuse(self):
        self._entrer_tache()
        r = self._poste(**{f"q_{self.ch.id}": "zzz"})
        self.assertContains(r, "invalide")
        self.assertEqual(Reponse.objects.count(), 0)

    def test_valeurs_valides_acceptees(self):
        self._entrer_tache()
        r = self._poste()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Reponse.objects.filter(question=self.ech).first().valeur, "3")


class MatriceTest(TestCase):
    def setUp(self):
        CodeAcces.objects.create(code="e")
        self.g = _groupe("G", ordre=0)
        self.qm = _question(self.g, "roles", type=Question.MATRICE, obligatoire=True)
        for v, l in [("AO01", "Socializer"), ("AO02", "Achiever")]:
            Choix.objects.create(question=self.qm, valeur=v, libelle=l)
        self.sq1 = SousQuestion.objects.create(question=self.qm, code="BLUE_role", libelle="BLUE")
        self.sq2 = SousQuestion.objects.create(question=self.qm, code="PINK_role", libelle="PINK")

    def test_matrice_une_reponse_par_ligne(self):
        self.client.post(reverse("acces"), {"code": "e"})
        self.client.post(reverse("index"))
        self.client.get(reverse("tache"))
        # Manque une ligne → refus, rien stocké.
        r = self.client.post(reverse("soumettre"), {f"q_{self.qm.id}_sq_{self.sq1.id}": "AO01"})
        self.assertContains(r, "obligatoires")
        self.assertEqual(Reponse.objects.count(), 0)
        # Les deux lignes → deux réponses, une par sous-question.
        self.client.post(reverse("soumettre"), {
            f"q_{self.qm.id}_sq_{self.sq1.id}": "AO01",
            f"q_{self.qm.id}_sq_{self.sq2.id}": "AO02",
        })
        passage = Passage.objects.get()
        reps = {r.sous_question.code: r.valeur for r in passage.reponses.all()}
        self.assertEqual(reps, {"BLUE_role": "AO01", "PINK_role": "AO02"})

    def test_export_matrice_colonnes_par_sous_question(self):
        p = Participant.objects.create(jeton="j", consentement=True)
        passage = Passage.objects.create(participant=p, groupe=self.g, fin=timezone.now())
        Reponse.objects.create(passage=passage, question=self.qm, sous_question=self.sq1, valeur="AO01")
        Reponse.objects.create(passage=passage, question=self.qm, sous_question=self.sq2, valeur="AO02")
        resp = PassageAdmin(Passage, None).exporter_csv(None, Passage.objects.all())
        rows = list(csv.reader(io.StringIO(resp.content.decode("utf-8"))))
        d = dict(zip(rows[0], rows[1]))
        self.assertIn("BLUE_role", rows[0])
        self.assertIn("PINK_role", rows[0])
        self.assertEqual(d["BLUE_role"], "AO01")
        self.assertEqual(d["PINK_role"], "AO02")


class TypesDiversTest(TestCase):
    """Cartes (multiple) et drag&drop : valeurs jointes par |."""

    def setUp(self):
        CodeAcces.objects.create(code="e")
        self.g = _groupe("G", ordre=0)
        self.qc = _question(self.g, "cartes", type=Question.CARTES, choix_multiple=True, obligatoire=True)
        for v in ("a", "b", "c"):
            Choix.objects.create(question=self.qc, valeur=v, libelle=v.upper())
        self.qd = _question(self.g, "rang", type=Question.DRAGDROP, obligatoire=True, ordre=1)
        for v in ("x", "y"):
            Choix.objects.create(question=self.qd, valeur=v, libelle=v.upper())

    def test_valeurs_jointes(self):
        self.client.post(reverse("acces"), {"code": "e"})
        self.client.post(reverse("index"))
        self.client.get(reverse("tache"))
        self.client.post(reverse("soumettre"), {
            f"q_{self.qc.id}": ["a", "c"],   # cartes multiples
            f"q_{self.qd.id}": "y|x",         # classement (champ caché)
        })
        passage = Passage.objects.get()
        reps = {r.question.code: r.valeur for r in passage.reponses.all()}
        self.assertEqual(reps["cartes"], "a|c")
        self.assertEqual(reps["rang"], "y|x")

    def test_dragdrop_boutons_clavier_rendus(self):
        self.client.post(reverse("acces"), {"code": "e"})
        self.client.post(reverse("index"))
        h = self.client.get(reverse("tache")).content.decode()
        self.assertIn("dd-monter", h)
        self.assertIn("dd-descendre", h)
        self.assertIn('aria-label="Monter', h)
        self.assertIn('aria-label="Descendre', h)


class ProfilTest(TestCase):
    def setUp(self):
        CodeAcces.objects.create(code="e")
        self.gp = _groupe("Profil", portee=Groupe.PROFIL, ordre=0)
        self.age = _question(self.gp, "age", obligatoire=True)
        self.gs = _groupe("Standard", ordre=1)
        self.qs = _question(self.gs, "s1", obligatoire=True)

    def _entrer(self):
        self.client.post(reverse("acces"), {"code": "e"})
        self.client.post(reverse("index"))

    def test_profil_une_fois(self):
        self._entrer()
        r = self.client.get(reverse("profil"))
        self.assertContains(r, "age")
        r = self.client.post(reverse("soumettre_profil"), {f"q_{self.age.id}": "30"})
        self.assertRedirects(r, reverse("tache"))
        participant = Participant.objects.get(jeton=self.client.session["jeton"])
        self.assertEqual(participant.reponses_profil.get(question=self.age).valeur, "30")
        # Déjà rempli → profil saute à la tâche.
        self.assertRedirects(self.client.get(reverse("profil")), reverse("tache"))
        # Le groupe tiré (standard) ne contient pas la question de profil.
        r = self.client.get(reverse("tache"))
        self.assertNotContains(r, f'name="q_{self.age.id}"')
        self.assertContains(r, f'name="q_{self.qs.id}"')


class SelectionTest(TestCase):
    def setUp(self):
        self.p = Participant.objects.create(jeton="j", consentement=True)

    def test_exclut_faits_et_non_standard(self):
        g1 = _groupe("A")
        g2 = _groupe("B")
        _groupe("Profil", portee=Groupe.PROFIL)            # exclu : profil
        _groupe("Off", inclure_tirage=False)               # exclu : hors tirage
        _groupe("Inactif", active=False)                   # exclu : inactif
        # Marque g1 comme fait.
        Passage.objects.create(participant=self.p, groupe=g1, fin=timezone.now())
        tire = tirer_groupe(self.p)
        self.assertEqual(tire, g2)
        Passage.objects.create(participant=self.p, groupe=g2, fin=timezone.now())
        self.assertIsNone(tirer_groupe(self.p))

    def test_ordre_fixe(self):
        cfg = Configuration.charger(); cfg.ordre_groupes_aleatoire = False; cfg.save()
        gb = _groupe("B", ordre=2)
        ga = _groupe("A", ordre=1)
        self.assertEqual(tirer_groupe(self.p), ga)  # plus petit ordre d'abord


class MaxGroupesTest(TestCase):
    def setUp(self):
        CodeAcces.objects.create(code="e")
        cfg = Configuration.charger(); cfg.max_groupes = 1; cfg.save()
        self.g1 = _groupe("A", ordre=0); _question(self.g1, "a1", obligatoire=False)
        self.g2 = _groupe("B", ordre=1); _question(self.g2, "b1", obligatoire=False)

    def test_limite(self):
        self.client.post(reverse("acces"), {"code": "e"})
        self.client.post(reverse("index"))
        self.client.get(reverse("tache"))
        q = Passage.objects.get().groupe.questions.first()
        self.client.post(reverse("soumettre"), {f"q_{q.id}": "x"})
        # 1 groupe fait, max=1 → la tâche redirige vers la fin.
        self.assertRedirects(self.client.get(reverse("tache")), reverse("fin"))


class MediaTest(TestCase):
    def setUp(self):
        CodeAcces.objects.create(code="e")
        self.gm = Media.objects.create(code="gv", type_media="video", fichier="videos/g.mp4")
        self.g = _groupe("A", ordre=0, inclure_tirage=True, media=self.gm)  # vidéo de groupe
        self.m = Media.objects.create(code="m1", type_media="audio", fichier="medias/a.mp3")
        self.q = _question(self.g, "a1", obligatoire=False, media=self.m)
        # Média rattaché à un AUTRE groupe, hors tirage (jamais le groupe en cours).
        self.g2 = _groupe("B", ordre=1, inclure_tirage=False)
        self.m2 = Media.objects.create(code="m2", fichier="medias/b.mp4")
        _question(self.g2, "b1", media=self.m2)

    def test_media_autorise_et_refuse(self):
        self.client.post(reverse("acces"), {"code": "e"})
        self.client.post(reverse("index"))
        self.client.get(reverse("tache"))  # ouvre un passage sur g (seul tirable)
        # Vidéo du groupe en cours : autorisée.
        rg = self.client.get(reverse("media_question", args=["fichier", "gv"]))
        self.assertEqual(rg.status_code, 200)
        self.assertEqual(rg["X-Accel-Redirect"], "/media-protege/videos/g.mp4")
        # Média d'une question du groupe en cours : autorisé.
        self.assertEqual(self.client.get(reverse("media_question", args=["fichier", "m1"])).status_code, 200)
        # Média d'un autre groupe : refusé.
        self.assertEqual(self.client.get(reverse("media_question", args=["fichier", "m2"])).status_code, 403)

    def test_media_sans_passage(self):
        self.assertEqual(self.client.get(reverse("media_question", args=["fichier", "gv"])).status_code, 403)


class ExportTest(TestCase):
    def test_export_large(self):
        gp = _groupe("Profil", portee=Groupe.PROFIL, ordre=0)
        age = _question(gp, "age")
        gs = _groupe("Standard", ordre=1)
        s1 = _question(gs, "s1")
        p = Participant.objects.create(jeton="jeton-x", consentement=True)
        ReponseProfil.objects.create(participant=p, question=age, valeur="42")
        passage = Passage.objects.create(participant=p, groupe=gs, fin=timezone.now())
        Reponse.objects.create(passage=passage, question=s1, valeur="oui")

        resp = PassageAdmin(Passage, None).exporter_csv(None, Passage.objects.all())
        rows = list(csv.reader(io.StringIO(resp.content.decode("utf-8"))))
        entete, ligne = rows[0], rows[1]
        self.assertEqual(entete, [
            "id_passage", "jeton_participant", "consentement",
            "code_groupe", "debut", "fin", "age", "s1",
        ])
        d = dict(zip(entete, ligne))
        self.assertEqual(d["jeton_participant"], "jeton-x")
        self.assertEqual(d["code_groupe"], "Standard")
        self.assertEqual(d["age"], "42")   # profil recopié
        self.assertEqual(d["s1"], "oui")


class ConfigurationTest(TestCase):
    def test_singleton_et_neutre(self):
        a = Configuration.charger(); b = Configuration.charger()
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(Configuration.objects.count(), 1)
        for t in (a.nom_etude, a.titre_accueil, a.description):
            self.assertNotIn("percept", t.lower())

    def test_textes_personnalises(self):
        cfg = Configuration.charger()
        cfg.nom_etude = "Sondage X"; cfg.titre_accueil = "Salut"; cfg.save()
        CodeAcces.objects.create(code="e")
        self.client.post(reverse("acces"), {"code": "e"})
        r = self.client.get(reverse("index"))
        self.assertContains(r, "Sondage X")
        self.assertContains(r, "Salut")


class EditeurTest(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("chef", password="x", is_staff=True)
        self.client.force_login(self.staff)

    def test_reserve_au_staff(self):
        anon = self.client.__class__()
        r = anon.get(reverse("editeur"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admin/login", r["Location"])

    def test_creer_groupe_et_reordonner(self):
        r = self.client.post(reverse("editeur_groupe"),
                             data=json.dumps({"titre": "G", "portee": "profil"}),
                             content_type="application/json")
        gid = r.json()["id"]
        g = Groupe.objects.get(pk=gid)
        self.assertEqual(g.portee, "profil")
        qa = _question(g, "a", ordre=0)
        qb = _question(g, "b", ordre=1)
        self.client.post(reverse("editeur_ordre"),
                         data=json.dumps({"groupes": [{"id": gid, "questions": [qb.id, qa.id]}], "sans_groupe": []}),
                         content_type="application/json")
        qa.refresh_from_db(); qb.refresh_from_db()
        self.assertEqual((qb.ordre, qa.ordre), (0, 1))

    def test_toggle_saut_de_page(self):
        g = _groupe("G"); q = _question(g, "a")
        self.client.post(reverse("editeur_question"),
                         data=json.dumps({"id": q.id, "saut_de_page": True}),
                         content_type="application/json")
        q.refresh_from_db()
        self.assertTrue(q.saut_de_page)

    def test_suppression_protegee(self):
        g = _groupe("G"); q = _question(g, "a")
        p = Participant.objects.create(jeton="j")
        passage = Passage.objects.create(participant=p, groupe=g, fin=timezone.now())
        Reponse.objects.create(passage=passage, question=q, valeur="v")
        r = self.client.post(reverse("editeur_question_supprimer", args=[q.id]),
                             data="{}", content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(Question.objects.filter(pk=q.id).exists())


class EditeurSitePagesTest(TestCase):
    """Construction dans l'interface du site (sans /admin)."""

    def setUp(self):
        self.staff = User.objects.create_user("chef", password="x", is_staff=True)
        self.client.force_login(self.staff)
        self.g = _groupe("G", ordre=0)

    def test_pages_reservees_au_staff(self):
        anon = self.client.__class__()
        for nom in ("editeur_question_nouveau", "editeur_medias", "editeur_parametres"):
            r = anon.get(reverse(nom))
            self.assertIn("/admin/login", r["Location"])

    def test_creer_question_avec_choix(self):
        r = self.client.post(reverse("editeur_question_nouveau"), {
            "groupe": self.g.id, "code": "q_new", "libelle": "Nouvelle", "type": "choix",
            "ordre": 0,
            "choix-TOTAL_FORMS": "2", "choix-INITIAL_FORMS": "0",
            "choix-MIN_NUM_FORMS": "0", "choix-MAX_NUM_FORMS": "1000",
            "choix-0-ordre": "0", "choix-0-valeur": "o", "choix-0-libelle": "Oui",
            "choix-1-ordre": "1", "choix-1-valeur": "n", "choix-1-libelle": "Non",
            "sousq-TOTAL_FORMS": "0", "sousq-INITIAL_FORMS": "0",
            "sousq-MIN_NUM_FORMS": "0", "sousq-MAX_NUM_FORMS": "1000",
        })
        self.assertRedirects(r, reverse("editeur"))
        q = Question.objects.get(code="q_new")
        self.assertEqual(q.groupe_id, self.g.id)
        self.assertEqual(q.choix.count(), 2)

    def test_televerser_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(MEDIA_ROOT=tmp):
                import os
                f = SimpleUploadedFile("Mon Clip.mp4", b"\x00\x01donnees", content_type="video/mp4")
                vtt = SimpleUploadedFile("st.vtt", b"WEBVTT\n", content_type="text/vtt")
                r = self.client.post(reverse("editeur_medias"),
                                     {"televerser": "1", "fichier": f, "vtt": vtt, "code": "", "titre": ""})
                self.assertRedirects(r, reverse("editeur_medias"))
                m = Media.objects.get()
                self.assertEqual(m.type_media, "video")
                self.assertEqual(m.code, "mon-clip")           # dérivé du nom
                self.assertTrue(m.fichier.startswith("videos/"))
                self.assertTrue(m.vtt.startswith("soustitres/"))
                self.assertTrue(os.path.exists(os.path.join(tmp, m.fichier)))

    def test_televerser_audio_detecte(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(MEDIA_ROOT=tmp):
                f = SimpleUploadedFile("son.mp3", b"\x00\x01", content_type="audio/mpeg")
                self.client.post(reverse("editeur_medias"), {"televerser": "1", "fichier": f})
                m = Media.objects.get()
                self.assertEqual(m.type_media, "audio")
                self.assertTrue(m.fichier.startswith("audios/"))

    def test_suppression_media_efface_le_fichier(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(MEDIA_ROOT=tmp):
                f = SimpleUploadedFile("clip.mp4", b"x", content_type="video/mp4")
                self.client.post(reverse("editeur_medias"), {"televerser": "1", "fichier": f})
                m = Media.objects.get()
                chemin = os.path.join(tmp, m.fichier)
                self.assertTrue(os.path.exists(chemin))
                self.client.post(reverse("editeur_media_supprimer", args=[m.id]))
                self.assertFalse(Media.objects.filter(pk=m.id).exists())
                self.assertFalse(os.path.exists(chemin))  # fichier disque effacé

    def test_fichier_partage_non_efface(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(MEDIA_ROOT=tmp):
                os.makedirs(os.path.join(tmp, "videos"))
                with open(os.path.join(tmp, "videos", "partage.mp4"), "wb") as fh:
                    fh.write(b"x")
                m1 = Media.objects.create(code="a", fichier="videos/partage.mp4")
                Media.objects.create(code="b", fichier="videos/partage.mp4")  # même fichier
                m1.delete()
                # Un autre Média l'utilise encore → fichier conservé.
                self.assertTrue(os.path.exists(os.path.join(tmp, "videos", "partage.mp4")))

    def test_creer_media_et_parametres(self):
        self.client.post(reverse("editeur_medias"), {
            "code": "v1", "type_media": "video", "fichier": "videos/x.mp4", "titre": "", "vtt": "",
        })
        self.assertTrue(Media.objects.filter(code="v1").exists())
        self.client.post(reverse("editeur_parametres"), {
            "nom_etude": "Mon étude", "titre_accueil": "Salut",
            "description": "desc", "bouton_consentement": "Go",
            "intro_profil": "", "texte_remerciement": "Merci",
            "ordre_groupes_aleatoire": "on", "max_groupes": "0",
        })
        Configuration.charger().refresh_from_db()
        self.assertEqual(Configuration.charger().nom_etude, "Mon étude")
