# Admin account management

Sign in as Admin and open **Accounts**. Staff and Customers cannot list accounts or call any account-management endpoint.

- **Create account:** the existing form supports Staff, Admin and Customer. Customer requires a name and receives a new customer record with zero points. Email addresses are trimmed, normalized and checked against both accounts and customer records. Creation never claims an existing customer's identity.
- **Search:** matches email, customer name, role, account ID or customer ID, without case sensitivity. It searches the complete account list, including disabled accounts, regardless of the selected status view. Clear search to return to the selected view. Refresh retrieves current account data.
- **Disabled accounts:** only active accounts appear initially. Choose **View disabled accounts** to see inactive accounts, reactivate them or attempt safe deletion. Searching can find either status.
- **Edit details:** change the login email and, for linked customer records, the customer name. Login and customer contact email change in the same transaction. IDs, customer links, points, password and purchase records stay intact. A changed login email ends existing sessions.
- **Save role:** existing role controls retain their protection against removing the last active Admin. An unlinked Staff/Admin account cannot be assigned Customer; create a Customer account instead. Changing the role of a linked account retains its customer association and history.
- **Reset password:** enter and confirm a new password of 12–128 characters. The old password and all issued sessions stop working. A reset does not reactivate a disabled account. Resetting your own password returns you to sign-in. Deliver the new password to the account owner separately; this feature does not send email.
- **Deactivate/Reactivate:** retain the account ID and history. Reactivation requires a fresh sign-in; previously revoked tokens remain invalid.
- **Delete unused account:** available in disabled-account rows, after confirmation. The backend requires the account to be disabled and rejects deletion if any SQL foreign key, nonzero customer balance, review/reply authorship or preference profile links to the account or its customer. MongoDB must be available to verify document links. When safe, only that account and its unused linked customer record are removed. Otherwise leave the account disabled.

## API contracts

| Method | Endpoint | Allowed request fields |
|---|---|---|
| GET | `/api/accounts` | None; returns safe account fields and linked customer name, including both statuses |
| POST | `/api/accounts` | `email`, `password`, `role`; also `name` for Customer |
| PUT | `/api/accounts/{id}` | `email`, optional linked customer `name` |
| PUT | `/api/accounts/{id}/password` | `password` |
| PUT | `/api/accounts/{id}/role` | `role` |
| PUT | `/api/accounts/{id}/status` | Boolean `active` |
| DELETE | `/api/accounts/{id}` | None; disabled, unused accounts only |

Every endpoint requires Admin on the server. Mutation transactions lock and recheck the acting Admin. Payloads reject unknown fields; passwords and session versions are never returned. Validation responses omit submitted input, including credentials. Mongo writes hold a shared SQL account lock so concurrent account disable/delete checks wait for in-flight authorship writes. SQL foreign keys remain enforced during deletion and concurrent checkout.

No MariaDB schema migration is required for these tools. SQLite test/preview schemas use monotonic account IDs to prevent deleted token subjects from being reused; MariaDB already uses persistent AUTO_INCREMENT IDs.
