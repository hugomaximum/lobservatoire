import asyncio
import json
import os
import re
from datetime import timedelta

import pydantic

import mistralai.workflows as workflows
import mistralai.workflows.plugins.mistralai as wm
from mistralai.client.models import WebSearchTool

MODELE_PAR_DEFAUT = "mistral-large-latest"
MAX_OFFRES = 5
DUREE_ATTENTE_REPONSE = timedelta(hours=12)

INSTRUCTIONS_AGENT = (
    "Tu es un assistant carrière francophone. Tu réponds toujours en français. "
    "Quand on te demande un objet JSON, tu réponds UNIQUEMENT avec cet objet JSON, "
    "sans texte autour et sans balises markdown."
)

PROMPT_RECHERCHE = """Date du jour : {date}.

Voici le CV du candidat :
{cv}

Mission : avec la recherche web, trouve des offres d'emploi publiées dans les dernières 48 heures en France \
(priorité Île-de-France, télétravail partiel accepté). Cherche LARGEMENT, pas seulement l'intitulé exact du CV : \
postes de corporate finance, financement de projets, financement de filiales/participations, analyste financier, \
analyste crédit, contrôleur de gestion/financier, trésorerie, FP&A, juriste financements, conseil financier/audit, \
et postes du secteur public/parapublic (financement et restructuration d'entreprises). \
Employeurs : grands groupes industriels (CAC 40 / ETI, ex. Groupe SNCF), banques et établissements financiers, \
cabinets de conseil/audit (Big Four), Bpifrance et organismes publics. \
Effectue au maximum 4 recherches web au total, puis réponds immédiatement.

Sources à privilégier : emploi.sncf.com, Welcome to the Jungle, APEC, LinkedIn, Indeed, France Travail, Les Jeudis, \
HelloWork, Wizbii, le portail talents de Bpifrance, passerelles.economie.gouv.fr, Robert Half. \
Cherche en français, et en anglais si le profil est anglophone.

Retourne au maximum {max_offres} offres, classées par pertinence (score de 0 à 100), sous la forme d'UNIQUE objet JSON :
{{"offres": [{{"titre": "...", "entreprise": "...", "lieu": "...", "type_contrat": "...", "salaire": "...", "url": "...", "email_contact": "...", "resume": "...", "score": 0}}]}}

Pour chaque offre : titre exact, entreprise, lieu, type de contrat, salaire si mentionné, URL de l'offre, \
email de contact du recruteur si visible publiquement (sinon chaîne vide), résumé de 2-3 phrases du poste, score de pertinence.
Si aucune offre ne correspond, retourne exactement : {{"offres": []}}
"""

PROMPT_BROUILLON = """Date du jour : {date}.

CV du candidat :
{cv}

Offre visée (JSON) :
{offre}

Rédige un brouillon d'email de candidature pour cette offre : un destinataire (l'email_contact de l'offre s'il est renseigné, sinon une chaîne vide), un objet, et un corps de message en français, professionnel et concis (150-250 mots), personnalisé pour cette offre et ce profil, terminé par une formule de politesse. Le CV sera joint en pièce jointe par le candidat ; mentionne-le.

Retourne UNIQUEMENT un objet JSON : {{"destinataire": "...", "objet": "...", "corps": "..."}}
"""


class Offre(pydantic.BaseModel):
    titre: str
    entreprise: str = ""
    lieu: str = ""
    type_contrat: str = ""
    salaire: str = ""
    url: str = ""
    email_contact: str = ""
    resume: str = ""
    score: int = 0


class RechercheOffres(pydantic.BaseModel):
    offres: list[Offre] = pydantic.Field(default_factory=list)


class BrouillonCandidature(pydantic.BaseModel):
    destinataire: str = ""
    objet: str = ""
    corps: str = ""


def _texte_sortie(outputs) -> str:
    parts: list[str] = []
    for entry in outputs or []:
        content = getattr(entry, "content", None)
        if isinstance(content, list):
            for chunk in content:
                texte = getattr(chunk, "text", None)
                if isinstance(texte, str):
                    parts.append(texte)
        elif isinstance(content, str):
            parts.append(content)
    return "\n".join(parts)


