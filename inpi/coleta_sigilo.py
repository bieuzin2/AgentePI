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
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

import requests

from enriquecimento.limitador import USER_AGENT, requisitar
from inpi import tor_proxy
from inpi.db import con
from inpi.escritorios import apelidos_com_motivo, normalizar

RAIZ = Path(__file__).resolve().parent
CSV_SIGILO = RAIZ / "referencias" / "procuradores-sigilo.csv"
CAMPOS = ["numero_inpi", "procurador", "escritorio_canonico", "fonte", "coletado_em", "observacao"]

_MOTIVOS_INUTEIS_PARA_BUSCA = ("erro de digitacao",)

_HOST = "busca.inpi.gov.br"
_BASE = f"https://{_HOST}/pePI"
_RE_NUMERO_MODERNO = re.compile(r"^(\d{2})(\d{4})(\d{6})$")
_RE_NUMERO_ANTIGO = re.compile(r"^[A-Z0-9]{6,12}$")
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
    """'102026015044' -> 'BR 10 2026 015044'. Formato unificado pos-2012
    (2+4+6 digitos: tipo+ano+sequencial).

    Formato antigo (pre-2012: 'PI0413188', 'C10305735' etc) -- confirmado ao
    vivo em 2026-08-11 que o pePI aceita esse numero CRU, sem transformacao
    nenhuma (testado com 'PI0413188' e 'C10305735', ambos encontraram o
    pedido). Devolve o numero como esta, so filtrando lixo obvio (caracteres
    fora de A-Z0-9 ou tamanho implausivel). Devolve None so quando nao bate
    com nenhum dos dois formatos -- quem chama pula o numero em vez de
    arriscar uma busca sem sentido."""
    m = _RE_NUMERO_MODERNO.match(numero_inpi)
    if m:
        tipo, ano, seq = m.groups()
        return f"BR {tipo} {ano} {seq}"
    candidato = numero_inpi.strip().upper()
    if _RE_NUMERO_ANTIGO.match(candidato):
        return candidato
    return None


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


class CircuitBreaker:
    """Pausa a coleta inteira se muitas falhas seguidas acontecerem -- sinal
    de bloqueio/instabilidade temporaria, nao vale insistir contra ele. Falha
    = ficha_html devolveu None depois do retry-on-session-loss (rede caiu, ou
    a sessao nao recuperou); 'pedido sem procurador' com ficha carregada com
    sucesso NAO conta como falha, e resultado valido. Compartilhado entre
    inpi.coleta_sigilo e inpi.coleta_ficha_extras -- mesma preocupacao,
    volume de producao (dezenas de milhares de numeros) 12x maior que o
    primeiro run que validou o paciamento simples."""

    def __init__(self, limite: int = 10, pausa_segundos: float = 180.0):
        self.limite = limite
        self.pausa_segundos = pausa_segundos
        self._lock = threading.Lock()
        self._falhas_seguidas = 0

    def sucesso(self) -> None:
        with self._lock:
            self._falhas_seguidas = 0

    def falha(self) -> None:
        with self._lock:
            self._falhas_seguidas += 1
            estourou = self._falhas_seguidas >= self.limite
            if estourou:
                self._falhas_seguidas = 0
        if not estourou:
            return
        if tor_proxy.ativo():
            # Com Tor, falhas seguidas provavelmente sao o EXIT NODE atual
            # tambem bloqueado -- pedir novo circuito (IP novo) resolve mais
            # rapido que so esperar parado com o mesmo IP problematico.
            print(f"  circuit breaker: {self.limite} falhas seguidas, "
                  f"pedindo novo circuito Tor", flush=True)
            if not tor_proxy.novo_circuito():
                time.sleep(self.pausa_segundos)
        else:
            print(f"  circuit breaker: {self.limite} falhas seguidas, "
                  f"pausando {self.pausa_segundos:.0f}s", flush=True)
            time.sleep(self.pausa_segundos)


_executor_timeout = ThreadPoolExecutor(max_workers=256, thread_name_prefix="rede-timeout")


