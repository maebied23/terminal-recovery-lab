// Teaching overlays are rendered in an isolated browser page before capture.
// No application source, stored state, or existing image is edited.
import {chromium} from 'playwright';
import fs from 'node:fs/promises';
const out='../docs/visual-walkthrough';await fs.mkdir(out,{recursive:true});
const browser=await chromium.launch({headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1200},deviceScaleFactor:1});
const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.goto('http://127.0.0.1:8790',{waitUntil:'domcontentloaded'});
await page.getByRole('button',{name:'Terminal overview',exact:true}).click();
await page.getByRole('heading',{name:'One terminal. Connected decisions.'}).waitFor();
// Read-only replay gives reproducible pictures regardless of the user's live run.
await page.getByRole('button',{name:'Evidence',exact:true}).click();
await page.getByLabel('Historical revision').fill('0');
await page.getByRole('button',{name:'Inspect snapshot'}).click();
await page.getByText('Read-only snapshot · revision 0').waitFor();
async function clear(){await page.evaluate(()=>document.querySelectorAll('[data-teaching-overlay]').forEach(el=>el.remove()));}
async function annotate(items){
 await clear();await page.evaluate(items=>{
  for(const {selector,number,label} of items){
   const target=document.querySelector(selector);if(!target)throw Error('Missing '+selector);
   const r=target.getBoundingClientRect();const box=document.createElement('div');box.dataset.teachingOverlay='true';
   Object.assign(box.style,{position:'absolute',left:`${r.left+scrollX-3}px`,top:`${r.top+scrollY-3}px`,width:`${r.width+6}px`,height:`${r.height+6}px`,border:'3px solid #f7a83e',borderRadius:'7px',pointerEvents:'none',zIndex:10000});
   const badge=document.createElement('span');badge.textContent=number;
   Object.assign(badge.style,{position:'absolute',left:'-13px',top:'-16px',display:'grid',placeItems:'center',width:'32px',height:'32px',borderRadius:'50%',background:'#ffba52',border:'2px solid #152a30',color:'#152a30',font:'bold 18px sans-serif',boxShadow:'0 2px 8px #0004'});
   box.append(badge);document.body.append(box);
  }
  const legend=document.createElement('div');legend.dataset.teachingOverlay='true';
  Object.assign(legend.style,{marginLeft:'216px',padding:'22px 30px',background:'#142b32',color:'#fff',font:'14px/1.5 sans-serif',borderTop:'4px solid #f7a83e'});
  const title=document.createElement('div');title.textContent='TEACHING ANNOTATIONS • Recorded starting state: main / revision 0';title.style.cssText='color:#ffc361;font-size:12px;font-weight:bold;letter-spacing:1px;margin-bottom:12px';legend.append(title);
  for(const item of items){const p=document.createElement('p');p.style.cssText='display:inline-block;vertical-align:top;width:48%;margin:5px 1% 5px 0';p.textContent=`${item.number}. ${item.label}`;legend.append(p)}document.body.append(legend);
 },items);
}
await annotate([
 {selector:'.clockbar',number:1,label:'Clock and revision: this is an unchanged, read-only starting snapshot.'},
 {selector:'.metrics',number:2,label:'Tracked cargo, running work, completed commitments, and failures/holds.'},
 {selector:'.map-wrap',number:3,label:'Physical context: vessels → quay → yard → road and rail.'},
 {selector:'.commitment-row',number:4,label:'Destinations and deadlines: why the handling work matters.'}
]);
await page.screenshot({path:`${out}/01-orientation.png`,fullPage:true});
await annotate([
 {selector:'[aria-label="Inspect QC-1"]',number:1,label:'QC: quay crane. The vessel-side lifting resource.'},
 {selector:'[aria-label="Inspect TT-2"]',number:2,label:'TT: terminal tractor. Horizontal transport between handling points.'},
 {selector:'[aria-label="Inspect YC-1"]',number:3,label:'YC: yard crane. Accessing and rearranging stacked cargo.'},
 {selector:'[aria-label="Inspect NORTH-RAIL"]',number:4,label:'Rail service: a destination with a cutoff, not an equipment unit.'}
]);
await page.locator('.map-wrap').screenshot({path:`${out}/02-equipment.png`});
await clear();await page.getByRole('button',{name:'Inspect A1',exact:true}).click();
await page.locator('.inspector h2').filter({hasText:'A1'}).waitFor();
await annotate([
 {selector:'.inspector .inspect-title',number:1,label:'We selected one location: A1. The inspector follows that selection.'},
 {selector:'.inspector .linked-item:nth-of-type(1)',number:2,label:'Top container CT-0122: it obstructs access to CT-0121.'},
 {selector:'.inspector .linked-item:nth-of-type(2)',number:3,label:'CT-0121 is below the cover. Its departure depends on clearing access.'},
 {selector:'.inspector .reason-list',number:4,label:'Derived blockers explain why connected work cannot yet proceed.'}
]);
await page.screenshot({path:`${out}/03-stack.png`,fullPage:true});
await clear();await page.locator('.inspector button').filter({hasText:'MV-001 · retrieve'}).click();
await page.locator('.inspector h2').filter({hasText:'MV-001'}).waitFor();
await annotate([
 {selector:'.inspector dl',number:1,label:'Move MV-001: pick up at A1, deliver to RAIL-1, assigned to YC-1.'},
 {selector:'.inspector .reason-list',number:2,label:'Two different checks: prerequisite incomplete and physical obstruction.'},
 {selector:'.inspector .linked-item:not(.two-line)',number:3,label:'MV-013 is the predecessor: move the covering container to D4 first.'}
]);
await page.screenshot({path:`${out}/04-move.png`,fullPage:true});
await fs.writeFile(`${out}/capture.json`,JSON.stringify({captured_at:new Date().toISOString(),run:'main',revision:0,mutations:false,errors},null,2));
console.log(JSON.stringify({out,errors}));await browser.close();
