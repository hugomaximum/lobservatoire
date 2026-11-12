# lobservatoire → veille-emplois

Workflow Mistral planifié : chaque matin, recherche d'offres d'emploi correspondant au CV (`cv.md`), résumé dans le chat avec question **oui/non**, puis brouillon de candidature si « oui » (rien n'est envoyé automatiquement).

Voir `src/worker/workflows/veille_emplois.py` pour le workflow, `Dockerfile` pour le déploiement managé, `tests/` pour les tests (12/12 OK en local).
