import mistralai.workflows as workflows
from mistralai.workflows import testing as wft

from worker.workflows.veille_emplois import (
    BrouillonCandidature,
    Offre,
    RechercheOffres,
    VeilleEmploisWorkflow,
    formater_brouillon,
    formater_digest,
    parse_choix,
)


def _offre(i: int) -> Offre:
    return Offre(
        titre=f"Poste {i}",
        entreprise=f"Boîte {i}",
        lieu="Paris",
        type_contrat="CDI",
        salaire="45-55k€",
        url=f"https://exemple.fr/offre/{i}",
        resume=f"Résumé du poste {i}.",
        score=95 - i,
    )


class TestParseChoix:
    def test_oui_donne_la_premiere(self):
        assert parse_choix("oui", 3) == [0]

    def test_numero(self):
        assert parse_choix("la 2 svp", 3) == [1]

    def test_oui_avec_numero(self):
        assert parse_choix("oui pour la 3", 3) == [2]

    def test_non(self):
        assert parse_choix("non merci", 3) == []

    def test_pas(self):
        assert parse_choix("pas la 2", 3) == []

    def test_hors_limites(self):
        assert parse_choix("la 9", 3) == []

    def test_vide(self):
        assert parse_choix("", 3) == []

    def test_multi_selection(self):
        assert parse_choix("oui 1 2 3", 3) == [0, 1, 2]

    def test_multi_avec_doublon_et_hors_limite(self):
        assert parse_choix("2 2 9 1", 3) == [0, 1]


class TestMiseEnForme:
    def test_digest_numerote(self):
        texte = formater_digest([_offre(1), _offre(2)], "10/11/2026")
        assert "**1. Poste 1**" in texte
        assert "**2. Poste 2**" in texte
        assert "oui" in texte and "non" in texte

    def test_brouillon_contient_avertissement(self):
        brouillon = BrouillonCandidature(
            destinataire="rh@boite1.fr", objet="Candidature", corps="Bonjour, ..."
        )
        texte = formater_brouillon(_offre(1), brouillon)
        assert "rh@boite1.fr" in texte
        assert "Rien n'a été envoyé" in texte


@workflows.activity(name="lire_cv")
async def _fake_lire_cv() -> str:
    return "CV de test : développeur Python senior, Paris, CDI, remote partiel."


@workflows.activity(name="rechercher_offres")
async def _fake_rechercher_offres(cv: str, date_str: str) -> RechercheOffres:
    return RechercheOffres(offres=[_offre(1), _offre(2)])


@workflows.activity(name="rediger_brouillon")
async def _fake_rediger_brouillon(cv: str, offre_json: str, date_str: str) -> BrouillonCandidature:
    return BrouillonCandidature(
        destinataire="rh@boite1.fr",
        objet="Candidature — Poste 1",
        corps="Bonjour, je vous contacte au sujet de l'offre Poste 1...",
    )


async def _lancer_et_repondre(temporal_env, reponse: str) -> object:
    async with wft.create_test_worker_with_events(
        temporal_env,
        [VeilleEmploisWorkflow],
        activities=[_fake_lire_cv, _fake_rechercher_offres, _fake_rediger_brouillon],
        task_queue="test-task-queue",
    ):
        handle = await temporal_env.client.start_workflow(
            "veille-emplois",
            id=f"test-veille-emplois-{reponse}",
            task_queue="test-task-queue",
        )
        pending = await wft.wait_for_pending_inputs(handle, expected_count=1, timeout=20)
        task_id = pending[0]["task_id"]
        await handle.execute_update(
            "__submit_input",
            {"task_id": task_id, "input": {"message": [{"type": "text", "text": reponse}]}},
        )
        return await handle.result()


async def test_reponse_oui_genere_un_brouillon(temporal_env):
    result = await _lancer_et_repondre(temporal_env, "oui")
    assert "Poste 1" in str(result)


async def test_reponse_numero_choisit_l_offre(temporal_env):
    result = await _lancer_et_repondre(temporal_env, "2")
    assert "Poste 2" in str(result)


async def test_reponse_non_ne_fait_rien(temporal_env):
    result = await _lancer_et_repondre(temporal_env, "non")
    assert "aucune candidature" in str(result).lower()


async def test_reponse_multi_genere_plusieurs_brouillons(temporal_env):
    result = await _lancer_et_repondre(temporal_env, "1 2")
    assert "Poste 1" in str(result) and "Poste 2" in str(result)
    assert "2 offre(s)" in str(result)


class TestExtraireJson:
    def test_json_dans_fence_markdown(self):
        from worker.workflows.veille_emplois import _extraire_json
        assert _extraire_json('voici :\n```json\n{"offres": []}\n```') == {"offres": []}

    def test_json_entoure_de_texte(self):
        from worker.workflows.veille_emplois import _extraire_json
        data = _extraire_json('Bla bla {"offres": [{"titre": "x", "score": 1}]} fin')
        assert data["offres"][0]["titre"] == "x"

    def test_json_imbrique(self):
        from worker.workflows.veille_emplois import _extraire_json
        data = _extraire_json('prose {"offres": [{"titre": "a", "resume": "b"}]}')
        assert data["offres"][0]["resume"] == "b"
