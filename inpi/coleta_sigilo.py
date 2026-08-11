"""Coleta de procurador para pedidos em sigilo, via busca basica do pePI.

O dump de dados abertos oculta o procurador de pedidos em sigilo (~43 mil
registros, so 3 com procurador). A FICHA do pedido no site do INPI mostra esse
vinculo -- campo (74) Nome do Procurador -- mesmo quando o pedido ainda esta em
sigilo (titulo/resumo ocultos, mas dados bibliograficos nao). Confirmado ao
vivo em 2026-08-11 com PETROLEO BRASILEIRO/UFRJ (numero_inpi 102026015044,
depositado 17/06/2026, sem titulo publicado, procurador CLARKE MODET visivel).

CONTRARIO ao suposto no desenho original: nao existe campo "Procurador" na
busca avancada (nem oculto -- o texto de ajuda, que lista um superset de
campos, tambem nao o menciona), e o servlet de detalhe (Action=detail) exige
estado de sessao de uma busca previa -- nao aceita CodPedido isolado. Por isso
o fluxo aqui e "buscar por NUMERO do pedido, abrir a ficha, ler o campo (74)",
nao "buscar por procurador".

Este modulo tem tres camadas:

1. `termos_busca` -- pura, deriva grafias do escritorio (nao usada para
   filtrar a coleta em si, mas documenta quais grafias contam como o mesmo
   escritorio; ver `escritorios.normalizar` para o match real).
2. `procurador_na_ficha` -- rede: busca 1 numero, le a ficha, devolve o
   procurador cru do site ou None. Via HTTP direto (httpx/enriquecimento
   .limitador), NAO navegador -- ao contrario do que o desenho original
   assumia (referencias/fontes-rpi.md registra bloqueio de TLS em
   revistas.inpi.gov.br e busca.inpi.gov.br a partir desta maquina; medido de
   novo em 2026-08-11 e o bloqueio NAO se repetiu para busca.inpi.gov.br --
   HTTP direto responde 200 normalmente).
3. `registrar` -- valida e grava um numero_inpi coletado em
   referencias/procuradores-sigilo.csv (a base curada que inpi/ingest.py
   mescla na tabela procuradores).

`varrer_e_registrar` encadeia as tres para uma lista de numero_inpi, sequencial.
`varrer_e_registrar_paralelo` faz o mesmo com N sessoes HTTP independentes em
paralelo (`_Trabalhador`) -- necessario a partir de algumas centenas de
numeros, onde o sequencial (~4s/numero: 2 requisicoes x rate-limit de
enriquecimento.limitador) levaria horas.
"""

from __future__ import annotations

import csv
import queue
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

import requests

from enriquecimento.limitador import USER_AGENT, requisitar
from inpi.db import con
from inpi.escritorios import apelidos_com_motivo, normalizar

RAIZ = Path(__file__).resolve().parent
CSV_SIGILO = RAIZ / "referencias" / "procuradores-sigilo.csv"
CAMPOS = ["numero_inpi", "procurador", "escritorio_canonico", "fonte", "coletado_em", "observacao"]

_MOTIVOS_INUTEIS_PARA_BUSCA = ("erro de digitacao",)

_HOST = "busca.inpi.gov.br"
_BASE = f"https://{_HOST}/pePI"
_RE_NUMERO_MODERNO = re.compile(r"^(\d{2})(\d{4})(\d{6})$")
_RE_CODPEDIDO = re.compile(r"CodPedido=(\d+)")
_RE_PROCURADOR = re.compile(
    r"\(74\).*?Nome do Procurador:.*?<font[^>]*>\s*&nbsp;\s*(.*?)\s*</font>", re.S
)


