"""Pacote busca: pipeline de anterioridade (INPI + EPO OPS + OpenAlex) e a tool busca_npl.

Ver docs/plano-v2.md secao 4.4. A decomposicao de conceitos/sinonimos e trabalho do
LLM via skill analista-patentes-inpi -- este pacote so executa consultas ja
decompostas, deduplica por familia INPADOC e organiza a saida. Nunca da veredito
de patenteabilidade.
"""
