// Run after browser_smoke.cjs against the isolated QA library on port 8766.
const {launchBrowser} = require('./browser_helpers.cjs');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = 'http://127.0.0.1:8766';
const qa = path.resolve('.qa');
const duplicate = path.join(qa, 'sources', 'experiments', 'qa_duplicate_prompt.png');
const emptySource = path.join(qa, 'empty-source');
let browser, page, originalSettings;
async function api(route, method = 'GET', body) {
  const response = await fetch(base + '/api' + route, {method, headers: body ? {'Content-Type':'application/json'} : {}, body: body ? JSON.stringify(body) : undefined});
  assert.ok(response.ok, await response.clone().text());
  return response.json();
}
async function until(predicate) {
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {if (await predicate()) return; await new Promise(r => setTimeout(r, 200));}
  throw new Error('Timed out waiting for the QA index');
}
(async () => {
  const config = await api('/settings');
  assert.equal(config.data_dir, path.join(qa, 'data'), 'Only the isolated QA library may be modified');
  originalSettings = config;
  if (fs.existsSync(duplicate)) fs.unlinkSync(duplicate);
  await until(async () => (await api('/images')).total === 12);
  fs.mkdirSync(emptySource, {recursive:true});
  browser = await launchBrowser();
  const context = await browser.newContext({viewport:{width:1440,height:1000}, permissions:['clipboard-read','clipboard-write']});
  page = await context.newPage();
  const errors = [];
  let navigations = 0;
  page.on('pageerror', error => errors.push(error.message));
  page.on('framenavigated', frame => {if (frame === page.mainFrame()) navigations++;});
  await page.goto(base);
  await page.getByRole('button', {name:/^Prompt library/}).click();
  await page.waitForFunction(() => document.querySelectorAll('.prompt-group-card').length === 12);
  fs.copyFileSync(path.join(qa,'sources','landscapes','alpine_stillness_00001.png'), duplicate);
  await page.getByRole('button',{name:'View 2 images',exact:true}).waitFor();
  assert.equal(await page.locator('.prompt-group-card').count(),12);
  assert.ok((await page.locator('.result-count').innerText()).includes('13 files'));
  const groups = await api('/images?unique_prompts=true');
  assert.equal(groups.total,12);assert.equal(groups.image_total,13);
  const repeated = groups.items.find(item => item.image_count === 2);
  assert.ok(repeated);
  const card = page.locator('.prompt-group-card').filter({has:page.getByRole('button',{name:'View 2 images',exact:true})});
  await card.getByRole('button',{name:'Copy prompt',exact:true}).click();
  const fullPrompt = (await api('/images/' + repeated.id)).positive;
  await until(async () => (await page.evaluate(() => navigator.clipboard.readText())) === fullPrompt);
  await page.screenshot({path:path.join(qa,'prompt-groups-desktop.png'),fullPage:true});
  await card.getByRole('button',{name:'View 2 images',exact:true}).click();
  await page.getByRole('heading',{name:/Files using prompt/}).waitFor();
  await page.waitForFunction(() => document.querySelectorAll('.image-card').length === 2);
  await page.getByRole('button',{name:'Back to prompt library',exact:true}).click();
  await page.waitForFunction(() => document.querySelectorAll('.prompt-group-card').length === 12);
  assert.equal(await page.getByRole('button',{name:'Select',exact:true}).count(),0);
  const beforeNavigations = navigations;
  await api('/settings','PUT',{roots:[...config.roots,emptySource],comfy_url:config.comfy_url});
  await page.waitForFunction(expected => Array.from(document.querySelectorAll('.source-path')).some(el => el.textContent === expected),emptySource);
  assert.equal(await page.locator('.source-root').count(),config.roots.length+1);
  assert.equal(navigations,beforeNavigations,'Adding a source must not reload the page');
  await api('/settings','PUT',{roots:config.roots,comfy_url:config.comfy_url});
  await page.waitForFunction(expected => !Array.from(document.querySelectorAll('.source-path')).some(el => el.textContent === expected),emptySource);
  assert.equal(navigations,beforeNavigations,'Removing a source must not reload the page');
  const text = await page.locator('body').innerText();
  assert.ok(!/YOUR IDEAS, REMEMBERED|Every image has a story|Made for the things you make/.test(text));
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  await page.screenshot({path:path.join(qa,'prompt-groups-mobile.png'),fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('Prompt group browser checks passed: duplicates grouped, correct counts, full-text copy, group drilldown/back, live add/remove empty sources without reload, plain interface text, mobile layout.');
})().catch(async error => {
  console.error(error);
  if (page) await page.screenshot({path:path.join(qa,'prompt-group-error.png'),fullPage:true}).catch(()=>{});
  process.exitCode = 1;
}).finally(async () => {
  if (originalSettings) {
    await api('/settings','PUT',{roots:originalSettings.roots,comfy_url:originalSettings.comfy_url}).catch(()=>{});
    if (fs.existsSync(duplicate)) fs.unlinkSync(duplicate);
  }
  await browser?.close();
});
