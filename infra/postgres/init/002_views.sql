-- migrations/002_views.sql
-- Create Virtual Views for SQL Lane

-- View: People
CREATE OR REPLACE VIEW view_people AS
SELECT
    row_id,
    commune_id,
    data_content->>'full_name' AS full_name,
    data_content->>'code' AS code,
    data_content->>'dob' AS dob,
    data_content->>'gender' AS gender,
    data_content->>'phone' AS phone,
    data_content->>'email' AS email,
    data_content->>'address' AS address,
    data_content->>'ward_commune' AS ward_commune,
    data_content->>'occupation' AS occupation
FROM structured_rows
WHERE doc_category = 'people';

-- View: Budget
CREATE OR REPLACE VIEW view_budget AS
SELECT
    row_id,
    commune_id,
    data_content->>'item' AS item,
    (data_content->>'amount')::numeric AS amount,
    (data_content->>'year')::int AS year
FROM structured_rows
WHERE doc_category = 'budget';
