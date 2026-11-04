# Customer signup and optional birthday verification

Verified on 4 November 2026. The updated local app is running at `http://localhost:8080`.

## Requirements checked

- Login links to the customer signup form, which requires Name, Email, Password and Confirm password. Birthday is optional.
- The backend assigns Customer unconditionally, rejects role/ID/points injection, validates names/emails/passwords and birthdays, and rejects email duplicates across login and customer records without claiming existing identities.
- Passwords use the existing salted PBKDF2 hash. Confirmation is checked in the browser and whenever provided to the API; it is never stored. Validation responses do not echo submitted passwords.
- A single SQL transaction creates the login and linked customer. Failure of either insert rolls back both. Concurrent duplicate signups create exactly one complete account.
- A new customer signs in immediately with zero points, empty own purchase history and empty loyalty activity. The website shows a Points balance and View my purchases; birthday is shown when supplied.
- The new customer summary uses the authenticated customer link. Other IDs in query parameters do not change its owner. It is Customer-only; operational customer lists do not expose birthdays. Private summary data clears on logout/access changes.

## Validation results

- **364 Python backend tests passed**, including **59 signup tests**. Six optional legacy migration tests skipped; 46 integration cases excluded from that unit/API run.
- **60 DOM UI tests passed.**
- **13 real MariaDB/MongoDB transaction tests passed**, including simultaneous duplicate signup and a failed second insert.
- **14 UI-to-real-HTTP integration flows passed** against disposable databases, including birthday persistence, immediate sign-in, zero points, own empty history, invalid/future dates, confirmation mismatch, duplicate emails and role/ownership boundaries.
- Native calendar/browser layout was not visually inspected; UI checks used jsdom with mocked and real HTTP responses.
- Localhost checks passed for all three existing roles, deployed asset/source equality, signup controls, customer summary ownership, duplicate rejection and invalid signup rejection. No valid signup or other live data mutation was submitted by these checks.

## Database release

Both stores were backed up. The SQL backup was restored to an owned test database, compared with every live table, and migration 005 was applied twice. A saved leap-day birthday also survived another repeat. Fresh backups and this rehearsal were repeated immediately before the live migration.

Migration `005_customer_birthday.py` added only `customers.birthday DATE NULL`. Existing rows, IDs, password hashes, role links, balances, purchases and Mongo documents remained unchanged. Before/after fingerprints verified **14 SQL tables, three Mongo collections, 54 accounts and 200 orders**. Existing birthdays remain unset.

The preview and all three owned test databases were removed after verification. Source changes and the live data backups remain available locally. Birthday data is stored for later features; signup does not award birthday points.
