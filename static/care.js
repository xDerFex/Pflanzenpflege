export const tasks = ['Düngen','Besprühen','Blätter reinigen','Rückschnitt prüfen','Fortschritt festhalten','Umtopfen'];
export const taskKinds = {'Düngen':'Gedüngt','Besprühen':'Besprüht','Blätter reinigen':'Blätter gereinigt','Rückschnitt prüfen':'Rückschnitt geprüft','Fortschritt festhalten':'Fortschritt','Umtopfen':'Umgetopft'};
export const substrates = ['Pflanzenerde','Aroid-Mix','Mineralisch','Kakteen- und Sukkulentenerde','Wasser','Anderes Substrat'];
export const directions = ['Norden','Nordosten','Osten','Südosten','Süden','Südwesten','Westen','Nordwesten'];
const localDay = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
export function uid(){
  const bytes=new Uint8Array(16);
  if(globalThis.crypto?.getRandomValues)globalThis.crypto.getRandomValues(bytes);
  else for(let i=0;i<bytes.length;i++)bytes[i]=Math.floor(Math.random()*256);
  bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
  const hex=[...bytes].map(x=>x.toString(16).padStart(2,'0')).join('');
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}
export const today = () => localDay(new Date());
export const dateOnly = value => value ? String(value).slice(0,10) : '';
export const addDays = (value, days) => {const d=new Date(dateOnly(value)+'T12:00:00'); d.setDate(d.getDate()+Number(days)); return localDay(d)};
export const due = value => !!value && dateOnly(value)<=today();
export const formatDate = value => value ? new Intl.DateTimeFormat('de-DE',{day:'numeric',month:'short',year:'numeric'}).format(new Date(dateOnly(value)+'T12:00:00')) : '–';
export const name = plant => plant.nickname?.trim() || plant.species;
export const event = (kind, extra={}) => ({id:uid(),date:new Date().toISOString(),kind,note:'',...extra});
export function suggestedDays(task,species='') {let s=species.toLowerCase(); return {'Düngen':s.includes('kakt')||s.includes('aloe')?42:28,'Besprühen':3,'Blätter reinigen':28,'Rückschnitt prüfen':56,'Fortschritt festhalten':30,'Umtopfen':365}[task]||30}
export function starterPlans(species){return ['Düngen','Fortschritt festhalten'].map(task=>({task,days:suggestedDays(task,species),next:addDays(today(),suggestedDays(task,species))}))}
export function interval(p,day=today()){
  const s=(p.species||'').toLowerCase();let n=s.includes('alocasia')||s.includes('farn')?4:s.includes('aloe')||s.includes('kakt')?10:5;
  if((+p.potDiameter||12)<=10)n--;if((+p.potDiameter||12)>=21)n++;
  if(['Lockerer Aroid-Mix','Aroid-Mix','Mineralisch','Kakteen- und Sukkulentenerde'].includes(p.substrate))n--;
  if(p.substrate==='Wasser')return 3; // Water level check, not a soil-drying estimate.
  if(p.heightCM&&p.potDiameter&&p.heightCM/p.potDiameter>=4)n--;
  const winter=[11,12,1,2,3].includes(new Date(day+'T12:00:00').getMonth()+1),lamp=p.growLight&&(+p.lightHours||8)>=8;
  if(+p.windowDistance>=2&&!lamp)n++;if(winter&&!lamp)n++;if(winter&&p.nearHeater)n-=2;n=Math.max(2,n);
  let samples=[...((winter?p.winterCycles:p.summerCycles)||[])].sort((a,b)=>a-b);
  if(samples.length){const observed=Math.max(2,samples[Math.floor(samples.length/2)]-1);n=Math.max(2,Math.min(n+2,Math.floor((n+observed)/2)))}
  return n;
}
function recordCycle(p,when){if(!p.lastWatered)return;const days=Math.round((new Date(dateOnly(when)+'T12:00:00')-new Date(dateOnly(p.lastWatered)+'T12:00:00'))/86400000);if(days<1||days>35)return;if((p.events||[]).some(e=>e.kind==='Schon trocken'&&e.date>=p.lastWatered))return;const key=[11,12,1,2,3].includes(new Date(when).getMonth()+1)?'winterCycles':'summerCycles';p[key]=[...(p[key]||[]),days].slice(-3)}
export function water(p,observedDry=true){const now=new Date().toISOString();if(p.substrate==='Wasser'){p.lastWatered=now;(p.events||=[]).push(event('Wasserstand geprüft'));p.nextCheck=addDays(today(),interval(p));return p}if(observedDry){const isDue=due(p.nextCheck);const checkedWet=(p.events||[]).some(e=>e.kind==='Noch feucht'&&p.lastWatered&&e.date>=p.lastWatered);if(!isDue||dateOnly(p.nextCheck)===today()||checkedWet)recordCycle(p,now);if(!isDue)(p.events||=[]).push(event('Schon trocken'))}p.lastWatered=now;p.sensorSnoozeUntil=null;(p.events||=[]).push(event('Gegossen'));p.nextCheck=addDays(today(),interval(p));return p}
export function postponeCheck(p,days,wet){if(wet)(p.events||=[]).push(event(p.substrate==='Wasser'?'Wasserstand okay':'Noch feucht'));p.nextCheck=addDays(today(),days);p.sensorSnoozeUntil=p.nextCheck;return p}
export function finishTask(p,task){(p.events||=[]).push(event(taskKinds[task]));const plan=(p.taskPlans||[]).find(x=>x.task===task);if(plan){let days=plan.days;if(task==='Düngen'&&[11,12,1,2].includes(new Date().getMonth()+1)&&!(p.growLight&&(+p.lightHours||0)>=8))days=Math.max(30,days*2);plan.next=addDays(today(),days)}return p}
export function newPlant(){return {id:uid(),species:'',nickname:'',roomID:'',windowID:'',windowDirection:'',windowDistance:null,growLight:false,lightHours:null,ppfd:null,dli:null,potDiameter:12,heightCM:null,substrate:'Pflanzenerde',nearHeater:false,lastWatered:null,nextCheck:addDays(today(),5),photoName:null,events:[],winterCycles:[],summerCycles:[],taskPlans:[],sensor:null,milestoneDate:null,scientificName:null,careNotes:null,referenceImageURL:null,useReferenceImage:false,extraNotification:false}}
