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
