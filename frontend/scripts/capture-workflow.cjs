/**
 * Refresh the homepage's annotated screenshots from the current production build.
 * Run npm run build first, then:
 * node scripts/capture-workflow.cjs <directory-containing-playwright-and-sharp> [browser-executable]
 *
 * Uses a disposable browser context, fabricated account/file data, and intercepted API
 * responses. No requests reach a real backend. These images illustrate the UI; this
 * capture is not evidence of backend upload, sharing, or decryption integration.
 */
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { generateKeyPairSync } = require('node:crypto');
const modules = process.argv[2];
if (!modules) throw new Error('Pass the directory containing playwright and sharp.');
const { chromium } = require(path.join(modules, 'playwright'));
const sharp = require(path.join(modules, 'sharp'));
const dist = path.resolve(__dirname, '../dist');
const output = path.resolve(__dirname, '../public/walkthrough');
const filename = 'Project notes.txt';
const envelope = data => ({success:true, status:'success', message:'Demo fixture', code:200, data});
const passphrase = 'ExampleOnly-not-a-real-secret';
const keyPair = generateKeyPairSync('rsa', {
  modulusLength:2048,
  publicKeyEncoding:{type:'spki', format:'pem'},
  privateKeyEncoding:{type:'pkcs8', format:'der'},
});
const publicKey = keyPair.publicKey;
const keyId = '00000000-0000-4000-8000-000000000002';

/** Seal the example private key with the app's own code, so the Unlock dialog really opens it. */
async function sealedExampleKey() {
  const { createJiti } = require(path.resolve(__dirname, '../node_modules/jiti'));
  const jiti = createJiti(__filename, { alias: { '@': path.resolve(__dirname, '../src') } });
  const { sealAccountKey } = await jiti.import(path.resolve(__dirname, '../src/utils/account-crypto.ts'));
  return sealAccountKey({
    privateKeyDer:new Uint8Array(keyPair.privateKey), passphrase, keyId,
    profileId:'00000000-0000-4000-8000-000000000005',
    bundleId:'00000000-0000-4000-8000-000000000006',
  });
}
const exampleFile = {
  file_id:'00000000-0000-4000-8000-000000000001',
  original_filename:filename, plaintext_size:1024, ciphertext_size:1024,
  mime_type:'text/plain', encryption_algorithm:'AES-256-GCM',
  status:'ACTIVE', owner:true, owner_username:'sam',
  created_at:'2026-09-05T10:00:00Z', updated_at:'2026-09-05T10:00:00Z',
};

/** Show the cipher <select> as a list of all its options, on its own line under its label. */
function expandCipherList(select) {
  select.size = select.options.length;
  Object.assign(select.style, {height:'auto', flexBasis:'100%', width:'100%', fontSize:'12px'});
  Object.assign(select.parentElement.style, {flexWrap:'wrap'});
}

/** Put the cipher <select> back as the page draws it. */
function collapseCipherList(select) {
  select.removeAttribute('size');
  for (const name of ['height', 'flex-basis', 'width', 'font-size']) select.style.removeProperty(name);
  select.parentElement.style.removeProperty('flex-wrap');
}

async function mark(page, locator, number) {
  await page.locator('[data-capture-mark]').evaluateAll(nodes => nodes.forEach(n => n.remove()));
  const box = await locator.boundingBox();
  if (!box) throw new Error('Cannot annotate an invisible control');
  await page.evaluate(({box, number}) => {
    const mark = document.createElement('div');
    mark.dataset.captureMark = '';
    Object.assign(mark.style, {
      position:'absolute', left:(box.x + scrollX - 5)+'px', top:(box.y + scrollY - 5)+'px',
      width:(box.width+10)+'px', height:(box.height+10)+'px',
      border:'3px solid #006dc7', borderRadius:'9px', pointerEvents:'none', zIndex:'9999',
      boxShadow:'0 0 0 4px #ffffffdd',
    });
    const badge = document.createElement('span');
    badge.textContent = number;
    Object.assign(badge.style, {
      position:'absolute', right:'-15px', top:'-19px', width:'28px', height:'28px',
      display:'grid', placeItems:'center', background:'#006dc7', color:'white',
      font:'bold 14px Arial', borderRadius:'50%', border:'2px solid white',
    });
    mark.append(badge);
    document.body.append(mark);
  }, {box, number});
}

