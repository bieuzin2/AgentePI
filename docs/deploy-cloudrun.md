# Deploy do servidor MCP no Google Cloud Run (grátis, sai do Render)

## Por que Cloud Run

O Render free suspende por quota (bandwidth) e tem cold-start lento. Cloud Run é
**grátis** (free tier: 2M requisições/mês, escala a zero quando ocioso), **liga na 1ª
mensagem** do Copilot (cold-start ~1-2s, dentro do timeout de 100s), dá **HTTPS com URL
estável**, e — como o BigQuery/landscape já é do seu GCP — a **service account de runtime
acessa o BigQuery nativamente** (sem injetar JSON). Bandwidth não é armadilha aqui: as
respostas ao Copilot são pequenas e o que vem do MotherDuck é ingress (não conta).

## O que já está pronto no repo (feito)

- `Dockerfile` — container que roda `remoto/servidor_mcp.py` escutando `$PORT`.
- `.dockerignore` — mantém `inpi/data` (1,8 GB) e o CSV de 609 MB FORA da imagem.
- Shim de credencial em `remoto/servidor_mcp.py` (`_materializa_credencial_gcp`) — só é
  usado em hosts que não têm creds nativas; no Cloud Run não precisa.

## Pré-requisitos (você)

- Conta Google Cloud com faturamento ativado (o free tier não cobra dentro dos limites,
  mas o Cloud Run exige billing habilitado). Use o **mesmo projeto** do BigQuery.
- `gcloud` CLI instalado (https://cloud.google.com/sdk/docs/install) OU usar o Cloud Shell
  no navegador (já vem com gcloud).
- As credenciais em mãos (você disse que tem): `API_KEY_AGENTE_PI`, `MOTHERDUCK_TOKEN`,
  `EPO_OPS_KEY`, `EPO_OPS_SECRET`.

## Passo a passo (o wizard `deploy-cloudrun.sh` automatiza isto)

1. Login e projeto:
   ```
   gcloud auth login
   gcloud config set project SEU_PROJECT_ID
   gcloud services enable run.googleapis.com cloudbuild.googleapis.com
   ```
2. Deploy a partir do código (o Cloud Build usa o Dockerfile):
   ```
   gcloud run deploy agentepi \
     --source . \
     --region southamerica-east1 \
     --allow-unauthenticated \
     --set-env-vars API_KEY_AGENTE_PI=XXX,MOTHERDUCK_TOKEN=XXX,EPO_OPS_KEY=XXX,EPO_OPS_SECRET=XXX
   ```
   - `--allow-unauthenticated`: o Cloud Run não pede auth do Google; **a nossa própria
     chave `API_KEY_AGENTE_PI` (header `X-API-Key`) continua protegendo o `/mcp`**.
   - `southamerica-east1` = São Paulo (mais perto). Pode trocar.
3. BigQuery/landscape (só se usar landscape no Copilot): dê à service account de runtime
   do serviço o papel de BigQuery. O wizard faz; manual:
   ```
   gcloud projects add-iam-policy-binding SEU_PROJECT_ID \
     --member="serviceAccount:$(gcloud run services describe agentepi --region southamerica-east1 --format='value(spec.template.spec.serviceAccountName)')" \
     --role="roles/bigquery.jobUser"
   # e roles/bigquery.dataViewer no dataset usado
   ```
4. Pegue a URL: o deploy imprime `https://agentepi-XXXX.a.run.app`. O endpoint MCP é essa
   URL + `/mcp`; verifique `https://.../tools` (deve listar 51 tools) e `/health`.

## Depois do deploy (repontar o Copilot + desligar o Render)

1. Copilot Studio → Agente PI → Tools → a conexão MCP: troque a **Server URL** para
   `https://agentepi-XXXX.a.run.app/mcp` (mesma auth: header `X-API-Key` = `API_KEY_AGENTE_PI`).
   Se não deixar editar a URL, **remova e recrie** a conexão MCP apontando pra nova URL
   (reimporta as 51 tools de uma vez — resolve também o refresh das tools novas).
2. Confirme `Allow all` ligado (senão tools novas entram desligadas).
3. Teste: "Quanto a Clarke pagou de anuidades em março/2025 vs 2026?" → R$ 822.836 / R$ 1.344.700.
4. **Render**: no dashboard, **Delete** (ou Suspend) o serviço AgentePI e **desligue o
   keep-alive** (cron-job.org/UptimeRobot) — não é mais necessário e era tráfego à toa.

## Custo/limites

Free tier do Cloud Run cobre folgado um piloto privado. Escala a zero = R$ 0 ocioso.
Se algum dia publicar para muitos usuários, revise os limites — mas aí já não é 0800.