def termos_busca(escritorio_canonico: str) -> list[str]:
    """Grafias a pesquisar na busca avancada para um escritorio canonico.

    Inclui o proprio nome canonico, as grafias reais da firma (matriz
    internacional, razao social antiga) e os agentes da casa (pessoa fisica
    cujos casos contam para a banca). Exclui erros de digitacao -- inuteis
    como termo de busca prospectiva, so existem porque alguem digitou errado
    um pedido ja publicado.
    """
    alvo = escritorio_canonico.strip().upper()
    termos = {alvo}
    for variante, info in apelidos_com_motivo().items():
        if info["canonico"] != alvo:
            continue
        observacao = info["observacao"].lower()
        if any(motivo in observacao for motivo in _MOTIVOS_INUTEIS_PARA_BUSCA):
            continue
        termos.add(variante)
    return sorted(termos)


def _formatar_numero_busca(numero_inpi: str) -> str | None:
    """'102026015044' -> 'BR 10 2026 015044'. So cobre o formato unificado pos
    -2012 (2+4+6 digitos: tipo+ano+sequencial) -- e o formato de todo alvo
    recente, que e o que importa (sigilo real dura 18 meses; numero antigo
    fora desse formato normalmente ja publicou ou foi arquivado sem publicar,
    ver observacao em varrer_e_registrar). Devolve None se nao bater --
    quem chama pula o numero em vez de arriscar uma busca sem sentido."""
    m = _RE_NUMERO_MODERNO.match(numero_inpi)
    if not m:
        return None
    tipo, ano, seq = m.groups()
    return f"BR {tipo} {ano} {seq}"


def _sessao_anonima() -> bool:
    if requisitar("get", f"{_BASE}/", host=_HOST, usar_cache=False) is None:
        return False
    r = requisitar("get", f"{_BASE}/servlet/LoginController", host=_HOST,
                    usar_cache=False, params={"action": "login"})
    return r is not None


def procurador_na_ficha(numero_inpi: str) -> str | None:
    """Busca o pedido pelo numero e devolve o texto cru do campo (74) Nome do
    Procurador na ficha, ou None se o numero nao foi encontrado, a busca
    falhou, ou a ficha nao tem procurador (pedido sem agente -- deposito
    direto, ou nunca tramitou a ponto de ter um)."""
    numero_busca = _formatar_numero_busca(numero_inpi)
    if numero_busca is None:
        return None

    resultado = requisitar(
        "post", f"{_BASE}/servlet/PatenteServletController", host=_HOST,
        usar_cache=False,
        data={"NumPedido": numero_busca, "Action": "SearchBasico", "RegisterPerPage": "20"},
    )
    if resultado is None:
        return None
    m = _RE_CODPEDIDO.search(resultado.text)
    if not m:
        if "Login" in resultado.text and "Senha" in resultado.text:
            if not _sessao_anonima():
                return None
            return procurador_na_ficha(numero_inpi)
        return None
    codpedido = m.group(1)

    # requisitar() cacheia GET pela URL passada -- SEM incluir kwargs['params'].
    # Usar params= aqui faria toda ficha (qualquer CodPedido) colidir na mesma
    # chave de cache "get:.../PatenteServletController" e devolver sempre a
    # PRIMEIRA ficha buscada no processo. Monta a query string na propria URL
    # para a chave de cache ficar unica por pedido.
    query = urlencode({"Action": "detail", "CodPedido": codpedido,
                       "SearchParameter": numero_busca, "Resumo": "", "Titulo": ""})
    ficha = requisitar(
        "get", f"{_BASE}/servlet/PatenteServletController?{query}", host=_HOST,
    )
    if ficha is None:
        return None
    m2 = _RE_PROCURADOR.search(ficha.text)
    return m2.group(1).strip() if m2 else None


