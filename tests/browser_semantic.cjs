// Explicit integration check against the isolated QA library. Downloads BGE if needed.
const {launchBrowser} = require('./browser_helpers.cjs');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const qa = path.resolve('.qa'), base='http://127.0.0.1:8766';
let browser,page,originalSettings,originalSemantic;
async function api(route,method='GET',body) {
  const response=await fetch(base+'/api'+route,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
  assert.ok(response.ok,await response.clone().text());return response.json();
}
async function until(predicate,timeout=90000) {
  const end=Date.now()+timeout;
  while(Date.now()<end){if(await predicate())return;await new Promise(r=>setTimeout(r,200));}
  throw new Error('Timed out waiting for semantic state');
}
(async()=>{
  originalSettings=await api('/settings');
  assert.equal(originalSettings.data_dir,path.join(qa,'data'),'Only isolated QA data may be modified');
  originalSemantic=(await api('/semantic')).config;
  await api('/semantic/settings','PUT',{...originalSemantic,enabled:false});
  await api('/settings','PUT',{roots:[...originalSettings.roots,path.join(qa,'prompt-diff-source')],comfy_url:originalSettings.comfy_url});
  await until(async()=> (await api('/images?unique_prompts=true&q=Prompt%20comparison%20fixture')).total===2);
  browser=await launchBrowser();
  page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];let originals=0,generations=0;
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(/\/original(?:\?|$)/.test(r.url()))originals++;if(/\/queue$/.test(r.url()))generations++;});
  await page.goto(base);
  await page.getByRole('button',{name:/^Prompt library/}).click();
  await page.getByRole('textbox',{name:'Search library'}).fill('Prompt comparison fixture');
  await page.waitForFunction(()=>document.querySelectorAll('.prompt-group-card').length===2);
  await page.getByRole('button',{name:'Find similar prompts',exact:true}).first().click();
  let related=page.getByRole('dialog',{name:'Similar prompts',exact:true});
  await related.locator('.similar-result').first().waitFor();
  assert.match(await related.innerText(),/Ranked by text similarity/);
  await related.getByRole('button',{name:'Compare variation',exact:true}).first().click();
  await page.getByRole('dialog',{name:'Compare prompts',exact:true}).locator('.diff-added').first().waitFor();
  await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Find similar prompts',exact:true}).first().click();
  await related.getByRole('button',{name:'Model settings',exact:true}).click();
  const settings=page.getByRole('dialog',{name:'Settings & sources',exact:true});
  const section=settings.locator('.semantic-settings');
  await section.getByLabel('Embedding model',{exact:true}).selectOption('embeddinggemma2');
  assert.match(await section.innerText(),/270M text parameters/);
  await section.getByLabel('Embedding model',{exact:true}).selectOption('bge-small');
  await section.getByLabel('Enable semantic matching',{exact:true}).check();
  await section.getByRole('button',{name:'Save model & build embeddings',exact:true}).click();
  await until(async()=> {const s=await api('/semantic');if(s.state==='error')throw new Error(s.error);return s.state==='ready';});
  await until(async()=> (await section.innerText()).includes('prompts cached'));
  await section.scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(qa,'semantic-settings-desktop.png'),fullPage:true});
  // Bring your own model: load the already downloaded preset as a local folder.
  const snapshots=path.join(qa,'data','models','models--BAAI--bge-small-en-v1.5','snapshots');
  const localModel=path.join(snapshots,fs.readdirSync(snapshots)[0]);
  await section.getByLabel('Embedding model',{exact:true}).selectOption('custom');
  await section.getByLabel('Model folder or Hugging Face ID',{exact:true}).fill(localModel);
  await section.getByLabel('Text prefix').fill('');
  await section.getByRole('button',{name:'Save model & build embeddings',exact:true}).click();
  await until(async()=> {const s=await api('/semantic');if(s.state==='error')throw new Error(s.error);return s.state==='ready'&&s.config.model==='custom';});
  await section.getByLabel('Embedding model',{exact:true}).selectOption('bge-small');
  await section.getByRole('button',{name:'Save model & build embeddings',exact:true}).click();
  await until(async()=> {const s=await api('/semantic');if(s.state==='error')throw new Error(s.error);return s.state==='ready'&&s.config.model==='bge-small';});
  await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'Find similar prompts',exact:true}).first().click();
  await related.locator('.similar-result').first().waitFor();
  assert.match(await related.innerText(),/Ranked by semantic and text similarity/);
  await related.getByLabel('Match by').selectOption('semantic');
  await until(async()=> (await related.innerText()).includes('Ranked by semantic similarity'));
  assert.match(await related.innerText(),/Meaning 0\./);
  await page.screenshot({path:path.join(qa,'similar-prompts-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
  await page.screenshot({path:path.join(qa,'similar-prompts-mobile.png'),fullPage:true});
  await related.getByRole('button',{name:'Compare variation',exact:true}).first().click();
  await page.getByRole('dialog',{name:'Compare prompts',exact:true}).locator('.prompt-diff-panel').first().waitFor();
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
  assert.equal(originals,0);assert.equal(generations,0);assert.deepEqual(errors,[]);
  console.log('Semantic browser checks passed: text fallback, both model options, real BGE indexing, custom local model, model switching, semantic/hybrid rankings, direct diff, desktop/mobile, no original-image or generation requests.');
})().catch(async e=>{console.error(e);if(page)await page.screenshot({path:path.join(qa,'semantic-error.png'),fullPage:true}).catch(()=>{});process.exitCode=1;}).finally(async()=>{
  if(originalSemantic)await api('/semantic/settings','PUT',{...originalSemantic,enabled:false}).catch(()=>{});
  if(originalSettings)await api('/settings','PUT',{roots:originalSettings.roots,comfy_url:originalSettings.comfy_url}).catch(()=>{});
  await browser?.close();
});
