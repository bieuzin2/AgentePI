"""Cliente BigQuery para o dataset publico Google Patents (plano-v2 4.6).

Autenticacao via ADC (Application Default Credentials) -- `gcloud auth
application-default login`, nao chave de service account. Isso e decisao do
plano: single-user, sem segredo extra no repo.

Regra dura (risco documentado no plano-v2 9): toda query roda dry-run
primeiro para estimar bytes processados. Se a estimativa passar de 10 GB, a
query e recusada com excecao clara -- nunca falha em silencio, nunca executa
"na duvida". O chamador so passa por cima com `confirmar_acima_10gb=True`.
"""

from __future__ import annotations

from google.cloud import bigquery

TETO_BYTES_PADRAO = 10 * 1024 ** 3  # 10 GB


class ConsultaMuitoGrandeError(Exception):
    """Dry-run estimou mais bytes processados que o teto permitido."""


def cliente(projeto: str | None = None) -> bigquery.Client:
    """Cliente BigQuery via ADC (local: `gcloud auth application-default
    login`; remoto: GOOGLE_APPLICATION_CREDENTIALS apontando pro JSON da
    service account). Levanta erro claro com a causa original -- nunca so
    "credenciais ausentes" quando o problema e outro (JSON invalido, sem
    permissao, projeto errado)."""
    try:
        return bigquery.Client(project=projeto)
    except Exception as exc:  # DefaultCredentialsError e outras da lib google-auth
        raise RuntimeError(
            "Falha ao criar cliente do Google Cloud (ADC). Local: rode "
            "'gcloud auth application-default login'. Remoto: confira "
            "GOOGLE_APPLICATION_CREDENTIALS. Causa original: "
            f"{type(exc).__name__}: {exc}"
        ) from exc


def estimar_bytes(client: bigquery.Client, sql: str,
                   parametros: list[bigquery.ScalarQueryParameter] | None = None) -> int:
    """Dry-run: quantos bytes essa query processaria, sem executar de fato."""
    config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False,
                                      query_parameters=parametros or [])
    job = client.query(sql, job_config=config)
    return job.total_bytes_processed


def executar(client: bigquery.Client, sql: str,
             parametros: list[bigquery.ScalarQueryParameter] | None = None,
             teto_bytes: int = TETO_BYTES_PADRAO,
             confirmar_acima_10gb: bool = False,
             info: dict | None = None) -> list[dict]:
    """Dry-run obrigatorio, depois executa se estiver dentro do teto (ou se o
    chamador confirmou explicitamente que quer estourar o teto).

    Levanta ConsultaMuitoGrandeError -- nunca executa em silencio uma query
    grande sem essa confirmacao. Se 'info' for passado, e preenchido com
    'bytes_estimados' e 'acima_do_teto' -- e como o chamador (consultas.py)
    sabe se deve devolver aviso mesmo quando a consulta RODOU (confirmada).
    """
    parametros = parametros or []
    bytes_estimados = estimar_bytes(client, sql, parametros)
    if info is not None:
        info["bytes_estimados"] = bytes_estimados
        info["acima_do_teto"] = bytes_estimados > teto_bytes
    if bytes_estimados > teto_bytes and not confirmar_acima_10gb:
        gb = bytes_estimados / 1024 ** 3
        raise ConsultaMuitoGrandeError(
            f"Consulta estimada em {gb:.2f} GB, acima do teto de "
            f"{teto_bytes / 1024 ** 3:.0f} GB. Passe confirmar_acima_10gb=True "
            "se quiser executar mesmo assim."
        )
    config = bigquery.QueryJobConfig(query_parameters=parametros)
    linhas = client.query(sql, job_config=config).result()
    return [dict(row.items()) for row in linhas]


def demo() -> None:
    """Self-check sem rede: teto recusa estimativa grande, aceita com confirmacao."""
    from unittest.mock import MagicMock

    fake_client = MagicMock()
    fake_job = MagicMock()
    fake_job.total_bytes_processed = 20 * 1024 ** 3
    fake_client.query.return_value = fake_job

    try:
        executar(fake_client, "SELECT 1")
        raise AssertionError("deveria ter recusado")
    except ConsultaMuitoGrandeError:
        pass

    fake_job.result.return_value = []
    resultado = executar(fake_client, "SELECT 1", confirmar_acima_10gb=True)
    assert resultado == []
    print("OK  teto de 10GB recusa e libera com confirmacao explicita")


if __name__ == "__main__":
    demo()
