Type: grilling
Status: resolved
Blocked by: 01

# Specify the simplified settings surface

## Question

Turn the settled settings intent into a precise user/admin settings contract.

All users retain theme, display name, Kindle address, notification email address, and notification enablement. Admins, not users, control usernames, passwords, and instance configuration. Decide the page structure and API/settings ownership, which existing Delivery Preferences/output mode/destination/metadata-provider controls are removed versus retained as admin-only configuration, and the clean deletion boundaries for obsolete user settings. BookFlow is greenfield: no compatibility or data migration path is required. Notification event selection and delivery behavior remain out of scope.

## Answer

- Preserve the existing administrator Settings modal: it retains its multi-section sidebar and all instance-level operational configuration. The MVP changes visibility and ownership, not this shell.
- Replace the normal-user settings experience with one self-settings pane. It displays login username/account email read-only and permits edits only to display name, Kindle address, notification email address, and notification enablement. Theme remains a local preference in that pane.
- Persist the four server-backed editable self-settings values through one explicit self-settings contract, rather than the generic per-user override categories. The notification ticket defines the replacement notification shape and behavior.
- Administrators manage account identity and access: username, password reset, active/admin state, and Library Capability. They do not edit another user's personal preferences.
- Remove the obsolete per-user override model rather than hiding it: its delivery, search, and request-policy sections, stored override keys, endpoints, and administrator editing UI. BookFlow is greenfield, so no migration or compatibility path is retained.