def _com_timeout_forte(fn, timeout: float = 12.0):
    """Roda `fn` (sem argumentos) com um timeout de parede real, driblando um
    bug observado ao vivo: `requests` com `timeout=15` passado pro SOCKS via
    PySocks as vezes NAO retorna -- fica preso indefinidamente numa conexao
    morta em vez de estourar o timeout declarado (visto em producao: um slot
    travado congelava o loop sequencial de _abrir_trabalhadores por dezenas de
    minutos, sem nenhum erro). Devolve None se `fn` nao retornar a tempo.
    ponytail: a thread presa NAO e morta (Python nao mata threads) -- so
    abandonada; aceitavel porque o processo e de vida curta (reinicia a cada
    rodada), mas um vazamento de threads persistente precisaria de outra
    abordagem (subprocess com kill, por exemplo)."""
    try:
        return _executor_timeout.submit(fn).result(timeout=timeout)
    except FuturesTimeoutError:
        return None


def _abrir_trabalhadores(paralelismo: int) -> "queue.Queue[_Trabalhador] | None":
    """Cria ate N _Trabalhador com sessao anonima propria, ESCALONADOS no tempo.

    Abrir todas de uma vez em rajada foi o que derrubou uma sessao real em
    producao (SSLEOFError/handshake resetado em busca.inpi.gov.br logo apos
    2 processos abrirem 6+6=12 sessoes quase simultaneas, 2026-08-11). Espalhar
    a abertura no tempo evita parecer rajada.

    Tolerante a falha individual: via Tor cada worker abre por um exit node
    novo (isolamento por credencial SOCKS) e um exit node isolado pode vir
    lento/morto -- isso derrubava a frente INTEIRA quando a abertura era
    tudo-ou-nada. Aqui cada slot tenta algumas vezes (circuito novo a cada
    tentativa); so aborta se nao juntar um minimo viavel de workers. Um exit
    ruim custa um retry, nao a coleta toda.

    Abertura EM PARALELO: o INPI bane uma fracao grande dos exit nodes Tor,
    entao cada tentativa de abrir pode gastar ate ~25s (timeout de parede num
    exit morto que nao reseta rapido). Abrir os 30 slots em SERIE, cada um com
    ate 8 tentativas, dava ate minutos POR slot e a frente ficava 0/min por
    tempo demais so abrindo (visto ao vivo). Abrir todos concorrentes faz o
    tempo total virar ~o de um slot, nao 30x. O stagger (jitter no inicio de
    cada task) ainda evita a rajada instantanea que ja derrubou a sessao uma
    vez."""
    # Distribui workers entre os daemons Tor vivos (round-robin): um daemon so
    # afoga sob ~10+ circuitos concorrentes, entao espalhar entre N daemons e o
    # que de fato multiplica a vazao. Sem Tor, portas fica [None] e todos os
    # workers vao direto.
    portas = tor_proxy.portas_vivas() if tor_proxy.ativo() else []
    portas = portas or [None]
    trabalhadores: queue.Queue[_Trabalhador] = queue.Queue()
    minimo = max(1, paralelismo // 2)

    def _abrir_um(i: int) -> None:
        # stagger: espalha o inicio no tempo pra nao abrir 30 sessoes na mesma
        # fracao de segundo (rajada ja resetou a sessao uma vez).
        time.sleep(random.uniform(0.0, min(15.0, paralelismo * 0.4)))
        porta = portas[i % len(portas)]
        # 8 tentativas: ~metade dos exits Tor cai em SSLEOFError instantaneo
        # (exit banido pelo INPI). Cada tentativa = credencial SOCKS nova =
        # circuito/exit novo. Mais tentativas = mais chance de exit vivo.
        for _tentativa in range(8):
            t = _Trabalhador(circuito=f"w{i}_{random.randint(0, 1_000_000)}",
                             socks_port=porta)
            if _com_timeout_forte(t.sessao_anonima):
                trabalhadores.put(t)
                return
            time.sleep(random.uniform(0.5, 1.5))

    with ThreadPoolExecutor(max_workers=paralelismo) as ex:
        for f in as_completed([ex.submit(_abrir_um, i) for i in range(paralelismo)]):
            f.result()
    abertos = trabalhadores.qsize()
    if abertos < minimo:
        return None
    if abertos < paralelismo:
        print(f"  aviso: {abertos}/{paralelismo} sessoes abriram "
              f"(exit nodes lentos/mortos); seguindo com {abertos}", flush=True)
    return trabalhadores


class _Trabalhador:
    """Sessao HTTP independente (login anonimo proprio) para coleta em paralelo.

    NAO reusa o _sessao module-level de enriquecimento.limitador: aquele e uma
    unica instancia global que serializa tudo via _espera por host, o oposto
    do que paralelismo precisa. Cada trabalhador pacea A SI MESMO -- com N
    trabalhadores rodando a ~1 requisicao a cada `intervalo` segundos cada, o
    agregado no host e N/intervalo req/s, deliberado e prop a `paralelismo`.
    """

    def __init__(self, intervalo: float = 1.0, circuito: str | None = None,
                 socks_port: int | None = None):
        self.socks_port = socks_port
        self.intervalo = intervalo
        self._ultima = 0.0
        self._montar_sessao(circuito)

    def _montar_sessao(self, circuito: str | None) -> None:
        self.circuito = circuito
        self.sessao = requests.Session()
        self.sessao.headers.update({"User-Agent": USER_AGENT})
        if tor_proxy.ativo():
            self.sessao.proxies.update(tor_proxy.proxies(circuito, self.socks_port))

    def renovar(self) -> bool:
        """Descarta a sessao atual e reabre por um CIRCUITO NOVO (credencial
        SOCKS nova = exit node novo). Chamado quando um fetch falha: o exit
        node do worker provavelmente degradou/foi banido pelo INPI, e reusar a
        mesma sessao so acumula fetches lentos (cada um consumindo o timeout de
        parede inteiro) -- medido ao vivo que sessoes de vida longa decaem de
        ~4 procs/min pra ~0,2 conforme os exits envelhecem, enquanto sessoes
        frescas mantem o ritmo. Renovar recupera o worker em vez de arrasta-lo
        degradado ate o fim da rodada."""
        try:
            self.sessao.close()
        except Exception:
            pass
        novo = f"r{random.randint(0, 1_000_000)}"
        self._montar_sessao(novo)
        return _com_timeout_forte(self.sessao_anonima) or False

    def _espera(self) -> None:
        # Jitter +-30%: em volume alto (dezenas de milhares de numeros), N
        # trabalhadores com intervalo fixo tendem a se alinhar em fase e bater
        # no host em rajadas periodicas em vez de espalhado -- jitter quebra
        # esse alinhamento sem mudar a taxa media.
        intervalo_com_jitter = self.intervalo * random.uniform(0.7, 1.3)
        falta = intervalo_com_jitter - (time.monotonic() - self._ultima)
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

    def ficha_html(self, numero_inpi: str) -> str | None:
        """Busca o pedido pelo numero e devolve o HTML cru da ficha, ou None
        se o numero nao foi encontrado ou a busca falhou. Base compartilhada
        de procurador_na_ficha (Frente 2 -- so o campo 74) e de
        inpi.coleta_ficha_extras (Frente 1 -- CPC/anuidades/peticoes),
        evitando duplicar a sequencia busca->ficha em dois modulos."""
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
                return self.ficha_html(numero_inpi) if self.sessao_anonima() else None
            return None
        codpedido = m.group(1)
        query = urlencode({"Action": "detail", "CodPedido": codpedido,
                           "SearchParameter": numero_busca, "Resumo": "", "Titulo": ""})
        try:
            self._espera()
            ficha = self.sessao.get(f"{_BASE}/servlet/PatenteServletController?{query}", timeout=15)
        except requests.RequestException:
            return None
        return ficha.text

    def procurador_na_ficha(self, numero_inpi: str) -> str | None:
        html = self.ficha_html(numero_inpi)
        if html is None:
            return None
        m2 = _RE_PROCURADOR.search(html)
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
    remove a duvida).

    Filtra os ja coletados ANTES do fetch de rede -- reprocessar uma
    populacao parcialmente coletada (ex.: retomar apos reiniciar Tor)
    desperdicava 2 requisicoes por numero_inpi so pra descartar no dedup
    de registrar()."""
    alvo = escritorio_canonico.strip().upper()
    numeros_inpi = [n for n in numeros_inpi if n not in _coletados()]

    trabalhadores = _abrir_trabalhadores(paralelismo)
    if trabalhadores is None:
        return {"erro": "nao foi possivel abrir sessao anonima no pePI"}

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
            html = _com_timeout_forte(lambda: trabalhador.ficha_html(numero_inpi))
            if html is None:
                trabalhador.renovar()
        finally:
            trabalhadores.put(trabalhador)
        procurador = None
        if html is not None:
            m = _RE_PROCURADOR.search(html)
            procurador = m.group(1).strip() if m else None
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


def varrer_e_registrar_geral_paralelo(
    numeros_inpi: list[str], paralelismo: int = 4,
    fonte: str = "pePI busca.inpi.gov.br (busca por numero + ficha, geral)",
) -> dict:
    """Como varrer_e_registrar_paralelo, mas SEM escritorio-alvo: grava
    qualquer procurador que a ficha mostrar, resolvido pela chave normalizada
    (escritorios.normalizar). Usado para descobrir procurador de todo pedido
    em sigilo -- nao so os ja associados a um escritorio conhecido. A
    extracao do campo (74) e agnosica de quem e o procurador (confirmado ao
    vivo com um agente que nao e da Clarke), entao nao ha razao pra restringir
    a coleta a um alvo: um pedido sigiloso pertence a algum escritorio ou a
    nenhum, nunca "nao interessa".

    Filtra os ja coletados ANTES do fetch de rede (mesmo motivo de
    varrer_e_registrar_paralelo acima)."""
    numeros_inpi = [n for n in numeros_inpi if n not in _coletados()]
    trabalhadores = _abrir_trabalhadores(paralelismo)
    if trabalhadores is None:
        return {"erro": "nao foi possivel abrir sessao anonima no pePI"}

    lock = threading.Lock()
    quebrador = CircuitBreaker()
    resumo = {"registrados": 0, "sem_procurador_ou_nao_encontrado": 0,
              "formato_nao_suportado": 0, "ja_coletado_ou_invalido": 0}
    progresso = {"n": 0, "t0": time.monotonic()}

    def _processar(numero_inpi: str) -> None:
        if _formatar_numero_busca(numero_inpi) is None:
            with lock:
                resumo["formato_nao_suportado"] += 1
            return
        trabalhador = trabalhadores.get()
        try:
            html = _com_timeout_forte(lambda: trabalhador.ficha_html(numero_inpi))
            if html is None:
                # exit degradou: renova o worker (circuito novo) antes de
                # devolve-lo a fila, pra nao arrastar uma sessao lenta o resto
                # da rodada.
                trabalhador.renovar()
        finally:
            trabalhadores.put(trabalhador)
        # heartbeat: fichas processadas/min (throughput real, independe do
        # rendimento de 2% de procurador) -- a cada 200, imprime taxa.
        with lock:
            progresso["n"] += 1
            if progresso["n"] % 200 == 0:
                dt = time.monotonic() - progresso["t0"]
                print(f"  progresso: {progresso['n']} fichas, "
                      f"{progresso['n']/dt*60:.0f} fichas/min, "
                      f"{resumo['registrados']} procs achados", flush=True)
        if html is None:
            quebrador.falha()
            with lock:
                resumo["sem_procurador_ou_nao_encontrado"] += 1
            return
        quebrador.sucesso()
        m2 = _RE_PROCURADOR.search(html)
        procurador = m2.group(1).strip() if m2 else None
        if not procurador:
            with lock:
                resumo["sem_procurador_ou_nao_encontrado"] += 1
            return
        escritorio_canonico = normalizar(procurador)
        with lock:
            ok = registrar(numero_inpi, procurador, escritorio_canonico, fonte,
                           date.today().isoformat())
            resumo["registrados" if ok else "ja_coletado_ou_invalido"] += 1

    with ThreadPoolExecutor(max_workers=paralelismo) as ex:
        futuros = [ex.submit(_processar, n) for n in numeros_inpi]
        for f in as_completed(futuros):
            f.result()
    return resumo


_cache_coletados: set[str] | None = None


def _coletados() -> set[str]:
    """Cache em memoria de numero_inpi ja no CSV -- ver mesmo comentario em
    inpi.coleta_ficha_extras._coletados: reler o CSV inteiro a cada gravacao
    virava lock global de centenas de ms por registro, piorando conforme o
    CSV cresce. Seguro sem lock proprio: registrar() so roda sob o lock do
    driver paralelo."""
    global _cache_coletados
    if _cache_coletados is None:
        _cache_coletados = {r["numero_inpi"] for r in _le_csv()}
    return _cache_coletados


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

    if numero_inpi in _coletados():
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
    _coletados().add(numero_inpi)
    return True


def _le_csv() -> list[dict]:
    if not CSV_SIGILO.exists():
        return []
    with CSV_SIGILO.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))
