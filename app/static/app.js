'use strict';
const token = document.querySelector('meta[name="bridge-token"]').content;
const el = id => document.getElementById(id);
let direction = 'toBLAKE2b';
let active = null;
let start9Configured = false;
let clock = null;
let quoteBusy = false;
let cameraStream = null;
let cameraFrame = null;
const formatSat = v => new Intl.NumberFormat('en-US', {maximumFractionDigits:3}).format(v);
const names = {toBLAKE2b:{pay:'SHA256BTC',receive:'BLAKE2BTC'},toSHA256:{pay:'BLAKE2BTC',receive:'SHA256BTC'}};
async function api(path, body) {
  const opts = {headers:{'X-Bridge-Token':token}};
  if (body !== undefined) { opts.method='POST';opts.headers['Content-Type']='application/json';opts.body=JSON.stringify(body); }
  const res = await fetch(path,opts);
  let data;
  try {data=await res.json();} catch {throw new Error('Unreadable response from bridge application');}
  if (!res.ok) throw new Error(data.error || 'Bridge request failed');
  return data;
}
function notice(id, message, isError=false) {
  const node=el(id);node.textContent=message;node.classList.toggle('error',isError);node.hidden=!message;
}
function chooseDirection(dir) {
  direction=dir;
  ['dir-to-blake','dir-to-sha'].forEach(id=>el(id).classList.toggle('selected',el(id).dataset.direction===dir));
  el('receive-label').textContent=names[dir].receive;
  el('destination-chain').textContent=names[dir].receive;
  active=null;el('quote-panel').hidden=true;el('payment-qr').hidden=true;el('destination').value='';stopCamera();
  notice('input-notice','');
}
function showQuote(q) {
  active=q;
  el('quote-panel').hidden=false;
  el('pay-amount').textContent=formatSat(q.incoming_sats);
  el('receive-amount').textContent=formatSat(q.outgoing_sats);
  el('pay-label').textContent=names[q.direction].pay+' sats';
  el('receive-name').textContent=names[q.direction].receive+' sats';
  el('spread').textContent=Number.isFinite(Number(q.spread))?(Number(q.spread)*100).toFixed(3)+'%':'—';
  el('hold-invoice').value=q.hold_invoice;
  renderPaymentQR(q);
  el('pay-btn').hidden=!(start9Configured && q.direction==='toBLAKE2b');
  notice('pay-notice',start9Configured?'Review amounts before authorization. No automatic retries.':'Scan the payment QR or copy the invoice into your '+names[q.direction].pay+' Lightning wallet.');
  if (clock) clearInterval(clock);
  clock=setInterval(tick,250);
  tick();
  el('quote-panel').scrollIntoView({behavior:'smooth',block:'start'});
}
function tick() {
  if (!active)return;
  const remain=Math.max(0, active.expires_at-Math.floor(Date.now()/1000));
  const duration=Math.max(1,active.expires_at-(active.created_at||active.expires_at-60));
  el('timer').textContent=remain?remain+' seconds remaining':'EXPIRED — request a new quote';
  el('timerfill').style.width=(100*remain/duration)+'%';
  el('timerfill').style.background=remain<15?'#c47659':'#418765';
  el('copy-btn').disabled=remain===0;
  el('payment-qr').classList.toggle('expired',remain===0);
  if(!remain)el('qr-caption').textContent='Expired — refresh the quote. Do not scan or pay this invoice.';
  el('pay-btn').disabled=remain<9||active.payment_state!=='NOT_STARTED';
  if(!remain)notice('pay-notice','The hold invoice has expired. Do not pay it. Choose Refresh quote.',true);
}
async function requestQuote() {
  if (quoteBusy)return;
  const invoice=el('destination').value.trim();
  if(!/^lnbc/i.test(invoice)){notice('input-notice','Paste a complete destination Lightning invoice that begins with lnbc.',true);return;}
  quoteBusy=true;el('quote-btn').disabled=true;el('requote-btn').disabled=true;
  el('quote-btn').textContent='Requesting quote…';notice('input-notice','');
  try {
    const q=await api('/api/quote',{invoice,direction});
    q.created_at=Math.floor(Date.now()/1000);
    showQuote(q);
  } catch(err) {notice('input-notice',err.message,true);}
  finally{quoteBusy=false;el('quote-btn').disabled=false;el('requote-btn').disabled=false;el('quote-btn').innerHTML='Get live quote <span>↗</span>';}
}
async function refreshStatus() {
  try {
    const s=await api('/api/bridge-status');
    const connected=s.connected===true;
    const openDirections=Array.isArray(s.directions)?s.directions:[];
    const closedDirections=Array.isArray(s.unavailable_directions)?s.unavailable_directions:[];
    const known=['toSHA256','toBLAKE2b'];
    const open=known.filter(name=>openDirections.includes(name));
    const displayDirection=name=>name==='toBLAKE2b'?'To BLAKE2BTC':'To SHA256BTC';
    el('dot').className='statusdot '+(connected?'good':'bad');
    el('connection').textContent=connected?'Bridge connected':'Bridge unavailable';
    el('sha-state').textContent=s.sha256_ready||'Operator-only';
    el('bridge-state').textContent=s.enabled===false?'Disabled':open.length?'Serving':'Not serving';
    el('swaps').textContent=s.swaps_in_flight==null?'Operator-only':String(s.swaps_in_flight);
    el('directions').textContent=open.map(displayDirection).join(' · ')||'None currently';
    for (const [id,dir] of [['dir-to-blake','toBLAKE2b'],['dir-to-sha','toSHA256']]) {
      const unavailable=closedDirections.some(d=>d.name===dir);
      el(id).disabled=unavailable;
      el(id).title=unavailable?'Unavailable until bridge liquidity/status changes':'';
    }
    if(closedDirections.some(d=>d.name===direction) && open.length)chooseDirection(open[0]);
    const issues=[...(s.refusals||[])];
    for(const item of closedDirections) {
      issues.push(displayDirection(item.name)+' unavailable: '+item.refusal);
    }
    if(s.needs_operator_count)issues.push('Operator action required for '+s.needs_operator_count+' swap(s)');
    el('bridge-warning').textContent=issues.join(' / ');
    el('bridge-warning').hidden=!issues.length;
  }catch(err){el('dot').className='statusdot bad';el('connection').textContent='Connection error';el('bridge-warning').hidden=false;el('bridge-warning').textContent=err.message;}
}
async function copyInvoice() {
  if(!active||active.expires_at<=Math.floor(Date.now()/1000))return;
  try{
    await navigator.clipboard.writeText(active.hold_invoice);
    notice('pay-notice','Invoice copied. Paste into your sending Lightning wallet and confirm before expiry.');
  }catch{el('hold-invoice').focus();el('hold-invoice').select();notice('pay-notice','Invoice selected. Press Command+C or Ctrl+C to copy.');}
}
async function pay() {
  if(!active||active.direction!=='toBLAKE2b')return;
  if(!confirm('Authorize your Start9 SHA256BTC node to pay '+formatSat(active.incoming_sats)+' sats plus at most the configured routing fee? This sends real funds.'))return;
  const id=active.id;
  el('pay-btn').disabled=true;
  notice('pay-notice','Payment submitted to Start9. Do not retry until payment history is checked.');
  try{
    const result=await api('/api/pay',{id});
    active.payment_state=result.status;
    notice('pay-notice','Start9 payment state: '+result.status+'. Check BLAKE2BTC receiving wallet and bridge status. '+(result.status==='UNKNOWN'?'Do not try again without verifying history.':''),result.status==='UNKNOWN'||result.status==='FAILED');
    refreshStatus();
  }catch(err){active.payment_state='UNKNOWN';notice('pay-notice',err.message+' — check Start9 history before another attempt.',true);}
  tick();
}

