# Inter BNI Soignies — 26 novembre 2026

Site public autonome de l’événement, servi par Flask/Gunicorn. Racine Railway : `/event-site`, branche `event-26-novembre-2026`. Le Hub existant reste sur sa branche habituelle.

- Page : `/` ou `/event/`
- Inscription : POST `/register.php` ou `/event/register.php`
- Santé : `/health`
- Export organisateur CSV : `/admin/inscriptions.csv`, authentification HTTP Basic, utilisateur `bni`, mot de passe défini dans la variable Railway `BNI_EVENT_ADMIN_PASSWORD`.
- Volume persistant monté en `/data`, variable `BNI_EVENT_DATA_DIR=/data`.
- `BNI_EVENT_RATE_SECRET` : secret pour le hachage des clés de limitation de débit.

Les inscriptions sont conservées dans SQLite sur le volume privé. Le total est calculé côté serveur à 15 EUR par personne. L’export conserve le statut « À vérifier par virement » : aucun rapprochement bancaire automatique. Les essais authentifiés marqués `isTest:true` sont exclus de l’export et peuvent être nettoyés via POST `/api/admin/test-registrations/cleanup` ; cette route ne supprime jamais de vraies inscriptions.

Tests : `python -m unittest -v test_app.py` (base temporaire indépendante).

## Photographies réelles

- Filip Rankovic Grobgaard, publié le 15 janvier 2026 : https://unsplash.com/photos/people-mingling-at-a-formal-event-with-drinks-fKzdMDr6wEo — licence https://unsplash.com/license
- George Morina : https://www.pexels.com/photo/men-in-black-and-blue-suit-having-conversation-while-holding-drinking-glasses-6918426/ — licence https://www.pexels.com/license/

Images d’illustration, sans lien avec les participants de l’événement. Crédits présents sur la page. Images servies localement.


## Notifications d’inscription

Chaque inscription réelle ajoute une notification dans une file SQLite persistante, dans la même transaction que la réservation. Le worker du processus Gunicorn unique transmet vers `event@bim-soignies.be` (variable `BNI_EVENT_NOTIFY_TO`) et réessaie en cas d’échec SMTP. Les doublons de soumission ne créent pas une deuxième notification. Les inscriptions réelles déjà présentes sont ajoutées à la file lors du premier démarrage de cette version.

Variables SMTP héritées par références Railway depuis le service BNI Hub API : SMTP_HOST, SMTP_PORT, SMTP_SSL, SMTP_STARTTLS, SMTP_USER, SMTP_PASSWORD, SMTP_FROM. Aucune valeur sensible dans le dépôt. `BNI_EVENT_NOTIFICATIONS_ENABLED=true` active le worker. Ne pas augmenter le nombre de workers ni activer le preload sans adapter le mécanisme de worker.

Les essais sont exclus des emails sauf si une requête administrateur comporte explicitement `isTest:true, notifyTest:true` ; le sujet porte alors le préfixe `[TEST]`. Suivi technique réservé à l’administrateur : GET `/api/admin/notifications/status`. Le statut `sent` signifie que le serveur SMTP a accepté l’email, pas qu’une lecture dans la boîte finale a été vérifiée.


## Confirmation participant et engagement de paiement

Email et téléphone obligatoires. Option facture / note de frais avec numéro de TVA obligatoire si sélectionnée. L’organisateur reçoit la demande de document ; aucune facture n’est produite automatiquement.

La validation exige `paymentAccepted:true` côté serveur. Le montant dû même en cas d’absence est affiché avant validation, dans la case obligatoire, sur le bouton avec le total, dans le récapitulatif et les emails. Le texte versionné et l’horodatage de l’accord sont conservés dans le payload et l’export CSV. Ce sont des informations d’inscription : elles ne constituent pas une confirmation bancaire.

Deux livraisons indépendantes sont créées dans `email_deliveries` : `organizer` vers event@bim-soignies.be et `participant` vers l’email saisi. L’ancienne table `email_outbox` est conservée pour migrer l’état des notifications sans renvoyer celles déjà acceptées par SMTP. Les anciens participants sans email renseigné ne peuvent pas recevoir de confirmation automatique.
