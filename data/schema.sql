-- Generated from app/models.py. 15 operational InnoDB tables.
-- Use an empty MariaDB schema; normal setup is scripts/seed.py.

CREATE TABLE branches (
	id INTEGER NOT NULL AUTO_INCREMENT,
	name VARCHAR(150) NOT NULL,
	address VARCHAR(300) NOT NULL,
	postal_code VARCHAR(6) NOT NULL,
	PRIMARY KEY (id)
)ENGINE=InnoDB;

CREATE TABLE customers (
	id INTEGER NOT NULL AUTO_INCREMENT,
	name VARCHAR(150) NOT NULL,
	email VARCHAR(254) NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (email)
)ENGINE=InnoDB;

CREATE TABLE ingredients (
	id INTEGER NOT NULL AUTO_INCREMENT,
	name VARCHAR(150) NOT NULL,
	unit VARCHAR(20) NOT NULL,
	PRIMARY KEY (id),
	UNIQUE (name)
)ENGINE=InnoDB;

CREATE TABLE menu_items (
	id INTEGER NOT NULL AUTO_INCREMENT,
	name VARCHAR(150) NOT NULL,
	category VARCHAR(80) NOT NULL,
	price NUMERIC(12, 2) NOT NULL,
	is_active BOOL NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_menu_price CHECK (price >= 0)
)ENGINE=InnoDB;

CREATE TABLE branch_stock (
	branch_id INTEGER NOT NULL,
	ingredient_id INTEGER NOT NULL,
	quantity NUMERIC(14, 4) NOT NULL,
	reorder_level NUMERIC(14, 4) NOT NULL,
	PRIMARY KEY (branch_id, ingredient_id),
	CONSTRAINT ck_stock_quantity CHECK (quantity >= 0),
	CONSTRAINT ck_stock_reorder CHECK (reorder_level >= 0),
	FOREIGN KEY(branch_id) REFERENCES branches (id),
	FOREIGN KEY(ingredient_id) REFERENCES ingredients (id)
)ENGINE=InnoDB;

CREATE TABLE orders (
	id INTEGER NOT NULL AUTO_INCREMENT,
	branch_id INTEGER NOT NULL,
	customer_id INTEGER NOT NULL,
	status VARCHAR(20) NOT NULL,
	total NUMERIC(12, 2) NOT NULL,
	points_redeemed INTEGER NOT NULL,
	request_key VARCHAR(100) NOT NULL,
	request_payload_hash VARCHAR(64) NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_order_total CHECK (total >= 0),
	CONSTRAINT ck_order_redemption CHECK (points_redeemed >= 0 AND points_redeemed % 100 = 0),
	CONSTRAINT ck_order_status CHECK (status = 'completed'),
	FOREIGN KEY(branch_id) REFERENCES branches (id),
	FOREIGN KEY(customer_id) REFERENCES customers (id),
	UNIQUE (request_key)
)ENGINE=InnoDB;

CREATE INDEX ix_orders_branch_date ON orders (branch_id, created_at);

CREATE INDEX ix_orders_customer_id ON orders (customer_id);

CREATE TABLE recipe_components (
	menu_item_id INTEGER NOT NULL,
	ingredient_id INTEGER NOT NULL,
	quantity NUMERIC(14, 4) NOT NULL,
	PRIMARY KEY (menu_item_id, ingredient_id),
	CONSTRAINT ck_recipe_quantity CHECK (quantity > 0),
	FOREIGN KEY(menu_item_id) REFERENCES menu_items (id),
	FOREIGN KEY(ingredient_id) REFERENCES ingredients (id)
)ENGINE=InnoDB;

CREATE TABLE stock_receipts (
	id INTEGER NOT NULL AUTO_INCREMENT,
	request_key VARCHAR(100) NOT NULL,
	branch_id INTEGER NOT NULL,
	ingredient_id INTEGER NOT NULL,
	quantity NUMERIC(14, 4) NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_receipt_quantity CHECK (quantity > 0),
	UNIQUE (request_key),
	FOREIGN KEY(branch_id) REFERENCES branches (id),
	FOREIGN KEY(ingredient_id) REFERENCES ingredients (id)
)ENGINE=InnoDB;

CREATE TABLE users (
	id INTEGER NOT NULL AUTO_INCREMENT,
	email VARCHAR(254) NOT NULL,
	name VARCHAR(150) NOT NULL,
	password_hash VARCHAR(255) NOT NULL,
	`role` VARCHAR(20) NOT NULL,
	customer_id INTEGER,
	branch_id INTEGER,
	is_active BOOL NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_user_role CHECK (role IN ('manager','cashier','customer')),
	UNIQUE (email),
	FOREIGN KEY(customer_id) REFERENCES customers (id),
	FOREIGN KEY(branch_id) REFERENCES branches (id)
)ENGINE=InnoDB;

CREATE TABLE loyalty_transactions (
	id INTEGER NOT NULL AUTO_INCREMENT,
	customer_id INTEGER NOT NULL,
	order_id INTEGER,
	points_delta INTEGER NOT NULL,
	event_type VARCHAR(40) NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_points_nonzero CHECK (points_delta <> 0),
	FOREIGN KEY(customer_id) REFERENCES customers (id),
	FOREIGN KEY(order_id) REFERENCES orders (id)
)ENGINE=InnoDB;

CREATE INDEX ix_loyalty_customer_date ON loyalty_transactions (customer_id, created_at);

