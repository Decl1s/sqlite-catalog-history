SELECT product_id, name, category, price_cents, valid_from, valid_to
FROM dim_product
WHERE valid_from <= :as_of AND (valid_to IS NULL OR :as_of < valid_to)
ORDER BY product_id;
