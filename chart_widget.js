/* ═══════════════════════════════════════════════════════════════
   chart_widget.js — componente grafico condiviso per etp
   Adattato da raptor-one/index.html (blocco CHART), v1 "solo dati
   precalcolati": timeframe giornalieri (1s/1m/3m/6m/1a), nessun
   fallback fetch live (Stooq/Yahoo), nessuna modalita' intraday
   (5h/1g) in questa prima versione.

   Uso: la pagina host deve definire `const CHART_BASE = '...';`
   PRIMA di caricare questo script, puntato alla propria cartella
   data/charts/ (es. 'data/charts/' per index.html/linea.html di etp).
   Poi richiama window.openChartModal(ticker, nomeVisualizzato).
   ═══════════════════════════════════════════════════════════════ */


// ═══ VARIABILI GLOBALI E COSTANTI SEGNALI ═══
let chartInstances={}, currentTF='1m', currentSym='', currentSrc='yahoo';
let chartJsonCache=null;
let chartIndexCache=null;

// ═══ SEGNALI CONFIG ═══
const SIG_ICON = {
  BUY1:'🟢 BUY1', BUY2:'🔵 BUY2', BUY3:'💎 BUY3',
  EXIT1:'🟡 EXIT1', EXIT2:'🔴 EXIT2',
  'MEAN REV':'🟠 MR', WATCH:'⚪ WATCH',
};
const SIG_COLOR = {
  BUY1:'#1a7f37', BUY2:'#0969da', BUY3:'#6e40c9',
  EXIT1:'#bc4c00', EXIT2:'#cf222e',
  'MEAN REV':'#bc4c00', WATCH:'#57606a',
};
const SIG_BG = {
  BUY1:'#dafbe1', BUY2:'#ddf4ff', BUY3:'#f0ebff',
  EXIT1:'#fff1e5', EXIT2:'#ffebe9',
  'MEAN REV':'#fff1e5', WATCH:'#f5f7fa',
};

// ═══ FETCH DATI DA data/charts/ ═══
async function getChartIndex(){
  if(chartIndexCache)return chartIndexCache;
  const res=await fetch(CHART_BASE+'index.json?t='+Date.now(),{signal:AbortSignal.timeout(8000)});
  if(!res.ok)throw new Error('HTTP '+res.status);
  chartIndexCache=await res.json();
  return chartIndexCache;
}

async function getTickerChartJson(sym){
  if(chartJsonCache&&chartJsonCache.__sym===sym)return chartJsonCache;
  const idx=await getChartIndex();
  const entry=(idx.index||[]).find(e=>e.y.toLowerCase()===sym.toLowerCase()||e.t.toLowerCase()===sym.toLowerCase());
  if(!entry)throw new Error('Ticker non presente in data/charts/');
  const res=await fetch(CHART_BASE+entry.f+'?t='+Date.now(),{signal:AbortSignal.timeout(8000)});
  if(!res.ok)throw new Error('HTTP '+res.status);
  const text=await res.text();
  if(!text.trim().startsWith('{'))throw new Error('JSON non valido: '+text.slice(0,40));
  chartJsonCache=JSON.parse(text);
  chartJsonCache.__sym=sym;
  return chartJsonCache;
}

function fmtLabel(ts,tf){
  const d=new Date(ts*1000);
  if(tf==='5h'||tf==='1d')return d.getHours()+':'+(d.getMinutes().toString().padStart(2,'0'));
  if(tf==='1w'||tf==='1m')return d.getDate()+'/'+(d.getMonth()+1);
  return d.getDate()+'/'+(d.getMonth()+1)+'/'+d.getFullYear().toString().slice(2);
}

