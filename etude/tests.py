"""
Tests bout-en-bout du parcours participant + export CSV.

Couverture demandée par le cahier des charges :
  consentement → tâche → streaming vidéo autorisé (jugement en cours)
  → soumission → page Continuer/Arrêter → jugement clos + compteur
  incrémenté + réponses stockées → accès média refusé (403) après clôture
  → nouveau tirage excluant le déjà-vu.
Plus : l'export CSV produit le format large repivoté.

Note : sous test, DEBUG=False par défaut, donc media_protege renvoie
l'en-tête X-Accel-Redirect (pas besoin de fichier réel sur disque). Un
test dédié couvre le chemin DEBUG=True (FileResponse) avec un fichier
temporaire.
"""
from __future__ import annotations

import csv
import io
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse

from django.contrib.auth.models import User

from .admin import JugementAdmin
from .models import (
    Choix,
    CodeAcces,
    Configuration,
    Enregistrement,
    Groupe,
    Jugement,
    Media,
    Participant,
    Question,
    Reponse,
)


def _creer_questions():
    """Une question de chaque type, dans l'ordre."""
    q_echelle = Question.objects.create(
        code="clarte", libelle="Le son est-il clair ?", type=Question.ECHELLE,
        min_val=1, max_val=7, label_min="Pas du tout", label_max="Très clair",
        obligatoire=True, ordre=1,
    )
    q_choix = Question.objects.create(
        code="choix_q", libelle="Quelle est votre réponse ?", type=Question.CHOIX,
        choix_multiple=True, obligatoire=True, ordre=2,
    )
    for i, (v, lib) in enumerate([("voix", "Une voix"), ("bruit", "Du bruit"),
                                  ("musique", "De la musique")]):
        Choix.objects.create(question=q_choix, valeur=v, libelle=lib, ordre=i)
    q_texte = Question.objects.create(
        code="comment", libelle="Précisez", type=Question.TEXTE,
        obligatoire=False, ordre=3,
    )
    return q_echelle, q_choix, q_texte


