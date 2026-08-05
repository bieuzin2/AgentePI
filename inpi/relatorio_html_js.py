"""JS client-side do dashboard (extraido de relatorio_html.py p/ manter
<500 linhas/arquivo). Agregacao sobre a fact table (DATA.fatos) + graficos
Chart.js + AutoFilter estilo Excel. Sem mudanca de comportamento -- so mudou
de arquivo. As secoes novas da Fase 2 (alertas, anuidades 90d, tarefas,
landscape) sao renderizadas em Python (relatorio_html.py), nao aqui: nao
precisam de segmentacao client-side, so de uma tabela/aviso estatico.
"""

_JS = r"""
const F=DATA.fatos, L=F.linhas, CLI=F.clientes, SIT=F.situacoes;
const C={anoDep:0,sit:1,ipc:2,pais:3,cli:4,conc:5,anoConc:6,anoFimVig:7};
const SIT_ROT={em_andamento:"Em andamento",concedida_vigente:"Concedida vigente",
  indeferida:"Indeferida",arquivada:"Arquivada",extinta:"Extinta"};
const SIT_COR={em_andamento:"#0D6EFD",concedida_vigente:"#047857",indeferida:"#dc2626",
  arquivada:"#94a3b8",extinta:"#FF0066"};
const IPC_ROT={A:"A · Necessidades humanas",B:"B · Operações/transporte",
  C:"C · Química/metalurgia",D:"D · Têxteis/papel",E:"E · Construções",
  F:"F · Mecânica",G:"G · Física",H:"H · Eletricidade"};
// Rampa azul->magenta: uma cor por seção IPC (categórica, não monótona).
const IPC_COR={A:"#0033FF",B:"#4A2BF0",C:"#7A24DB",D:"#A11FC4",E:"#C71DA6",
  F:"#E51C84",G:"#FF1F63",H:"#FF5C93"};
const AZUL="#0033FF",AZUL2="#0D6EFD",MAGENTA="#FF0066";
const fmt=n=>n.toLocaleString("pt-BR");
const pct=x=>(100*x).toFixed(1).replace(".",",");
const anos=L.map(r=>r[C.anoDep]).filter(Boolean);
const ANO_MIN=Math.min(...anos), ANO_MAX=Math.max(...anos);

let filt={cli:"",anoMin:null,anoMax:null,ipc:"",sit:"",pais:""};
let charts={};

// Uma so regra de recorte, aplicada a casos E a prazos (que carregam as mesmas dims).
function match(sit,ipc,pais,cli,ano){
  if(filt.sit!==""&&sit!==+filt.sit)return false;
  if(filt.ipc!==""&&ipc!==filt.ipc)return false;
  if(filt.pais!==""&&pais!==filt.pais)return false;
  if(filt.anoMin&&(!ano||ano<filt.anoMin))return false;
  if(filt.anoMax&&(!ano||ano>filt.anoMax))return false;
  if(filt.cli){const nome=CLI[cli]||"";
    if(!nome.toLowerCase().includes(filt.cli.toLowerCase()))return false;}
  return true;
}
function passa(r){return match(r[C.sit],r[C.ipc],r[C.pais],r[C.cli],r[C.anoDep]);}
function passaPrazo(p){const[s,i,pa,c,a]=p.dim;return match(s,i,pa,c,a);}
function filtra(){return L.filter(passa);}
function prazosFiltrados(){return DATA.prazos_12m.lista.filter(passaPrazo);}
function contar(rows,col){const m=new Map();
  for(const r of rows){const k=r[col];if(k==null||k==="")continue;
    m.set(k,(m.get(k)||0)+1);}return m;}
function paisesTop(){const m=contar(L,C.pais);
  return [...m.entries()].sort((a,b)=>b[1]-a[1]).slice(0,15).map(e=>e[0]);}

// Toggle de filtro: seta o valor; se ja for o mesmo, limpa (cross-filter Power BI).
function toggle(dim,val){
  if(dim==="ano"){
    if(filt.anoMin===val&&filt.anoMax===val){filt.anoMin=filt.anoMax=null;}
    else{filt.anoMin=filt.anoMax=val;}
  }else if(dim==="cli"){
    filt.cli=(filt.cli===val)?"":val;
  }else{
    filt[dim]=(String(filt[dim])===String(val))?"":val;
  }
  segBar();render();
}

function segBar(){
  const paises=paisesTop();
  const opt=(v,t,sel)=>`<option value="${v}"${sel?" selected":""}>${t}</option>`;
  document.getElementById("seg").innerHTML=`
   <div class="grp"><label>Cliente</label>
     <input type="text" id="f_cli" placeholder="buscar titular..." value="${filt.cli}"></div>
   <div class="grp"><label>Situação</label><select id="f_sit">
     ${opt("","todas",!filt.sit&&filt.sit!==0)}${SIT.map((s,i)=>opt(i,SIT_ROT[s],String(filt.sit)===String(i))).join("")}
   </select></div>
   <div class="grp"><label>Classificação</label><select id="f_ipc">
     ${opt("","todas",!filt.ipc)}${Object.keys(IPC_ROT).map(k=>opt(k,IPC_ROT[k],filt.ipc==k)).join("")}
   </select></div>
   <div class="grp"><label>País prioridade</label><select id="f_pais">
     ${opt("","todos",!filt.pais)}${paises.map(p=>opt(p,p,filt.pais==p)).join("")}
   </select></div>
   <div class="grp"><label>Depósito de</label>
     <input type="number" id="f_amin" min="${ANO_MIN}" max="${ANO_MAX}"
       placeholder="${ANO_MIN}" value="${filt.anoMin||""}" style="min-width:80px"></div>
   <div class="grp"><label>até</label>
     <input type="number" id="f_amax" min="${ANO_MIN}" max="${ANO_MAX}"
       placeholder="${ANO_MAX}" value="${filt.anoMax||""}" style="min-width:80px"></div>
   <button class="clear" id="f_clear">Limpar filtros</button>`;
  const on=(id,ev,fn)=>document.getElementById(id).addEventListener(ev,fn);
  let t;on("f_cli","input",e=>{clearTimeout(t);t=setTimeout(()=>{filt.cli=e.target.value;render();},250);});
  on("f_sit","change",e=>{filt.sit=e.target.value;render();});
  on("f_ipc","change",e=>{filt.ipc=e.target.value;render();});
  on("f_pais","change",e=>{filt.pais=e.target.value;render();});
  on("f_amin","input",e=>{filt.anoMin=e.target.value?+e.target.value:null;render();});
  on("f_amax","input",e=>{filt.anoMax=e.target.value?+e.target.value:null;render();});
  on("f_clear","click",()=>{filt={cli:"",anoMin:null,anoMax:null,ipc:"",sit:"",pais:""};
    segBar();render();});
}

function recorte(rows){
  const p=[];
  if(filt.cli)p.push(`cliente ~ "<b>${filt.cli}</b>"`);
  if(filt.sit!=="")p.push(`situação <b>${SIT_ROT[SIT[filt.sit]]}</b>`);
  if(filt.ipc)p.push(`IPC <b>${filt.ipc}</b>`);
  if(filt.pais)p.push(`prioridade <b>${filt.pais}</b>`);
  if(filt.anoMin||filt.anoMax)p.push(`depósito <b>${filt.anoMin||ANO_MIN}–${filt.anoMax||ANO_MAX}</b>`);
  const txt=p.length?`Recorte: ${p.join(" · ")} — <b>${fmt(rows.length)}</b> de ${fmt(L.length)} casos`
    :`Carteira completa — <b>${fmt(rows.length)}</b> casos`;
  document.getElementById("recorte").innerHTML=txt;
  document.getElementById("printRecorte").innerHTML=txt;
}

const iSit=s=>SIT.indexOf(s);
function kpis(rows){
  const n=rows.length;
  const conc=rows.filter(r=>r[C.conc]).length;
  const viva=rows.filter(r=>r[C.sit]===iSit("concedida_vigente")).length;
  const andamento=rows.filter(r=>r[C.sit]===iSit("em_andamento")).length;
  const arq=rows.filter(r=>r[C.sit]===iSit("arquivada")).length;
  const taxa=n?(100*conc/n).toFixed(1):"0";
  const pz=prazosFiltrados();
  const lim90=new Date(DATA.referencia);lim90.setDate(lim90.getDate()+90);
  const fatal=pz.filter(p=>p.fatal&&p.prazo<=lim90.toISOString().slice(0,10)).length;
  const compl=pz.filter(p=>p.status==="prazo_complementar_corrente").length;
  // dim/val -> card clicavel (toggle de situacao). Sem dim -> card de leitura.
  const cards=[
    {v:fmt(n),l:"casos no recorte"},
    {v:taxa+"%",l:"taxa de concessão"},
    {v:fmt(viva),l:"concedidas vigentes",dim:"sit",val:iSit("concedida_vigente")},
    {v:fmt(andamento),l:"em andamento",dim:"sit",val:iSit("em_andamento")},
    {v:fmt(arq),l:"arquivadas",cls:"warn",dim:"sit",val:iSit("arquivada")},
    {v:fmt(fatal),l:"exames/recursos FATAIS < 90d",cls:"risk"},
    {v:fmt(compl),l:"anuidades em prazo compl.",cls:"warn"},
    {v:fmt(pz.length),l:"prazos projetados 12m"},
  ];
  document.getElementById("kpis").innerHTML=cards.map(c=>{
    const on=c.dim&&String(filt[c.dim])===String(c.val);
    const cls=`kpi ${c.cls||""} ${c.dim?"click":""} ${on?"active":""}`;
    const at=c.dim?` role="button" tabindex="0" aria-pressed="${on}" data-dim="${c.dim}" data-val="${c.val}"`:"";
    return `<div class="${cls}"${at}><div class="v">${c.v}</div><div class="l">${c.l}</div></div>`;
  }).join("");
  document.querySelectorAll(".kpi.click").forEach(k=>{
    const fire=()=>toggle(k.dataset.dim,+k.dataset.val);
    k.onclick=fire;
    k.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();fire();}};
  });
}

// ---- Graficos ----
function baseChart(el,cfg){if(charts[el])charts[el].destroy();
  charts[el]=new Chart(document.getElementById(el),cfg);}
const gridOpt={grid:{color:"#eef2f6"},ticks:{color:"#64748b",font:{size:11}}};
const noLeg={legend:{display:false}};
// onClick generico: mapeia o elemento clicado -> valor da dimensao -> toggle.
function clickFilter(mapIdx){return (e,els)=>{if(els&&els.length)mapIdx(els[0].index);};}

function secoes(rows){
  const host=document.getElementById("secoes");
  if(!host.dataset.built){host.innerHTML=SECOES_HTML;host.dataset.built="1";}

  // 1. Depositos no tempo (linha) — eixo X dinamico ao recorte.
  const dep=contar(rows,C.anoDep);
  const dAnos=[...dep.keys()].filter(Boolean).sort((a,b)=>a-b);
  let lo=filt.anoMin||dAnos[0], hi=filt.anoMax||dAnos[dAnos.length-1];
  const ys=[];if(dAnos.length){for(let y=lo;y<=hi;y++)ys.push(y);}
  baseChart("cDep",{type:"line",data:{labels:ys,
    datasets:[{data:ys.map(y=>dep.get(y)||0),borderColor:AZUL,
      backgroundColor:"rgba(0,51,255,.10)",fill:true,tension:.3,pointRadius:0,borderWidth:2}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:noLeg,
      onClick:clickFilter(i=>toggle("ano",ys[i])),
      scales:{x:gridOpt,y:{...gridOpt,beginAtZero:true}}}});

  // 2. Situacao (donut) — clique filtra situacao.
  const st=contar(rows,C.sit);
  baseChart("cSit",{type:"doughnut",data:{labels:SIT.map(s=>SIT_ROT[s]),
    datasets:[{data:SIT.map((_,i)=>st.get(i)||0),hoverOffset:6,borderWidth:2,borderColor:"#fff",
      backgroundColor:SIT.map((s,i)=>filt.sit!==""&&i!==+filt.sit?SIT_COR[s]+"3d":SIT_COR[s])}]},
    options:{responsive:true,maintainAspectRatio:false,cutout:"58%",
      onClick:clickFilter(i=>toggle("sit",i)),
      plugins:{legend:{position:"right",labels:{font:{size:11},boxWidth:12,padding:8}}}}});

  // 3. IPC (barra) — cor por secao + clique filtra.
  const ip=contar(rows,C.ipc);
  const ipk=[...ip.keys()].filter(k=>k&&/[A-H]/.test(k)).sort();
  baseChart("cIpc",{type:"bar",data:{labels:ipk,
    datasets:[{data:ipk.map(k=>ip.get(k)),borderRadius:5,
      backgroundColor:ipk.map(k=>filt.ipc&&k!==filt.ipc?(IPC_COR[k]||AZUL)+"3d":(IPC_COR[k]||AZUL))}]},
    options:{responsive:true,maintainAspectRatio:false,
      onClick:clickFilter(i=>toggle("ipc",ipk[i])),
      plugins:{legend:{display:false},
        tooltip:{callbacks:{title:i=>IPC_ROT[i[0].label]||i[0].label}}},
      scales:{x:gridOpt,y:{...gridOpt,beginAtZero:true}}}});
  // legenda IPC (rótulos com cor) — HTML, fora do canvas
  document.getElementById("legIpc").innerHTML=ipk.map(k=>
    `<span class="lg"><i style="background:${IPC_COR[k]||AZUL}"></i>${IPC_ROT[k]}</span>`).join("");

  // 4. Pais prioridade (barra horizontal) — clique filtra.
  const pa=contar(rows,C.pais);
  const pak=[...pa.entries()].sort((a,b)=>b[1]-a[1]).slice(0,10);
  baseChart("cPais",{type:"bar",data:{labels:pak.map(e=>e[0]),
    datasets:[{data:pak.map(e=>e[1]),borderRadius:5,
      backgroundColor:pak.map(e=>filt.pais&&e[0]!==filt.pais?AZUL2+"3d":AZUL2)}]},
    options:{indexAxis:"y",responsive:true,maintainAspectRatio:false,plugins:noLeg,
      onClick:clickFilter(i=>toggle("pais",pak[i][0])),
      scales:{x:{...gridOpt,beginAtZero:true},y:gridOpt}}});

  // 5. Coorte de vigencia (barra) — dinamica ao recorte (usa anoFimVig do fato).
  const vg=contar(rows.filter(r=>r[C.anoFimVig]),C.anoFimVig);
  const vgk=[...vg.keys()].sort((a,b)=>a-b);
  baseChart("cVig",{type:"bar",data:{labels:vgk,
    datasets:[{data:vgk.map(k=>vg.get(k)),backgroundColor:MAGENTA,borderRadius:5}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:noLeg,
      scales:{x:gridOpt,y:{...gridOpt,beginAtZero:true}}}});

  // 6. Pareto clientes (barra + acumulada) — clique filtra o cliente.
  const cl=contar(rows,C.cli);
  const clk=[...cl.entries()].sort((a,b)=>b[1]-a[1]).slice(0,12);
  const tot=rows.length||1;let acc=0;const cum=clk.map(e=>{acc+=e[1];return (100*acc/tot).toFixed(1);});
  const nomes=clk.map(e=>CLI[e[0]]||"(s/ titular)");
  baseChart("cPar",{data:{labels:nomes.map(s=>s.slice(0,22)),
    datasets:[{type:"bar",data:clk.map(e=>e[1]),borderRadius:5,order:2,
      backgroundColor:nomes.map(nm=>filt.cli&&nm!==filt.cli?AZUL+"3d":AZUL)},
      {type:"line",data:cum,yAxisID:"y2",borderColor:MAGENTA,borderWidth:2,
       pointRadius:2,tension:.2,order:1}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:noLeg,
      onClick:clickFilter(i=>toggle("cli",nomes[i])),
      scales:{x:{...gridOpt,ticks:{...gridOpt.ticks,maxRotation:60,minRotation:45,font:{size:9}}},
        y:{...gridOpt,beginAtZero:true},
        y2:{position:"right",beginAtZero:true,max:100,grid:{display:false},
          ticks:{color:MAGENTA,callback:v=>v+"%"}}}}});

  insightCards(rows);
  insightFrases(rows);
  tabelaPrazos();
  renderTabelaClientes(rows);
}

// Dois "graficos fracos" viraram cards de insight.
function insightCards(rows){
  // Tempo ate concessao — DINAMICO ao recorte (mediana anoConc-anoDep).
  const difs=rows.filter(r=>r[C.conc]&&r[C.anoConc]&&r[C.anoDep]&&r[C.anoConc]>=r[C.anoDep])
    .map(r=>r[C.anoConc]-r[C.anoDep]).sort((a,b)=>a-b);
  const med=difs.length?difs[Math.floor(difs.length/2)]:null;
  document.getElementById("icConc").innerHTML=med==null
    ? `<div class="big">—</div><div class="cap">Nenhuma concessão neste recorte.</div>`
    : `<div class="big">${med}<small>anos</small></div>
       <div class="cap">Mediana do <b>depósito à concessão</b> (${fmt(difs.length)} concedidas no recorte).</div>
       <div class="sub2">Aproxima o backlog do INPI — quanto mais alto, mais lenta a concessão.</div>`;
  // Anuidades notificadas — serie histórica global (não está por caso).
  const an=DATA.anuidades_notificadas;
  const ult=an.length?an[an.length-1]:null;
  const tt=an.reduce((s,a)=>s+a.n,0);
  document.getElementById("icAnu").innerHTML=!ult
    ? `<div class="big">—</div>`
    : `<div class="big">${fmt(ult.n)}</div>
       <div class="cap">anuidades <b>notificadas</b> em ${ult.ano} — <b>notificadas, não pagas</b>.</div>
       <div class="sub2">${fmt(tt)} no histórico (despachos 21.x, carteira toda — não refiltra).</div>`;
}

// Insights curtos, redigidos, por seção — recomputam no filtro.
function insightFrases(rows){
  const n=rows.length||1;
  const dep=contar(rows,C.anoDep);
  const pico=[...dep.entries()].sort((a,b)=>b[1]-a[1])[0];
  document.getElementById("insDep").innerHTML=pico
    ? `Pico de <b>${fmt(pico[1])}</b> depósitos em <b>${pico[0]}</b>.`:"Sem depósitos no recorte.";
  const viva=rows.filter(r=>r[C.sit]===iSit("concedida_vigente")||r[C.sit]===iSit("em_andamento")).length;
  document.getElementById("insSit").innerHTML=
    `<b>${pct(viva/n)}%</b> da carteira segue viva (em andamento + concedida vigente).`;
  const ip=contar(rows,C.ipc);const ipTop=[...ip.entries()].sort((a,b)=>b[1]-a[1])[0];
  document.getElementById("insIpc").innerHTML=ipTop
    ? `Seção <b>${IPC_ROT[ipTop[0]]||ipTop[0]}</b> lidera com <b>${fmt(ipTop[1])}</b> casos.`:"";
  const estr=rows.filter(r=>r[C.pais]).length;
  const pa=contar(rows,C.pais);const paTop=[...pa.entries()].sort((a,b)=>b[1]-a[1])[0];
  document.getElementById("insPais").innerHTML=paTop
    ? `<b>${pct(estr/n)}%</b> têm prioridade estrangeira · <b>${paTop[0]}</b> no topo (${fmt(paTop[1])}).`
    : "Nenhuma prioridade unionista no recorte.";
  const ref=+DATA.referencia.slice(0,4);
  const exp5=rows.filter(r=>r[C.anoFimVig]&&r[C.anoFimVig]<=ref+5).length;
  document.getElementById("insVig").innerHTML=
    `<b>${fmt(exp5)}</b> patentes vivas expiram até <b>${ref+5}</b> (perda de exclusividade).`;
  const cl=contar(rows,C.cli);const cls=[...cl.values()].sort((a,b)=>b-a);
  const top10=cls.slice(0,10).reduce((s,x)=>s+x,0);
  document.getElementById("insCli").innerHTML=
    `Top 10 clientes = <b>${pct(top10/n)}%</b> da carteira · <b>${fmt(cls.length)}</b> titulares no recorte.`;
}

const SECOES_HTML=`
<div class="grid2">
 <section><h2>Depósitos no tempo</h2><p class="sub" id="insDep"></p>
   <div class="chart-box"><canvas id="cDep"></canvas></div></section>
 <section><h2>Situação da carteira</h2><p class="sub" id="insSit"></p>
   <div class="chart-box"><canvas id="cSit"></canvas></div></section>
</div>
<div class="grid2">
 <section><h2>Classificação técnica (IPC)</h2><p class="sub" id="insIpc"></p>
   <div class="chart-box"><canvas id="cIpc"></canvas></div>
   <div class="legend" id="legIpc"></div></section>
 <section><h2>País de prioridade</h2><p class="sub" id="insPais"></p>
   <div class="chart-box"><canvas id="cPais"></canvas></div></section>
</div>
<div class="grid2">
 <section><h2>Tempo até concessão</h2><div class="icard" id="icConc"></div></section>
 <section><h2>Anuidades notificadas</h2><div class="icard" id="icAnu"></div></section>
</div>
<div class="grid2">
 <section><h2>Coorte de vigência</h2><p class="sub" id="insVig"></p>
   <div class="chart-box"><canvas id="cVig"></canvas></div></section>
 <section><h2>Concentração de clientes</h2><p class="sub" id="insCli"></p>
   <div class="chart-box"><canvas id="cPar"></canvas></div></section>
</div>
<section><h2>Prazos projetados — próximos 12 meses</h2>
  <p class="sub">Projeção sob a LPI (arts. 33/40/84/212). Lista de conferência contra o
    docketing — não é fatura.</p>
  <div class="aviso">Prazo <b>calculado</b>, não consultado. O INPI publica consequência,
    não vencimento futuro; pagamento em dia não gera despacho. Confira na GRU e no
    controle de prazos.</div>
  <div id="tblPrazos"></div></section>
<section><h2>Clientes da carteira</h2>
  <p class="sub" id="insCli2">Titulares no recorte, por volume de casos</p>
  <div id="tblCli"></div></section>`;

// ---- Tabelas ----
function tabelaPrazos(){
  const P=prazosFiltrados().map(p=>[p.numero_inpi,p.cliente,p.tipo,p.descricao,p.prazo,
    p.status,p.fatal?"FATAL":""]);
  autoTable("tblPrazos",
    ["Processo","Cliente","Tipo","Descrição","Prazo","Situação","Alerta"],P,
    {6:v=>v==="FATAL"?'<span class="tag fatal">FATAL</span>':"",
     0:v=>`<span class="num">${v}</span>`,4:v=>`<span class="num">${v}</span>`},[4,"asc"]);
}
function renderTabelaClientes(rows){
  const m=contar(rows,C.cli);
  const cliRows=[...m.entries()].sort((a,b)=>b[1]-a[1])
    .map(e=>[CLI[e[0]]||"(sem titular)",e[1]]);
  autoTable("tblCli",["Cliente / titular","Casos"],cliRows,
    {1:v=>`<span class="num">${fmt(v)}</span>`},[1,"desc"]);
}

// Funil SVG (afford de filtro explicito, sempre visivel no header).
const FUNNEL='<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">'+
  '<path d="M1.5 2h13l-5.2 6.1V14L6.7 12V8.1z" fill="currentColor"/></svg>';

// Tabela: ordenar (label) + filtrar (funil dedicado, popup busca+checkboxes) + paginacao.
function autoTable(elId,cols,rows,fmts,defSort){
  const st={sort:defSort||[0,"asc"],page:0,per:12,af:{}};
  const el=document.getElementById(elId);
  function dados(){
    let r=rows.filter(row=>cols.every((_,i)=>{
      const f=st.af[i];if(!f||!f.size)return true;return f.has(String(row[i]));}));
    const[si,sd]=st.sort;
    return r.slice().sort((a,b)=>{let x=a[si],y=b[si];
      if(typeof x==="number"&&typeof y==="number")return sd==="asc"?x-y:y-x;
      x=String(x);y=String(y);return sd==="asc"?x.localeCompare(y,"pt"):y.localeCompare(x,"pt");});
  }
  function view(){
    const r=dados();
    const pages=Math.max(1,Math.ceil(r.length/st.per));
    st.page=Math.min(st.page,pages-1);
    const slice=r.slice(st.page*st.per,st.page*st.per+st.per);
    const head=cols.map((c,i)=>{
      const ar=st.sort[0]==i?(st.sort[1]==="asc"?"▲":"▼"):"";
      const on=st.af[i]&&st.af[i].size?" on":"";
      return `<th><div class="th-in">
        <span class="th-lbl" data-sort="${i}">${c}<span class="ar">${ar}</span></span>
        <button class="fn${on}" data-af="${i}" aria-label="Filtrar ${c}">${FUNNEL}</button>
      </div></th>`;}).join("");
    el.innerHTML=`<div style="overflow-x:auto"><table><thead><tr>${head}</tr></thead>
      <tbody>${slice.map(row=>`<tr>${row.map((v,i)=>{
        const cell=fmts&&fmts[i]?fmts[i](v):v;
        const cls=(typeof v==="number")?' class="n"':"";
        return `<td${cls}>${cell}</td>`;}).join("")}</tr>`).join("")}</tbody></table></div>
      <div class="tbl-foot"><span>${fmt(r.length)} linhas</span>
      <div class="pg"><button ${st.page<=0?"disabled":""} data-pg="p">‹</button>
      <span>${st.page+1}/${pages}</span>
      <button ${st.page>=pages-1?"disabled":""} data-pg="n">›</button></div></div>`;
    el.querySelectorAll(".th-lbl").forEach(s=>s.onclick=()=>{
      const i=+s.dataset.sort;
      st.sort=[i,st.sort[0]==i&&st.sort[1]==="asc"?"desc":"asc"];view();});
    el.querySelectorAll(".fn").forEach(b=>b.onclick=e=>{e.stopPropagation();
      openAF(b,+b.dataset.af);});
    el.querySelectorAll("[data-pg]").forEach(b=>b.onclick=()=>{
      st.page+=b.dataset.pg==="n"?1:-1;view();});
  }
  function openAF(btn,i){
    const aberto=document.querySelector(".af");
    document.querySelectorAll(".af").forEach(x=>x.remove());
    if(aberto&&aberto.dataset.col==i){return;}  // segundo clique fecha
    const vals=[...new Set(rows.map(r=>String(r[i])))]
      .sort((a,b)=>a.localeCompare(b,"pt",{numeric:true}));
    const cur=st.af[i]||new Set();
    const af=document.createElement("div");af.className="af";af.dataset.col=i;
    af.innerHTML=`<input class="q" placeholder="buscar valor...">
      <div class="af-tools"><button class="all">Todos</button><button class="none">Nenhum</button></div>
      <div class="vals">${vals.map(v=>`<label><input type="checkbox" value="${v.replace(/"/g,"&quot;")}"
        ${cur.size===0||cur.has(v)?"checked":""}><span>${v||"(vazio)"}</span></label>`).join("")}</div>
      <div class="act"><button class="ok">Aplicar</button><button class="cl">Limpar filtro</button></div>`;
    btn.parentNode.appendChild(af);
    af.querySelector(".q").oninput=e=>{const q=e.target.value.toLowerCase();
      af.querySelectorAll(".vals label").forEach(l=>l.style.display=
        l.textContent.toLowerCase().includes(q)?"":"none");};
    const boxes=()=>[...af.querySelectorAll('.vals label:not([style*="none"]) input')];
    af.querySelector(".all").onclick=()=>boxes().forEach(c=>c.checked=true);
    af.querySelector(".none").onclick=()=>boxes().forEach(c=>c.checked=false);
    af.querySelector(".ok").onclick=()=>{
      const sel=[...af.querySelectorAll("input[type=checkbox]:checked")].map(c=>c.value);
      st.af[i]=sel.length===vals.length?null:new Set(sel);st.page=0;af.remove();view();};
    af.querySelector(".cl").onclick=()=>{st.af[i]=null;af.remove();view();};
    af.querySelector(".q").focus();
    af.onclick=e=>e.stopPropagation();
  }
  view();
}
document.addEventListener("click",e=>{
  if(!e.target.closest(".af")&&!e.target.closest(".fn"))
    document.querySelectorAll(".af").forEach(x=>x.remove());});

function render(){const rows=filtra();recorte(rows);kpis(rows);secoes(rows);}
segBar();render();
"""