def _extraire_json(texte: str) -> dict:
    texte = re.sub(r"```(?:json)?", "", texte)
    debut = texte.find("{")
    while debut != -1:
        profondeur = 0
        for i in range(debut, len(texte)):
            if texte[i] == "{":
                profondeur += 1
            elif texte[i] == "}":
                profondeur -= 1
                if profondeur == 0:
                    try:
                        data = json.loads(texte[debut : i + 1])
                    except ValueError:
                        break
                    if isinstance(data, dict):
                        return data
                    break
        debut = texte.find("{", debut + 1)
    raise ValueError(f"Aucun objet JSON valide trouvé dans la réponse de l'agent : {texte[:500]}")


async def _demander_au_modele(prompt: str, avec_recherche_web: bool = False, max_tentatives: int = 4) -> str:
    client = wm.get_mistral_client()
    outils = [WebSearchTool()] if avec_recherche_web else []
    for tentative in range(1, max_tentatives + 1):
        try:
            conversation = await client.beta.conversations.start_async(
                inputs=prompt,
                model=os.environ.get("VEILLE_MODEL", MODELE_PAR_DEFAUT),
                instructions=INSTRUCTIONS_AGENT,
                tools=outils,
            )
            return _texte_sortie(conversation.outputs)
        except Exception as exc:
            if "429" in str(exc) and tentative < max_tentatives:
                await asyncio.sleep(45 * tentative)
                workflows.activity_heartbeat()
                continue
            raise


@workflows.activity()
async def lire_cv() -> str:
    path = os.environ.get("CV_PATH", "cv.md")
    try:
        with open(path, "r", encoding="utf-8") as fichier:
            return fichier.read().strip()
    except OSError:
        return ""


@workflows.activity()
async def rechercher_offres(cv: str, date_str: str) -> RechercheOffres:
    prompt = PROMPT_RECHERCHE.format(date=date_str, cv=cv or "(CV non fourni)", max_offres=MAX_OFFRES)
    texte = await _demander_au_modele(prompt, avec_recherche_web=True)
    return RechercheOffres.model_validate(_extraire_json(texte))


@workflows.activity()
async def rediger_brouillon(cv: str, offre_json: str, date_str: str) -> BrouillonCandidature:
    prompt = PROMPT_BROUILLON.format(date=date_str, cv=cv or "(CV non fourni)", offre=offre_json)
    texte = await _demander_au_modele(prompt)
    return BrouillonCandidature.model_validate(_extraire_json(texte))


def _texte_reponse(reponse) -> str:
    parts: list[str] = []
    for chunk in getattr(reponse, "message", None) or []:
        texte = getattr(chunk, "text", None)
        if isinstance(texte, str):
            parts.append(texte)
    return " ".join(parts).strip().lower()


def parse_choix(texte: str, nb_offres: int) -> int | None:
    if not texte or nb_offres <= 0:
        return None
    if re.search(r"\b(non|no|nop|rien|aucune|stop|pas)\b", texte):
        return None
    match = re.search(r"\d+", texte)
    if match:
        index = int(match.group()) - 1
        return index if 0 <= index < nb_offres else None
    if re.search(r"\b(oui|yes|ok|go|vas[- ]y|d'accord|accord)\b", texte):
        return 0
    return None


def formater_digest(offres: list[Offre], date_str: str) -> str:
    lignes = [f"## 📋 Offres du {date_str}", ""]
    for i, offre in enumerate(offres, start=1):
        lignes.append(f"**{i}. {offre.titre}** — {offre.entreprise} ({offre.lieu})")
        details = []
        if offre.type_contrat:
            details.append(f"contrat : {offre.type_contrat}")
        details.append(f"salaire : {offre.salaire or 'non précisé'}")
        lignes.append(f"   {' | '.join(details)}")
        if offre.resume:
            lignes.append(f"   {offre.resume}")
        if offre.url:
            lignes.append(f"   🔗 {offre.url}")
        lignes.append(f"   Pertinence : {offre.score}/100")
        lignes.append("")
    lignes.append(
        "Réponds par le **numéro** de l'offre à laquelle postuler, **« oui »** pour la n°1, ou **« non »** pour ne rien faire."
    )
    return "\n".join(lignes)


