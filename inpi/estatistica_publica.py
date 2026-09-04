"""Baixa o dataset agregado nacional do Portal de Estatisticas do INPI
(servicos.estatistica.inpi.gov.br), publico, sem login. Os numeros vem
pre-decodificados em window.pivotData depois que a pagina carrega os
scripts db-data.js/db-engine.js -- o formato de codificacao colunar desses
arquivos NAO foi decifrado (ver docs/pesquisa/inpi_plataforma_nova.md), entao
usamos um Chromium headless (Playwright) so pra deixar o proprio JS da pagina
fazer esse trabalho, em vez de reimplementar o decoder em Python.

ponytail: dependencia pesada (Chromium) so pra ler uma variavel JS ja
decodificada -- se o formato de db-data.js for decifrado depois, trocar por
parse direto em Python e derrubar essa dependencia.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent
CSV_SAIDA = RAIZ / "referencias" / "estatistica-nacional.csv"
URL = "https://servicos.estatistica.inpi.gov.br/"

_CAMPOS = ["ano", "tipo_ativo", "sub_tipo", "tipo_patente", "via_entrada",
          "origem", "pais", "uf", "regiao", "campo_tecnologico", "decisao",
          "ano_decisao", "depositos", "concessoes", "n_decisoes", "n_vigentes",
          "coletado_em"]

_MAPA_CAMPOS = {
    "ano": "ano", "tipoAtivo": "tipo_ativo", "subTipo": "sub_tipo",
    "tipoPatente": "tipo_patente", "viaEntrada": "via_entrada",
    "origem": "origem", "pais": "pais", "uf": "uf", "regiao": "regiao",
    "campoTecnologico": "campo_tecnologico", "decisao": "decisao",
    "anoDecisao": "ano_decisao", "depositos": "depositos",
    "concessoes": "concessoes", "nDecisoes": "n_decisoes",
    "nVigentes": "n_vigentes",
}


def _linha_csv(linha_js: dict[str, Any], coletado_em: str) -> dict[str, Any]:
    """Traduz uma linha de window.pivotData (chaves camelCase, como o JS da
    pagina produz) pro schema snake_case do CSV/DuckDB (inpi/ingest.py). Chave
    ausente vira string vazia -- linha de window.pivotData pode nao ter todas
    as dimensoes (ex.: 'origem' so existe pra Patentes, nao pra Marcas)."""
    saida: dict[str, Any] = {c: "" for c in _CAMPOS}
    for chave_js, chave_csv in _MAPA_CAMPOS.items():
        if chave_js in linha_js and linha_js[chave_js] is not None:
            saida[chave_csv] = linha_js[chave_js]
    saida["coletado_em"] = coletado_em
    return saida


def _buscar_pivot_data() -> list[dict[str, Any]]:
    """Abre a pagina publica num Chromium headless e le window.pivotData
    depois que a pagina termina de carregar. Rede real -- so chamada por
    main(), nunca em teste automatizado (import de playwright fica local a
    esta funcao pra nao exigir o pacote instalado so pra rodar os testes)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        pagina = navegador.new_page()
        pagina.goto(URL, wait_until="networkidle")
        dados = pagina.evaluate("window.pivotData")
        navegador.close()
        return dados


def gravar_csv(linhas_js: list[dict[str, Any]], destino: Path = CSV_SAIDA,
              coletado_em: str | None = None) -> int:
    """Escreve o CSV a partir de linhas ja obtidas (testavel sem rede/
    navegador -- separado de _buscar_pivot_data de proposito). Devolve o
    numero de linhas gravadas."""
    coletado_em = coletado_em or date.today().isoformat()
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_CAMPOS, lineterminator="\n")
        w.writeheader()
        for linha_js in linhas_js:
            w.writerow(_linha_csv(linha_js, coletado_em))
    return len(linhas_js)


def main() -> int:
    linhas_js = _buscar_pivot_data()
    n = gravar_csv(linhas_js)
    print(f"estatistica-nacional.csv: {n:,} linhas")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
