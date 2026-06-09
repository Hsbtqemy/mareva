"""
Tirage d'un groupe de questions à proposer au participant.

On tire un groupe STANDARD, actif, inclus dans le tirage, et non encore abordé
par ce participant. Selon la configuration :
  - aléatoire pondéré : poids = 1 / (1 + nb_evaluations) → les groupes les moins
    vus passent en priorité, ce qui équilibre la couverture ;
  - ordre fixe : le premier groupe restant dans l'ordre défini.

Retourne None si plus aucun groupe disponible.
"""
import random

from .models import Groupe, Configuration


def tirer_groupe(participant):
    """Retourne un Groupe standard non encore abordé par `participant`, ou None."""
    deja_vus = participant.passages.values_list("groupe_id", flat=True)
    candidats = list(
        Groupe.objects.filter(
            active=True, portee=Groupe.STANDARD, inclure_tirage=True
        ).exclude(id__in=deja_vus)
    )
    if not candidats:
        return None

    config = Configuration.charger()
    if config.ordre_groupes_aleatoire:
        poids = [1.0 / (1 + g.nb_evaluations) for g in candidats]
        return random.choices(candidats, weights=poids, k=1)[0]
    # Ordre fixe : le premier restant (candidats déjà triés par ordre via Meta).
    return candidats[0]
