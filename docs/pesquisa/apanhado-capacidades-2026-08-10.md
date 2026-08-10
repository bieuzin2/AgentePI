# Apanhado de capacidades — ferramenta interna de pesquisa de patentes

**Data:** 2026-08-10 · **Autor:** Agente de PI (Clarke Modet) · **Método:** ~20 consultas exploratórias reais nos MCP servers `inpi`, `epo`, `uspto`, `busca`, `landscape`.

## Resumo executivo

A ferramenta é forte no **miolo brasileiro**: a base local do INPI está fresca (RPI 2900, corte 2026-08-04, ~6 dias de atraso; 1.014.210 processos, 5,3 mi despachos) e cobre com profundidade a ficha processual, o portfólio por titular, a carteira por escritório, projeções de anuidade/prazo (art. 84/33/40) e métricas de gestão (backlog, tempo entre fases). A grande virtude transversal é a **honestidade epistêmica**: quase toda saída distingue vazio-por-cobertura de vazio-real e avisa que projeção não é fatura. Os pontos fracos são hoje **operacionais, não conceituais**: o servidor EPO está parcialmente quebrado neste host Windows (`No module named 'fcntl'` derruba `epo_busca`, `epo_familia_inpadoc` e `epo_status_legal` — ou seja, família no exterior e status legal estrangeiro estão indisponíveis), o servidor `landscape` não abre o cache DuckDB (arquivo travado por outro processo), o USPTO está limitado a PPUBS (ODP sem chave; PatentsView/office actions descontinuados) e o PPUBS 500a com sintaxe booleana por campo. Também há atritos menores de parsing de número entre servidores e um bloco de "composição" de escritório que a documentação da tarefa esperava e que o `inpi_escritorio_resolver` não entrega.

## Matriz de capacidades

