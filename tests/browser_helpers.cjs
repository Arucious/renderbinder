// Installed project dependency by default; desktop sessions may supply a package path.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || '../frontend/node_modules/playwright');
const channel = process.env.BROWSER_CHANNEL || (process.platform === 'win32' ? 'msedge' : 'chrome');
function launchBrowser() {
  return chromium.launch({channel,headless:true});
}
module.exports = {launchBrowser};
