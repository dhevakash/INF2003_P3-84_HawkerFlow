# HawkerFlow implementation contract

Use Python FastAPI, SQLAlchemy 2, MariaDB 10.11.14 (InnoDB), MongoDB 7.0.16, a plain HTML/CSS/JS frontend. API prefix /api. Database image tags match the real engines tested. Core workflow is order -> batches -> stock -> points in one SQL transaction; Mongo is not on the checkout commit path. Expiry allocation uses FEFO and excludes expired batches. Reports distinguish real location data and synthetic operational data. Enhancement details and verification: docs/EXTRA_CREDIT_GUIDE.md and evidence/extra-credit/RESULTS.md.

## Shared dependencies
`app.db.get_session()` yields SQLAlchemy Session; `app.db.SessionLocal`, `engine`, `init_db()`. Models use `app.db.Base`. SQL services must be independent of FastAPI and callable from tests.
`app.security.current_user` is FastAPI dependency returning User; `app.security.require_roles(*roles)` returns dependency; The security module supplies hash_password and verify_password. User has id, email, name, password_hash, role (manager/cashier/customer), customer_id nullable, branch_id nullable, is_active. Authentication routes return bearer token and user {id,name,email,role,customer_id,branch_id}.
`app.config.settings` exposes sql_url,mongo_url,mongo_database,secret_key, token_minutes. env SQL_URL, MONGO_URL, MONGO_DATABASE, SECRET_KEY. No silent mock fallback in live app. The health route must distinguish connectivity to both stores.

## SQL model contract
Branch(id,name,address,postal_code); Customer(id,name,email); MenuItem(id,name,category,price,is_active); Ingredient(id,name,unit); RecipeComponent(menu_item_id,ingredient_id,quantity); BranchStock(branch_id,ingredient_id,quantity,reorder_level); StockMovement(id,branch_id,ingredient_id,quantity_delta,reason,order_id nullable,created_at); Order(id,branch_id,customer_id,status,total,points_redeemed,request_key unique,created_at); OrderLine(id,order_id,menu_item_id,quantity,unit_price,notes); LoyaltyTransaction(id,customer_id,order_id nullable,points_delta,event_type,created_at); User as above. StockReceipt(id,branch_id,ingredient_id,quantity,request_key unique,payload_hash,created_at) supports audited idempotent restocking. Independent benchmark tables are created only by scripts/benchmark.py.

## HTTP contract
List endpoints return arrays, errors JSON {detail:...}. IDs integers. Decimal values serialized numeric or string accepted by frontend. Dates ISO8601 UTC. No SQL sessions span Mongo writes. Routes should respond clear 409 business conflict, 422 invalid inputs, 401/403 authorization failures, 503 Mongo unavailable.

SQL:
GET /branches; GET /customers; POST /customers {name,email}; GET /menu; POST /menu {name,category,price}; PATCH /menu/{id} subset; DELETE /menu/{id} soft deactivation.
GET /ingredients; GET /inventory?branch_id=1 returns ingredient_id,name,unit,quantity,reorder_level; POST /inventory/receive {branch_id,ingredient_id,quantity,request_key}; receiving deduplicated and audited.
POST /orders {branch_id,customer_id,request_key,redeem_points:0,lines:[{menu_item_id,quantity,notes:""}]} -> order including lines, points_earned and loyalty_balance. 1 point per dollar floor after redemption; 100 points -> $1 discount, redemption multiples of 100; cannot exceed balance or bill; complete cash sale only; refunds deferred. Never consume stock from user prices. Seed recipes required for every sold item.
GET /orders?branch_id=1&customer_id= optional; GET /orders/{id}; GET /loyalty/{customer_id} {balance,transactions}; GET /analytics/sales?start=YYYY-MM-DD&end=YYYY-MM-DD returns branches/menu analytics, dates use end-exclusive; GET /analytics/low-stock?branch_id=1.
Staff roles manager/cashier can checkout; customers can only read their own order/points. Manager only menu mutations/restocks; cashier restricted to assigned branch. SQL analytics managerial only. Menu/branches read authenticated. Customers list staff only.

Mongo:
GET /reviews?branch_id=&limit=; POST /reviews {order_id,rating,text,tags:[],category_ratings:{}} verifies completed order ownership (customers own; manager may demo but customer_id derived from order). PATCH /reviews/{id} fields; DELETE /reviews/{id} owner/manager; POST /reviews/{id}/replies {text} manager only. Single review per order, required ids/date, rating1..5, bounded text/tags/replies, deduplicate normalized tags. Only manager can reply; POST body cannot override IDs/moderation/replies.
GET /profiles/{customer_id}; PUT /profiles/{customer_id} {dietary_preferences:[],favourite_categories:[],communication_preferences:{},milestones:{}} owner/manager. No point balance stored in Mongo.
GET /analytics/feedback?branch_id=&start=&end= -> {complaints:[{tag,count}],rating_trends:[{month,average,count}],total_reviews}. Negative tag allowlist and low-rating rule explicit. Only manager.

UI is 4 sections orders/inventory/customer feedback/manager intelligence. Manager intelligence has sales, forecast, waste/promotions, loyalty and reviews tabs. Login switches manager/cashier/customer test roles. Document provided development credentials; no real payments, no production claims.

## Extra-credit contract

Additive tables: StockBatch(id,branch_id,ingredient_id,receipt_id nullable unique,initial_quantity,remaining_quantity,expires_on nullable,unit_cost nullable,source,created_at); StockBatchAllocation(id,batch_id,order_id,quantity); StockBatchDiscard(id,batch_id unique,request_key unique,quantity,actor_user_id nullable,movement_id unique,created_at). init_db creates added tables and backfills aggregate stock as unknown-expiry batches without altering existing table layouts. Unit cost is per ingredient stock unit.

GET /menu/availability?branch_id: staff and assigned-branch scope; recipe-based portions and ingredient requirements. GET /inventory/batches?branch_id: staff scoped; batch expiry statuses. POST /inventory/receive additionally accepts expires_on/unit_cost and includes them in replay identity. POST /inventory/batches/{id}/discard {request_key}: manager-only, past-date expired batches, idempotent audit and stock movement.

GET /analytics/dashboard?start=&end=&branch_id= optional: manager-only; net summary, gross menu sales, DENSE_RANK quantity rankings, daily zero-filled totals, UTC peak hours, equal-period comparisons and declining dishes. End exclusive; max range 366 days.

GET /analytics/forecast?branch_id=&as_of=&window_days=28&target_days=7&lead_days=2: manager-only; negative recorded sale movements, calendar CTE, seven-day window average and restock calculation. as_of is exclusive UTC history cutoff; current stock/expiry uses Singapore stock_as_of; not reconstructed historical stock.

GET /analytics/waste?branch_id=&as_of=&horizon_days=7: manager-only; current remaining batches assessed for expiry on as_of, known values and explained promotion ranking. Window for promotion popularity is 28 Singapore calendar days ending on assessment day. No automatic discounts.

GET /analytics/loyalty?as_of=&window_days=90&branch_id= optional: manager-only; lifetime recency and trailing-window frequency/net spend, deterministic RFM scores and segments. Customers with zero orders retained; no churn-model claim.

## Verification
SQLite/mongomock unit checks and actual MariaDB/Mongo integration checks have both run successfully; see docs/EVALUATION.md. Include rollback, overselling, duplicate request, historic price, point balance/redemption, role/ownership, Mongo validator/unique constraints, SQL-Mongo benchmark identical answers. Benchmark on real DB only, no fabricated times.