/** Switch the interface language in place, so the page keeps its state (open dialogs, selected tab). */
async function setLanguage(page, code) {
  await page.evaluate(code => {
    const select = document.querySelector('[data-testid=language-switcher]');
    select.value = code;
    select.dispatchEvent(new Event('change', {bubbles:true}));
  }, code);
  await page.waitForTimeout(400);
}

/**
 * Capture one state twice: in English as `<name>.webp` and in Chinese as `<name>-zh.webp`. The
 * element handles are taken first, because the English locators (by role name) do not exist
 * once the page is in Chinese; the elements themselves stay the same.
 */
async function capture(page, area, name, target, number) {
  const areaHandle = await area.elementHandle();
  const targetHandle = await target.elementHandle();
  for (const [code, suffix] of [['en', ''], ['zh-CN', '-zh']]) {
    if (code !== 'en') await setLanguage(page, code);
    await areaHandle.scrollIntoViewIfNeeded();
    await page.mouse.move(0,0);
    await mark(page, targetHandle, number);
    const box = await areaHandle.boundingBox();
    const scroll = await page.evaluate(() => ({x:scrollX, y:scrollY}));
    const padding = 22;
    const png = await page.screenshot({clip:{
      x:Math.max(0,box.x+scroll.x-padding), y:Math.max(0,box.y+scroll.y-padding),
      width:box.width+padding*2, height:box.height+padding*2,
    }, animations:'disabled'});
    await sharp(png).webp({quality:88}).toFile(path.join(output, name+suffix+'.webp'));
    console.log('Captured '+name+suffix);
  }
  await setLanguage(page, 'en');
}

