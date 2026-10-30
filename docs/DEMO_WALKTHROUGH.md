# Working demo walkthrough

## SQL sale and inventory

1. Run schema initialization and seed, then check `/api/health`.
2. Sign in as manager. Open Customers and note Customer 1's points. Open Stock and note the ingredient amounts for branch 1.
3. Complete a sale for branch 1/customer 1/menu item 1. Orders should show the new order, stock should decrease according to its three recipe components, and points should increase by the whole-dollar net total.
4. In `/docs`, authenticate using the bearer token returned by `/api/auth/login`. Submit the same checkout request key/payload twice. Expect one order and no second stock/points change.
5. Submit a cart that requires more stock than available. Expect rejection and unchanged order, stock and points counts. Use dedicated test data for this scenario.
6. Record a receipt. Stock rises and its movement references the receipt. Inspect `/api/stock/movements`.
7. Use `/api/menu` POST, PUT and DELETE on a temporary unused menu item to demonstrate SQL CRUD. Historical items cannot be physically deleted.
8. Open Sales insights: explain SQL views, joins, aggregates, revenue ranking and the above-average-customer nested query using the source code.

## NoSQL review and preferences

1. Note the new order ID, sign out and sign in as `customer1@hawkerflow.local`.
2. Submit a review for that new order. A review for another customer's order must fail. A duplicate review for the same order must fail.
3. In `/docs`, edit and delete a review using the same customer's token. Re-create it for the reply demo.
4. Save and retrieve preferences with `/api/profiles/me`.
5. Sign in as manager. Use `/api/reviews/{order_id}/replies`, then show that the reply is embedded in the review document.
6. Open Feedback insights. Explain negative-tag counts and monthly branch ratings. Do not treat the separate UCI examples as purchase feedback.
7. Run real integration tests to demonstrate server-side document rejection and unique indexes, not only API input checks.

## Evaluation

Run `python scripts/benchmark.py --rows 10000 --repetitions 20` with real MariaDB/MongoDB configuration. Open the resulting JSON from `evidence/`. Explain equal inputs, verified equal results, indexes, warmups, alternating timing order and scope. Record CPU/RAM/container limits and repeat at more than one data size. Do not generalize one workload into a universal SQL/NoSQL winner.

For the eventual presentation follow the brief's order: background/data, relational design and demo, NoSQL design and demo, then optional evaluation. All five members must appear. Slides, video and final report are separate future deliverables.
