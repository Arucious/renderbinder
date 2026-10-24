const {launchBrowser} = require('./browser_helpers.cjs');
const assert = require('node:assert/strict');
const path = require('node:path');
const base = 'http://127.0.0.1:8766', qa = path.resolve('.qa');
let browser, original;
async function api(route, method='GET', body) {
  const response = await fetch(base+'/api'+route, {method, headers:body?{'Content-Type':'application/json'}:{}, body:body?JSON.stringify(body):undefined});
  assert.ok(response.ok, await response.clone().text()); return response.json();
}
(async()=>{
  original = await api('/settings');
  assert.equal(original.data_dir, path.join(qa,'data'), 'Only the QA library may be modified');
  await api('/settings','PUT',{roots:[...original.roots,path.join(qa,'negative-status-source')],comfy_url:original.comfy_url});
  const deadline = Date.now()+30000;
  while (Date.now()<deadline) {
    if ((await api('/images?q=negative_')).items.filter(i=>i.filename.startsWith('negative_')).length===5) break;
    await new Promise(r=>setTimeout(r,200));
  }
  browser = await launchBrowser();
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base);
  for (const [state,label,message] of [
    ['present',null,'blurry, watermark'],
    ['empty','Explicitly empty','Negative prompt was explicitly left empty in the workflow.'],
    ['zeroed','Zeroed out','The workflow zeroed out negative conditioning.'],
    ['empty_and_zeroed','Empty / zeroed out','All recorded negative conditioning is explicitly empty or zeroed out.'],
    ['unavailable',null,'No negative prompt could be determined from the stored metadata.'],
  ]) {
    const name='negative_'+state+'.png';
    const item=(await api('/images?q='+name)).items.find(i=>i.filename===name);
    assert.ok(item,name);
    const detail=await api('/images/'+item.id);
    assert.equal(detail.metadata.negative_status.state,state);
    await page.getByRole('textbox',{name:'Search library'}).fill(name);
    await page.getByRole('button',{name:'Inspect '+name,exact:true}).click();
    const block=page.getByRole('dialog',{name,exact:true}).locator('.prompt-block.negative');
    assert.equal(await block.locator('p').textContent(),message);
    assert.equal(await block.locator('.prompt-state-label').count(),label?1:0);
    if(label) assert.equal(await block.locator('.prompt-state-label').textContent(),label);
    assert.equal(await block.getByRole('button',{name:'Copy negative prompt'}).isDisabled(),state!=='present');
    if(state==='empty') await page.screenshot({path:path.join(qa,'negative-empty-desktop.png'),fullPage:true});
    if(state==='zeroed') {
      await page.setViewportSize({width:390,height:844});
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
      await page.screenshot({path:path.join(qa,'negative-zeroed-mobile.png'),fullPage:true});
      await page.setViewportSize({width:1440,height:1000});
    }
    await page.keyboard.press('Escape');
  }
  assert.deepEqual(errors,[]);
  console.log('Negative status browser checks passed: explicit empty, zeroed, mixed, real text, unavailable, copy state, desktop/mobile.');
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{
  await browser?.close();
  if(original) await api('/settings','PUT',{roots:original.roots,comfy_url:original.comfy_url});
});