def varrer_e_registrar(numeros_inpi: list[str], escritorio_canonico: str,
                       fonte: str = "pePI busca.inpi.gov.br (busca por numero + ficha)") -> dict:
    """Roda procurador_na_ficha para cada numero e registra os que baterem com
    o escritorio (comparado pela chave normalizada, nao string exata -- pega
    qualquer grafia que `escritorios.normalizar` ja saiba resolver).

    Numeros fora do formato unificado (_formatar_numero_busca == None), sem
    resultado na busca, sem procurador, ou de outro escritorio contam como
    'pulados', nao erro -- normal dado que a lista de entrada e so um indicio
    (sigilo=1 sem procurador no dump), nao uma confirmacao."""
    alvo = escritorio_canonico.strip().upper()
    if not _sessao_anonima():
        return {"erro": "nao foi possivel abrir sessao anonima no pePI"}

    resumo = {"registrados": 0, "sem_procurador_ou_nao_encontrado": 0,
              "outro_escritorio": 0, "formato_nao_suportado": 0, "ja_coletado_ou_invalido": 0}
    for numero_inpi in numeros_inpi:
        if _formatar_numero_busca(numero_inpi) is None:
            resumo["formato_nao_suportado"] += 1
            continue
        procurador = procurador_na_ficha(numero_inpi)
        if not procurador:
            resumo["sem_procurador_ou_nao_encontrado"] += 1
            continue
        if normalizar(procurador) != alvo:
            resumo["outro_escritorio"] += 1
            continue
        ok = registrar(numero_inpi, procurador, escritorio_canonico, fonte,
                       date.today().isoformat())
        resumo["registrados" if ok else "ja_coletado_ou_invalido"] += 1
    return resumo


class _Trabalhador:
    """Sessao HTTP independente (login anonimo proprio) para coleta em paralelo.

    NAO reusa o _sessao module-level de enriquecimento.limitador: aquele e uma
    unica instancia global que serializa tudo via _espera por host, o oposto
    do que paralelismo precisa. Cada trabalhador pacea A SI MESMO -- com N
    trabalhadores rodando a ~1 requisicao a cada `intervalo` segundos cada, o
    agregado no host e N/intervalo req/s, deliberado e prop a `paralelismo`.
    """

    def __init__(self, intervalo: float = 1.5):
        self.sessao = requests.Session()
        self.sessao.headers.update({"User-Agent": USER_AGENT})
        self.intervalo = intervalo
        self._ultima = 0.0

    def _espera(self) -> None:
        falta = self.intervalo - (time.monotonic() - self._ultima)
        if falta > 0:
            time.sleep(falta)
        self._ultima = time.monotonic()

    def sessao_anonima(self) -> bool:
        try:
            self._espera()
            self.sessao.get(f"{_BASE}/", timeout=15)
            self._espera()
            r = self.sessao.get(f"{_BASE}/servlet/LoginController", timeout=15,
                                 params={"action": "login"})
            return r.status_code == 200
        except requests.RequestException:
            return False

    def procurador_na_ficha(self, numero_inpi: str) -> str | None:
        numero_busca = _formatar_numero_busca(numero_inpi)
        if numero_busca is None:
            return None
        try:
            self._espera()
            resultado = self.sessao.post(
                f"{_BASE}/servlet/PatenteServletController", timeout=15,
                data={"NumPedido": numero_busca, "Action": "SearchBasico", "RegisterPerPage": "20"},
            )
        except requests.RequestException:
            return None
        m = _RE_CODPEDIDO.search(resultado.text)
        if not m:
            if "Login" in resultado.text and "Senha" in resultado.text:
                return self.procurador_na_ficha(numero_inpi) if self.sessao_anonima() else None
            return None
        codpedido = m.group(1)
        query = urlencode({"Action": "detail", "CodPedido": codpedido,
                           "SearchParameter": numero_busca, "Resumo": "", "Titulo": ""})
        try:
            self._espera()
            ficha = self.sessao.get(f"{_BASE}/servlet/PatenteServletController?{query}", timeout=15)
        except requests.RequestException:
            return None
        m2 = _RE_PROCURADOR.search(ficha.text)
        return m2.group(1).strip() if m2 else None


