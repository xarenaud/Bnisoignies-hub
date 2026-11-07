# Member and Alumni spaces

One application and identity, with server-enforced spaces. No data is deleted by this migration.

- Official membership: current ACTIVE/ONBOARDING membership outside network OFF.
- Admitted alumni: OFF membership or legacy active membership in network OFF.
- Former, not admitted: inactive space with profile, own archived figures and an admission request.
- `members.alumni_bridge_enabled` is false by default. Legacy network flags and administrator roles never imply consent. Only `/api/me/alumni-bridge` changes this preference for the authenticated official member.
- Allowed new business pairs: alumni/alumni, or alumni/official with personal consent. Official/official encoding is disabled.
- Alumni cannot read official meetings, welcome planning, documents, platforms, vault or committee inboxes. Historical submissions and business records remain personal.
- System administrators retain administration rights. Former board assignments confer no official permissions in the Alumni space.
- Admission request: `/api/me/alumni-request`. System validation: `/api/members/:id/alumni-activate`. Identity and historical records retain their IDs; future welcome assignments become replacement requests.
- Existing admitted OFF members automatically use the Alumni interface. Existing official users have no connection until they choose it in Profile.
- Availability is an alumni proposal, not a meeting invitation. An opted-in official requests a specific future date with an existing meeting; only the targeted alumnus can accept or decline. Only the parties see the meeting details. Competing accepted requests on the same availability are prevented with a database row lock.
- Incoming lists of alumni e-mails can use existing member creation (status OFF) and individual invitation actions. This release sends no bulk invitations.

Checks: `python -m unittest discover -s backend/tests -q` and `node --test tests/updates.test.mjs tests/alumni-ui.test.cjs`.

## Création et imports administratifs

Dans Administration → Membres, la création à l’unité et les deux imports Excel
partagent le choix `memberType`: `BNI` ou `ALUMNI`. Le serveur impose respectivement
`OFFICIAL_BNI` + `ACTIVE` (ou `ONBOARDING`) et `OFF` + `OFF`, sans consentement
implicite à la liaison personnelle. Le compte ouvre donc l’espace correspondant.
Nom et prénom sont obligatoires ; l’e-mail est facultatif pour créer la fiche.
Créer/importer ne crée pas de compte et n’envoie aucune invitation automatiquement.
L’import présente un aperçu, bloque les doublons et les changements d’espace
involontaires, puis revalide tout le lot avant toute écriture. Les anciens déjà
archivés conservent leur identifiant et leurs anciennes adhésions.

## Suppléances en production

Les appels ouverts sont disponibles dans Participer → Solliciter une suppléance
pour chaque membre actif ayant personnellement activé sa liaison. La date est
choisie parmi les réunions à venir. La publication avertit par notification et
par e-mail tous les anciens admis ayant un compte actif. Aucun mailing de
recrutement ou d’invitation n’est lancé au déploiement.

Le premier ancien qui confirme son engagement obtient le remplacement. Les
autres voient que l’appel est pourvu. Le membre remplacé reçoit une notification
et un e-mail nommant les deux personnes, la date et le lien vers la demande.
Les détails du lieu et de l’horaire restent réservés au membre demandeur et au
suppléant retenu ; les autres anciens gardent uniquement l’annonce de l’appel.

Les routes sont `GET/POST /alumni-space/replacement-needs`,
`POST /alumni-space/replacement-needs/<id>` pour accepter et `DELETE` pour
annuler son propre appel. La table `alumni_replacement_needs` est créée au
démarrage, sans modifier les historiques existants. Une contrainte unique
empêche deux appels du même membre pour la même date. L’acceptation prend les
verrous des membres dans un ordre stable, verrouille l’appel et applique une
mise à jour conditionnelle `OPEN → ACCEPTED`. Les demandes ciblées utilisent les
mêmes verrous et vérifications de conflit, pour éviter les doubles réservations
d’un membre ou d’un suppléant entre les deux parcours.

Les e-mails sont envoyés après validation de la transaction ; une panne SMTP
ne revient pas sur un engagement enregistré. Le rejeu d’une acceptation est
refusé et ne renvoie pas la confirmation. Les contrôles d’accès et de consentement
sont appliqués côté serveur à chaque opération. Les liens d’e-mail et les
notifications ouvrent l’onglet Suppléances de l’interface du destinataire.

Le simulateur, sa boîte mail et l’aperçu Ancien membre de l’administrateur ont
été supprimés. Les données du simulateur étaient uniquement en mémoire dans le
navigateur et n’ont pas été transférées dans la base réelle.

La suite vérifie les accès, les dates, les destinataires des mails, les deux
parcours, les conflits et deux acceptations concurrentes sur la base SQLite
isolée. Les verrous `FOR UPDATE` sont appliqués par PostgreSQL en production ;
les essais automatisés locaux ne constituent pas un test de charge PostgreSQL.
