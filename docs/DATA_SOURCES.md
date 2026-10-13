# Data provenance and reproducible fixtures

HawkerFlow is a fictional teaching chain. Real public location and review-example
data are clearly separated from synthetic sales, customers, stock and feedback.
Neither source endorses this project. No source reviews are attached to invented
local customers or purchases.

## 1. Historical Singapore locations: NEA / data.gov.sg

- **Dataset:** List of Government Markets Hawker Centres.
- **Publisher:** National Environment Agency (NEA).
- **Dataset ID:** `d_68a42f09f350881996d83f9cd73ab02f`.
- **Source:** https://data.gov.sg/datasets/d_68a42f09f350881996d83f9cd73ab02f/view
- **Download API:** https://data.gov.sg/api/action/datastore_search?resource_id=d_68a42f09f350881996d83f9cd73ab02f&limit=1000
- **Licence:** Singapore Open Data Licence v1.0,
  https://data.gov.sg/open-data-licence
- **Source period:** January–September 2016; catalogue last updated 6 June 2024.
- **Retrieved:** 2 October 2026. Exact UTC retrieval time is in `data/source_manifest.json`.
- **Snapshot:** 107 records, seven source columns, plus the API's `_id` field.

The untouched API response is `data/nea_hawker_centres_raw.json`; the CSV is a
serialization of those records. Five centres are selected deterministically:
Adam Road, Amoy Street, Bedok, Berseh and Chomp Chomp. Addresses are retained;
the six-digit postal code is extracted from `S(XXXXXX)`, preserving leading zeros.
The application prefixes centre names with **HawkerFlow Demo**. These fictional
branches are illustrative locations, not actual tenants or a claimed operating
chain. Historical addresses are unsuitable for claims of current operation.

**Required attribution:** Contains information from List of Government Markets
Hawker Centres, accessed on 2026-10-02 from data.gov.sg, made available under
Singapore Open Data Licence v1.0: https://data.gov.sg/open-data-licence

## 2. External restaurant-feedback examples: UCI Yelp subset

- **Dataset:** Sentiment Labelled Sentences, Yelp subset.
- **Creator:** Dimitrios Kotzias, 2015; UCI Machine Learning Repository.
- **Source:** https://archive.ics.uci.edu/dataset/331/sentiment+labelled+sentences
- **DOI:** https://doi.org/10.24432/C57604
- **Download:** https://archive.ics.uci.edu/static/public/331/sentiment+labelled+sentences.zip
- **Licence:** CC BY 4.0, https://creativecommons.org/licenses/by/4.0/
- **Retrieved:** 2 October 2026; exact UTC time in `data/review_source_manifest.json`.
- **Selected file:** `sentiment labelled sentences/yelp_labelled.txt`.
- **Rows:** 1,000 restaurant-review sentences: 500 negative (`0`), 500 positive (`1`).

The original ZIP, extracted Yelp file and source README are bundled. Each source
line is split at its final tab into text and sentiment, given a reproducible
one-based source row number, and imported into the **separate** MongoDB collection
`external_review_examples`. Text is preserved. This collection is a manager-visible
reference corpus; it is not a collection of HawkerFlow customer reviews. There are
no inferred star ratings, tags, order IDs, business IDs, locations or timestamps.

The research sample deliberately excludes neutral examples and balances classes;
its 50% negative share is not a restaurant complaint rate. The app performs no
machine-learning sentiment prediction and makes no model-accuracy claim.

**Dataset citation:** Kotzias, D. (2015). *Sentiment Labelled Sentences* [Dataset].
UCI Machine Learning Repository. https://doi.org/10.24432/C57604

**Associated paper:** Kotzias, D., Denil, M., de Freitas, N., & Smyth, P. (2015).
*From Group to Individual Labels Using Deep Features*. KDD.

## 3. Synthetic operational teaching data

