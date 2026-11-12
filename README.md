# veille-emplois

Workflow Mistral planifié qui, chaque matin :

1. lit ton CV (`cv.md` à la racine du dépôt, texte ou markdown) ;
2. recherche sur le web les offres d'emploi récentes correspondant à ton profil ;
3. te poste un résumé numéroté dans le chat (Vibe Work / vue exécution Studio) ;
4. te demande **oui / non** (ou le numéro de l'offre) ;
5. si « oui » : rédige un **brouillon** d'email de candidature (destinataire, objet, lettre personnalisée + CV à joindre) — **rien n'est envoyé automatiquement** ;
6. si « non » : ne fait rien.

## Prérequis

- L'application **Mistral GitHub App** installée sur ce dépôt (github.com/apps/mistralai) avec **Contents: Read and write** pour le déploiement managé.
- Un plan permettant les déploiements managés (pay-as-you-go activé sur l'organisation).
- Ton CV à la racine du dépôt sous `cv.md` (texte/markdown lisible).

## Développement local

```bash
uv sync --group dev
cp .env.example .env  # renseigner MISTRAL_API_KEY pour un run local
uv run pytest -q
```

## Déploiement

Le déploiement managé build la racine du dépôt (`Dockerfile`) et lance le worker
(`python -m worker.entrypoints.worker`). Ensuite, créer un schedule, par exemple
8h00 Europe/Paris du lundi au vendredi :

```bash
curl -X POST "https://api.mistral.ai/v1/workflows/schedules" \
  -H "Authorization: Bearer $MISTRAL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "workflow_identifier": "veille-emplois",
    "deployment_name": "<nom-du-deploiement>",
    "schedule": {
      "input": {},
      "cron_expressions": ["0 8 * * 1-5"],
      "time_zone_name": "Europe/Paris"
    }
  }'
```

## Variables d'environnement (optionnelles)

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `CV_PATH` | `cv.md` | Chemin du CV lu à chaque exécution |
| `VEILLE_MODEL` | `mistral-large-latest` | Modèle utilisé par l'agent |

En déploiement managé, le worker s'authentifie via le token du compte de service
(`MISTRAL_SA_TOKEN_PATH`) : aucune clé API dans le dépôt.
