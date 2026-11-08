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

## Invitation des anciens

Le bouton Inviter envoie aux anciens le message validé « Et si on gardait le lien ? »
avec le prénom, le lien d’activation personnel valable 48 h, le tutoriel iPhone/Android,
les contacts et la signature HUB – BIM. `hub@bim-soignies.be` est en copie (Cc).
Les nouveaux membres BNI conservent leur modèle distinct, sans cette copie.
Le déploiement ne renvoie pas les invitations précédentes et ne lance aucun lot.

## Sessions et statut des copies

Les sessions durent 90 jours. `GET /auth/me` prolonge une session valide à 90 jours
au maximum une fois par jour, et met aussi à niveau les anciennes sessions valides.
Les sessions expirées ou révoquées ne sont pas réactivées. Logout et changement
de mot de passe conservent leurs mécanismes de révocation. L’interface ne supprime
le jeton qu’en cas de réponse 401 ; une panne réseau ou une erreur serveur conserve
la session et propose de réessayer. Les réponses d’une ancienne session ne doivent
pas effacer un nouveau jeton.

Les copies d’invitations couvrent les anciens admis et les fiches archivées FORMER.
Elles gardent l’en-tête Cc mais sont transmises dans une enveloppe SMTP séparée,
explicitement adressée à hub@bim-soignies.be. Le statut de l’invitation et celui de
la copie sont suivis indépendamment (`emailSent`, `copyEmailSent`) et présentés
dans l’administration. Les acceptations/refus sont inscrits au journal d’audit
sans stocker le contenu du message ni son jeton. SMTP accepté ne prouve pas une
réception dans la boîte principale : le classement, les quarantaines et les
rejets ultérieurs restent à vérifier sur le serveur de messagerie.

## Visibilité de la liaison pour les membres

Le bloc Profil initialise sa visibilité à partir de l’environnement déjà
validé par `/auth/me`. Un échec du chargement complémentaire `/alumni-space/me`
ne masque plus le bouton d’activation d’un membre actif. Une actualisation est
proposée en cas d’erreur ; les autorisations restent vérifiées par le serveur.
L’annuaire d’administration expose pour chaque fiche l’environnement effectif,
la possibilité d’activer la liaison et son état choisi par le membre. Il
distingue les actifs/en intégration (choix personnel disponible), les anciens
admis (interface Anciens directe) et les fiches archivées hors groupe.
Aucun consentement n’est activé automatiquement par cette vérification.

## Mode Doppelganger / assistance réelle

Le super administrateur peut ouvrir « Voir comme ce membre » depuis une fiche
de l’annuaire dont le compte est actif. Aucun mot de passe n’est utilisé ou
modifié. Le serveur crée une session déléguée de 30 minutes maximum, liée au
compte cible et à la session du super administrateur. Les sessions normales du
membre restent valides. Les comptes super administrateurs ne sont pas des cibles.

La session déléguée est en lecture seule, sans droits d’administration. Le serveur
bloque ses mutations, même en appelant directement une route, et contrôle le
compte du membre ainsi que les droits et la validité de la session de l’acteur
à chaque requête. La session n’est pas prolongée par `/auth/me`. La révocation
ou l’expiration du parent invalide aussi l’accès délégué.

Le jeton d’assistance reste dans le sessionStorage de l’onglet, séparé du jeton
administrateur conservé. Une bannière identifie le membre et permet de revenir
au compte administrateur ; les navigations sont séparées. Une expiration restaure
la session administrateur si elle est encore valide. L’ouverture et la fermeture
sont auditées au nom de l’acteur, sans stocker le jeton brut.

Routes : `POST /system/support-sessions` avec `memberId` (super administrateur),
puis `POST /system/support-sessions/stop` avec le jeton délégué. Deux colonnes
nullables de `auth_sessions` identifient l’acteur et la session parente ; elles
sont ajoutées au démarrage sur PostgreSQL sans changer les sessions existantes.

## Diagnostic et récupération des copies d’invitation

Chaque copie possède désormais son propre en-tête To (hub@bim-soignies.be),
un objet préfixé « Copie HUB », une date et un Message-ID distinct. Le contenu
d’invitation est conservé ; l’enveloppe SMTP n’inclut que le HUB. L’original
conserve son destinataire et son Cc visibles, sans deuxième envoi au membre.
Les erreurs exposent une catégorie non secrète et, si disponible, le code SMTP.
Le refus d’un destinataire peut inclure la réponse du serveur (bornée et sans
sauts de ligne) ; les erreurs d’authentification n’exposent jamais leur contenu.

`POST /members/<id>/invite-copy` est réservé aux administrateurs et reprend le
lien existant d’une invitation d’ancien encore valide, sans changer le compte,
le jeton ou la date d’expiration, et sans envoyer de message au membre. Une
invitation consommée ou expirée est refusée. L’annuaire propose « Renvoyer copie
HUB » pour les anciens dont l’invitation est en attente.

