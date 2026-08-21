# Servidor MCP remoto (remoto/servidor_mcp.py) para Cloud Run / Koyeb / qualquer host.
# Escuta em $PORT (Cloud Run injeta PORT=8080; o codigo ja respeita os.environ["PORT"]).
# Dados vem do MotherDuck (nao ha .duckdb no container) e o landscape usa a service
# account de runtime (Cloud Run) ou GOOGLE_APPLICATION_CREDENTIALS_JSON (outros hosts).
FROM python:3.12-slim

WORKDIR /app

# Copia so o necessario (ver .dockerignore -- inpi/data e os CSVs gigantes ficam de fora).
COPY . .

# Instala as dependencias declaradas no pyproject. Wheels manylinux cobrem duckdb,
# bigquery, reportlab etc.; se algum dia faltar toolchain, descomente build-essential.
# RUN apt-get update && apt-get install -y --no-install-recommends build-essential
RUN pip install --no-cache-dir .

# Roda a partir do CODIGO em /app (nao do pacote instalado em site-packages): os
# modulos leem CSVs de inpi/referencias via __file__, e esses arquivos so existem
# na arvore de /app. PYTHONPATH=/app garante que /app/inpi vence site-packages/inpi.
ENV PYTHONPATH=/app

# Cloud Run/Koyeb definem PORT; default local 8000. O servidor recusa subir sem
# API_KEY_AGENTE_PI -- configure no painel do host.
CMD ["python", "remoto/servidor_mcp.py"]
