CREATE DATABASE IF NOT EXISTS hawkerflow_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE DATABASE IF NOT EXISTS hawkerflow_benchmark CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON hawkerflow_test.* TO 'hawkerflow'@'%';
GRANT ALL PRIVILEGES ON hawkerflow_benchmark.* TO 'hawkerflow'@'%';