class ParcoursParticipantTest(TestCase):
    def setUp(self):
        self.q_echelle, self.q_choix, self.q_texte = _creer_questions()
        self.code = CodeAcces.objects.create(code="entree-1")
        self.clip_a = Enregistrement.objects.create(
            code="clip_a", fichier_video="videos/a.mp4",
            fichier_vtt="videos/a.vtt", categorie="test",
        )
        self.clip_b = Enregistrement.objects.create(
            code="clip_b", fichier_video="videos/b.mp4",
            fichier_vtt="videos/b.vtt", categorie="test",
        )

    def _franchir_acces(self):
        """Saisit un code d'accès valide (participant créé/restauré en session)."""
        self.client.post(reverse("acces"), {"code": "entree-1"})

    def test_gate_acces(self):
        # Mauvais code : reste sur la barrière, sans drapeau ni participant.
        r = self.client.post(reverse("acces"), {"code": "mauvais"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "incorrect")
        self.assertNotIn("acces_ok", self.client.session)
        self.assertEqual(Participant.objects.count(), 0)

        # Bon code : crée et lie un participant, pose le drapeau, redirige.
        r = self.client.post(reverse("acces"), {"code": "entree-1"})
        self.assertRedirects(r, reverse("index"))
        self.assertTrue(self.client.session.get("acces_ok"))
        self.code.refresh_from_db()
        self.assertIsNotNone(self.code.participant)
        self.assertEqual(self.client.session["jeton"], self.code.participant.jeton)

    def test_meme_code_restaure_le_participant(self):
        """Resaisir le même code dans une nouvelle session reprend le participant."""
        self.client.post(reverse("acces"), {"code": "entree-1"})
        self.code.refresh_from_db()
        participant = self.code.participant
        self.client.session.flush()  # simule un nouveau navigateur
        self.client.post(reverse("acces"), {"code": "entree-1"})
        self.assertEqual(self.client.session["jeton"], participant.jeton)
        self.assertEqual(Participant.objects.count(), 1)  # pas de doublon

    def test_code_inactif_refuse(self):
        CodeAcces.objects.filter(pk=self.code.pk).update(actif=False)
        r = self.client.post(reverse("acces"), {"code": "entree-1"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "incorrect")

    def test_lien_individuel_get(self):
        """Lien personnel cliquable : lie puis restaure le même participant."""
        from django.test import Client
        r = self.client.get(reverse("acces_lien", args=["entree-1"]))
        self.assertRedirects(r, reverse("index"))
        self.code.refresh_from_db()
        self.assertIsNotNone(self.code.participant)
        # Un autre navigateur sur le même lien individuel reprend le participant.
        autre = Client()
        autre.get(reverse("acces_lien", args=["entree-1"]))
        self.assertEqual(autre.session["jeton"], self.code.participant.jeton)
        self.assertEqual(Participant.objects.count(), 1)

    def test_lien_collectif_cree_un_participant_par_visiteur(self):
        """Lien collectif : chaque visiteur devient un participant distinct."""
        from django.test import Client
        collectif = CodeAcces.objects.create(code="ouvert", collectif=True)
        c1, c2 = Client(), Client()
        c1.get(reverse("acces_lien", args=["ouvert"]))
        c2.get(reverse("acces_lien", args=["ouvert"]))
        self.assertNotEqual(c1.session["jeton"], c2.session["jeton"])
        self.assertEqual(Participant.objects.count(), 2)
        # Le code collectif n'est lié à aucun participant en particulier.
        collectif.refresh_from_db()
        self.assertIsNone(collectif.participant)

    def test_lien_invalide(self):
        r = self.client.get(reverse("acces_lien", args=["inconnu"]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "invalide")

    def test_parcours_complet(self):
        # 0. Sans code d'accès, le consentement renvoie vers la barrière.
        r = self.client.get(reverse("index"))
        self.assertRedirects(r, reverse("acces"))

        # 1. Code d'accès correct → consentement accessible.
        self._franchir_acces()
        r = self.client.get(reverse("index"))
        self.assertEqual(r.status_code, 200)

        # 2. Consentement (POST) → passe par le profil, qui redirige vers la
        #    tâche faute de question profil. Le participant existe déjà (accès).
        r = self.client.post(reverse("index"))
        self.assertRedirects(r, reverse("profil"), target_status_code=302)
        self.assertIn("jeton", self.client.session)
        participant = Participant.objects.get(jeton=self.client.session["jeton"])
        self.assertTrue(participant.consentement)

        # 3. La tâche ouvre un jugement (fin IS NULL) sur un clip actif.
        r = self.client.get(reverse("tache"))
        self.assertEqual(r.status_code, 200)
        jugement = participant.jugements.get(fin__isnull=True)
        clip = jugement.enregistrement

        # 4. Streaming autorisé tant que le jugement est en cours.
        r = self.client.get(reverse("media_protege", args=["video", clip.code]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["X-Accel-Redirect"], f"/media-protege/{clip.fichier_video}")
        self.assertEqual(r["Content-Type"], "video/mp4")
        r = self.client.get(reverse("media_protege", args=["vtt", clip.code]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "text/vtt")

        # Un autre clip non en cours n'est pas accessible.
        autre = self.clip_b if clip == self.clip_a else self.clip_a
        r = self.client.get(reverse("media_protege", args=["video", autre.code]))
        self.assertEqual(r.status_code, 403)

        # 5. Soumission valide → page Continuer/Arrêter.
        r = self.client.post(reverse("soumettre"), {
            f"q_{self.q_echelle.id}": "5",
            f"q_{self.q_choix.id}": ["voix", "musique"],
            f"q_{self.q_texte.id}": "léger souffle",
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Évaluer un autre extrait")  # il reste clip_b

        # 6. Jugement clos + compteur incrémenté + réponses stockées.
        jugement.refresh_from_db()
        clip.refresh_from_db()
        self.assertIsNotNone(jugement.fin)
        self.assertEqual(clip.nb_evaluations, 1)
        reps = {r.question.code: r.valeur for r in jugement.reponses.all()}
        self.assertEqual(reps["clarte"], "5")
        self.assertEqual(reps["choix_q"], "voix|musique")  # multiple joint par |
        self.assertEqual(reps["comment"], "léger souffle")

        # 7. Accès média refusé (403) une fois le jugement clos.
        r = self.client.get(reverse("media_protege", args=["video", clip.code]))
        self.assertEqual(r.status_code, 403)

        # 8. Nouveau tirage : exclut le clip déjà jugé.
        r = self.client.get(reverse("tache"))
        self.assertEqual(r.status_code, 200)
        nouveau = participant.jugements.get(fin__isnull=True)
        self.assertEqual(nouveau.enregistrement, autre)

    def test_obligatoire_manquant_reaffiche(self):
        """Une réponse obligatoire manquante n'enregistre rien et réaffiche."""
        self._franchir_acces()
        self.client.post(reverse("index"))
        self.client.get(reverse("tache"))
        r = self.client.post(reverse("soumettre"), {
            f"q_{self.q_texte.id}": "facultatif rempli",
            # q_echelle et q_choix obligatoires omis
        })
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "obligatoires")
        self.assertEqual(Reponse.objects.count(), 0)
        self.assertFalse(Jugement.objects.filter(fin__isnull=False).exists())

    def test_banque_epuisee_redirige_fin(self):
        """Quand tous les clips sont jugés, la tâche redirige vers la fin."""
        self._franchir_acces()
        self.client.post(reverse("index"))
        participant = Participant.objects.get(jeton=self.client.session["jeton"])
        # Marque les deux clips comme déjà jugés et clos.
        from django.utils import timezone
        for clip in (self.clip_a, self.clip_b):
            Jugement.objects.create(
                participant=participant, enregistrement=clip, fin=timezone.now(),
            )
        r = self.client.get(reverse("tache"))
        self.assertRedirects(r, reverse("fin"))

    def test_acces_media_sans_participant(self):
        """Sans session participant : accès média interdit."""
        r = self.client.get(reverse("media_protege", args=["video", self.clip_a.code]))
        self.assertEqual(r.status_code, 403)

    @override_settings(DEBUG=True)
    def test_media_debug_sert_fichier(self):
        """En DEBUG, le fichier est servi directement (FileResponse)."""
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp)
            (media / "videos").mkdir()
            (media / "videos" / "a.mp4").write_bytes(b"\x00\x01octets-video")
            with override_settings(MEDIA_ROOT=media):
                # On désactive clip_b pour forcer le tirage sur clip_a (fichier dispo).
                Enregistrement.objects.filter(pk=self.clip_b.pk).update(actif=False)
                self._franchir_acces()
                self.client.post(reverse("index"))
                self.client.get(reverse("tache"))
                participant = Participant.objects.get(jeton=self.client.session["jeton"])
                clip = participant.jugements.get(fin__isnull=True).enregistrement
                self.assertEqual(clip, self.clip_a)
                r = self.client.get(reverse("media_protege", args=["video", "clip_a"]))
                self.assertEqual(r.status_code, 200)
                contenu = b"".join(r.streaming_content)
                self.assertEqual(contenu, b"\x00\x01octets-video")


class ExportCSVTest(TestCase):
    def setUp(self):
        self.q_echelle, self.q_choix, self.q_texte = _creer_questions()
        self.clip = Enregistrement.objects.create(
            code="clip_x", fichier_video="videos/x.mp4", categorie="condition_1",
        )
        from django.utils import timezone
        self.participant = Participant.objects.create(jeton="jeton-test", consentement=True)
        self.jugement = Jugement.objects.create(
            participant=self.participant, enregistrement=self.clip, fin=timezone.now(),
        )
        Reponse.objects.create(jugement=self.jugement, question=self.q_echelle, valeur="6")
        Reponse.objects.create(jugement=self.jugement, question=self.q_choix, valeur="voix|bruit")
        Reponse.objects.create(jugement=self.jugement, question=self.q_texte, valeur="rien")

    def test_export_format_large(self):
        admin = JugementAdmin(Jugement, None)
        reponse = admin.exporter_csv(request=None, queryset=Jugement.objects.all())
        self.assertEqual(reponse["Content-Type"], "text/csv")
        self.assertIn("attachment", reponse["Content-Disposition"])

        lignes = list(csv.reader(io.StringIO(reponse.content.decode("utf-8"))))
        entete, donnees = lignes[0], lignes[1]

        # Colonnes fixes PUIS une colonne par question (par code, dans l'ordre).
        self.assertEqual(entete, [
            "id_jugement", "jeton_participant", "consentement",
            "code_enregistrement", "categorie", "debut", "fin",
            "clarte", "choix_q", "comment",
        ])
        d = dict(zip(entete, donnees))
        self.assertEqual(d["jeton_participant"], "jeton-test")
        self.assertEqual(d["code_enregistrement"], "clip_x")
        self.assertEqual(d["categorie"], "condition_1")
        self.assertEqual(d["clarte"], "6")
        self.assertEqual(d["choix_q"], "voix|bruit")
        self.assertEqual(d["comment"], "rien")


class ConfigurationTest(TestCase):
    """Identité de l'étude éditable (nom, textes) et neutralité par défaut."""

    def test_singleton(self):
        a = Configuration.charger()
        b = Configuration.charger()
        self.assertEqual(a.pk, b.pk)
        self.assertEqual(Configuration.objects.count(), 1)

    def test_defaut_neutre(self):
        # Aucun défaut ne mentionne la perception.
        c = Configuration.charger()
        for texte in (c.nom_etude, c.titre_accueil, c.description, c.texte_remerciement):
            self.assertNotIn("percept", texte.lower())

    def test_textes_personnalises_affiches(self):
        c = Configuration.charger()
        c.nom_etude = "Étude sur les couleurs"
        c.titre_accueil = "Bonjour et bienvenue"
        c.description = "Vous allez voir des images."
        c.save()
        CodeAcces.objects.create(code="e")
        self.client.post(reverse("acces"), {"code": "e"})
        r = self.client.get(reverse("index"))
        self.assertContains(r, "Étude sur les couleurs")
        self.assertContains(r, "Bonjour et bienvenue")
        self.assertContains(r, "Vous allez voir des images.")


class ProfilTest(TestCase):
    """Questions de portée profil : posées une fois, stockées sur le participant."""

    def setUp(self):
        CodeAcces.objects.create(code="e")
        self.clip = Enregistrement.objects.create(code="c", fichier_video="v.mp4")
        self.age = Question.objects.create(
            code="age", libelle="Quel âge ?", type=Question.TEXTE,
            portee=Question.PROFIL, obligatoire=True, ordre=0,
        )
        self.extrait = Question.objects.create(
            code="clarte", libelle="Le son est-il clair ?", type=Question.TEXTE,
            portee=Question.EXTRAIT, obligatoire=True, ordre=0,
        )

    def _entrer(self):
        self.client.post(reverse("acces"), {"code": "e"})
        self.client.post(reverse("index"))  # consentement

    def test_profil_pose_une_fois_puis_tache(self):
        self._entrer()
        # Le consentement redirige vers le profil (question profil non répondue).
        r = self.client.get(reverse("profil"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Quel âge")

        r = self.client.post(reverse("soumettre_profil"), {f"q_{self.age.id}": "32"})
        self.assertRedirects(r, reverse("tache"))
        participant = Participant.objects.get(jeton=self.client.session["jeton"])
        self.assertEqual(participant.reponses_profil.get(question=self.age).valeur, "32")

        # Profil déjà rempli → on saute directement à la tâche.
        r = self.client.get(reverse("profil"))
        self.assertRedirects(r, reverse("tache"))

        # La question profil n'apparaît PAS dans l'évaluation d'extrait.
        r = self.client.get(reverse("tache"))
        self.assertNotContains(r, "Quel âge")
        self.assertContains(r, "Le son est-il clair")

    def test_profil_obligatoire_manquant(self):
        self._entrer()
        r = self.client.post(reverse("soumettre_profil"), {})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "obligatoires")
        self.assertEqual(Participant.objects.get(jeton=self.client.session["jeton"]).reponses_profil.count(), 0)

    def test_export_profil_repete_par_ligne(self):
        from django.utils import timezone
        self._entrer()
        self.client.post(reverse("soumettre_profil"), {f"q_{self.age.id}": "32"})
        participant = Participant.objects.get(jeton=self.client.session["jeton"])
        clip2 = Enregistrement.objects.create(code="c2", fichier_video="v2.mp4")
        for clip in (self.clip, clip2):
            j = Jugement.objects.create(participant=participant, enregistrement=clip, fin=timezone.now())
            Reponse.objects.create(jugement=j, question=self.extrait, valeur="oui")

        resp = JugementAdmin(Jugement, None).exporter_csv(None, Jugement.objects.all())
        rows = list(csv.reader(io.StringIO(resp.content.decode("utf-8"))))
        entete = rows[0]
        self.assertIn("age", entete)
        self.assertIn("clarte", entete)
        # Colonnes profil avant colonnes d'extrait.
        self.assertLess(entete.index("age"), entete.index("clarte"))
        # La réponse de profil est recopiée sur chacune des deux lignes de jugement.
        self.assertEqual(len(rows) - 1, 2)
        for row in rows[1:]:
            d = dict(zip(entete, row))
            self.assertEqual(d["age"], "32")
            self.assertEqual(d["clarte"], "oui")


class GroupesPaginationTest(TestCase):
    """Groupes, mise en page configurable, et média par question."""

    def setUp(self):
        self.code = CodeAcces.objects.create(code="entree-1")
        self.clip = Enregistrement.objects.create(code="clip_p", fichier_video="videos/p.mp4")
        # Deux groupes : g2 commence une nouvelle page → deux pages.
        self.g1 = Groupe.objects.create(titre="Première section", ordre=0)
        self.g2 = Groupe.objects.create(titre="Seconde section", ordre=1, nouvelle_page=True)
        self.media = Media.objects.create(code="m_audio", type_media="audio", fichier="medias/a.mp3")
        self.q1 = Question.objects.create(
            code="q1", libelle="Q1", type=Question.TEXTE, obligatoire=True,
            groupe=self.g1, ordre=0,
        )
        self.q2 = Question.objects.create(
            code="q2", libelle="Q2", type=Question.TEXTE, obligatoire=True,
            groupe=self.g2, ordre=0, media=self.media,
        )

    def _entrer(self):
        self.client.post(reverse("acces"), {"code": "entree-1"})
        self.client.post(reverse("index"))

    def test_parcours_multi_pages(self):
        self._entrer()
        # Page 1 : voit Q1 et le clip, pas encore Q2.
        r = self.client.get(reverse("tache"))
        self.assertContains(r, "page 1 / 2")
        self.assertContains(r, "Première section")
        self.assertNotContains(r, "Seconde section")

        participant = Participant.objects.get(jeton=self.client.session["jeton"])
        jugement = participant.jugements.get(fin__isnull=True)

        # Soumettre la page 1 → ne clôt pas, passe à la page 2.
        r = self.client.post(reverse("soumettre"), {f"q_{self.q1.id}": "réponse 1"})
        self.assertRedirects(r, reverse("tache"))
        jugement.refresh_from_db()
        self.assertIsNone(jugement.fin)

        # Page 2 : voit Q2 (avec son média audio), plus le clip.
        r = self.client.get(reverse("tache"))
        self.assertContains(r, "page 2 / 2")
        self.assertContains(r, "Seconde section")
        self.assertContains(r, reverse("media_question", args=["fichier", "m_audio"]))

        # Soumettre la page 2 → clôture + incrément + page remise à 0.
        r = self.client.post(reverse("soumettre"), {f"q_{self.q2.id}": "réponse 2"})
        self.assertEqual(r.status_code, 200)
        jugement.refresh_from_db()
        self.clip.refresh_from_db()
        self.assertIsNotNone(jugement.fin)
        self.assertEqual(self.clip.nb_evaluations, 1)
        reps = {r.question.code: r.valeur for r in jugement.reponses.all()}
        self.assertEqual(reps, {"q1": "réponse 1", "q2": "réponse 2"})

    def test_media_question_autorise_puis_refuse(self):
        self._entrer()
        self.client.get(reverse("tache"))  # ouvre un jugement
        r = self.client.get(reverse("media_question", args=["fichier", "m_audio"]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["X-Accel-Redirect"], "/media-protege/medias/a.mp3")

        # Média non rattaché à une question active → refusé.
        orphelin = Media.objects.create(code="m_orph", fichier="medias/o.mp3")
        r = self.client.get(reverse("media_question", args=["fichier", "m_orph"]))
        self.assertEqual(r.status_code, 403)

    def test_media_question_sans_jugement_refuse(self):
        r = self.client.get(reverse("media_question", args=["fichier", "m_audio"]))
        self.assertEqual(r.status_code, 403)


class EditeurTest(TestCase):
    """API de l'éditeur visuel (réservé au staff)."""

    def setUp(self):
        self.staff = User.objects.create_user("chef", password="x", is_staff=True)
        self.client.force_login(self.staff)

    def test_acces_reserve_au_staff(self):
        anon = self.client.__class__()
        r = anon.get(reverse("editeur"))
        self.assertEqual(r.status_code, 302)  # redirigé vers le login admin
        self.assertIn("/admin/login", r["Location"])

    def test_creer_groupe_et_question(self):
        import json
        r = self.client.post(reverse("editeur_groupe"),
                             data=json.dumps({"titre": "G"}), content_type="application/json")
        gid = r.json()["id"]
        self.assertTrue(Groupe.objects.filter(pk=gid, titre="G").exists())

        r = self.client.post(reverse("editeur_question"),
                             data=json.dumps({"groupe_id": gid, "libelle": "Ma question",
                                              "type": "choix",
                                              "choix": [{"libelle": "Oui"}, {"libelle": "Non"}]}),
                             content_type="application/json")
        qid = r.json()["id"]
        q = Question.objects.get(pk=qid)
        self.assertEqual(q.groupe_id, gid)
        self.assertEqual(q.choix.count(), 2)

    def test_reordonner(self):
        import json
        g = Groupe.objects.create(titre="G")
        qa = Question.objects.create(code="a", libelle="A", type=Question.TEXTE, ordre=0)
        qb = Question.objects.create(code="b", libelle="B", type=Question.TEXTE, ordre=1)
        r = self.client.post(reverse("editeur_ordre"),
                             data=json.dumps({"groupes": [{"id": g.id, "questions": [qb.id, qa.id]}],
                                              "sans_groupe": []}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        qa.refresh_from_db(); qb.refresh_from_db()
        self.assertEqual((qb.groupe_id, qb.ordre), (g.id, 0))
        self.assertEqual((qa.groupe_id, qa.ordre), (g.id, 1))

    def test_min_val_non_entier_refuse_proprement(self):
        """Une borne d'échelle non numérique renvoie une erreur 400, pas un 500."""
        import json
        r = self.client.post(reverse("editeur_question"),
                             data=json.dumps({"libelle": "Q", "type": "echelle", "min_val": "abc"}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("entier", r.json()["erreur"])

    def test_suppression_question_avec_reponses_refusee(self):
        import json
        from django.utils import timezone
        q = Question.objects.create(code="x", libelle="X", type=Question.TEXTE)
        clip = Enregistrement.objects.create(code="c", fichier_video="v.mp4")
        p = Participant.objects.create(jeton="j")
        j = Jugement.objects.create(participant=p, enregistrement=clip, fin=timezone.now())
        Reponse.objects.create(jugement=j, question=q, valeur="v")
        r = self.client.post(reverse("editeur_question_supprimer", args=[q.id]),
                             data="{}", content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(Question.objects.filter(pk=q.id).exists())
