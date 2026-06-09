"""
Context processor : rend la configuration de l'étude disponible dans tous les
templates sous la variable `config` (nom de l'étude, textes d'accueil, etc.).
"""
from __future__ import annotations

from .models import Configuration


def configuration(request):
    return {"config": Configuration.charger()}
