import {chromium} from 'playwright';
import fs from 'node:fs/promises';
const base='http://127.0.0.1:8790';
const browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1280,height:800},reducedMotion:'reduce'});const errors=[];page.on('pageerror',e=>errors.push(e.message));const check=(v,m)=>{if(!v)throw Error(m)};
try{
const {run}=JSON.parse(await fs.readFile('../docs/frontend-redesign/walkthrough.json','utf8'));
await page.goto(`${base}/?run=${run}&page=Operations&departure=NORTH-RAIL&cargo=CT-0121&stage=Compare%20%26%20book`);
await page.locator('.schedule-candidates').waitFor();
const competitor=page.locator('.booking-lane button').filter({hasText:'133'}).first();await competitor.click();
check((await page.locator('.selected-bundle').allTextContents()).every(t=>t.trim()==='133'),'competing job selection highlights its bundle');
check(await page.getByLabel('Case container').inputValue()==='CT-0121','competing job does not change case');
await page.getByRole('button',{name:'Review schedule for approval',exact:true}).click();await page.keyboard.press('Tab');await page.keyboard.press('Tab');check(await page.evaluate(()=>!!document.activeElement.closest('[role=dialog]')),'focus stays within review');await page.keyboard.press('Escape');check(await page.getByRole('dialog').count()===0,'escape closes review');
await page.getByRole('button',{name:'Work & commitments',exact:true}).click();await page.locator('.resource-competition').waitFor();await page.goBack();await page.getByRole('heading',{name:'North Rail',exact:true}).waitFor();check(new URL(page.url()).searchParams.get('stage')==='Compare & book','back restores case stage');
await page.goto(`${base}/?run=eval-daa648df&page=Scenario%20lab&departure=NORTH-RAIL&cargo=CT-0121`);
await page.getByRole('button',{name:'Evaluation',exact:true}).click();await page.getByLabel('Evaluation report').waitFor({timeout:20000});await page.getByLabel('Evaluation report').selectOption('25954807-cd69-41f9-a9d9-2c7a8443fa24');await page.locator('.evaluation-cards').waitFor();check((await page.locator('.evaluation-panel').innerText()).toLowerCase().includes('loss'),'measured losses remain visible');
await page.getByRole('button',{name:'Ask the terminal',exact:true}).click();await page.getByLabel('Question for terminal assistant').fill('What did the evaluation show?');await page.locator('.assistant-form').getByRole('button',{name:'Ask',exact:true}).click();await page.locator('.assistant-answer').waitFor({timeout:20000});check(await page.locator('.assistant-answer a').count()>0,'assistant keeps citations');
await page.screenshot({path:'../docs/frontend-redesign/12-evaluation-assistant.png'});
await page.setViewportSize({width:760,height:800});await page.goto(`${base}/?run=${run}&page=Operations&departure=NORTH-RAIL&cargo=CT-0121`);await page.getByLabel('Case container').waitFor();check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'760px no document overflow');
await fs.writeFile('../docs/frontend-redesign/preserved-capabilities.json',JSON.stringify({errors,checks:['competing-job bundle selection','case preserved','dialog keyboard focus','escape','browser Back stage restoration','saved evaluation losses','assistant citations','760px overflow']},null,2));check(!errors.length,JSON.stringify(errors));console.log('Preserved capability browser checks passed');
}finally{await browser.close()}
