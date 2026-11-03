# HawkerFlow role permissions

Status: Implemented in the coordinated role upgrade. See ACCOUNT_ACTIVATION_AND_ROLLOUT.md and the final rollout evidence for verification.

## Roles

Store role values as `admin`, `staff`, and `customer`. Display them as Admin, Staff, and Customer.

- **Admin:** Access to every application feature, including account and role administration, review moderation, and management of all customer preference profiles. Required validation and historical data protections still apply.
- **Staff:** The combined operational permissions of the legacy Manager and Cashier roles. Review access is limited to reading reviews and adding business replies. Staff cannot administer reviews or access customer preference profiles.
- **Customer:** Self-service access to their own account details, purchases, loyalty history, reviews, and preferences. Customers cannot access another customer's private records.

## Permission matrix

| Action | Admin | Staff | Customer |
|---|---|---|---|
| View the menu | Yes | Yes | Yes |
| Create, edit, or deactivate menu items | Yes | Yes | No |
| View ingredient stock and recipes | Yes | Yes | No |
| Receive ingredients and view stock movements | Yes | Yes | No |
| Correct an existing stock quantity with a reason and audit history | Yes | No | No |
| Process sales and redeem points through checkout | Yes | Yes | No |
| Create or update operational customer records | Yes | Yes | Own details through customer self-service only |
| View orders and loyalty history | All | All | Own only |
| Edit or delete an already placed order | No | No | No |
| View sales and feedback analytics | Yes | Yes | No |
| Read purchase reviews | All | All, to support business replies | Own only |
| Add business replies to reviews | Yes | Yes | No |
| Submit a customer purchase review | Yes, with valid customer and purchase context | No | Own verified purchases only |
| Edit or delete review content, ratings, or tags | Any review | No | Own reviews only |
| Moderate reviews or edit/delete business replies | Yes | No | No |
| Read customer preference profiles | Any profile | No | Own profile only |
| Create, edit, or delete customer preference profiles | Any profile | No | Own profile through supported self-service actions only |
| Create Staff or additional Admin accounts | Yes, through protected administration | No | No |
| Change account roles or deactivate login accounts | Yes | No | No |

Operational customer records are separate from login accounts and MongoDB preference profiles. Staff access to customer names, contact details, and sales-related records does not grant access to preference profiles, passwords, account activation, or role assignment. Loyalty changes must use the application's validated business operations.

## Review and preference boundaries

- Admin is the only role that can administer other users' reviews and preference profiles.
- Staff can read reviews and add business replies. They cannot create customer reviews, change ratings or tags, edit or delete customer feedback, moderate reviews, or edit or delete business replies, including their own replies.
- Staff cannot read, create, update, or delete customer preference profiles.
- Customers retain their own review and preference self-service permissions. This is ownership-based self-service, not administration of other users' data.
- Administrative changes must preserve the actual customer/purchase association and authorship. Admin access does not permit fabricated purchase references or rewriting historical account identities.

## Existing account migration

| Existing role | New role |
|---|---|
| `manager` | `staff` |
| `cashier` | `staff` |
| `customer` | `customer` |

Update roles on the existing account rows. Preserve account IDs, passwords, customer links, and all historical references. Do not delete and recreate accounts to change their roles. Do not automatically promote a Manager or Cashier account to Admin.

Existing historical fields such as `orders.cashier_user_id` and MongoDB reply `manager_user_id` may keep their names; their referenced account IDs must remain valid.

## Initial Admin and account creation

- On a fresh installation, a dedicated setup operation creates one initial Admin using explicitly supplied credentials.
- The setup operation is repeatable: if an Admin already exists, it creates no additional Admin and does not reset an existing password.
- On an upgrade with no Admin, bootstrap the initial Admin separately from the migrated Staff accounts.
- Only an authenticated Admin can create privileged accounts or change account roles through protected account administration.
- Public signup always creates a Customer. The server assigns `customer`; signup input must not allow a caller to select or inject `admin` or `staff`.
- Ordinary account/profile updates must not accept role changes. Role assignment belongs to the protected Admin operation.
- Seed accounts must use the new role names and must not assume that the Admin has ID `1`.

## Enforcement and completion checks

The backend must enforce every permission and ownership boundary. Hidden navigation or buttons are not authorization. Use explicit allowlists for known roles and deny unknown roles.

Implementation is complete when automated tests and direct API checks demonstrate that:

1. Admin, Staff, and Customer can each sign in and perform their allowed actions.
2. Staff can use all approved legacy Manager and Cashier operational features.
3. Staff can read reviews and add business replies, but review edits/deletions, moderation, reply edits/deletions, and all preference-profile operations are rejected.
4. Admin can perform all protected administrative actions, including review/profile management and account/role administration.
5. Customers can use their own reviews and preferences but cannot access or change another customer's records.
6. Public signup cannot create privileged accounts, including when a caller submits a forged role or bypasses the website.
7. Unauthenticated requests receive `401`; authenticated requests forbidden by role receive `403`. Ownership failures may use `404` to avoid exposing another user's records. Rejected requests make no unauthorized database changes.
8. Account migration preserves existing account IDs and historical references, and repeated setup does not create duplicate initial Admin accounts.
