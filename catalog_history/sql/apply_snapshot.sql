UPDATE dim_product
SET valid_to = :snapshot_date
WHERE valid_to IS NULL
  AND NOT EXISTS (
      SELECT 1 FROM stage s
      WHERE s.product_id = dim_product.product_id
        AND s.name = dim_product.name
        AND s.category = dim_product.category
        AND s.price_cents = dim_product.price_cents
  );

INSERT INTO dim_product(product_id, name, category, price_cents, valid_from)
SELECT s.product_id, s.name, s.category, s.price_cents, :snapshot_date
FROM stage s
WHERE NOT EXISTS (SELECT 1 FROM current_products c WHERE c.product_id = s.product_id)
ORDER BY s.product_id;