| Área | Pergunta testada | Tool | Veredito | Observação |
|---|---|---|---|---|
| Cobertura da base | Até quando a base está atualizada? | `inpi_cobertura` | ✅ | RPI 2900, corte 2026-08-04, 6 dias de atraso. Base é dump local. |
| Cota EPO | Quanto da cota semanal foi gasta? | `epo_quota` | ✅ | 0,72% de 4 GB. Funciona mesmo com o resto do EPO quebrado. |
| Ficha/andamento BR | Andamento do BR 10 2022 010731 2 (UFERSA) | `inpi_processo` | ✅ | Histórico completo, IPC, despachos; último 9.2 (indeferimento). Sem procurador (depósito pró-se). Aceita vários formatos de número. |
| Carteira de escritório | Casos Clarke × cliente Petrobras | `inpi_carteira` | ✅ | 497 vivos, `truncado:true` (limite 20). Agrupa 97 grafias sob chave CLARKE MODET. |
| Resolver escritório | Em que chave "Clarke Modet" cai? | `inpi_escritorio_resolver` | ⚠️ | 44.722 processos, 97 grafias. **NÃO retorna bloco `composicao` (firma vs. agentes afiliados)** que a tarefa esperava; agrega nomes de procuradores pessoas físicas (Orlando de Souza, Flávia Salim Lopes) dentro da firma sem separá-los. |
| Movimentação de carteira | Entradas de processos por ano na Clarke | `inpi_movimentacao_escritorio` | ⚠️ | Usado como substituto de `inpi_exigencias_escritorio` (ver bug). Conta entradas, nunca origem; "de qual banca veio" é estruturalmente irrespondível. |
| Perfil de titular (cliente) | Perfil analítico Petrobras | `inpi_perfil_titular` | ✅ | 2.620 processos, evolução anual, foco IPC (E21B líder), troca de banca. Cross-check BigQuery indisponível (ConsultaMuitoGrandeError). |
| Perfil de titular (concorrente) | Perfil analítico Huawei | `inpi_perfil_titular` | ✅ | 5.101 processos, foco H04W/H04L. 2025 mostra só 16 depósitos (defasagem de sigilo 18m) sem a tool sinalizar isso como lag. |
| Anterioridade por texto | Embalagem biodegradável de alginato | `inpi_busca_texto` | ✅ | 5 hits BR relevantes. Substring literal (ILIKE), não semântica — avisa para cruzar com IPC. |
| Anterioridade por IPC | Classe B65D 65/46 | `inpi_busca_ipc` | ✅ | 10 hits; imune a vocabulário. Alguns títulos `null` (pedidos recém-publicados). |
| Backlog / gestão | Pendentes da carteira Clarke por idade | `inpi_backlog` | ✅ | 26.146 pendentes; 16.639 com 8+ anos. Não distingue arquivado de em trâmite. |
| Tempo entre fases | Quanto tempo em E21B? | `inpi_tempo_fases` | ✅ | Mediana depósito→concessão 2.610 dias; p25/p75 explícitos. Só casos já concluídos. |
| Anuidade de um caso | Quando vence a próxima anuidade do PI0803071? | `inpi_anuidades` | ✅ | 19ª anuidade, fim complementar 2027-05-21; puxou vigência do despacho 16.1 (ADI 5.529). Projeção, não fatura. |
| Prazos de carteira | Anuidades Petrobras vencendo em set/2026 | `inpi_prazos_carteira` | ⚠️ | 897 prazos; `truncado` em 15. Todos em "prazo_complementar_corrente" (ordinário já fechou em março) — a "data do prazo" é o fim da janela com multa, o que pode confundir o cliente. |
| Score de saúde | Um número para abrir reunião Petrobras | `carteira_saude` | ✅ | Score 80,3/100 com componentes e lacunas explícitas (497 casos encerrados). Exterior fora do score (e hoje inacessível via EPO). |
| Família INPADOC no exterior | Família do BR UFERSA | `epo_familia_inpadoc` | ❌ | 1ª tentativa: rejeitou o formato "BR 10 2022 010731 2" que o `inpi_processo` aceita. 2ª (número normalizado): `No module named 'fcntl'`. **Quebrado no Windows.** |
| Status legal no exterior | Onde a família ainda vive/caducou? | `epo_status_legal` | ❌ | `No module named 'fcntl'`. **Quebrado no Windows.** |
| Busca EPO (BR/CN/EP) | Busca CQL Braskem | `epo_busca` | ❌ | `No module named 'fcntl'`. **Quebrado no Windows.** |
| Panorama de tópico — país coberto | Embalagem biodegradável na China | `epo_panorama_topico` | ✅ | Total 2.550. Funciona apesar do fcntl. Amostra de 50 toda de 2026 (viés de recência na amostra). |
| Panorama de tópico — país mal coberto | Idem no Omã (OM) | `epo_panorama_topico` | ⚠️ | Total 0. Enquadra como "vazio válido, confira o termo" — **não distingue explicitamente lacuna de cobertura de OM na DOCDB de ausência real**. |
| Landscape mundial por IPC | Top titulares em B65D65/46 | `landscape_top_titulares` | ❌ | `IO Error: cache DuckDB travado por outro processo (PID 12420)`. Falhou 2×. **Servidor landscape inteiro indisponível.** |
| USPTO status | Quais fontes US estão configuradas? | `check_api_status` | ⚠️ | PPUBS ok; ODP sem chave; PatentsView e office-actions descontinuados/decomissionados em 2026; TSDR sem chave. |
| USPTO busca | Patentes US de embalagem biodegradável | `ppubs_search_patents` | ⚠️ | Sintaxe `TTL/"x" AND TTL/"y"` → 500. Query simples funciona, mas relevância fraca (retornou os grants mais recentes, pouco aderentes aos termos). |

## Limites estruturais (do desenho, não bugs)

