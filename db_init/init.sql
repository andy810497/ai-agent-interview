CREATE TABLE IF NOT EXISTS policies (
    policy_id VARCHAR(50) PRIMARY KEY,
    status VARCHAR(20),
    policy_type VARCHAR(50),
    coverage_amount DECIMAL(15, 2)
);

INSERT INTO policies (policy_id, status, policy_type, coverage_amount) VALUES 
('TX-9981', 'Active', 'Life Insurance', 5000000.00),
('HL-2024', 'Active', 'Health Insurance', 1200000.00),
('AUTO-777', 'Expired', 'Auto Insurance', 0.00);