CREATE TABLE order_lines (
	id INTEGER NOT NULL AUTO_INCREMENT,
	order_id INTEGER NOT NULL,
	menu_item_id INTEGER NOT NULL,
	quantity INTEGER NOT NULL,
	unit_price NUMERIC(12, 2) NOT NULL,
	notes VARCHAR(500) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_line_quantity CHECK (quantity > 0),
	CONSTRAINT ck_line_price CHECK (unit_price >= 0),
	FOREIGN KEY(order_id) REFERENCES orders (id),
	FOREIGN KEY(menu_item_id) REFERENCES menu_items (id)
)ENGINE=InnoDB;

CREATE INDEX ix_order_lines_order_id ON order_lines (order_id);

CREATE TABLE stock_batches (
	id INTEGER NOT NULL AUTO_INCREMENT,
	branch_id INTEGER NOT NULL,
	ingredient_id INTEGER NOT NULL,
	receipt_id INTEGER,
	initial_quantity NUMERIC(14, 4) NOT NULL,
	remaining_quantity NUMERIC(14, 4) NOT NULL,
	expires_on DATE,
	unit_cost NUMERIC(14, 4),
	source VARCHAR(40) NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_batch_initial CHECK (initial_quantity > 0),
	CONSTRAINT ck_batch_remaining CHECK (remaining_quantity >= 0 AND remaining_quantity <= initial_quantity),
	CONSTRAINT ck_batch_cost CHECK (unit_cost IS NULL OR unit_cost >= 0),
	FOREIGN KEY(branch_id) REFERENCES branches (id),
	FOREIGN KEY(ingredient_id) REFERENCES ingredients (id),
	UNIQUE (receipt_id),
	FOREIGN KEY(receipt_id) REFERENCES stock_receipts (id)
)ENGINE=InnoDB;

CREATE INDEX ix_batches_branch_ingredient_expiry ON stock_batches (branch_id, ingredient_id, expires_on);

CREATE TABLE stock_movements (
	id INTEGER NOT NULL AUTO_INCREMENT,
	branch_id INTEGER NOT NULL,
	ingredient_id INTEGER NOT NULL,
	quantity_delta NUMERIC(14, 4) NOT NULL,
	reason VARCHAR(40) NOT NULL,
	order_id INTEGER,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_movement_nonzero CHECK (quantity_delta <> 0),
	FOREIGN KEY(branch_id) REFERENCES branches (id),
	FOREIGN KEY(ingredient_id) REFERENCES ingredients (id),
	FOREIGN KEY(order_id) REFERENCES orders (id)
)ENGINE=InnoDB;

CREATE INDEX ix_movements_branch_date ON stock_movements (branch_id, created_at);

CREATE TABLE stock_batch_allocations (
	id INTEGER NOT NULL AUTO_INCREMENT,
	batch_id INTEGER NOT NULL,
	order_id INTEGER NOT NULL,
	quantity NUMERIC(14, 4) NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_allocation_quantity CHECK (quantity > 0),
	FOREIGN KEY(batch_id) REFERENCES stock_batches (id),
	FOREIGN KEY(order_id) REFERENCES orders (id)
)ENGINE=InnoDB;

CREATE INDEX ix_stock_batch_allocations_batch_id ON stock_batch_allocations (batch_id);

CREATE INDEX ix_stock_batch_allocations_order_id ON stock_batch_allocations (order_id);

CREATE TABLE stock_batch_discards (
	id INTEGER NOT NULL AUTO_INCREMENT,
	batch_id INTEGER NOT NULL,
	request_key VARCHAR(100) NOT NULL,
	quantity NUMERIC(14, 4) NOT NULL,
	actor_user_id INTEGER,
	movement_id INTEGER NOT NULL,
	created_at DATETIME NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT ck_discard_quantity CHECK (quantity > 0),
	UNIQUE (batch_id),
	FOREIGN KEY(batch_id) REFERENCES stock_batches (id),
	UNIQUE (request_key),
	FOREIGN KEY(actor_user_id) REFERENCES users (id),
	UNIQUE (movement_id),
	FOREIGN KEY(movement_id) REFERENCES stock_movements (id)
)ENGINE=InnoDB;

CREATE OR REPLACE VIEW v_stock_batch_inventory AS SELECT batch.id AS batch_id, batch.branch_id, branches.name AS branch_name,
       batch.ingredient_id, ingredients.name AS ingredient_name, ingredients.unit,
       batch.initial_quantity, batch.remaining_quantity, batch.expires_on,
       batch.unit_cost, batch.remaining_quantity * batch.unit_cost AS remaining_value,
       batch.source
FROM stock_batches AS batch
JOIN branches ON branches.id = batch.branch_id
JOIN ingredients ON ingredients.id = batch.ingredient_id
WHERE batch.remaining_quantity > 0;

CREATE OR REPLACE VIEW v_low_stock AS SELECT stock.branch_id, branches.name AS branch_name,
       stock.ingredient_id, ingredients.name AS ingredient_name,
       ingredients.unit, stock.quantity, stock.reorder_level,
       stock.reorder_level - stock.quantity AS shortfall
FROM branch_stock AS stock
JOIN branches ON branches.id = stock.branch_id
JOIN ingredients ON ingredients.id = stock.ingredient_id
WHERE stock.quantity <= stock.reorder_level;

CREATE OR REPLACE VIEW v_completed_branch_revenue AS SELECT branches.id AS branch_id, branches.name AS branch_name,
       COUNT(orders.id) AS completed_orders,
       COALESCE(SUM(orders.total), 0) AS net_revenue,
       COALESCE(SUM(orders.points_redeemed), 0) AS points_redeemed
FROM branches
LEFT JOIN orders ON orders.branch_id = branches.id
                AND orders.status = 'completed'
GROUP BY branches.id, branches.name;
