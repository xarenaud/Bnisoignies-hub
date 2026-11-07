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

## Aperçu administrateur des deux participants

Le bouton « Vue Ancien membre » est réservé au compte administrateur système.
Il ouvre un parcours local en mémoire avec deux identités fictives, et réutilise
les composants Membres et Anciens. Le bandeau permet de changer de participant,
réinitialiser les essais ou revenir au compte réel. Aucun statut réel ne change.
`src/preview.js` intercepte les appels de ces composants pendant le test :
seule la lecture de la session réelle (`GET /auth/me`) est transmise au serveur.
Toutes les autres requêtes restent locales et les écritures non simulées sont
refusées. La navigation de test est séparée de la navigation réelle. Les essais
(recommandations, MPB, TAT, liaison, notifications et suppléances) disparaissent
à la fermeture du test ou au rechargement. Ce simulateur vérifie le parcours
visuel et les échanges entre participants ; il ne remplace pas les tests API
d’isolation, de consentement, de réunion existante ou d’envoi de mails.