`POST /system/mail-test`, réservé au super administrateur, envoie un message de
vérification uniquement au HUB. Le bouton est disponible dans Administration
→ Membres. Ces deux actions restent interdites en session Doppelganger.
Les résultats sont affichés dans l’administration et les refus techniques sont
tracés dans les logs et le journal d’audit. Un résultat SMTP accepté ne confirme
pas le classement effectif dans la boîte principale.

## Agenda partagé

`GET /api/agenda?month=YYYY-MM` est accessible aux comptes actifs des deux espaces,
indépendamment du consentement aux échanges business. L'agenda présente les réunions
(dates, type, horaire et lieu) ainsi que les demandes EVENT datées. Il ne donne pas
accès aux invités, notes internes, documents ni fonctions administratives du groupe.
Voir une réunion ne vaut pas invitation : les anciens utilisent les suppléances.

Un membre ou un ancien publie un événement avec `POST /api/me/requests` (type EVENT,
titre et eventDate obligatoires, eventTime et eventLocation facultatifs, pièce jointe
jusqu'à 5 Mo). Les autres comptes activés des deux espaces reçoivent une notification
qui ouvre le mois concerné. Les pièces jointes des événements datés sont partagées ;
les autres demandes et leurs pièces jointes conservent leurs accès privés. Les
anciennes propositions datées apparaissent aussi ; aucune date n'est inventée pour
les propositions historiques sans date. Les mails au comité restent en place.

Le Planning affiche le prochain rôle d'accueil publié du membre et ses collègues,
quelle que soit la page mensuelle sélectionnée. Le bouton des permanences est gardé ;
chez un ancien, il ouvre ses disponibilités et remplacements. Le mode assistance
reste en lecture seule, y compris pour la publication d'événements.

## Sessions et confirmations au comité d'accueil

Le Profil des membres, anciens et comptes hors groupe propose la déconnexion
volontaire de la session courante. La durée des sessions ordinaires reste de
90 jours, renouvelée par l'usage. En assistance, ce bouton revient au compte
administrateur et ne déconnecte pas le compte du membre consulté.

Lors de l'acceptation d'une suppléance (appel ouvert ou demande ciblée), le membre
remplacé garde son e-mail et une confirmation est aussi adressée à Amélie Loedt et
Simon Vanwymeersch, identités du roster du groupe. Les adresses viennent de leurs
fiches actuelles (compte actif, sinon adresse membre). Aucun choix sur le seul prénom,
aucune adresse inventée : un doublon d'identité, une fiche absente ou une adresse
manquante empêche cet envoi et est journalisé. L'e-mail comporte ancien, membre
remplacé, date, horaire, lieu et lien Planning. L'acceptation répétée est rejetée et ne
renvoie pas les e-mails. Les échecs SMTP ne défont pas une suppléance confirmée.

## Correction des encodages

Administration → Corriger les encodages : le comité directeur actuel et le super
admin peuvent rechercher les MPB, TAT ou recommandations d'un membre, corriger date,
montant/valeur estimée, durée ou notes, et supprimer un doublon. Un motif est exigé.
Les modifications sont atomiques et refusent une version devenue obsolète. Les
valeurs avant/après, le motif et l'auteur restent dans l'audit ; aucune notification
ni aucun e-mail business n'est renvoyé lors d'une correction. Les statistiques
relisent les enregistrements corrigés. L'assistance reste en lecture seule.
Une recommandation ayant des MPB ne peut pas être supprimée directement. Supprimer
son dernier MPB la remet à PENDING si elle était WON, avec entrée d'historique.

## Anciens venant comme invités

`/api/alumni-visits` permet à un ancien actif de demander une venue personnelle,
avec date et projet. Deux demandes maximum sont admises par mandature de la réunion,
y compris celles refusées ou retirées ; les répétitions d'une même requête en attente
ne consomment pas de demande supplémentaire. Un verrou membre protège ce quota.
L'historique est conservé dans alumni_guest_visits et ne peut pas être effacé par
l'ancien pour récupérer une demande.

Les demandes sont notifiées et envoyées aux identités exactes Amélie Loedt, Simon
Vanwymeersch et Xavier Renaud, via les adresses de leurs fiches. Le lien canonique
`/?guestVisits=1` ouvre le formulaire de décision après connexion. Seuls les deux
responsables identifiés ou le super admin peuvent valider/refuser. Une validation
atomique crée un NetworkVisitor INVITED ; un refus ne crée aucun invité. L'ancien
reçoit un e-mail de décision et une notification. Le compteur des demandes ne change
pas lors d'une décision ou d'un retrait.

Depuis ses disponibilités, l'ancien peut choisir « Venir comme invité ». La conversion
retire cette disponibilité et annule ses sollicitations ciblées en attente pour le
même jour. Une suppléance déjà confirmée ne peut pas être convertie silencieusement :
il faut contacter le comité. Une visite approuvée empêche une réservation concurrente
comme suppléant. Une demande d'invitation en attente peut être retirée par son auteur ;
une inscription déjà acceptée doit être modifiée avec le comité.

Les identités des validateurs sont figées par identifiant membre lors de la mise en service (guest_visit_reviewers). Modifier un prénom ou un nom dans son profil ne donne aucun droit de validation et ne détourne pas les e-mails.
