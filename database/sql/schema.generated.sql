-- Generated from app/models.py. Do not hand-edit; regenerate instead.


CREATE TABLE branches (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(120) NOT NULL, 
	address VARCHAR(255) NOT NULL, 
	source_label VARCHAR(120) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
)ENGINE=InnoDB

;


CREATE TABLE customers (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(120) NOT NULL, 
	email VARCHAR(180) NOT NULL, 
	points INTEGER NOT NULL, 
	active BOOL NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_customer_points CHECK (points >= 0), 
	UNIQUE (email)
)ENGINE=InnoDB

;


CREATE TABLE ingredients (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(100) NOT NULL, 
	unit VARCHAR(12) NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
)ENGINE=InnoDB

;


CREATE TABLE menu_items (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(120) NOT NULL, 
	price NUMERIC(10, 2) NOT NULL, 
	active BOOL NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_menu_price CHECK (price > 0), 
	UNIQUE (name)
)ENGINE=InnoDB

;


CREATE TABLE branch_stock (
	branch_id INTEGER NOT NULL, 
	ingredient_id INTEGER NOT NULL, 
	quantity NUMERIC(14, 3) NOT NULL, 
	PRIMARY KEY (branch_id, ingredient_id), 
	CONSTRAINT ck_stock_quantity CHECK (quantity >= 0), 
	FOREIGN KEY(branch_id) REFERENCES branches (id), 
	FOREIGN KEY(ingredient_id) REFERENCES ingredients (id)
)ENGINE=InnoDB

;


CREATE TABLE recipe_components (
	menu_item_id INTEGER NOT NULL, 
	ingredient_id INTEGER NOT NULL, 
	quantity NUMERIC(14, 3) NOT NULL, 
	PRIMARY KEY (menu_item_id, ingredient_id), 
	CONSTRAINT ck_recipe_quantity CHECK (quantity > 0), 
	FOREIGN KEY(menu_item_id) REFERENCES menu_items (id), 
	FOREIGN KEY(ingredient_id) REFERENCES ingredients (id)
)ENGINE=InnoDB

;


CREATE TABLE users (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	email VARCHAR(180) NOT NULL, 
	password_hash VARCHAR(255) NOT NULL, 
	`role` VARCHAR(20) NOT NULL, 
	customer_id INTEGER, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_user_role CHECK (role IN ('manager','cashier','customer')), 
	UNIQUE (email), 
	UNIQUE (customer_id), 
	FOREIGN KEY(customer_id) REFERENCES customers (id)
)ENGINE=InnoDB

;


CREATE TABLE orders (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	request_key VARCHAR(80) NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	branch_id INTEGER NOT NULL, 
	customer_id INTEGER NOT NULL, 
	cashier_user_id INTEGER NOT NULL, 
	subtotal NUMERIC(12, 2) NOT NULL, 
	discount NUMERIC(12, 2) NOT NULL, 
	total NUMERIC(12, 2) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_order_money CHECK (subtotal >= 0 AND discount >= 0 AND total >= 0), 
	CONSTRAINT ck_order_total CHECK (total = subtotal - discount), 
	UNIQUE (request_key), 
	FOREIGN KEY(branch_id) REFERENCES branches (id), 
	FOREIGN KEY(customer_id) REFERENCES customers (id), 
	FOREIGN KEY(cashier_user_id) REFERENCES users (id)
)ENGINE=InnoDB

;


CREATE TABLE stock_receipts (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	branch_id INTEGER NOT NULL, 
	ingredient_id INTEGER NOT NULL, 
	quantity NUMERIC(14, 3) NOT NULL, 
	actor_user_id INTEGER NOT NULL, 
	note VARCHAR(255) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_receipt_quantity CHECK (quantity > 0), 
	FOREIGN KEY(branch_id) REFERENCES branches (id), 
	FOREIGN KEY(ingredient_id) REFERENCES ingredients (id), 
	FOREIGN KEY(actor_user_id) REFERENCES users (id)
)ENGINE=InnoDB

;


CREATE TABLE loyalty_transactions (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	customer_id INTEGER NOT NULL, 
	order_id INTEGER NOT NULL, 
	kind VARCHAR(12) NOT NULL, 
	delta INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_loyalty_order_kind UNIQUE (order_id, kind), 
	CONSTRAINT ck_loyalty_kind CHECK (kind IN ('earn','redeem')), 
	CONSTRAINT ck_loyalty_sign CHECK ((kind = 'earn' AND delta > 0) OR (kind = 'redeem' AND delta < 0)), 
	FOREIGN KEY(customer_id) REFERENCES customers (id), 
	FOREIGN KEY(order_id) REFERENCES orders (id)
)ENGINE=InnoDB

;


CREATE TABLE order_lines (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	order_id INTEGER NOT NULL, 
	menu_item_id INTEGER NOT NULL, 
	quantity INTEGER NOT NULL, 
	unit_price NUMERIC(10, 2) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_order_menu UNIQUE (order_id, menu_item_id), 
	CONSTRAINT ck_line_values CHECK (quantity > 0 AND unit_price > 0), 
	FOREIGN KEY(order_id) REFERENCES orders (id), 
	FOREIGN KEY(menu_item_id) REFERENCES menu_items (id)
)ENGINE=InnoDB

;


CREATE TABLE stock_movements (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	branch_id INTEGER NOT NULL, 
	ingredient_id INTEGER NOT NULL, 
	delta NUMERIC(14, 3) NOT NULL, 
	order_id INTEGER, 
	receipt_id INTEGER, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_movement_nonzero CHECK (delta <> 0), 
	CONSTRAINT ck_movement_origin CHECK ((order_id IS NOT NULL AND receipt_id IS NULL AND delta < 0) OR (order_id IS NULL AND receipt_id IS NOT NULL AND delta > 0)), 
	FOREIGN KEY(branch_id) REFERENCES branches (id), 
	FOREIGN KEY(ingredient_id) REFERENCES ingredients (id), 
	FOREIGN KEY(order_id) REFERENCES orders (id), 
	FOREIGN KEY(receipt_id) REFERENCES stock_receipts (id)
)ENGINE=InnoDB

;

CREATE INDEX ix_orders_branch_created ON orders (branch_id, created_at);