(async () => {
  fs.mkdirSync(output,{recursive:true});
  const sealed = await sealedExampleKey();
  const server = http.createServer((req,res) => {
    const name = path.resolve(dist, '.'+new URL(req.url,'http://localhost').pathname);
    if (!name.startsWith(dist+path.sep) && name!==dist) {res.writeHead(403).end();return;}
    const file = fs.existsSync(name) && fs.statSync(name).isFile() ? name : path.join(dist,'index.html');
    res.setHeader('Content-Type', ({'.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.webp':'image/webp'})[path.extname(file)] || 'text/html');
    res.end(fs.readFileSync(file));
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  let browser;
  try {
    browser = await chromium.launch({headless:true, ...(process.argv[3] ? {executablePath:process.argv[3]} : {})});
    const context = await browser.newContext({viewport:{width:1200,height:1100}, deviceScaleFactor:1.5, locale:'en-GB', timezoneId:'UTC', reducedMotion:'reduce'});
    await context.addInitScript(() => {
      localStorage.setItem('access_token','local-screenshot-fixture');
      localStorage.setItem('auth_username','sam');
      localStorage.setItem('theme','light');
    });
    let recipient = false;
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.pathname.includes('/api/v1/')) {
        const api = url.pathname.split('/api/v1')[1];
        let data;
        if (api === '/auth/me') data = {user:{user_id:'demo-sam',username:recipient?'alex':'sam',email:'demo@example.invalid',roles:['USER']}};
        else if (api === '/keys/me') data = {key:{key_id:keyId,public_key_pem:publicKey}, ...sealed};
        else if (api === '/recovery/public-key') data = {key_id:'00000000-0000-4000-8000-000000000003',public_key_pem:publicKey,status:'ACTIVE'};
        else if (api === '/files/upload') data = {};
        else if (api === '/files') {
          // sam owns the file and has nothing shared with him; alex sees it only as shared.
          const shared = url.searchParams.get('scope') === 'shared';
          const items = shared === recipient ? [{...exampleFile,owner:!recipient}] : [];
          data = {items,page:1,page_size:100,total:items.length,owned_total:recipient?0:1,shared_total:recipient?1:0};
        }
        else if (api === '/files/folders') data = {items:[]};
        else if (api.endsWith('/shared-users')) data = {users:[]};
        else if (api === '/keys/users/by-identifier/alex/active') data = {user_id:'demo-alex',key_id:'00000000-0000-4000-8000-000000000004',public_key_pem:publicKey};
        else {await route.fulfill({status:404,json:{message:'Unconfigured screenshot fixture'}});return;}
        await route.fulfill({status:200,json:envelope(data)});
      } else if (url.hostname==='127.0.0.1' && url.port===String(server.address().port)) await route.continue();
      else await route.abort();
    });
    const page = await context.newPage();
    const base = 'http://127.0.0.1:'+server.address().port;
    await page.goto(base+'/upload');
    const upload = page.getByTestId('encrypt-card');
    const columns = upload.locator(':scope > div > div');
    const select = page.locator('label').filter({hasText:'Select Files'});
    await capture(page,upload,'01-select',select,'1');
    await capture(page,columns.nth(0),'01-select-mobile',select,'1');
    await page.locator('input[type=file]').setInputFiles({name:filename,mimeType:'text/plain',buffer:Buffer.alloc(1024,65)});
    // The cipher list is a native <select>, whose pop-up the OS draws outside the page, so a
    // screenshot never shows it. For this one capture the same element is shown as a list of all
    // its options (size = option count, on its own line under its label), then put back.
    const cipher = page.locator('#content-algorithm');
    await cipher.evaluate(expandCipherList);
    await capture(page,upload,'01b-cipher',cipher,'2');
    await capture(page,columns.nth(1),'01b-cipher-mobile',cipher,'2');
    await cipher.evaluate(collapseCipherList);
    const encrypt = page.getByRole('button',{name:'Start Encryption',exact:true});
    await capture(page,upload,'02-encrypt',encrypt,'3');
    await capture(page,columns.nth(1),'02-encrypt-mobile',encrypt,'3');
    await encrypt.click();
    await page.getByRole('button',{name:'View Encrypted Files',exact:true}).click();
    await page.getByText(filename,{exact:true}).waitFor();
    const files = page.getByTestId('files-card');
    const share = page.getByTitle('Share',{exact:true});
    await capture(page,files,'03-file',share,'4');
    await page.setViewportSize({width:600,height:1100});
    await capture(page,files,'03-file-mobile',share,'4');
    await page.setViewportSize({width:1200,height:1100});
    await share.click();
    const modal = page.locator('.fixed.inset-0 > .max-w-md');
    await page.getByRole('heading',{name:'Unlock your files'}).waitFor();
    await page.getByPlaceholder('Your encryption passphrase').fill(passphrase);
    const unlock = page.getByRole('button',{name:'Unlock',exact:true});
    await capture(page,modal,'05-unlock',unlock,'5');
    await page.setViewportSize({width:600,height:1100});
    await capture(page,modal,'05-unlock-mobile',unlock,'5');
    await page.setViewportSize({width:1200,height:1100});
    await unlock.click();
    await page.getByText('Nobody yet — only you can open this file.').waitFor();
    await page.getByPlaceholder('Their username/ Email address on Secureview.').fill('alex');
    await modal.getByRole('button',{name:'Share',exact:true}).click();
    // The share is confirmed against the recipient's key fingerprint before anything is sent.
    await page.getByTestId('recipient-fingerprint').waitFor();
    const submitShare = modal.getByRole('button',{name:'Confirm and share',exact:true});
    await capture(page,modal,'04-recipient',submitShare,'6');
    await page.setViewportSize({width:600,height:1100});
    await capture(page,modal,'04-recipient-mobile',submitShare,'6');
    await page.setViewportSize({width:1200,height:1100});
    recipient = true;
    await page.goto(base+'/files');
    await page.getByRole('button',{name:/Shared with me/}).click();
    await page.getByText('Shared by sam').waitFor();
    const download = page.getByTitle('Download and decrypt',{exact:true});
    await capture(page,files,'06-download',download,'7');
    await page.setViewportSize({width:600,height:1100});
    await capture(page,files,'06-download-mobile',download,'7');
    await context.close();
  } finally {
    if (browser) await browser.close();
    server.close();
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