async function renderPaymentQR(q) {
  el('payment-qr').hidden=true;
  el('qr-image').replaceChildren();
  el('qr-caption').textContent='Scan with your '+names[q.direction].pay+' Lightning wallet before the quote expires.';
  try {
    const result=await api('/api/payment-qr',{invoice:q.hold_invoice});
    if(active!==q || q.expires_at<=Math.floor(Date.now()/1000))return;
    // SVG is generated entirely by our server from a verified quote, never a remote QR service.
    const parser=new DOMParser();
    const doc=parser.parseFromString(result.svg,'image/svg+xml');
    const svg=doc.documentElement;

    if(svg.localName!=='svg' ||
       svg.namespaceURI!=='http://www.w3.org/2000/svg' ||
       doc.querySelector('parsererror')) {
      throw new Error('Invalid QR image');
    }

    svg.setAttribute('width','100%');
    svg.setAttribute('height','100%');
    el('qr-image').replaceChildren(document.importNode(svg,true));
    el('payment-qr').hidden=false;
  }catch(err){notice('pay-notice','QR unavailable: '+err.message+'. You can still copy the invoice.',true);}
}
async function detectQR(source) {
  if(!('BarcodeDetector' in window))throw new Error('QR scanning is not supported by this browser. Paste the invoice instead.');
  const detector=new BarcodeDetector({formats:['qr_code']});
  const found=await detector.detect(source);
  const value=found.find(x=>x.rawValue)?.rawValue;
  if(!value)throw new Error('No QR code found. Try a sharper image.');
  const cleaned=value.trim().replace(/^lightning:/i,'');
  if(!/^lnbc/i.test(cleaned))throw new Error('QR code is not a BOLT11 Lightning invoice.');
  el('destination').value=cleaned;
  notice('input-notice','Invoice scanned. Review the receiving chain, then request a quote.');
  stopCamera();
}
function stopCamera() {
  if(cameraFrame)cancelAnimationFrame(cameraFrame);
  cameraFrame=null;
  if(cameraStream){cameraStream.getTracks().forEach(t=>t.stop());cameraStream=null;}
  el('qr-video').srcObject=null;
  el('camera-panel').hidden=true;
}
async function startCamera() {
  try {
    if(!navigator.mediaDevices?.getUserMedia)throw new Error('Camera requires HTTPS or localhost. Use Upload QR image or paste the invoice.');
    if(!('BarcodeDetector' in window))throw new Error('Camera QR decoding is unsupported in this browser. Paste the invoice instead.');
    cameraStream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'},audio:false});
    el('qr-video').srcObject=cameraStream;
    el('camera-panel').hidden=false;
    let last=0;
    const frame=async timestamp=>{
      if(!cameraStream)return;
      if(timestamp-last>450 && el('qr-video').readyState>=2){
        last=timestamp;
        try {await detectQR(el('qr-video'));}catch(e){if(!e.message.startsWith('No QR'))notice('input-notice',e.message,true);}
      }
      if(cameraStream)cameraFrame=requestAnimationFrame(frame);
    };
    cameraFrame=requestAnimationFrame(frame);
  }catch(err){stopCamera();notice('input-notice',err.message,true);}
}
async function uploadQR(event) {
  const file=event.target.files?.[0];event.target.value='';if(!file)return;
  try {
    const bitmap=await createImageBitmap(file);
    try{await detectQR(bitmap);}finally{bitmap.close();}
  }catch(err){notice('input-notice',err.message,true);}
}

document.querySelectorAll('.toggle button').forEach(b=>b.addEventListener('click',()=>chooseDirection(b.dataset.direction)));
el('scan-camera').addEventListener('click',startCamera);
el('stop-camera').addEventListener('click',stopCamera);
el('scan-upload').addEventListener('click',()=>el('qr-upload').click());
el('qr-upload').addEventListener('change',uploadQR);
el('quote-btn').addEventListener('click',requestQuote);
el('requote-btn').addEventListener('click',requestQuote);
el('refresh-btn').addEventListener('click',refreshStatus);
el('copy-btn').addEventListener('click',copyInvoice);
el('pay-btn').addEventListener('click',pay);
(async()=>{try{const config=await api('/api/health');start9Configured=config.start9_configured;}catch{}refreshStatus();})();
