"""
Tirage pondéré d'un enregistrement.

Objectif : équilibrer le nombre d'évaluations entre clips (les moins vus
sont prioritaires) tout en excluant ceux que le participant a déjà jugés.

Poids = 1 / (1 + nb_evaluations). Un clip jamais vu pèse 1 ; un clip vu
10 fois pèse ~0.09. Le tirage reste aléatoire mais favorise nettement
les clips sous-évalués, ce qui lisse la couverture de la banque.
"""
import random

from .models import Enregistrement


def tirer_enregistrement(participant):
    """Retourne un Enregistrement non encore jugé par `participant`, ou None."""
    deja_vus = participant.jugements.values_list("enregistrement_id", flat=True)
    candidats = list(
        Enregistrement.objects.filter(actif=True).exclude(id__in=deja_vus)
    )
    if not candidats:
        return None

    poids = [1.0 / (1 + e.nb_evaluations) for e in candidats]
    return random.choices(candidats, weights=poids, k=1)[0]
