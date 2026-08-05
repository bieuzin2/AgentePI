"""Carrega os CSVs de dados abertos do INPI num DuckDB local.

Fonte: https://dadosabertos.inpi.gov.br/index/patentes/ (atualizado diariamente).

    python inpi/ingest.py            # carrega o que ja esta em inpi/data/raw/
    python inpi/ingest.py --baixar   # baixa os CSVs antes de carregar

Idempotente: recria as tabelas do zero a cada execucao. Os CSVs sao a fonte de
verdade; o .duckdb e derivado e pode ser jogado fora sem perda.

NOTA DE REDE: revistas.inpi.gov.br e busca.inpi.gov.br derrubam o handshake TLS
(ver referencias/fontes-rpi.md), mas dadosabertos.inpi.gov.br responde normal.
E de la que vem tudo isto.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import duckdb

BASE_URL = "https://dadosabertos.inpi.gov.br/download/patentes/"

RAIZ = Path(__file__).resolve().parent
BRUTO = RAIZ / "data" / "raw"
BANCO = RAIZ / "data" / "inpi.duckdb"

# nome_da_tabela -> arquivo CSV
TABELAS = {
    "despachos": "PATENTES_DESPACHOS.csv",
    "biblio": "PATENTES_DADOS_BIBLIOGRAFICOS.csv",
    "conteudo": "PATENTES_CONTEUDO.csv",
    "depositantes": "PATENTES_DEPOSITANTES.csv",
    "inventores": "PATENTES_INVENTORES.csv",
    "ipc": "PATENTES_CLASSIFICACAO_IPC.csv",
    "prioridades": "PATENTES_PRIORIDADES.csv",
    "procuradores": "PATENTES_PROCURADORES.csv",
    "vinculos": "PATENTES_VINCULOS.csv",
    "renumeracoes": "PATENTES_RENUMERACOES.csv",
}


def baixar() -> int:
    """Baixa os CSVs do INPI para inpi/data/raw/.

    Grava em arquivo temporario e so renomeia no fim: uma queda no meio deixaria
    um CSV truncado que o read_csv_auto carregaria em silencio, e a base ficaria
    faltando processos sem ninguem perceber.
    """
    import httpx

    BRUTO.mkdir(parents=True, exist_ok=True)
    total = 0
    for arquivo in TABELAS.values():
        destino = BRUTO / arquivo
        parcial = destino.with_suffix(destino.suffix + ".parcial")
        t0 = time.time()
        try:
            with httpx.stream("GET", BASE_URL + arquivo, timeout=120,
                              follow_redirects=True) as r:
                r.raise_for_status()
                esperado = int(r.headers.get("content-length") or 0)
                with parcial.open("wb") as fh:
                    for bloco in r.iter_bytes(1 << 20):
                        fh.write(bloco)
            baixado = parcial.stat().st_size
            if esperado and baixado != esperado:
                parcial.unlink(missing_ok=True)
                print(f"  {arquivo:<34} FALHOU: {baixado:,} de {esperado:,} bytes",
                      flush=True)
                return 1
            parcial.replace(destino)
            total += baixado
            print(f"  {arquivo:<34} {baixado/1e6:>7.1f} MB  {time.time()-t0:5.1f}s",
                  flush=True)
        except Exception as e:
            parcial.unlink(missing_ok=True)
            print(f"  {arquivo:<34} FALHOU: {type(e).__name__}: {str(e)[:70]}", flush=True)
            return 1
    print(f"\n  total baixado: {total/1e9:.2f} GB\n", flush=True)
    return 0


# Sufixos societarios de titular. Lista diferente da de escritorio: aqui entram as
# formas estrangeiras (GMBH, LLC, KABUSHIKI KAISHA...), que sao a maioria -- 65% dos
# depositantes tem documento 'estrangeiro'.
_SUFIXOS_TITULAR = (
    "S A|SA|LTDA|LTD|LIMITADA|EIRELI|EPP|ME|INC|CORP|CORPORATION|CO|COMPANY|"
    "GMBH|AG|KG|MBH|BV|NV|SE|SAS|SARL|SPA|SRL|PLC|LLC|LP|AB|AS|OY|OYJ|"
    "PTY|PTE|KK|KABUSHIKI KAISHA|SOCIEDADE ANONIMA|INDUSTRIA E COMERCIO|"
    "PARTICIPACOES|EMPREENDIMENTOS|DO BRASIL|BRASIL|SS"
)

# Normalizacao de nome em SQL puro. Roda vetorizada no motor: 362 mil nomes em 1,1 s.
# Em Python levava minutos e nao terminava -- foi o que derrubou a primeira tentativa.
# O '[BR]' no fim e sufixo de pais do formato epodoc, que o EPO acrescenta e o INPI as
# vezes copia. Sai antes de tudo: se virasse ' BR ', 'PETROLEO BRASILEIRO SA [BR]'
# fecharia numa chave propria e nao encontraria a Petrobras.
_NOME_NORM = f"""
  nullif(trim(regexp_replace(
    regexp_replace(
      regexp_replace(
        regexp_replace(upper(strip_accents({{col}})), '\\[[A-Z]{{{{2}}}}\\]', ' ', 'g'),
        '[^A-Z0-9 ]', ' ', 'g'),
      '(^| )({_SUFIXOS_TITULAR})( |$)', ' ', 'g'),
    ' +', ' ', 'g')), '')
