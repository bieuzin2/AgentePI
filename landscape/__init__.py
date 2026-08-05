"""Pacote landscape: patent landscape via Google Patents Public Data (BigQuery).

Ver docs/plano-v2.md secao 4.6. Dataset publico patents-public-data.patents.publications
(166M publicacoes). Dry-run obrigatorio com teto de 10 GB antes de qualquer consulta real
(landscape/bigquery_client.py) -- protege o free tier de 1 TB/mes contra custo acidental.
Resultados cacheados 30 dias em DuckDB (landscape/cache.py).
"""