- **Base BR é dump local com atraso** (~6 dias): despachos posteriores à última RPI não existem aqui. Vazio recente ≠ ausência.
- **Projeção não é fatura**: anuidades/prazos são calculados de data de depósito + regra legal. A base registra *consequência* (despacho de extinção), nunca *vencimento futuro*; pagamento em dia não gera despacho. Nunca substitui o docketing do escritório.
- **Origem de banca é irrespondível**: só 248 de 774.026 processos têm mais de um escritório gravado. "Quantos vieram da Dannemann para a Clarke" não tem resposta em nenhuma agregação.
- **Ambiguidade de grafia/titular**: 17.521 grafias para ~10 mil escritórios; Clarke aparece em 97 formas. Confiar em número de carteira sem resolver a chave leva a erro sistemático. Cross-check BigQuery para portfólios grandes está indisponível (ConsultaMuitoGrandeError).
- **Cobertura de texto integral**: só BR (via INPI) e US (via PPUBS). EPO quase não tem texto integral de BR; não há full-text CN/EP aqui.
- **Panorama de país mal coberto**: total 0 pode ser lacuna da DOCDB para aquela jurisdição, não ausência real — a tool não separa os dois casos.

## Bugs / atritos encontrados

1. **EPO quebrado no Windows (`No module named 'fcntl'`)** — derruba `epo_busca`, `epo_familia_inpadoc`, `epo_status_legal`. `fcntl` é POSIX-only (provável file-lock do log de quota). `epo_quota` e `epo_panorama_topico` escapam. **Impacto alto**: família no exterior e status legal estrangeiro estão zerados.
2. **`landscape` inteiro fora do ar** — `IO Error: cache DuckDB travado por outro processo (PID 12420 python.exe)`. Falta de lock/pool de conexão single-writer; nenhuma consulta de landscape mundial roda enquanto outro processo segurar o arquivo.
3. **Parsing de número inconsistente entre servidores** — `inpi_processo` aceita "BR 10 2022 010731 2"; `epo_familia_inpadoc` rejeita o mesmo texto e exige "BR102022010731". Deveria normalizar na borda.
4. **`inpi_exigencias_escritorio` não existe** no toolset (nomeada na tarefa). Não há tool dedicada a "exigências por período cumpridas/pendentes"; o mais próximo é filtrar despachos manualmente. Ressalva "cumprimento = petição" não pôde ser verificada.
5. **`inpi_escritorio_resolver` sem bloco `composicao`** — não separa a firma dos agentes pessoas físicas afiliados; joga tudo na mesma chave, o que pode inflar/confundir a leitura de carteira.
6. **PPUBS 500 com sintaxe por campo** (`TTL/"x" AND TTL/"y"`) e relevância fraca em query livre — retorna os grants mais recentes, não os mais aderentes.
7. **`inpi_prazos_carteira` — semântica da "data do prazo"** — em set/2026 devolve 897 itens todos já no prazo complementar (ordinário fechou em março); a data exibida é o fim da janela com multa. Fácil de ler como "vence agora, tranquilo".

## Perguntas de cliente que a ferramenta NÃO aguenta hoje

- **"Onde no exterior minha família caducou / ainda está viva?"** — dependia de `epo_status_legal`/`epo_familia_inpadoc`, ambos quebrados no Windows (fcntl).
- **"Quem são os maiores depositantes mundiais nessa tecnologia?"** — `landscape` fora do ar (lock DuckDB).
- **"Achei o equivalente US, qual é o BR da mesma família?"** — mapeamento de família INPADOC indisponível agora.
- **"Quantas exigências nós cumprimos no ano passado?"** — sem tool dedicada; `inpi_exigencias_escritorio` não existe.
- **"De qual banca esses processos vieram para nós?"** — estruturalmente irrespondível (a base guarda representação vigente, não série histórica).
- **"Essa anuidade já foi paga?"** — a base só sabe o que foi *notificado* por despacho; silêncio não prova pagamento nem inadimplência.
- **Busca full-text em patente chinesa/europeia** — sem cobertura de texto integral CN/EP neste ambiente.
