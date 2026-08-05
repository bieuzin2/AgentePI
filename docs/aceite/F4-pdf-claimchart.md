# Fase 4 — PDFs INPI + Claim Chart BR — evidência de aceite

## Escopo (plano-v2.md §4.5)

`inpi/pdf_inpi.py` (download best-effort + fallback manual, extração de texto via
`pypdf`, parser de seções) e tool MCP `inpi_reivindicacoes`.

## Status real do download automático: FICOU NO FALLBACK MANUAL

Investigado em 2026-08-05. O portal público do INPI (`busca.inpi.gov.br/pePI`)
responde (`GET https://busca.inpi.gov.br` → 301 → `https://busca.inpi.gov.br/pePI/`
→ 200), mas é uma aplicação Java **stateful**: a busca por número de processo exige
sessão (`JSESSIONID`) e um ID interno de pedido (`CodPedido`) que só se obtém depois
de uma consulta prévia pela interface — não existe endpoint público documentado e
estável do tipo "documento por número de processo" sem essas etapas. Implementar um
scraper multi-request contra uma app stateful sem contrato de API é exatamente o
risco descrito no plano §9 ("portal INPI instável").

Decisão: `pdf_inpi.baixar_pdf()` **não tenta scraping**. Ele sempre checa primeiro
`inpi/data/pdfs/{numero_normalizado}.pdf`; se o arquivo não existe, devolve o
caminho esperado e instrui o operador a baixar manualmente pelo portal e salvar
ali. Esse fallback é o caminho único hoje, por design — não é um bug a corrigir
depois sem mais informação sobre uma rota estável.

Não foi possível testar com PDF real de pedido BR nesta sessão (nenhum PDF salvo
localmente e sem rota automática); os testes usam texto sintético que reproduz a
estrutura oficial (RELATÓRIO DESCRITIVO / RESUMO / REIVINDICAÇÕES numeradas).

## O que funciona

- `pdf_inpi.baixar_pdf(numero)` — resolve `inpi/data/pdfs/{numero}.pdf`; ok=True se
  existir, ok=False com instrução clara se não.
- `pdf_inpi.extrair_texto(caminho)` — `pypdf`; PDF sem texto extraível (imagem)
  devolve `ok=False` com mensagem "requer OCR — fora de escopo v2.0" (nunca falha
  silenciosamente).
- `pdf_inpi.parse_secoes(texto)` — heurística por marcador de linha
  (`RELATÓRIO DESCRITIVO`, `RESUMO`, `REIVINDICAÇÕES`, `DESENHOS`); seção sem
  marcador no texto vai para `secoes_ausentes`, nunca é inventada.
- `pdf_inpi.quadro_reivindicatorio(texto)` — separa por numeração `"N. "` no início
  de linha; formato `{numero, texto}` compatível com o claim chart US/EP já
  produzido pela skill `analista-patentes-inpi`.
- `pdf_inpi.carregar(numero)` — pipeline completo; declara cobertura em cada etapa
  (PDF ausente, PDF-imagem, seções ausentes) em vez de erro genérico.
- Tool MCP `inpi_reivindicacoes(numero)` registrada em `inpi/inpi_mcp.py`, mesmo
  padrão de docstring anti-alucinação das demais tools (USE QUANDO / fonte /
  avisos de cobertura).

## O que foi pulado/adiado

- OCR para PDF-imagem: explicitamente fora de escopo v2.0 (plano §4.5); mensagem de
  cobertura já deixa isso claro ao operador.
- Scraper automático do portal pePI: não implementado — ver decisão acima. Se uma
  rota pública estável for encontrada no futuro, entra em `baixar_pdf()` sem mudar
  assinatura.
- Testes com PDF real: não disponível nesta sessão (nem 1, nem 2-3 conforme
  plano); cobertos por fixture de texto sintético em `inpi/test_pdf_inpi.py`
  (8 casos: parser de seções, ausência de marcador, quadro reivindicatório
  numerado/sem numeração/vazio, fallback manual com e sem arquivo local).

## Comandos e resultado

```
.venv/Scripts/python.exe -m pytest epo inpi vigilancia -q
```

- Antes: 145 passed.
- Depois: 145 + 8 novos (`inpi/test_pdf_inpi.py`) = 153 passed, sem regressão.

Dependência nova: `pypdf` adicionada em `pyproject.toml` (`dependencies`).

## Commits

1. `feat(inpi): download best-effort e extracao de PDFs de pedidos publicados`
2. `feat(inpi): parser de secoes e tool inpi_reivindicacoes`
3. `docs: evidencia de aceite Fase 4` (este arquivo)