def formater_brouillon(offre: Offre, brouillon: BrouillonCandidature) -> str:
    destinataire = brouillon.destinataire or "(à compléter — aucun email de contact public trouvé sur l'offre)"
    return (
        f"## ✉️ Brouillon de candidature — {offre.titre} ({offre.entreprise})\n\n"
        f"**Destinataire :** {destinataire}\n"
        f"**Objet :** {brouillon.objet}\n\n"
        f"**Message :**\n\n{brouillon.corps}\n\n"
        "📎 *Joindre le CV (`cv.md`) en pièce jointe.*\n"
        "⚠️ *Rien n'a été envoyé : ce brouillon est à relire, valider et envoyer toi-même.*"
    )


@workflows.workflow.define(
    name="veille-emplois",
    workflow_display_name="Veille emplois",
    workflow_description=(
        "Chaque matin : recherche d'offres d'emploi correspondant au CV, résumé dans le chat, "
        "validation oui/non, puis brouillon de candidature si « oui »."
    ),
)
class VeilleEmploisWorkflow(workflows.InteractiveWorkflow):
    @workflows.workflow.entrypoint
    async def run(self) -> wm.ChatAssistantWorkflowOutput:
        date_str = workflows.workflow.now().strftime("%d/%m/%Y")
        cv = await lire_cv()
        if cv:
            await wm.send_assistant_message(f"🔎 Bonjour ! Je recherche les offres du {date_str} correspondant à ton profil…")
        else:
            await wm.send_assistant_message(
                "⚠️ Aucun CV trouvé (`cv.md` à la racine du dépôt) : la recherche sera générique. "
                f"Sinon, je lance la recherche des offres du {date_str}…"
            )

        recherche = await rechercher_offres(cv, date_str)
        offres = sorted(recherche.offres, key=lambda o: o.score, reverse=True)[:MAX_OFFRES]
        if not offres:
            await wm.send_assistant_message("😕 Aucune offre pertinente trouvée aujourd'hui.")
            return wm.ChatAssistantWorkflowOutput(
                content=[wm.TextOutput(text="Aucune offre pertinente aujourd'hui.")]
            )

        await wm.send_assistant_message(formater_digest(offres, date_str))

        try:
            reponse = await self.wait_for_input(
                wm.ChatInput(
                    prompt="Numéro de l'offre à laquelle postuler (ou « oui » pour la n°1, « non » pour ne rien faire) :",
                    suggestions=[[wm.TextChunk(text="oui")], [wm.TextChunk(text="non")]],
                ),
                label="Choix de candidature",
                timeout=DUREE_ATTENTE_REPONSE,
            )
        except asyncio.TimeoutError:
            await wm.send_assistant_message(
                "⏳ Pas de réponse sous 12h : aucune candidature préparée aujourd'hui."
            )
            return wm.ChatAssistantWorkflowOutput(
                content=[wm.TextOutput(text="Délai de réponse dépassé, aucune candidature.")]
            )

        index = parse_choix(_texte_reponse(reponse), len(offres))
        if index is None:
            await wm.send_assistant_message("👍 Compris, aucune candidature aujourd'hui.")
            return wm.ChatAssistantWorkflowOutput(
                content=[wm.TextOutput(text="Aucune candidature (réponse négative ou non comprise).")]
            )

        offre = offres[index]
        brouillon = await rediger_brouillon(cv, offre.model_dump_json(), date_str)
        await wm.send_assistant_message(formater_brouillon(offre, brouillon))
        return wm.ChatAssistantWorkflowOutput(
            content=[wm.TextOutput(text=f"Brouillon préparé pour « {offre.titre} » ({offre.entreprise}).")]
        )