`data/menu_recipes.json` contains a manually curated illustrative menu. Prices and
recipes are project assumptions, not NEA stall measurements or nutritional data.
Quantities use each ingredient's declared unit (`g`, `ml` or `each`); there is no
automatic conversion or certified allergy handling. Optional order notes do not
change recipe deductions or promise allergy-safe preparation.

The default deterministic generator uses seed **20261002** and produces:

| Entity | Default fixtures | Origin |
|---|---:|---|
| Fictional branches | 5 | Historical NEA locations with fictional affiliation |
| Customers | 50 | Synthetic names and `.local` email addresses |
| Menu items | 20 | Curated synthetic teaching catalogue |
| Ingredients | 15 | Curated synthetic teaching catalogue |
| Recipe components | 68 | Explicit ingredient requirements |
| Branch stock rows | 75 | Synthetic opening balances and reorder levels |
| Completed orders | 200 | Seeded through the real SQL checkout service |
| Purchase-linked reviews | 100 | Synthetic and explicitly labelled in review text |
| Customer profiles | 50 | Synthetic optional preferences |
| External review examples | 1,000 | Genuine UCI Yelp sentences, stored separately |
| Development login accounts | 3 | Synthetic manager, cashier and customer |

Orders are dated from 25 August through 27 September 2026. Stock movements and
points records receive the corresponding order timestamp. Each review derives its
order, customer and branch IDs from a completed SQL order and is dated after that
sale. There is no fake cross-dataset purchase join. All balances follow actual recipe
deductions and checkout-generated ledger entries. Customer 1 has sufficient earned
points to demonstrate a 100-point redemption; no hidden points balance is injected.

Opening stock is recorded as positive `seed_opening` movements. Rice and selected
other ingredients have illustrative thresholds that allow the low-stock view to
demonstrate reorder alerts. These are configured scenario thresholds, not empirical
recommendations for a real restaurant.

Synthetic ratings and tags are generated for repeatable analytics. A complaint is
defined as a distinct negative-allowlisted tag on a published review rated 1 or 2;
positive tags are never counted as complaints. Counts describe the teaching fixture,
not any real centre or business.

## Refresh, setup and idempotency

Run from the project directory after installing requirements and configuring both
database connections:

```sh
python scripts/fetch_locations.py
python scripts/fetch_review_examples.py
python scripts/seed.py
```

Both downloads are optional when using the bundled, checksum-verified snapshots.
Refresh replaces snapshot files only; it does not mutate application database rows.
The fetchers refuse incomplete API results, unexpected sentiment labels and wrong
class counts. Raw bytes and derived files have SHA-256 hashes in their manifests.

`seed.py` creates schema/validators and adds missing fixtures. It checks both stores
before SQL mutation, uses stable order request keys, and uses MongoDB `$setOnInsert`
upserts. Repeating the command does not reset stock, reaward points, overwrite edited
reviews/profiles or reset existing passwords. Occupied fixture IDs with incompatible
identities raise an error rather than overwrite user records. Setup assumes a fresh
project database; it is not a migration utility for arbitrary existing schemas.

SQL commits are individually durable. If MongoDB fails after sales are seeded,
rerunning seeds only missing documents. The command is not a cross-database atomic
transaction. `--sql-only` explicitly skips MongoDB and reports that limitation.

`data/seed_run_manifest.json`, written after a successful run, records actual row and
document counts. These counts may exceed fixture counts after interactive use.
Benchmark fixture data and timings are documented separately and must not be confused
with genuine business traffic.

## Development credentials

| Role | Email | Password | Scope |
|---|---|---|---|
| Manager | `manager@hawkerflow.local` | `DemoPass123!` | Demo administration |
| Cashier | `cashier@hawkerflow.local` | `DemoPass123!` | Branch 1 |
| Customer | `customer1@hawkerflow.local` | `DemoPass123!` | Customer 1 orders/profile |

These public credentials are for the local assessed prototype only. Passwords are
salted and hashed through the application's password-hashing function, never stored
as plaintext in the user table.
