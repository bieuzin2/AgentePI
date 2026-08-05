"""CSS do dashboard (extraido de relatorio_html.py p/ manter <500 linhas/arquivo).

Paleta oficial ClarkeModet (azul royal #0033FF + magenta #FF0066), validada
com ui-ux-pro-max. Inclui os estilos das secoes novas da Fase 2 (plano 4.3):
alertas da semana (tags de severidade), anuidades 90 dias e os dois cards de
placeholder (tarefas, landscape) -- lidos como "ainda nao implementado", nao
como erro.
"""

CSS = """
:root{
  /* Marca ClarkeModet (extraida do site): azul royal + magenta. */
  --azul:#0033FF; --azul2:#0D6EFD; --magenta:#FF0066; --azul-claro:#DAE3FF;
  --bg:#f5f7fa; --card:#ffffff; --ink:#212529;
  --muted:#64748b; --border:#e2e8f0; --red:#dc2626; --amber:#d97706; --green:#047857;
  --grid:#eef2f6;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:"Inter","Segoe UI",system-ui,-apple-system,Roboto,sans-serif;font-size:14px;
  line-height:1.5;-webkit-font-smoothing:antialiased}
.num{font-variant-numeric:tabular-nums;letter-spacing:-.01em}
.wrap{max-width:1180px;margin:0 auto;padding:0 20px 60px}
header.top{position:sticky;top:0;z-index:20;background:var(--card);
  border-bottom:2px solid var(--azul);box-shadow:0 1px 4px rgba(15,23,42,.06)}
.top-in{max-width:1180px;margin:0 auto;padding:12px 20px;display:flex;
  align-items:center;gap:16px;flex-wrap:wrap}
.top svg{height:34px;width:auto}
.top h1{font-size:15px;font-weight:600;color:var(--muted);margin:0;
  padding-left:16px;border-left:1px solid var(--border)}
.cobertura{margin-left:auto;font-size:12px;color:var(--muted);text-align:right}
.cobertura .alerta{color:var(--amber);font-weight:600}

/* Barra de segmentacao global */
.seg{background:var(--card);border:1px solid var(--border);border-radius:10px;
  padding:12px 14px;margin:18px 0;display:flex;gap:10px;flex-wrap:wrap;
  align-items:flex-end}
.seg .grp{display:flex;flex-direction:column;gap:3px}
.seg label{font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;
  letter-spacing:.03em}
.seg select,.seg input{border:1px solid var(--border);border-radius:6px;padding:6px 8px;
  font-size:13px;background:#fff;color:var(--ink);min-width:110px}
.seg input[type=text]{min-width:180px}
.seg .clear{margin-left:auto;align-self:center;background:var(--azul);color:#fff;
  border:0;border-radius:6px;padding:8px 14px;font-size:13px;cursor:pointer;
  transition:background .18s}
.seg .clear:hover{background:#0026bf}
.recorte{font-size:12px;color:var(--muted);margin:-6px 0 14px}
.recorte b{color:var(--azul)}

/* KPIs */
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));gap:12px;
  margin:16px 0}
.kpi{background:var(--card);border:1px solid var(--border);border-radius:12px;
  padding:15px 16px 13px;border-top:3px solid var(--azul);position:relative;
  transition:box-shadow .18s,transform .18s,border-color .18s}
.kpi.risk{border-top-color:var(--red)} .kpi.warn{border-top-color:var(--amber)}
.kpi .v{font-size:30px;font-weight:700;color:var(--ink);line-height:1.05;
  font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.kpi.risk .v{color:var(--red)} .kpi.warn .v{color:var(--amber)}
.kpi .l{font-size:11px;color:var(--muted);margin-top:5px;text-transform:uppercase;
  letter-spacing:.04em;font-weight:500;line-height:1.3}
/* KPI clicavel (toggle de filtro) */
.kpi.click{cursor:pointer}
.kpi.click:hover{box-shadow:0 4px 14px rgba(0,51,255,.12);transform:translateY(-2px)}
.kpi.click:active{transform:translateY(0)}
.kpi.click::after{content:"";position:absolute;right:11px;top:11px;width:7px;height:7px;
  border-radius:50%;background:var(--border)}
.kpi.active{border-color:var(--magenta);box-shadow:0 0 0 2px var(--magenta) inset}
.kpi.active::after{background:var(--magenta)}
.kpi.active .v{color:var(--azul)}

/* Insight card grande (gráfico virou número + frase) */
.icard{display:flex;flex-direction:column;justify-content:center;min-height:200px;
  padding:8px 4px}
.icard .big{font-size:52px;font-weight:700;color:var(--azul);line-height:1;
  font-variant-numeric:tabular-nums;letter-spacing:-.03em}
.icard .big small{font-size:22px;color:var(--muted);font-weight:600;margin-left:4px}
.icard .cap{font-size:14px;color:var(--ink);margin-top:10px;font-weight:500}
.icard .cap b{color:var(--azul)}
.icard .sub2{font-size:12px;color:var(--muted);margin-top:6px}

/* Secoes e graficos */
section{background:var(--card);border:1px solid var(--border);border-radius:10px;
  padding:16px 18px;margin:16px 0;break-inside:avoid}
section h2{font-size:15px;margin:0 0 4px;color:var(--azul)}
section p.sub{font-size:12px;color:var(--muted);margin:0 0 14px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:820px){.grid2{grid-template-columns:1fr}}
.chart-box{position:relative;height:260px}
canvas{cursor:pointer}
/* Legenda IPC (rótulos coloridos) */
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;margin-top:10px;font-size:11px;
  color:var(--muted)}
.legend .lg{display:inline-flex;align-items:center;gap:5px}
.legend .lg i{width:10px;height:10px;border-radius:2px;display:inline-block}

/* Tabelas com AutoFilter */
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:7px 9px;text-align:left;border-bottom:1px solid var(--grid)}
th{background:var(--azul);color:#fff;font-weight:600;position:relative;
  user-select:none;white-space:nowrap;padding:0}
th .th-in{display:flex;align-items:center;gap:6px;padding:6px 9px}
th .th-lbl{display:inline-flex;align-items:center;gap:4px;cursor:pointer;flex:1;
  min-height:26px}
th .ar{font-size:10px;opacity:.85}
th .fn{margin-left:auto;display:inline-flex;align-items:center;justify-content:center;
  width:26px;height:26px;border-radius:6px;cursor:pointer;color:#fff;opacity:.65;
  background:transparent;border:0;transition:background .15s,opacity .15s}
th .fn:hover{background:rgba(255,255,255,.18);opacity:1}
th .fn.on{opacity:1;background:var(--magenta)}
td.n{text-align:right}
tbody tr:hover{background:#f0f7fc}
tbody tr:nth-child(even){background:#fafcfe}
.tag{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;
  font-weight:600}
.tag.fatal{background:#fef2f2;color:var(--red)}
.tag.compl{background:#fffbeb;color:var(--amber)}
/* Tags de severidade dos alertas da vigilancia (plano 4.1/4.3) */
.tag.alta{background:#fef2f2;color:var(--red)}
.tag.media{background:#fffbeb;color:var(--amber)}
.tag.baixa{background:var(--azul-claro);color:var(--azul)}
.tbl-foot{display:flex;justify-content:space-between;align-items:center;
  margin-top:10px;font-size:12px;color:var(--muted)}
.pg{display:flex;gap:6px}
.pg button{border:1px solid var(--border);background:#fff;border-radius:5px;
  padding:4px 9px;cursor:pointer;font-size:12px}
.pg button:disabled{opacity:.4;cursor:default}

/* AutoFilter popup (ancorado ao funil) */
th .th-in{position:relative}
.af{position:absolute;top:calc(100% + 6px);right:0;z-index:40;background:#fff;color:var(--ink);
  border:1px solid var(--border);border-radius:8px;box-shadow:0 8px 24px rgba(15,23,42,.18);
  padding:8px;min-width:210px;font-weight:400;text-transform:none;letter-spacing:0}
.af input.q{width:100%;margin-bottom:6px;padding:6px 8px;border:1px solid var(--border);
  border-radius:5px;font-size:12px}
.af .af-tools{display:flex;gap:6px;margin-bottom:6px}
.af .af-tools button{flex:1;border:1px solid var(--border);background:#f8fafc;
  border-radius:5px;padding:5px;cursor:pointer;font-size:11px;color:var(--azul)}
.af .vals{max-height:210px;overflow:auto;font-size:12px}
.af .vals label{display:flex;gap:7px;align-items:center;padding:4px 3px;cursor:pointer;
  color:var(--ink);font-weight:400;border-radius:4px}
.af .vals label:hover{background:var(--azul-claro)}
.af .act{display:flex;gap:6px;margin-top:7px}
.af .act button{flex:1;border:0;border-radius:5px;padding:7px;cursor:pointer;font-size:12px;
  font-weight:500}
.af .ok{background:var(--azul);color:#fff} .af .cl{background:#e2e8f0}

.aviso{background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:10px 12px;
  font-size:12px;color:#78350f;margin:14px 0}
.alertas li{margin:4px 0}
/* Placeholder de secao ainda nao implementada (tarefas/landscape, Fases 6 e 5) --
   borda tracejada + tom neutro para ler como "em construcao", nao como erro. */
.placeholder{border:1.5px dashed var(--border);border-radius:8px;padding:22px 16px;
  text-align:center;color:var(--muted);font-size:13px;background:#fafcfe}
.placeholder b{color:var(--azul2);display:block;font-size:13px;margin-bottom:4px}
footer{margin-top:30px;padding-top:14px;border-top:1px solid var(--border);
  font-size:11px;color:var(--muted);display:flex;justify-content:space-between;
  flex-wrap:wrap;gap:8px}

@media print{
  @page{size:A4;margin:12mm}
  body{background:#fff;font-size:11px}
  header.top{position:static;box-shadow:none}
  .cobertura,.seg .clear{}
  .seg{display:none}
  .print-recorte{display:block!important}
  section,.kpi{box-shadow:none;break-inside:avoid}
  .chart-box{height:220px}
  .pg,.af,.tbl-foot .pg{display:none}
  tbody tr:hover{background:none}
}
.print-recorte{display:none;font-size:12px;margin:6px 0 14px;color:var(--azul)}
"""
