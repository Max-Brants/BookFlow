Type: grilling
Status: resolved
Blocked by: 01, 03

# Specify the user notification contract

## Question

Define the notification contract that fits the library-first MVP and reconcile it with BookFlow's existing notification machinery.

For regular users, delivery is email only, configured with an email address distinct from the Kindle address, and controlled by one enable/disable switch rather than per-event preferences. The only user-visible events are request approved, request rejected, and requested book available (the requested book now has actual files). Decide the exact event-to-state-transition mappings, whether admins need a separate event surface under this MVP, API/settings shape, and how existing irrelevant user notification choices are removed or migrated. Role relevance is mandatory: a non-admin must never subscribe to events such as new request submitted.

## Answer

Notifications separate role-relevant events from delivery transports.

- Personal Notifications are optional and use exactly one saved transport: SMTP email or a user-provided Apprise URL. Their persisted self-settings shape is `notifications_enabled`, `notification_transport`, and `notification_destination`. Changing transport replaces the old destination. Enabling requires a valid destination for the selected transport. `PUT /api/users/me` is the single self-settings contract, and a saved enabled destination may receive a transport-neutral test notification.
- Personal Notifications have no event picker. They send only `Requested book available` when a pending Request becomes `fulfilled` because completed Files become available by any path, and `Request rejected` when an administrator explicitly transitions that Request from `pending` to `rejected`. The available message includes the Book title, author, and a direct Book-detail link; rejection has the same context plus an optional administrator note.
- `Request approved` is removed: queueing a Download is not a user-visible state transition. No personal notification is sent for Request creation, Download queueing or failure, cancellation, or another requester's Request transition.
- The existing SMTP configuration is the one email delivery system. It is reused for Send to Kindle, Personal Notifications sent by email, and administrator email targets. Apprise remains available for arbitrary personal and administrator Apprise targets.
- Administrator Notifications remain instance-level operational configuration. Each target is `{ transport, destination, events }`, with email or Apprise as the transport and any subset of `New request submitted`, `Download complete`, and `Download failed` as events. Personal event types are never exposed to a non-admin, and user event types are not an administrator target requirement.
- Delete the existing per-user notification-route preferences, their per-event selectors, and their user/admin override and test endpoints. Replace them with the self-settings contract and active-destination test endpoint. BookFlow is greenfield, so no migration is retained.
