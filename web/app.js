/* NextGen VoiceDesk | Private, browser-only portfolio demo.
 * No real AI, live calls, CRM, mail or booking provider is connected.
 */
(() => {
  'use strict';
  const STORE_KEY = 'nextgen-voicedesk-demo-v1';
  const $ = (id) => document.getElementById(id);
  const escape = (input) => String(input ?? '').replace(/[&<>"']/g, (char) =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const uniqueId = () => (globalThis.crypto?.randomUUID?.() ?? String(Date.now()) + Math.random().toString(16).slice(2));
  const localDate = (d) => [d.getFullYear(),String(d.getMonth()+1).padStart(2,'0'),String(d.getDate()).padStart(2,'0')].join('-');
  const nextBusinessDay = (delta) => {
    const d = new Date();d.setHours(12,0,0,0);d.setDate(d.getDate()+delta);
    while ([0,6].includes(d.getDay())) d.setDate(d.getDate()+1);
    return localDate(d);
  };
  function initialData() {
    return {
      isSample: true,
      calls: 24,
      leads: [
        {id:'sample-1',name:'Olivia Carter',contact:'olivia@example.test',interest:'New patient consultation',source:'Sample phone call',status:'new',sample:true},
        {id:'sample-2',name:'Noah Williams',contact:'noah@example.test',interest:'Pricing inquiry',source:'Sample phone call',status:'new',sample:true},
        {id:'sample-3',name:'Sophia Chen',contact:'sophia@example.test',interest:'Appointment inquiry',source:'Sample web form',status:'follow-up',sample:true},
        {id:'sample-4',name:'Ethan Brooks',contact:'ethan@example.test',interest:'General inquiry',source:'Sample phone call',status:'new',sample:true}
      ],
      appointments: [
        {id:'sample-a1',name:'Olivia Carter',contact:'olivia@example.test',service:'Consultation',date:nextBusinessDay(2),time:'10:00',status:'requested',sample:true},
        {id:'sample-a2',name:'Sophia Chen',contact:'sophia@example.test',service:'Follow-up',date:nextBusinessDay(3),time:'11:30',status:'requested',sample:true}
      ]
    };
  }
  function load() {
    try {
      const old = JSON.parse(localStorage.getItem(STORE_KEY) || 'null');
      if (old && typeof old === 'object' && Array.isArray(old.leads) && Array.isArray(old.appointments) && Number.isInteger(old.calls)) return old;
    } catch (_) {}
    return initialData();
  }
  let data = load();
  let activeCall = false;
  let pendingCapture = null;
  let voiceEnabled = true;
  let recognizer = null;
  function persist() { try { localStorage.setItem(STORE_KEY,JSON.stringify(data)); } catch (_) { notify('Browser storage unavailable; changes will not persist.'); } }
  function notify(message) {
    const toast = $('toast');
    toast.textContent = message;toast.classList.add('show');
    clearTimeout(notify.timer);
    notify.timer = setTimeout(() => toast.classList.remove('show'), 4200);
  }
  function initials(name) { return String(name).trim().split(/\s+/).slice(0,2).map(v => v[0]?.toUpperCase() || '').join('') || '?'; }
  function show(view) {
    const allowed = ['overview','calls','appointments','leads','settings'];
    if (!allowed.includes(view)) view = 'overview';
    document.querySelectorAll('.view').forEach(node => node.classList.toggle('active',node.id === 'view-' + view));
    document.querySelectorAll('.nav-link').forEach(node => node.classList.toggle('active',node.dataset.viewTarget === view));
    $('breadcrumb').textContent = ({overview:'Overview',calls:'Live receptionist',appointments:'Appointments',leads:'Lead inbox',settings:'Settings'})[view];
    if (location.hash !== '#' + view) history.replaceState(null,'','#' + view);
    window.scrollTo({top:0,behavior:'smooth'});
  }
  function rowPerson(name, detail) {
    return '<div class="person-cell"><span class="table-avatar">' + escape(initials(name)) + '</span><span><strong>' +
      escape(name) + '</strong><small>' + escape(detail) + '</small></span></div>';
  }
  function render() {
    $('stat-calls').textContent = data.calls;
    $('stat-appointments').textContent = data.appointments.length;
    $('stat-leads').textContent = data.leads.length;
    $('nav-lead-count').textContent = data.leads.length;
    $('booking-count').textContent = data.appointments.length;
    $('lead-list-count').textContent = data.leads.length;
    $('overview-leads').innerHTML = data.leads.slice(-4).reverse().map((lead) =>
      '<div class="recent-item"><span class="recent-avatar">' + escape(initials(lead.name)) +
      '</span><span class="recent-person"><strong>' + escape(lead.name) + '</strong><span>' + escape(lead.interest) +
      '</span></span><span class="recent-source">' + escape(lead.sample ? 'Sample' : 'Demo-added') + '</span></div>'
    ).join('') || '<p class="empty-row">No demo leads yet.</p>';
    const appointments = [...data.appointments].sort((a,b) => a.date.localeCompare(b.date) || a.time.localeCompare(b.time));
    $('appointment-rows').innerHTML = appointments.map(item => '<tr><td>' + rowPerson(item.name,item.service) +
      '</td><td>' + escape(item.date) + ' · ' + escape(item.time) +
      '</td><td><span class="tag pending">Request only</span> ' + (item.sample ? '<span class="tag sample">Sample</span>' : '') + '</td></tr>'
    ).join('') || '<tr><td class="empty-row" colspan="3">No appointments requested.</td></tr>';
    renderLeads();
  }
  function renderLeads() {
    const q = $('lead-search').value.trim().toLowerCase();
    const matches = data.leads.filter(item =>
      [item.name,item.contact,item.interest,item.source].some(field => String(field).toLowerCase().includes(q)));
    $('lead-rows').innerHTML = matches.slice().reverse().map(item =>
      '<tr><td>' + rowPerson(item.name,item.contact) + '</td><td>' + escape(item.interest) +
      '</td><td>' + escape(item.source) + (item.sample ? ' <span class="tag sample">Sample</span>' : '') +
      '</td><td><span class="tag ' + (item.status === 'new' ? 'new' : 'pending') + '">' +
      escape(item.status === 'new' ? 'New' : 'Follow-up') + '</span></td></tr>'
    ).join('') || '<tr><td class="empty-row" colspan="4">No leads match your search.</td></tr>';
  }
  function setFeedback(id, text, success) {
    const el = $(id);el.textContent = text;el.className = 'form-feedback ' + (success ? 'success':'error');
  }
  function timeSlots() {
    const select = $('booking-time');
    for (let hour=9;hour<=16;hour++) for (const minute of ['00','30']) {
      const opt = document.createElement('option');opt.value = String(hour).padStart(2,'0') + ':' + minute;opt.textContent = opt.value;select.appendChild(opt);
    }
    select.value='09:00';
    $('booking-date').min=localDate(new Date());
    const cap = new Date();cap.setDate(cap.getDate()+180);$('booking-date').max=localDate(cap);
    $('booking-date').value=nextBusinessDay(1);
  }
  function validateSlot(date, time) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !/^(09|1[0-6]):(00|30)$/.test(time)) return 'Select a valid date and time.';
    const d = new Date(date + 'T12:00:00');
    if (!Number.isFinite(d.getTime()) || localDate(d) !== date || [0,6].includes(d.getDay())) return 'Please choose a weekday (Monday–Friday).';
    if (date < localDate(new Date())) return 'Please choose a future date.';
    const max = new Date();max.setDate(max.getDate()+180);
    if (date > localDate(max)) return 'Please choose a date within 180 days.';
    const now = new Date();
    if (date === localDate(now) && time <= String(now.getHours()).padStart(2,'0') + ':' + String(now.getMinutes()).padStart(2,'0')) return 'Please select a future time.';
    if (data.appointments.some(a => a.date===date && a.time===time)) return 'This demo slot is already requested. Choose another time.';
    return '';
  }
  $('booking-form').addEventListener('submit',event => {
    event.preventDefault();
    const payload={id:uniqueId(),name:$('booking-name').value.trim(),contact:$('booking-contact').value.trim(),service:$('booking-service').value,
      date:$('booking-date').value,time:$('booking-time').value,status:'requested',sample:false};
    if (!payload.name || !payload.contact) {setFeedback('booking-feedback','Enter your name and contact.',false);return;}
    const problem=validateSlot(payload.date,payload.time);
    if(problem){setFeedback('booking-feedback',problem,false);return;}
    data.appointments.push(payload);persist();render();
    setFeedback('booking-feedback','Demo appointment request saved. It is not confirmed and no notification was sent.',true);
    $('booking-form').reset();$('booking-date').value=nextBusinessDay(1);$('booking-time').value='09:00';
    notify('Appointment request added to demo calendar.');
  });
  $('lead-form').addEventListener('submit',event => {
    event.preventDefault();
    const name=$('lead-name').value.trim(),contact=$('lead-contact').value.trim(),interest=$('lead-interest').value.trim();
    if(!name||!contact||!interest) return;
    data.leads.push({id:uniqueId(),name,contact,interest,source:'Manual demo entry',status:'new',sample:false});
    persist();render();$('lead-form').reset();setFeedback('lead-feedback','Demo lead saved locally in this browser.',true);notify('Lead added to demo inbox.');
  });
  $('lead-search').addEventListener('input',renderLeads);
  $('export-leads').addEventListener('click',() => {
    const payload=JSON.stringify({export_type:'NextGen VoiceDesk browser sandbox',real_customer_data:false,leads:data.leads},null,2);
    const url=URL.createObjectURL(new Blob([payload],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download='voicedesk-demo-leads.json';document.body.appendChild(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1000);notify('Demo lead export generated.');
  });
  $('reset-demo').addEventListener('click',() => {
    if (!window.confirm('Reset all browser demo records to their fictional sample values?')) return;
    data=initialData();persist();render();setFeedback('booking-feedback','',true);setFeedback('lead-feedback','',true);
    $('lead-search').value='';renderLeads();if(activeCall) endCall();notify('Demo reset to original samples.');
  });
  function speak(message) {
    if (!voiceEnabled || !('speechSynthesis' in window)) return;
    try {
      window.speechSynthesis.cancel();
      const utterance=new SpeechSynthesisUtterance(message);utterance.lang='en-US';utterance.rate=1.02;utterance.pitch=1.01;
      window.speechSynthesis.speak(utterance);
    } catch (_) { /* Silent fallback to text */ }
  }
  function addBubble(role,text) {
    const transcript=$('transcript');
    transcript.querySelector('.empty-transcript')?.remove();
    const bubble=document.createElement('div');bubble.className='bubble '+role;
    const avatar=document.createElement('span');avatar.className='bubble-avatar';avatar.textContent=role==='assistant'?'✦':'◉';
    const content=document.createElement('div');content.className='bubble-content';
    content.textContent=text;
    const time=document.createElement('small');time.textContent=role==='assistant'?'Receptionist · Demo':'Caller · Demo';
    content.appendChild(time);bubble.append(avatar,content);transcript.appendChild(bubble);transcript.scrollTop=transcript.scrollHeight;
    if(role==='assistant') speak(text);
  }
  function classify(msg) {
    const m=msg.toLowerCase();
    if (/\b(human|person|agent|staff|representative|manager|call\s?back|speak to)\b/.test(m))
      return ['human','I can take your details for a staff callback. What is your full name?'];
    if (/\b(book|appointment|schedule|reservation|visit|consultation|available slot)\b/.test(m))
      return ['booking','I can help request an appointment. What is your full name?'];
    if (/\b(price|cost|fee|quote|insurance|payment|how much)\b/.test(m))
      return ['pricing','Pricing depends on the service. I can forward your question to the team for an accurate quote.'];
    if (/\b(hours?|open|close|weekend|when are you)\b/.test(m))
      return ['hours','The demo business lists Monday to Friday, 9 AM to 5 PM. Please verify hours before using this in production.'];
    if (/\b(where|address|location|direction|parking)\b/.test(m))
      return ['location','I can ask the team to send accurate location and parking information.'];
    return ['general','Thanks for sharing. I can pass your request to the team, or help you request an appointment.'];
  }
  function startCall() {
    if(activeCall) return;
    activeCall=true;pendingCapture=null;data.calls+=1;persist();render();
    $('call-orbit').classList.add('active');$('call-status').textContent='DEMO CALL IN PROGRESS';$('call-title').textContent='Connected to VoiceDesk';
    $('call-subtitle').textContent='Try a question, speak, or request an appointment.';
    $('call-toggle').textContent='■ End demo call';$('quick-questions').hidden=false;
    $('message-input').disabled=false;$('send-btn').disabled=false;$('mic-btn').disabled=false;
    $('message-input').placeholder='Type a customer question…';
    $('transcript').innerHTML='';
    addBubble('assistant','Hello! I am the automated receptionist for Aster Dental, a fictional demo business. How may I help? You can ask about appointments, pricing, hours, or a callback.');
  }
  function endCall() {
    activeCall=false;pendingCapture=null;recognizer?.stop?.();
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    $('call-orbit').classList.remove('active');$('call-status').textContent='READY TO CONNECT';
    $('call-title').textContent='Your virtual front desk';$('call-subtitle').textContent='Start a simulated call to meet the receptionist.';
    $('call-toggle').textContent='☎ Start demo call';$('quick-questions').hidden=true;
    $('message-input').disabled=true;$('send-btn').disabled=true;$('mic-btn').disabled=true;
    $('message-input').placeholder='Start a call to type a customer question…';
  }
  function handleMessage(message) {
    const text=String(message||'').trim().slice(0,500);
    if(!activeCall || !text) return;
    addBubble('user',text);
    if (pendingCapture?.step==='name') {
      if(text.length<2){addBubble('assistant','Please give a name with at least two characters.');return;}
      pendingCapture.name=text;pendingCapture.step='contact';
      addBubble('assistant','Thanks, '+text+'. What email or phone number should the team use to contact you?');
      return;
    }
    if (pendingCapture?.step==='contact') {
      if(text.length<5){addBubble('assistant','Please provide a valid-looking email or phone contact (at least five characters).');return;}
      const intent=pendingCapture.intent;
      data.leads.push({id:uniqueId(),name:pendingCapture.name.slice(0,100),contact:text.slice(0,150),
        interest:intent==='booking'?'Appointment inquiry':'Callback request',source:'Browser demo call',status:'new',sample:false});
      persist();render();
      if(intent==='booking') {
        $('booking-name').value=pendingCapture.name.slice(0,100);$('booking-contact').value=text.slice(0,150);
        addBubble('assistant','Your inquiry is saved in this demo inbox. To request a preferred time, open Appointments. A request is not a confirmed booking.');
      } else {
        addBubble('assistant','Your callback request was saved in this browser demo. A real staff member will not be notified.');
      }
      pendingCapture=null;notify('Conversation lead captured in demo inbox.');return;
    }
    const [intent,answer]=classify(text);
    addBubble('assistant',answer);
    if(intent==='booking'||intent==='human') pendingCapture={step:'name',intent};
  }
  $('call-toggle').addEventListener('click',()=>activeCall?endCall():startCall());
  $('message-form').addEventListener('submit',ev=>{
    ev.preventDefault();const message=$('message-input').value;$('message-input').value='';handleMessage(message);
  });
  document.querySelectorAll('[data-question]').forEach(btn=>btn.addEventListener('click',()=>handleMessage(btn.dataset.question)));
  $('voice-enabled').addEventListener('change',ev=>{
    voiceEnabled=ev.target.checked;if(!voiceEnabled && 'speechSynthesis' in window) window.speechSynthesis.cancel();
  });
  $('mic-btn').addEventListener('click',() => {
    if(!activeCall) return;
    const SpeechRecognition=window.SpeechRecognition || window.webkitSpeechRecognition;
    if(!SpeechRecognition){notify('Speech recognition is unavailable in this browser. Type your question instead.');return;}
    try {
      recognizer?.abort?.();
      recognizer=new SpeechRecognition();recognizer.lang='en-US';recognizer.interimResults=false;recognizer.maxAlternatives=1;
      recognizer.onresult=(event)=>{const phrase=event.results?.[0]?.[0]?.transcript||'';if(activeCall) handleMessage(phrase);};
      recognizer.onerror=()=>notify('Microphone input failed or was denied; typing still works.');
      recognizer.start();notify('Browser microphone active. Speak a question.');
    }catch(_){notify('Could not start microphone. Try typing instead.');}
  });
  $('header-try').addEventListener('click',()=>{show('calls');startCall();});
  $('overview-try').addEventListener('click',()=>{show('calls');startCall();});
  document.querySelectorAll('[data-view-target]').forEach(item=>item.addEventListener('click',(event)=>{
    event.preventDefault();show(item.dataset.viewTarget);
  }));
  window.addEventListener('hashchange',()=>show(location.hash.replace('#','')));
  timeSlots();render();show(location.hash.replace('#','') || 'overview');
})();