"""


def _materializa_titulares(con) -> None:
    """Chave canonica de titular, em tres camadas.

    O problema: 362.483 grafias de depositante. So a Petrobras aparece em 66 formas e
    com 8 documentos diferentes (matriz, filiais e 'N/D'). Sem agrupar, toda estatistica
    de titular esta errada.

    As camadas, em ordem de confiabilidade:

    1. RAIZ DO CNPJ (8 primeiros digitos). Identidade juridica, nao heuristica de
       string. Junta matriz e filial: Petrobras 33000167000101 e 33000167081942 caem
       na mesma raiz 33000167. Vale para 10% das linhas -- pessoa juridica brasileira.

    2. HERANCA DO CNPJ PELO NOME. 65% dos depositantes tem documento 'estrangeiro' e
       10% tem 'N/D'. Quando o nome normalizado coincide com o de um registro que TEM
       CNPJ, herda a raiz. E isto que junta os 104 processos da Petrobras marcados
       'N/D' aos 1.743 que trazem o CNPJ.

    3. NOME NORMALIZADO. Para quem nao tem documento nem homonimo com documento --
       tipicamente estrangeiro. Junta W.R. Grace (104 grafias), Air Liquide (93),
       DuPont (78) e Samsung (60).
    """
    t0 = time.time()
    raiz = """CASE WHEN tipopessoadepositante = 'pessoa jurídica'
                    AND length(cgccpfdepositante) >= 8
                    AND cgccpfdepositante NOT LIKE '%*%'
                   THEN 'CNPJ:' || substr(cgccpfdepositante, 1, 8) END"""
    nome = _NOME_NORM.format(col="depositante")

    con.execute("DROP TABLE IF EXISTS titulares")
    con.execute(f"""
      CREATE TABLE titulares AS
      WITH base AS (
        SELECT DISTINCT depositante AS original, {raiz} AS raiz_cnpj, {nome} AS nome_norm
        FROM depositantes WHERE depositante IS NOT NULL
      ),
      -- camada 2: para cada nome normalizado, a raiz de CNPJ mais frequente
      heranca AS (
        SELECT nome_norm, arg_max(raiz_cnpj, n) AS raiz_herdada FROM (
          SELECT nome_norm, raiz_cnpj, count(*) n FROM base
          WHERE raiz_cnpj IS NOT NULL AND nome_norm IS NOT NULL GROUP BY 1, 2
        ) GROUP BY 1
      )
      SELECT b.original,
             coalesce(b.raiz_cnpj, h.raiz_herdada, b.nome_norm, upper(b.original)) AS chave,
             b.raiz_cnpj IS NOT NULL AS tem_cnpj
      FROM base b LEFT JOIN heranca h USING (nome_norm)
    """)
    n, ch = con.execute(
        "SELECT count(*), count(DISTINCT chave) FROM titulares"
    ).fetchone()
    print(f"  titulares      {n:>12,} grafias -> {ch:,} chaves "
          f"(-{1 - ch / max(n, 1):.0%})   {time.time() - t0:5.1f}s", flush=True)


def _vota_identidade(con) -> None:
    """Cruza nome normalizado x documento do procurador, e marca os conflitos.

    POR QUE CRUZAR: nenhum dos dois campos e confiavel sozinho.
      - O nome vem em 17.521 grafias para ~10 mil bancas.
      - O documento parece resolver, mas esta poluido: pureza media de 91,4%, e
        255 dos 1.073 CNPJs mapeiam para mais de uma banca com menos de 90% de
        concentracao.

    O caso que define o desenho: o CNPJ 33163049 tem 181.760 processos com nome
    DANNEMANN e 6.675 com nome CLARKE MODET. Investigado -- as duas carteiras tem
    clientes completamente diferentes (Motorola/Lucent/Mobil de um lado,
    Huawei/Syngenta/Petrobras do outro) e datas sobrepostas de 1981 a 2026. NAO da
    para decidir por regra qual lado esta certo.

    Por isso esta funcao NAO desempata. Ela marca:
      confianca='alta'      nome e documento apontam um para o outro
      confianca='conflito'  discordam -- vai para revisao humana com a evidencia
      confianca='sem_doc'   nao ha documento utilizavel
    """
    t0 = time.time()
    con.execute("""
      CREATE OR REPLACE TEMP VIEW _pares AS
      SELECT e.chave AS nome,
             CASE WHEN p.tipopessoaprocurador = 'Pessoa Jurídica'
                       AND length(p.cgccpfprocurador) >= 8
                       AND p.cgccpfprocurador NOT LIKE '%*%'
                       AND p.cgccpfprocurador <> 'N/D'
                  THEN substr(p.cgccpfprocurador, 1, 8) END AS doc,
             count(DISTINCT p.numero_inpi) AS n
      FROM procuradores p JOIN escritorios e ON e.original = p.procurador
      GROUP BY 1, 2
    """)
    con.execute("DROP TABLE IF EXISTS identidade_escritorio")
    con.execute("""
      CREATE TABLE identidade_escritorio AS
      WITH
      -- para cada documento, o nome majoritario
      doc_para_nome AS (
        SELECT doc, arg_max(nome, n) AS nome_do_doc, sum(n) AS total_doc,
               max(n) AS dom_doc
        FROM _pares WHERE doc IS NOT NULL GROUP BY doc
      ),
      -- para cada nome, o documento majoritario
      nome_para_doc AS (
        SELECT nome, arg_max(doc, n) AS doc_do_nome, sum(n) AS total_nome,
               max(n) AS dom_nome
        FROM _pares WHERE doc IS NOT NULL GROUP BY nome
      )
      SELECT p.nome, p.doc, p.n AS processos,
             d.nome_do_doc, n2.doc_do_nome,
             round(d.dom_doc * 1.0 / d.total_doc, 3) AS pureza_doc,
             round(n2.dom_nome * 1.0 / n2.total_nome, 3) AS pureza_nome,
             CASE
               WHEN p.doc IS NULL THEN 'sem_doc'
               WHEN d.nome_do_doc = p.nome AND n2.doc_do_nome = p.doc THEN 'alta'
               ELSE 'conflito'
             END AS confianca
      FROM _pares p
      LEFT JOIN doc_para_nome d USING (doc)
      LEFT JOIN nome_para_doc n2 USING (nome)
    """)
    r = con.execute("""
      SELECT count(*) pares,
             sum(processos) FILTER (WHERE confianca='alta') alta,
             sum(processos) FILTER (WHERE confianca='conflito') conflito,
             sum(processos) FILTER (WHERE confianca='sem_doc') sem_doc
      FROM identidade_escritorio
    """).fetchone()
    tot = (r[1] or 0) + (r[2] or 0) + (r[3] or 0)
    print(f"  identidade     {r[0]:>12,} pares   alta={r[1] or 0:,} "
          f"conflito={r[2] or 0:,} ({(r[2] or 0)/max(tot,1):.1%}) "
          f"sem_doc={r[3] or 0:,}   {time.time()-t0:5.1f}s", flush=True)


def _materializa_nomes(con) -> None:
    """Cria a tabela de chaves normalizadas de ESCRITORIO.

    Sao 17.521 grafias de procurador para ~10 mil bancas reais -- a Clarke Modet
    sozinha aparece em dezenas de formas, e sem agrupar toda estatistica de mercado
    sai errada e a carteira sai fragmentada.

    Aqui a normalizacao roda em Python (e nao em SQL como a de titular) porque
    consulta escritorios-apelidos.csv, que mapeia erro de digitacao a mao. Sao poucos
    nomes distintos, entao o custo e aceitavel.
    """
    from inpi.escritorios import normalizar

    for tabela, coluna, nova in (
        ("procuradores", "procurador", "escritorios"),
    ):
        t0 = time.time()
        distintos = [
            r[0] for r in con.execute(
                f"SELECT DISTINCT {coluna} FROM {tabela} WHERE {coluna} IS NOT NULL"
            ).fetchall()
        ]
        chaves = [normalizar(n) for n in distintos]
        con.execute(f"DROP TABLE IF EXISTS {nova}")
        # Uma query com dois arrays, nao executemany. Com ~500 mil titulares o
        # INSERT linha a linha nao terminava: o WAL crescia 2 MB/min e a carga
        # passava de uma hora. unnest resolve em segundos.
        con.execute(
            f"""CREATE TABLE {nova} AS
                SELECT unnest(?::VARCHAR[]) AS original, unnest(?::VARCHAR[]) AS chave""",
            [distintos, chaves],
        )
        pares = distintos
        n_chaves = con.execute(f"SELECT count(DISTINCT chave) FROM {nova}").fetchone()[0]
        print(f"  {nova:<14} {len(pares):>12,} grafias -> {n_chaves:,} chaves "
              f"(-{1 - n_chaves / max(len(pares), 1):.0%})   {time.time()-t0:5.1f}s",
              flush=True)


def main() -> int:
    if "--baixar" in sys.argv:
        print(f"Baixando de {BASE_URL}", flush=True)
        if baixar() != 0:
            return 1

    faltando = [f for f in TABELAS.values() if not (BRUTO / f).exists()]
    if faltando:
        print(f"CSVs ausentes em {BRUTO}:", ", ".join(faltando))
        print("Rode com --baixar, ou baixe de "
              "https://dadosabertos.inpi.gov.br/index/patentes/")
        return 1

    BANCO.parent.mkdir(parents=True, exist_ok=True)
    # DROP TABLE nao devolve espaco ao arquivo: reingerir por cima quase dobrava o
    # .duckdb a cada rodada. Recriar do zero e mais simples que CHECKPOINT/VACUUM,
    # e o custo e baixo -- a carga inteira leva ~2 min.
    BANCO.unlink(missing_ok=True)
    con = duckdb.connect(str(BANCO))
    for tabela, arquivo in TABELAS.items():
        caminho = (BRUTO / arquivo).as_posix()
        t0 = time.time()
        con.execute(f"DROP TABLE IF EXISTS {tabela}")
        # SELECT DISTINCT nao e paranoia: os CSVs do INPI vem com linhas
        # integralmente repetidas na origem -- medimos 4 linhas identicas do mesmo
        # depositante, IPC 2x, inventores 3,3x em media. Sem deduplicar aqui, toda
        # ficha de processo sai com o titular repetido quatro vezes.
        con.execute(
            f"""CREATE TABLE {tabela} AS
                SELECT DISTINCT * FROM read_csv_auto('{caminho}', header=true,
                                                     sample_size=-1, ignore_errors=false)"""
        )
        n = con.execute(f"SELECT count(*) FROM {tabela}").fetchone()[0]
        bruto = con.execute(
            f"SELECT count(*) FROM read_csv_auto('{caminho}', header=true, sample_size=-1)"
        ).fetchone()[0]
        dup = f"  (-{bruto - n:,} duplicatas, {bruto / n:.2f}x)" if bruto > n else ""
        print(f"  {tabela:<14} {n:>12,} linhas   {time.time()-t0:5.1f}s{dup}", flush=True)

    # Sem CREATE INDEX de proposito. DuckDB e colunar: um scan filtrado de 5,3 milhoes
    # de linhas custa milissegundos, e o indice ART so ajuda em point lookup. Medido:
    # com indices em 8 tabelas a carga travava por mais de 20 minutos a 100% de CPU
    # (construcao de ART sobre VARCHAR); sem eles, termina em ~2 min e as consultas do
    # servidor respondem igual -- a carteira Petrobras sai em 2 s de qualquer jeito.
    _materializa_nomes(con)
    _materializa_titulares(con)
    _vota_identidade(con)

    print(f"\nBanco: {BANCO}  ({BANCO.stat().st_size/1e6:.0f} MB)")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