// ═══ MODALE — creazione DOM on-demand (idempotente) ═══
function ensureChartModalDOM(){
  if(document.getElementById('cwModalOverlay')) return;

  const css = document.createElement('style');
  css.textContent = `
#cwModalOverlay{display:none;position:fixed;inset:0;background:rgba(15,20,25,.55);z-index:9999;overflow-y:auto;padding:24px 12px}
#cwModal{background:#fff;max-width:1100px;margin:0 auto;border-radius:10px;overflow:hidden;box-shadow:0 24px 80px rgba(0,0,0,.35);font-family:'Segoe UI',sans-serif}
#cwChartHeader{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:12px 16px;border-bottom:1px solid #d0d7de;background:#fbfcfd}
#cwChartTitle{font-size:15px;font-weight:700;color:#1f2328}
#cwChartSub{font-size:12px;color:#57606a}
.cw-tf-btn{border:1px solid #d0d7de;background:#fff;color:#57606a;font-size:12px;padding:5px 10px;border-radius:6px;cursor:pointer}
.cw-tf-btn.active{background:#0969da;border-color:#0969da;color:#fff}
#cwInfoBar{display:grid;grid-template-columns:repeat(auto-fit,minmax(90px,1fr));gap:8px;padding:12px 16px;background:#fff;border-bottom:1px solid #d0d7de}
.cw-info-card{border:1px solid #eef0f3;border-radius:8px;padding:8px 10px;background:#fbfcfd}
.cw-info-card .lbl{font-size:10px;color:#8b949e;text-transform:uppercase;letter-spacing:.03em}
.cw-info-card .val{font-size:15px;font-weight:700;color:#1f2328;margin:2px 0}
.cw-info-card .sub{font-size:10px;color:#57606a}
#cwStoriaWrap{padding:12px 16px;border-bottom:1px solid #d0d7de}
#cwStoriaTitle{font-size:12px;font-weight:700;color:#1f2328;margin-bottom:6px}
#cwStoriaTable{width:100%;border-collapse:collapse;font-size:11px}
#cwStoriaTable th{text-align:left;color:#8b949e;font-weight:600;padding:4px 6px;border-bottom:1px solid #eef0f3}
#cwStoriaTable td{padding:4px 6px;border-bottom:1px solid #f6f8fa;color:#1f2328}
#cwChartSvgWrap{width:100%;overflow-x:auto;background:#fff;padding:0 16px 16px}
#cwLoadOverlay{display:none;position:absolute;inset:0;background:rgba(255,255,255,.85);align-items:center;justify-content:center;flex-direction:column;gap:8px;z-index:2}
.cw-spinner{width:28px;height:28px;border:3px solid #d0d7de;border-top-color:#0969da;border-radius:50%;animation:cwspin .8s linear infinite}
@keyframes cwspin{to{transform:rotate(360deg)}}
#cwCloseBtn{margin-left:auto;background:#ffebe9;border:1px solid #cf222e;color:#cf222e;border-radius:6px;padding:5px 10px;font-size:12px;cursor:pointer}
`;
  document.head.appendChild(css);

  const overlay = document.createElement('div');
  overlay.id = 'cwModalOverlay';
  overlay.innerHTML = `
    <div id="cwModal">
      <div style="position:relative">
        <div id="cwChartHeader">
          <div><div id="cwChartTitle">—</div><div id="cwChartSub"></div></div>
          <div style="flex:1"></div>
          <button class="cw-tf-btn" data-tf="1w" onclick="cwSetTF(this)">1s</button>
          <button class="cw-tf-btn active" data-tf="1m" onclick="cwSetTF(this)">1m</button>
          <button class="cw-tf-btn" data-tf="3m" onclick="cwSetTF(this)">3m</button>
          <button class="cw-tf-btn" data-tf="6m" onclick="cwSetTF(this)">6m</button>
          <button class="cw-tf-btn" data-tf="1y" onclick="cwSetTF(this)">1a</button>
          <button class="cw-tf-btn" data-tf="2y" onclick="cwSetTF(this)">2a</button>
          <button id="cwCloseBtn" onclick="closeChartModal()">✕ Chiudi</button>
        </div>
        <div id="cwInfoBar">
          <div class="cw-info-card"><div class="lbl">Segnale</div><div class="val" id="ic-sig">—</div><div class="sub" id="ic-mr">—</div></div>
          <div class="cw-info-card"><div class="lbl">Prezzo</div><div class="val" id="ic-price">—</div><div class="sub" id="ic-chg">—</div></div>
          <div class="cw-info-card"><div class="lbl">KAMA</div><div class="val" id="ic-kama">—</div><div class="sub" id="ic-kgap">—</div></div>
          <div class="cw-info-card"><div class="lbl">SAR</div><div class="val" id="ic-sar">—</div><div class="sub" id="ic-sarlbl">—</div></div>
          <div class="cw-info-card"><div class="lbl">ER</div><div class="val" id="ic-er">—</div><div class="sub" id="ic-erlbl">—</div></div>
          <div class="cw-info-card"><div class="lbl">RSI(14)</div><div class="val" id="ic-rsi">—</div><div class="sub" id="ic-rsilbl">—</div></div>
          <div class="cw-info-card"><div class="lbl">Baffetti</div><div class="val" id="ic-baff">—</div><div class="sub" id="ic-bafflbl">—</div></div>
          <div class="cw-info-card"><div class="lbl">AO↑</div><div class="val" id="ic-ao">—</div><div class="sub" id="ic-aolbl">—</div></div>
          <div class="cw-info-card"><div class="lbl">Trendycator</div><div class="val" id="ic-trend">—</div><div class="sub" style="font-size:9px;color:#aaa">solo info</div></div>
          <div class="cw-info-card"><div class="lbl">ATR(14)</div><div class="val" id="ic-atr">—</div><div class="sub" id="ic-atrpct">—</div></div>
          <div class="cw-info-card"><div class="lbl">Trail Stop</div><div class="val" id="ic-trail">—</div><div class="sub" id="ic-trailpct">—</div></div>
          <div class="cw-info-card" id="ic-mlexit-card" style="display:none;border-color:#6e40c9">
            <div class="lbl" style="color:#6e40c9">🎯 Uscita ML</div>
            <div class="val" id="ic-mlexit" style="color:#6e40c9">—</div>
            <div class="sub" id="ic-mlexitlbl">—</div>
          </div>
        </div>
        <div id="cwStoriaWrap">
          <div id="cwStoriaTitle">📊 Storia segnali — ultime barre</div>
          <table id="cwStoriaTable">
            <thead><tr>
              <th>#</th><th>Data Entrata</th><th>Data Uscita</th><th>Segnale</th>
              <th>Prezzo Entrata</th><th>Prezzo Uscita</th><th>Δ%</th><th>Giorni</th><th>Note</th>
            </tr></thead>
            <tbody id="storiaBody"></tbody>
          </table>
        </div>
        <div id="cwChartSvgWrap"><div id="chartSvgWrap" style="width:100%;overflow-x:auto;background:#fff"></div></div>
        <div id="cwLoadOverlay"><div class="cw-spinner"></div><div id="loadMsg">Caricamento...</div></div>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.addEventListener('click', e=>{ if(e.target===overlay) closeChartModal(); });

  // Alias richiesti dal codice ereditato da raptor-one (usa questi ID)
  window.__cwAlias = true;
  document.getElementById('chartTitle') || (overlay.querySelector('#cwChartTitle').id='chartTitle');
  document.getElementById('chartSub') || (overlay.querySelector('#cwChartSub').id='chartSub');
  document.getElementById('loadOverlay') || (overlay.querySelector('#cwLoadOverlay').id='loadOverlay');
}

// ═══ APERTURA / CHIUSURA MODALE ═══
function openChartModal(sym, name){
  ensureChartModalDOM();
  currentSym = sym; currentTF = '1m';
  document.getElementById('cwModalOverlay').style.display = 'block';
  document.getElementById('chartTitle').textContent = sym + (name && name!==sym ? ' — ' + name : '');
  document.querySelectorAll('.cw-tf-btn').forEach(b=>b.classList.toggle('active', b.dataset.tf==='1m'));
  loadChartData(sym, '1m');
}

function closeChartModal(){
  const ov = document.getElementById('cwModalOverlay');
  if(ov) ov.style.display = 'none';
}

function cwSetTF(btn){
  document.querySelectorAll('.cw-tf-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  currentTF = btn.dataset.tf;
  document.getElementById('loadOverlay').style.display = 'flex';
  document.getElementById('loadMsg').textContent = 'Caricamento...';
  loadChartData(currentSym, currentTF);
}

// ═══ TIMEFRAME (v1: solo giornalieri — 5h/1g intraday non ancora supportati) ═══
function tfParams(tf){
  if(tf==='1w')return{hourly:false,n:5};
  if(tf==='1m')return{hourly:false,n:21};
  if(tf==='3m')return{hourly:false,n:63};
  if(tf==='6m')return{hourly:false,n:126};
  if(tf==='2y')return{hourly:false,n:502};
  return{hourly:false,n:252};
}

// ═══ CARICAMENTO DATI — v1: solo data/charts/ precalcolato, nessun fallback live ═══
async function loadChartData(sym, tf){
  try{
    const p = tfParams(tf);
    let bars=[], pre=null, renko=null, renkoBrick=null, mlExit=null;

    const j = await getTickerChartJson(sym);
    const raw = j.d || [];
    bars = raw.slice(-p.n);

    if(bars.length < 10){
      throw new Error('Dati insufficienti in data/charts/ per questo ETF (storico troppo corto)');
    }

    document.getElementById('chartSub').textContent = 'data/charts · ' + new Date().toLocaleDateString('it-IT');
    const src_ind = {kama:j.kama_d, sar:j.sar_d, sarBull:j.sarBull_d, ao:j.ao_d, rsi:j.rsi_d,
                      rsi5:j.rsi5_d, baff:j.baff_d, segnale:j.segnale_d, er:j.er_d,
                      cross:j.crossDays_d, mmAlign:j.mmAlign_d, sarStreak:j.sarStreak_d};
    if(src_ind.kama && src_ind.kama.length){
      const off = src_ind.kama.length - bars.length;
      pre = {};
      Object.keys(src_ind).forEach(k=>{ if(src_ind[k]) pre[k]=src_ind[k].slice(Math.max(0,off)); });
    }
    renko = j.renko || []; renkoBrick = j.renko_brick || null; mlExit = j.ml_exit || null;

    let c=[],h=[],l=[],v=[],t=[];
    bars.forEach(b=>{ t.push(b[0]); c.push(b[4]); h.push(b[2]); l.push(b[3]); v.push(b[5]||0); });

    if(pre && pre.segnale){
      renderStoriaFromPrecomputed(t,c,pre.segnale,pre.er,pre.baff,pre.rsi,pre.ao,pre.cross,pre.mmAlign,pre.sarStreak,mlExit);
    }else if(raw.length>=60){
      renderStoria(calcStoriaFromBars(raw));
    }

    document.getElementById('loadOverlay').style.display = 'none';
    setTimeout(()=>{ renderChartSVG(c,h,l,v,t,tf,pre,renko,renkoBrick,mlExit); }, 30);
  }catch(e){
    document.getElementById('loadOverlay').style.display = 'none';
    const wrap = document.getElementById('chartSvgWrap');
    if(wrap) wrap.innerHTML = '<div style="padding:40px;text-align:center;color:#cf222e;font-size:14px">Errore caricamento: '+e.message+'</div>';
    const sb = document.getElementById('storiaBody');
    if(sb) sb.innerHTML = '<tr><td colspan="9" style="color:#57606a;padding:12px">Dati non disponibili</td></tr>';
    document.getElementById('chartSub').textContent = 'Errore: ' + e.message;
  }
}


// ═══ INDICATORI TECNICI (per header info-bar, calcolati dai bar caricati) ═══
// ═══ INDICATORI BROWSER (per storia segnali) ═══
function sma(arr,n){return arr.map((_,i)=>i<n-1?null:arr.slice(i-n+1,i+1).reduce((a,b)=>a+(b||0),0)/n);}
function emaArr(arr,p){const k=2/(p+1);const out=[arr[0]];for(let i=1;i<arr.length;i++)out.push(arr[i]*k+out[i-1]*(1-k));return out;}

function calcKAMA(close,n=10,fast=2,slow=30){
  const fsc=2/(fast+1),ssc=2/(slow+1);
  const kama=new Array(close.length).fill(null);
  if(close.length<=n)return kama;
  kama[n]=close[n];
  for(let i=n+1;i<close.length;i++){
    const dir=Math.abs(close[i]-close[i-n]);
    let noise=0;for(let j=i-n+1;j<=i;j++)noise+=Math.abs(close[j]-close[j-1]);
    const er=noise===0?0:dir/noise;
    const sc=Math.pow(er*(fsc-ssc)+ssc,2);
    kama[i]=kama[i-1]+sc*(close[i]-kama[i-1]);
  }
  return kama;
}

function calcSAR(high,low,af0=0.02,afMax=0.20){
  if(high.length<5)return{sar:new Array(high.length).fill(null),bull:new Array(high.length).fill(true)};
  const sarArr=new Array(high.length).fill(null);
  const bullArr=new Array(high.length).fill(true);
  let sar=low[0],ep=high[0],af=af0,bull=true;
  sarArr[0]=sar;bullArr[0]=bull;
  for(let i=1;i<high.length;i++){
    let newSar;
    if(bull){
      newSar=sar+af*(ep-sar);
      newSar=Math.min(newSar,low[Math.max(0,i-1)],low[Math.max(0,i-2)]);
      if(low[i]<newSar){bull=false;newSar=ep;ep=low[i];af=af0;}
      else if(high[i]>ep){ep=high[i];af=Math.min(af+af0,afMax);}
    }else{
      newSar=sar+af*(ep-sar);
      newSar=Math.max(newSar,high[Math.max(0,i-1)],high[Math.max(0,i-2)]);
      if(high[i]>newSar){bull=true;newSar=ep;ep=high[i];af=af0;}
      else if(low[i]<ep){ep=low[i];af=Math.min(af+af0,afMax);}
    }
    sar=newSar;sarArr[i]=sar;bullArr[i]=bull;
  }
  return{sar:sarArr,bull:bullArr};
}

function calcAOArray(high,low){
  const mid=high.map((h,i)=>(h+low[i])/2);
  const s5=sma(mid,5),s34=sma(mid,34);
  return s5.map((v,i)=>v!==null&&s34[i]!==null?v-s34[i]:null);
}

function calcBaf(ao){
  let b=0;
  for(let i=ao.length-1;i>0;i--){
    if(ao[i]!==null&&ao[i-1]!==null&&ao[i]>ao[i-1])b++;else break;
  }
  return b;
}

function calcER(close,n=10){
  if(close.length<n+1)return 0;
  const dir=Math.abs(close[close.length-1]-close[close.length-1-n]);
  let noise=0;
  for(let i=close.length-n;i<close.length;i++)noise+=Math.abs(close[i]-close[i-1]);
  return noise===0?0:dir/noise;
}

function calcRSI(close,n=14){
  if(close.length<n+1)return null;
  let g=0,l=0;
  for(let i=close.length-n;i<close.length;i++){const d=close[i]-close[i-1];if(d>0)g+=d;else l-=d;}
  const ag=g/n,al=l/n;return al===0?100:100-(100/(1+ag/al));
}

function calcMmAlign(close){
  if(close.length<100)return false;
  const mm20=close.slice(-20).reduce((a,b)=>a+b,0)/20;
  const mm50=close.slice(-50).reduce((a,b)=>a+b,0)/50;
  const mm100=close.slice(-100).reduce((a,b)=>a+b,0)/100;
  return close[close.length-1]>mm20&&mm20>mm50&&mm50>mm100;
}

function calcCrossKAMA(close,kama){
  for(let i=close.length-1;i>0;i--){
    if(kama[i]!=null&&kama[i-1]!=null&&close[i]>kama[i]&&close[i-1]<=kama[i-1])return close.length-1-i;
    if(kama[i]!=null&&kama[i-1]!=null&&close[i]<kama[i]&&close[i-1]>=kama[i-1])return close.length-1-i;
  }
  return 999;
}

// ═══ CALCOLA SEGNALE (browser) ═══
function calcSegnale(close,kama,sar,sarBull,ao,er,baff,mmAlign,rsi){
  const lk=kama[kama.length-1],lc=close[close.length-1];
  if(lk==null)return'WATCH';
  const aboveKama=lc>lk;
  const cross=calcCrossKAMA(close,kama);
  const aoArr=[...ao].filter(v=>v!=null);
  const aoImproving=aoArr.length>=2&&aoArr[aoArr.length-1]>aoArr[aoArr.length-2];
  const nearKama=lk>0&&Math.abs(lc-lk)/lk<0.03;

  if(sarBull&&cross<=3&&aoImproving)return'BUY1';
  if(aboveKama&&baff>=2)return'BUY2';
  if(aboveKama&&er>=0.50&&baff>=3&&mmAlign)return'BUY3';
  if(!aboveKama&&!sarBull)return'EXIT2';
  if(!sarBull)return'EXIT1';
  if(er<0.30&&rsi<30&&aoImproving&&(nearKama||!aboveKama))return'MEAN REV';
  return'WATCH';
}

// ═══ STORIA SEGNALI — note dinamiche dai valori reali degli indicatori ═══
function buildSignalNote(tier, ctx){
  const er=ctx.er, baff=ctx.baff, rsi=ctx.rsi, cross=ctx.cross, sarStreak=ctx.sarStreak, mmAlign=ctx.mmAlign;
  const erPct=er!=null?Math.round(er*100):null;
  switch(tier){
    case 'BUY1':
      return `SAR rialzista da ${sarStreak!=null?sarStreak:'?'}gg, incrocio KAMA ${cross!=null?cross:'?'}gg fa, AO in miglioramento`;
    case 'BUY2':
      return `Prezzo sopra KAMA, baffetti=${baff!=null?baff:'?'} barre consecutive in salita`;
    case 'BUY3':
      return `ER=${erPct!=null?erPct+'%':'?'} (forte), baffetti=${baff!=null?baff:'?'}, medie mobili allineate, sopra KAMA`;
    case 'EXIT1':
      return `SAR passato ribassista da ${sarStreak!=null?sarStreak:'?'}gg`;
    case 'EXIT2':
      return `Prezzo sotto KAMA e SAR ribassista`;
    case 'MEAN REV':
      return `ER basso (${erPct!=null?erPct+'%':'?'}), RSI ipervenduto (${rsi!=null?Math.round(rsi):'?'}), AO in miglioramento`;
    case 'WATCH':
      return 'Nessuna condizione di ingresso attiva';
    default:
      return '—';
  }
}

const BUY_TIERS=['BUY1','BUY2','BUY3'];
const EXIT_TIERS=['EXIT1','EXIT2'];

function fmtDataIt(ts){
  const d=new Date(ts*1000);
  return d.getDate().toString().padStart(2,'0')+'/'+(d.getMonth()+1).toString().padStart(2,'0')+'/'+d.getFullYear();
}

/** Accoppia ogni ingresso BUY1/2/3 con la sua uscita EXIT1/2 (o "ancora aperta" se non trovata),
    costruendo una riga-trade con note dinamiche calcolate sui valori reali degli indicatori. */
function buildTrades(ts, closes, segArr, erArr, baffArr, rsiArr, aoArr, crossArr, mmArr, sarStreakArr, mlExit){
  const trades=[];
  const n=segArr.length;
  let i=0, prevSeg=null;
  const ctxAt=(idx)=>({
    er: erArr?erArr[idx]:null, baff: baffArr?baffArr[idx]:null, rsi: rsiArr?rsiArr[idx]:null,
    ao: aoArr?aoArr[idx]:null, cross: crossArr?crossArr[idx]:null,
    mmAlign: mmArr?mmArr[idx]:null, sarStreak: sarStreakArr?sarStreakArr[idx]:null,
  });
  while(i<n){
    const seg=segArr[i];
    if(BUY_TIERS.includes(seg) && seg!==prevSeg){
      const entryIdx=i, entryTier=seg;
      let exitIdx=null, exitTier=null;
      let j=i+1;
      while(j<n){ if(EXIT_TIERS.includes(segArr[j])){exitIdx=j; exitTier=segArr[j]; break;} j++; }
      const entryPrice=closes[entryIdx];
      const isOpen=exitIdx===null;
      const exitPrice=isOpen?closes[n-1]:closes[exitIdx];
      const deltaPct=entryPrice?((exitPrice/entryPrice-1)*100):null;
      let exitNote;
      if(!isOpen){
        exitNote=buildSignalNote(exitTier, ctxAt(exitIdx));
      }else if(mlExit){
        const sign=mlExit.peak_return_pct>=0?'+':'';
        exitNote=`Posizione ancora aperta — 🎯 ML: picco atteso ${sign}${mlExit.peak_return_pct.toFixed(1)}%, di solito entro ${Math.round(mlExit.days_to_peak)}gg`;
      }else{
        exitNote='Posizione ancora aperta';
      }
      trades.push({
        entryDate: fmtDataIt(ts[entryIdx]), exitDate: isOpen?null:fmtDataIt(ts[exitIdx]),
        entryTier, exitTier, entryPrice, exitPrice,
        deltaPct, days: (isOpen?n-1:exitIdx)-entryIdx, isOpen,
        entryNote: buildSignalNote(entryTier, ctxAt(entryIdx)),
        exitNote,
      });
      i = isOpen? n : exitIdx+1;
      prevSeg = isOpen? seg : exitTier;
      continue;
    }
    prevSeg=seg; i++;
  }
  return trades.reverse().slice(0,20);
}

// ═══ STORIA SEGNALI ═══
function calcStoriaFromBars(bars){
  if(!bars||bars.length<60)return[];
  const c=bars.map(b=>b[4]), h=bars.map(b=>b[2]), l=bars.map(b=>b[3]), ts=bars.map(b=>b[0]);
  const kama=calcKAMA(c);
  const {sar:sarArr,bull:sarBull}=calcSAR(h,l);
  const ao=calcAOArray(h,l);
  const n=c.length;
  const segArr=new Array(n).fill(null), erArr=new Array(n).fill(null), baffArr=new Array(n).fill(null),
        rsiArr=new Array(n).fill(null), crossArr=new Array(n).fill(null), mmArr=new Array(n).fill(null),
        sarStreakArr=new Array(n).fill(0);
  let lastBull=null;
  for(let i=60;i<n;i++){
    const sc=c.slice(0,i+1), sh=h.slice(0,i+1), sl=l.slice(0,i+1), sk=kama.slice(0,i+1), sao=ao.slice(0,i+1);
    const er=calcER(sc), baff=calcBaf(sao), rsi=calcRSI(sc)||50, mmAlign=calcMmAlign(sc);
    segArr[i]=calcSegnale(sc,sk,sarArr[i],sarBull[i],sao,er,baff,mmAlign,rsi);
    erArr[i]=er; baffArr[i]=baff; rsiArr[i]=rsi; mmArr[i]=mmAlign;
    sarStreakArr[i]= (lastBull===sarBull[i]) ? (sarStreakArr[i-1]||0)+1 : 0;
    lastBull=sarBull[i];
    // giorni dall'ultimo incrocio KAMA
    let cross=0;
    for(let k=i;k>0;k--){ if((c[k]>kama[k])!==(c[k-1]>kama[k-1]))break; cross++; }
    crossArr[i]=cross;
  }
  return buildTrades(ts,c,segArr,erArr,baffArr,rsiArr,ao,crossArr,mmArr,sarStreakArr);
}

function renderStoriaFromPrecomputed(ts,closes,segArr,erArr,baffArr,rsiArr,aoArr,crossArr,mmArr,sarStreakArr,mlExit){
  const trades=buildTrades(ts,closes,segArr,erArr,baffArr,rsiArr,aoArr,crossArr,mmArr,sarStreakArr,mlExit);
  renderStoria(trades);
}

function renderStoria(trades){
  const tb=document.getElementById('storiaBody');
  if(!trades||!trades.length){tb.innerHTML='<tr><td colspan="9" style="text-align:center;color:var(--text2);padding:12px">Nessun trade completo nelle ultime 252 barre</td></tr>';return;}
  tb.innerHTML=trades.map((tr,idx)=>{
    const deltaStr=tr.deltaPct!=null?(tr.deltaPct>=0?'+':'')+tr.deltaPct.toFixed(2)+'%':'—';
    const deltaC=tr.deltaPct==null?'':tr.deltaPct>=0?'color:var(--green)':'color:var(--red)';
    const entryColor=SIG_COLOR[tr.entryTier]||'#57606a', entryBg=SIG_BG[tr.entryTier]||'#fff';
    const exitBadge=tr.isOpen?
      `<span style="display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;background:#fff8e6;color:#9a6700;border:1px solid #9a6700">APERTA</span>`:
      `<span style="display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;background:${SIG_BG[tr.exitTier]||'#fff'};color:${SIG_COLOR[tr.exitTier]||'#57606a'};border:1px solid ${SIG_COLOR[tr.exitTier]||'#57606a'}">${SIG_ICON[tr.exitTier]||tr.exitTier}</span>`;
    return `<tr style="background:${idx===0?entryBg:''}">
      <td style="color:var(--text2);font-size:11px">${trades.length-idx}</td>
      <td style="font-family:monospace;font-size:11px">${tr.entryDate}</td>
      <td style="font-family:monospace;font-size:11px">${tr.exitDate||'—'}</td>
      <td>
        <span style="display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;background:${entryBg};color:${entryColor};border:1px solid ${entryColor}">${SIG_ICON[tr.entryTier]||tr.entryTier}</span>
        → ${exitBadge}
      </td>
      <td style="font-family:monospace;font-weight:600">${tr.entryPrice!=null?tr.entryPrice.toFixed(4):'—'}</td>
      <td style="font-family:monospace;font-weight:600">${tr.exitPrice!=null?tr.exitPrice.toFixed(4):'—'}</td>
      <td style="font-family:monospace;${deltaC}">${deltaStr}</td>
      <td style="font-family:monospace;font-size:11px">${tr.days}</td>
      <td style="font-size:10px;color:var(--text2);max-width:260px">
        <div><b>Entrata:</b> ${tr.entryNote}</div>
        <div><b>Uscita:</b> ${tr.exitNote}</div>
        ${idx===0&&tr.isOpen?'<div style="color:var(--green);font-weight:600">← attuale</div>':''}
      </td>
    </tr>`;
  }).join('');
}

// ═══ FETCH ═══

// ═══ RENDER GRAFICO SVG ═══
// ADX / +DI / -DI (Wilder standard) — SOLO per visualizzazione nel grafico, non usato in nessun calcolo di score/segnale/exit
function calcADX(h,l,c,period){
  period=period||14;
  const n=c.length;
  if(n<period*2+1)return{plusDI:new Array(n).fill(null),minusDI:new Array(n).fill(null),adx:new Array(n).fill(null)};
  const plusDM=new Array(n).fill(0),minusDM=new Array(n).fill(0),tr=new Array(n).fill(0);
  for(let i=1;i<n;i++){
    const up=h[i]-h[i-1], down=l[i-1]-l[i];
    plusDM[i]=(up>down&&up>0)?up:0;
    minusDM[i]=(down>up&&down>0)?down:0;
    tr[i]=Math.max(h[i]-l[i], Math.abs(h[i]-c[i-1]), Math.abs(l[i]-c[i-1]));
  }
  const atr=new Array(n).fill(null), pdmS=new Array(n).fill(null), mdmS=new Array(n).fill(null);
  let sTr=0,sP=0,sM=0;
  for(let i=1;i<=period;i++){sTr+=tr[i];sP+=plusDM[i];sM+=minusDM[i];}
  atr[period]=sTr; pdmS[period]=sP; mdmS[period]=sM;
  for(let i=period+1;i<n;i++){
    atr[i]=atr[i-1]-atr[i-1]/period+tr[i];
    pdmS[i]=pdmS[i-1]-pdmS[i-1]/period+plusDM[i];
    mdmS[i]=mdmS[i-1]-mdmS[i-1]/period+minusDM[i];
  }
  const plusDI=new Array(n).fill(null), minusDI=new Array(n).fill(null), dx=new Array(n).fill(null), adx=new Array(n).fill(null);
  for(let i=period;i<n;i++){
    if(atr[i]&&atr[i]>0){
      plusDI[i]=100*pdmS[i]/atr[i];
      minusDI[i]=100*mdmS[i]/atr[i];
      const s=plusDI[i]+minusDI[i];
      dx[i]=s>0?100*Math.abs(plusDI[i]-minusDI[i])/s:0;
    }
  }
  const start=period*2;
  if(start<n){
    let ok=true,sDx=0;
    for(let i=period+1;i<=start;i++){if(dx[i]==null){ok=false;break;}sDx+=dx[i];}
    if(ok){
      adx[start]=sDx/period;
      for(let i=start+1;i<n;i++){if(dx[i]!=null)adx[i]=(adx[i-1]*(period-1)+dx[i])/period;}
    }
  }
  return{plusDI,minusDI,adx};
}

function renderChartSVG(c,h,l,v,t,tf,pre,renko,renkoBrick,mlExit){


  const N=c.length;
  const kama=(pre&&pre.kama)?pre.kama:calcKAMA(c);
  const ao=(pre&&pre.ao)?pre.ao:calcAOArray(h,l);
  const rsiArr=(pre&&pre.rsi)?pre.rsi:c.map((_,i)=>calcRSI(c.slice(0,i+1)));
  const rsi5Arr=(pre&&pre.rsi5)?pre.rsi5:c.map((_,i)=>calcRSI(c.slice(0,i+1),5));
  const mm20=sma(c,20),mm50=sma(c,50),mm100=sma(c,100);
  const sarSrc=(pre&&pre.sar&&pre.sarBull)?{sar:pre.sar,bull:pre.sarBull}:calcSAR(h,l);
  const sarArr=sarSrc.sar,sarBull=sarSrc.bull;

  function calcHA(o,h,l,c){const haO=[],haH=[],haL=[],haC=[];haO.push((o[0]+c[0])/2);haC.push((o[0]+h[0]+l[0]+c[0])/4);haH.push(Math.max(h[0],haO[0],haC[0]));haL.push(Math.min(l[0],haO[0],haC[0]));for(let i=1;i<c.length;i++){const nc=(o[i]+h[i]+l[i]+c[i])/4,no=(haO[i-1]+haC[i-1])/2;haO.push(no);haC.push(nc);haH.push(Math.max(h[i],no,nc));haL.push(Math.min(l[i],no,nc));}return{haO,haH,haL,haC};}
  const ha=calcHA(h.map((_,i)=>i===0?c[0]:c[i]),h,l,c);

  // Marker segnali: usa segnale_d precalcolato se disponibile, altrimenti ricalcola in JS (fallback live)
  let segnalePerBar;
  if(pre&&pre.segnale){
    segnalePerBar=pre.segnale;
  }else{
    segnalePerBar=c.map((_,i)=>{
      if(i<40)return null;
      const sc=c.slice(0,i+1),sh=h.slice(0,i+1),sl=l.slice(0,i+1);
      const sk=calcKAMA(sc);
      const sao=calcAOArray(sh,sl);
      const ser=calcER(sc),sbaf=calcBaf(sao),srsi=calcRSI(sc)||50;
      const smm=calcMmAlign(sc);
      return calcSegnale(sc,sk,sarArr[i],sarBull[i],sao,ser,sbaf,smm,srsi);
    });
  }

  // Baffetti: usa baff_d precalcolato (coerente col motore segnali) se disponibile
  const bafC=(pre&&pre.baff)?pre.baff:ao.map((vv,i)=>{if(vv===null)return 0;let n=0;for(let j=i;j>0;j--){if(ao[j]!==null&&ao[j-1]!==null&&ao[j]>ao[j-1])n++;else break;}return n;});

  updateInfoBar(c,h,l,v,kama,sarArr,sarBull,ao,mlExit);

  // ── Costruzione SVG unico ──
  const wrap=document.getElementById('chartSvgWrap');
  if(!wrap)return;
  const W=Math.max(wrap.clientWidth-2,600);
  const PAD={l:50,r:66,t:8,b:22};
  const PW=W-PAD.l-PAD.r;
  const adxInd = calcADX(h,l,c,14);
  const panels=[
    {id:'price',h:280},{id:'renko',h:90},
    {id:'vol',h:60},{id:'baf',h:50},{id:'ao',h:70},{id:'rsi',h:100},{id:'adx',h:80},
  ];
  const GAP=4;
  const totalH=panels.reduce((s,p)=>s+p.h+GAP,0)+PAD.t+PAD.b;

  const ns='http://www.w3.org/2000/svg';
  const svg=document.createElementNS(ns,'svg');
  svg.setAttribute('width',W); svg.setAttribute('height',totalH);
  svg.setAttribute('viewBox','0 0 '+W+' '+totalH);
  svg.style.cssText='display:block;background:#fff';

  function xPos(i,count){count=count||N;return PAD.l+(i/Math.max(count-1,1))*PW;}
  function scY(val,mn,mx,yT,hh){if(mx===mn)return yT+hh/2;return yT+hh-((val-mn)/(mx-mn))*hh;}
  function el(tag,attrs,par){const e=document.createElementNS(ns,tag);for(const[k,vv]of Object.entries(attrs))e.setAttribute(k,vv);(par||svg).appendChild(e);return e;}
  function line(x1,y1,x2,y2,stroke,sw,dash){el('line',{x1:x1.toFixed(1),y1:y1.toFixed(1),x2:x2.toFixed(1),y2:y2.toFixed(1),stroke,'stroke-width':sw||1,...(dash?{'stroke-dasharray':dash}:{})});}
  function polyline(pts,stroke,sw,dash){if(pts.length<2)return;el('polyline',{points:pts.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' '),stroke,'stroke-width':sw||1.5,fill:'none','stroke-linejoin':'round',...(dash?{'stroke-dasharray':dash}:{})});}
  function rectEl(x,y,w2,h2,fill,op){if(w2<=0||h2<=0)return;el('rect',{x:x.toFixed(1),y:y.toFixed(1),width:Math.max(0,w2).toFixed(1),height:Math.max(0,h2).toFixed(1),fill,opacity:op!=null?op:1});}
  function txt(x,y,s,fill,size,anchor,weight){const e=el('text',{x:x.toFixed(1),y:y.toFixed(1),fill,'font-size':size||9,'font-family':'Segoe UI,sans-serif','text-anchor':anchor||'middle','font-weight':weight||400});e.textContent=s;}
  function tri(cx,cy,sz,up,fill){const pts=up?`${cx},${cy-sz} ${cx-sz},${cy+sz} ${cx+sz},${cy+sz}`:`${cx},${cy+sz} ${cx-sz},${cy-sz} ${cx+sz},${cy-sz}`;el('polygon',{points:pts,fill});}
  function diamond(cx,cy,sz,fill){el('polygon',{points:`${cx},${cy-sz} ${cx+sz},${cy} ${cx},${cy+sz} ${cx-sz},${cy}`,fill});}

  let yOff=PAD.t;
  panels.forEach(panel=>{
    const yTop=yOff,hh=panel.h;
    rectEl(PAD.l,yTop,PW,hh,'#fbfcfd');
    for(let g=0;g<=4;g++){const gy=yTop+hh/4*g;line(PAD.l,gy,PAD.l+PW,gy,g===0||g===4?'#d0d7de':'#eef0f3',g===0||g===4?0.8:0.5);}

    if(panel.id==='price'){
      const allP=[...ha.haH,...ha.haL,...kama.filter(x=>x!=null),...mm20.filter(x=>x!=null),...mm100.filter(x=>x!=null)];
      const mn=Math.min(...allP)*0.995, mx=Math.max(...allP)*1.005;
      const sy=vv=>scY(vv,mn,mx,yTop,hh);
      for(let g=0;g<=4;g++){const vv=mn+(mx-mn)/4*g; txt(PAD.l-4,sy(vv)+3,vv<10?vv.toFixed(3):vv.toFixed(2),'#57606a',8,'end');}
      // Heikin-Ashi (sostituisce la linea prezzo grezza — stesso stile di raptor-leva)
      const bw=Math.max(1,PW/N*0.6);
      for(let i=0;i<N;i++){
        const bull=ha.haC[i]>=ha.haO[i];
        const col=bull?'#1a7f37':'#cf222e';
        line(xPos(i),sy(ha.haH[i]),xPos(i),sy(ha.haL[i]),col,1);
        const yb=sy(Math.max(ha.haO[i],ha.haC[i])),yb2=sy(Math.min(ha.haO[i],ha.haC[i]));
        rectEl(xPos(i)-bw/2,yb,bw,Math.max(1,yb2-yb),col,0.85);
      }
      polyline(mm100.map((vv,i)=>vv!=null?[xPos(i),sy(vv)]:null).filter(Boolean),'#bc8cff',1,'8,4');
      polyline(mm50.map((vv,i)=>vv!=null?[xPos(i),sy(vv)]:null).filter(Boolean),'#e3b341',1,'5,3');
      polyline(mm20.map((vv,i)=>vv!=null?[xPos(i),sy(vv)]:null).filter(Boolean),'#58a6ff',1,'3,3');
      polyline(kama.map((vv,i)=>vv!=null?[xPos(i),sy(vv)]:null).filter(Boolean),'#f0883e',2);
      sarArr.forEach((s,i)=>{if(s==null)return;el('circle',{cx:xPos(i).toFixed(1),cy:sy(s).toFixed(1),r:2.6,fill:sarBull[i]?'#6e40c9':'#f85149',stroke:'#fff','stroke-width':0.8});});
      let ps=null;
      const segCol={BUY1:'#1a7f37',BUY2:'#0969da',BUY3:'#6e40c9',EXIT1:'#bc4c00',EXIT2:'#cf222e'};
      segnalePerBar.forEach((s,i)=>{
        if(!s||s===ps||!segCol[s])return;
        const up=s==='BUY1'||s==='BUY2'||s==='BUY3';
        if(s==='BUY3')diamond(xPos(i),sy(c[i])+(up?12:-12),5,segCol[s]);
        else tri(xPos(i),sy(c[i])+(up?12:-12),5,up,segCol[s]);
        ps=s;
      });
      const lc=c[N-1];
      rectEl(PAD.l+PW+2,sy(lc)-7,50,14,'#1f2328');
      txt(PAD.l+PW+27,sy(lc)+4,lc<10?lc.toFixed(4):lc.toFixed(2),'#fff',8);
      txt(PAD.l+2,yTop+10,'PREZZO (HEIKIN-ASHI) · KAMA · MM20/50/100 · SAR','#57606a',7.5,'start',700);
    }

    if(panel.id==='renko'){
      const info=document.getElementById('renkoBrickInfo');
      if(!renko||!renko.length){
        if(info)info.textContent='Renko: non disponibile';
        txt(PAD.l+PW/2,yTop+hh/2,'Renko non disponibile per questo ticker','#8b949e',9);
      }else{
        if(info)info.textContent='Renko brick='+renkoBrick;
        const rn=renko.length;
        const vals=renko.flatMap(b=>[b.o,b.c]);
        const mn=Math.min(...vals),mx=Math.max(...vals);
        const sy=vv=>scY(vv,mn,mx,yTop,hh);
        const bw=Math.max(2,PW/rn*0.8);
        renko.forEach((b,i)=>{
          const col=b.dir>0?'#1a7f37':'#cf222e';
          const y0=sy(Math.max(b.o,b.c)),y1=sy(Math.min(b.o,b.c));
          rectEl(xPos(i,rn)-bw/2,y0,bw,Math.max(1,y1-y0),col,0.9);
        });
      }
      txt(PAD.l+2,yTop+10,'RENKO (ATR14)','#57606a',7.5,'start',700);
    }

    if(panel.id==='vol'){
      const vmax=Math.max(...v,1);
      const vAvg=sma(v,20);
      const bw=Math.max(1,PW/N*0.7);
      v.forEach((vv,i)=>{
        const vh=(vv/vmax)*hh;
        const col=i===0?'#58a6ff':c[i]>=c[i-1]?'rgba(26,127,55,.55)':'rgba(207,34,46,.55)';
        rectEl(xPos(i)-bw/2,yTop+hh-vh,bw,vh,col);
      });
      polyline(vAvg.map((vv,i)=>vv!=null?[xPos(i),yTop+hh-Math.min(vv/vmax,1)*hh]:null).filter(Boolean),'#0969da',1.2);
      txt(PAD.l+2,yTop+10,'VOLUME vs Media20','#57606a',7.5,'start',700);
    }

    if(panel.id==='baf'){
      const bmax=Math.max(5,...bafC);
      const bw=Math.max(1,PW/N*0.7);
      bafC.forEach((n,i)=>{
        const bh=(n/bmax)*hh;
        const col=n>=2?'rgba(26,127,55,.85)':n>=1?'rgba(240,136,62,.7)':'rgba(208,215,222,.6)';
        rectEl(xPos(i)-bw/2,yTop+hh-bh,bw,bh,col);
      });
      txt(PAD.l+2,yTop+10,'BAFFETTI','#57606a',7.5,'start',700);
    }

    if(panel.id==='ao'){
      const vals=ao.filter(x=>x!=null);
      const mn=Math.min(...vals,0),mx=Math.max(...vals,0);
      const zero=scY(0,mn,mx,yTop,hh);
      const bw=Math.max(1,PW/N*0.7);
      line(PAD.l,zero,PAD.l+PW,zero,'#d0d7de',1);
      ao.forEach((vv,i)=>{
        if(vv==null)return;
        const prev=ao[i-1];
        const up=vv>=(prev==null?vv:prev);
        const col=vv>=0?(up?'#1a7f37':'rgba(26,127,55,.4)'):(up?'rgba(207,34,46,.4)':'#cf222e');
        const y0=scY(vv,mn,mx,yTop,hh);
        rectEl(xPos(i)-bw/2,Math.min(y0,zero),bw,Math.abs(y0-zero)||1,col);
      });
      txt(PAD.l+2,yTop+10,'AO (Awesome Oscillator)','#57606a',7.5,'start',700);
    }

    if(panel.id==='rsi'){
      const sy=vv=>scY(vv,0,100,yTop,hh);
      rectEl(PAD.l,sy(70),PW,sy(30)-sy(70),'#fff7e6',0.7);
      [70,50,30].forEach(lv=>{line(PAD.l,sy(lv),PAD.l+PW,sy(lv),lv===50?'#d0d7de':'#eef0f3',0.8,lv!==50?'3,3':'');txt(PAD.l-4,sy(lv)+3,lv,'#57606a',7.5,'end');});
      // Area riempita tra RSI5 e RSI14: verde quando RSI5 sopra (momentum corto in accelerazione), rosso quando sotto
      for(let i=1;i<N;i++){
        if(rsiArr[i]==null||rsiArr[i-1]==null||rsi5Arr[i]==null||rsi5Arr[i-1]==null)continue;
        const bullish=(rsi5Arr[i]+rsi5Arr[i-1])>=(rsiArr[i]+rsiArr[i-1]);
        const col=bullish?'rgba(26,127,55,.18)':'rgba(207,34,46,.18)';
        const pts=`${xPos(i-1).toFixed(1)},${sy(rsiArr[i-1]).toFixed(1)} ${xPos(i).toFixed(1)},${sy(rsiArr[i]).toFixed(1)} ${xPos(i).toFixed(1)},${sy(rsi5Arr[i]).toFixed(1)} ${xPos(i-1).toFixed(1)},${sy(rsi5Arr[i-1]).toFixed(1)}`;
        el('polygon',{points:pts,fill:col});
      }
      polyline(rsiArr.map((vv,i)=>vv!=null?[xPos(i),sy(vv)]:null).filter(Boolean),'#e3b341',1.5);
      polyline(rsi5Arr.map((vv,i)=>vv!=null?[xPos(i),sy(vv)]:null).filter(Boolean),'#58a6ff',1.2,'3,2');
      const lr=rsiArr.filter(x=>x!=null).at(-1);
      if(lr!=null){rectEl(PAD.l+PW+2,sy(lr)-6,32,12,'#e3b341');txt(PAD.l+PW+18,sy(lr)+4,lr.toFixed(0),'#1f2328',8);}
      txt(PAD.l+2,yTop+10,'RSI(14) arancio · RSI(5) blu tratteggiato','#57606a',7.5,'start',700);
    }

    if(panel.id==='adx'){
      const valsDi=[...adxInd.plusDI,...adxInd.minusDI,...adxInd.adx].filter(x=>x!=null);
      const mn=0, mx=Math.max(50,...valsDi);
      const sy=vv=>scY(vv,mn,mx,yTop,hh);
      [25,50].forEach(lv=>{ if(lv<=mx) line(PAD.l,sy(lv),PAD.l+PW,sy(lv),lv===25?'#e3b341':'#eef0f3',0.8,'3,3'); });
      txt(PAD.l-4,sy(25)+3,'25','#57606a',7,'end');
      // Area colorata tra +DI e -DI: verde quando +DI>-DI (spinta rialzista), rosso quando -DI>+DI (ribassista)
      for(let i=1;i<N;i++){
        const p0=adxInd.plusDI[i-1],m0=adxInd.minusDI[i-1],p1=adxInd.plusDI[i],m1=adxInd.minusDI[i];
        if(p0==null||m0==null||p1==null||m1==null)continue;
        const bull=(p0+p1)>=(m0+m1);
        const col=bull?'rgba(26,127,55,.22)':'rgba(207,34,46,.22)';
        const pts=`${xPos(i-1).toFixed(1)},${sy(p0).toFixed(1)} ${xPos(i).toFixed(1)},${sy(p1).toFixed(1)} ${xPos(i).toFixed(1)},${sy(m1).toFixed(1)} ${xPos(i-1).toFixed(1)},${sy(m0).toFixed(1)}`;
        el('polygon',{points:pts,fill:col});
      }
      polyline(adxInd.plusDI.map((vv,i)=>vv!=null?[xPos(i),sy(vv)]:null).filter(Boolean),'#1a7f37',1.3);
      polyline(adxInd.minusDI.map((vv,i)=>vv!=null?[xPos(i),sy(vv)]:null).filter(Boolean),'#cf222e',1.3);
      polyline(adxInd.adx.map((vv,i)=>vv!=null?[xPos(i),sy(vv)]:null).filter(Boolean),'#1f2328',1.6);
      const lastAdx=adxInd.adx.filter(x=>x!=null).at(-1);
      if(lastAdx!=null){rectEl(PAD.l+PW+2,sy(lastAdx)-6,32,12,'#1f2328');txt(PAD.l+PW+18,sy(lastAdx)+4,lastAdx.toFixed(0),'#fff',8);}
      txt(PAD.l+2,yTop+10,'ADX nero (forza, soglia 25) · +DI verde · -DI rosso — solo informativo','#57606a',7.5,'start',700);
    }

    if(panel === panels[panels.length-1]){
      const step=Math.max(1,Math.floor(N/8));
      for(let i=0;i<N;i+=step){
        const dd=new Date(t[i]*1000);
        txt(xPos(i),totalH-PAD.b+13,dd.getDate()+'/'+(dd.getMonth()+1),'#57606a',7.5);
      }
    }

    yOff+=hh+GAP;
  });

  wrap.innerHTML='';
  wrap.appendChild(svg);

  const legEl=document.getElementById('chartLegend');
  if(legEl){
    const swf=(color,label)=>`<span style="display:inline-flex;align-items:center;gap:4px"><span style="width:10px;height:10px;background:${color};display:inline-block;border-radius:2px"></span>${label}</span>`;
    legEl.innerHTML=[swf('#1a7f37','HA Verde'),swf('#cf222e','HA Rosso'),swf('#f0883e','KAMA'),swf('#58a6ff','MM20'),swf('#e3b341','MM50'),swf('#bc8cff','MM100'),
      swf('#1a7f37','BUY1'),swf('#0969da','BUY2'),swf('#6e40c9','BUY3'),swf('#bc4c00','EXIT1'),swf('#cf222e','EXIT2')].join('');
  }
}


// ═══ INFO BAR (header segnale/prezzo/ecc.) ═══
function updateInfoBar(c,h,l,v,kama,sarArr,sarBull,ao,mlExit){
  const price=c[c.length-1],prev=c[c.length-2],chg=prev?((price-prev)/prev*100):0;
  const kNow=kama[kama.length-1],er=calcER(c),rsi=calcRSI(c);
  const aoArr=[...ao].filter(v=>v!=null);
  const aoImproving=aoArr.length>=2&&aoArr[aoArr.length-1]>aoArr[aoArr.length-2];
  const baff=calcBaf(ao);
  const sarVal=sarArr[sarArr.length-1],sarIsBull=sarBull[sarBull.length-1];
  const e=id=>document.getElementById(id);

  // Calcola ATR
  let atr=null;
  if(h.length>=14){const tr=c.map((_,i)=>i===0?h[i]-l[i]:Math.max(h[i]-l[i],Math.abs(h[i]-c[i-1]),Math.abs(l[i]-c[i-1])));let a=tr.slice(1,15).reduce((x,y)=>x+y,0)/14;for(let i=15;i<tr.length;i++)a=(a*13+tr[i])/14;atr=a;}

  const e21=emaArr(c,21),e55=emaArr(c,55);
  const trd=e21[e21.length-1]>e55[e55.length-1]?'VERDE':e21[e21.length-1]<e55[e55.length-1]?'ROSSO':'GRIGIO';
  const mmAlign=calcMmAlign(c);
  const cross=calcCrossKAMA(c,kama);
  const segnale=calcSegnale(c,kama,sarVal,sarIsBull,ao,er,baff,mmAlign,rsi||50);
  const trail=atr?price-2*atr:null;

  e('ic-sig').textContent=SIG_ICON[segnale]||segnale;
  e('ic-sig').style.color=SIG_COLOR[segnale]||'#57606a';
  e('ic-mr').textContent='Cross: '+cross+' barre fa';
  e('ic-price').textContent=price.toFixed(3);e('ic-price').style.color=chg>=0?'#1a7f37':'#cf222e';
  e('ic-chg').textContent=(chg>=0?'+':'')+chg.toFixed(2)+'%';
  e('ic-kama').textContent=kNow?kNow.toFixed(3):'—';const kgap=kNow?((price-kNow)/kNow*100):0;e('ic-kgap').textContent='Gap: '+kgap.toFixed(2)+'%';
  e('ic-sar').textContent=sarVal?sarVal.toFixed(3):'—';e('ic-sar').style.color=sarIsBull?'#6e40c9':'#f85149';e('ic-sarlbl').textContent=sarIsBull?'▲ Bullish':'▼ Bearish';
  e('ic-er').textContent=er?(er*100).toFixed(1)+'%':'—';e('ic-erlbl').textContent=er>=0.5?'Forte':er<0.3?'Laterale':'Moderato';
  e('ic-rsi').textContent=rsi?rsi.toFixed(1):'—';e('ic-rsi').style.color=rsi>=70?'#f85149':rsi<=30?'#3fb950':'#e3b341';e('ic-rsilbl').textContent=rsi>=70?'Ipercomprato':rsi<=30?'Ipervenduto':'Neutro';
  e('ic-baff').textContent=baff;e('ic-bafflbl').textContent=baff>=3?'Forte':baff>=2?'BUY2':baff>=1?'Inizia':'Assente';
  e('ic-ao').textContent=aoImproving?'↑ Sì':'— No';e('ic-ao').style.color=aoImproving?'#1a7f37':'#cf222e';e('ic-aolbl').textContent=aoImproving?'In miglioramento':'Stagnante';
  const trCls={VERDE:'#1a7f37',ROSSO:'#cf222e',GRIGIO:'#57606a'};e('ic-trend').textContent=trd;e('ic-trend').style.color=trCls[trd];
  e('ic-atr').textContent=atr?atr.toFixed(3):'—';e('ic-atrpct').textContent=atr&&price?(atr/price*100).toFixed(2)+'%':'—';
  e('ic-trail').textContent=trail?trail.toFixed(3):'—';e('ic-trailpct').textContent=trail&&price?((price-trail)/price*100).toFixed(2)+'% gap':'—';

  // Card "Uscita ML": visibile solo se posizione aperta (BUY1/BUY2) e il modello ha una previsione
  const mlCard=e('ic-mlexit-card');
  if(mlCard){
    if(mlExit&&(segnale==='BUY1'||segnale==='BUY2')){
      mlCard.style.display='';
      e('ic-mlexit').textContent=(mlExit.peak_return_pct>=0?'+':'')+mlExit.peak_return_pct.toFixed(1)+'%';
      e('ic-mlexitlbl').textContent='di solito entro '+Math.round(mlExit.days_to_peak)+'gg';
    }else{
      mlCard.style.display='none';
    }
  }
}