def varrer_e_registrar_paralelo(
    numeros_inpi: list[str], escritorio_canonico: str, paralelismo: int = 4,
    fonte: str = "pePI busca.inpi.gov.br (busca por numero + ficha, paralelo)",
) -> dict:
    """Como varrer_e_registrar, mas com N sessoes independentes em paralelo.

    Cada _Trabalhador vive numa fila (queue.Queue): uma tarefa pega um
    trabalhador livre, usa exclusivamente ate terminar, devolve a fila. Isso
    evita duas threads reusando a MESMA requests.Session ao mesmo tempo --
    session nao e thread-safe, e a troca busca->ficha depende de cookies
    coerentes dentro de uma unica sequencia. `registrar` roda sob lock: e
    leitura+escrita do mesmo CSV, threads concorrentes sem lock poderiam
    perder update (duas threads leem "nao coletado ainda" antes de qualquer
    uma escrever, e a segunda escrita nao adiciona informacao mas desperdica
    uma checagem -- barato demais para valer complexidade extra, mas o lock
    remove a duvida)."""
    alvo = escritorio_canonico.strip().upper()

    trabalhadores: queue.Queue[_Trabalhador] = queue.Queue()
    for _ in range(paralelismo):
        t = _Trabalhador()
        if not t.sessao_anonima():
            return {"erro": "nao foi possivel abrir sessao anonima no pePI"}
        trabalhadores.put(t)

    lock = threading.Lock()
    resumo = {"registrados": 0, "sem_procurador_ou_nao_encontrado": 0,
              "outro_escritorio": 0, "formato_nao_suportado": 0, "ja_coletado_ou_invalido": 0}

    def _processar(numero_inpi: str) -> None:
        if _formatar_numero_busca(numero_inpi) is None:
            with lock:
                resumo["formato_nao_suportado"] += 1
            return
        trabalhador = trabalhadores.get()
        try:
            procurador = trabalhador.procurador_na_ficha(numero_inpi)
        finally:
            trabalhadores.put(trabalhador)
        if not procurador:
            with lock:
                resumo["sem_procurador_ou_nao_encontrado"] += 1
            return
        if normalizar(procurador) != alvo:
            with lock:
                resumo["outro_escritorio"] += 1
            return
        with lock:
            ok = registrar(numero_inpi, procurador, escritorio_canonico, fonte,
                           date.today().isoformat())
            resumo["registrados" if ok else "ja_coletado_ou_invalido"] += 1

    with ThreadPoolExecutor(max_workers=paralelismo) as ex:
        futuros = [ex.submit(_processar, n) for n in numeros_inpi]
        for f in as_completed(futuros):
            f.result()
    return resumo


def registrar(
    numero_inpi: str,
    procurador: str,
    escritorio_canonico: str,
    fonte: str,
    coletado_em: str,
    observacao: str = "",
) -> bool:
    """Grava uma linha coletada no CSV curado, se ainda fizer sentido gravar.

    Recusa (devolve False) quando o numero_inpi nao existe na base ou ja tem
    procurador oficial -- gravar mesmo assim so inflaria o CSV com linhas que
    o merge do ingest vai ignorar de qualquer forma.
    """
    c = con()
    existe = c.execute(
        "SELECT 1 FROM biblio WHERE numero_inpi = ?", [numero_inpi]
    ).fetchone()
    if not existe:
        return False
    tem_procurador = c.execute(
        "SELECT 1 FROM procuradores WHERE numero_inpi = ?", [numero_inpi]
    ).fetchone()
    if tem_procurador:
        return False

    ja_coletados = {r["numero_inpi"] for r in _le_csv()}
    if numero_inpi in ja_coletados:
        return False

    novo = not CSV_SIGILO.exists()
    with CSV_SIGILO.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CAMPOS, lineterminator="\n")
        if novo:
            w.writeheader()
        w.writerow({
            "numero_inpi": numero_inpi,
            "procurador": procurador,
            "escritorio_canonico": escritorio_canonico,
            "fonte": fonte,
            "coletado_em": coletado_em,
            "observacao": observacao,
        })
    return True


def _le_csv() -> list[dict]:
    if not CSV_SIGILO.exists():
        return []
    with CSV_SIGILO.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))
