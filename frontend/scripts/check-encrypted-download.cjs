/**
 * Browser smoke test against a production build and fabricated API responses.
 * npm run build
 * node scripts/check-encrypted-download.cjs <directory-containing-playwright> [browser-executable]
 * This checks the browser download flow; it is not live-backend or deployment evidence.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');

if (!process.argv[2]) throw new Error('Pass the directory containing playwright.');
const { chromium } = require(path.resolve(process.argv[2], 'playwright'));
const dist = path.resolve(__dirname, '../dist');
const envelope = data => ({ success: true, status: 'success', message: 'Fixture', code: 200, data });
const ciphertext = Buffer.from([0, 255, 128, 13, 10, 1]);
const summary = (id, owner) => ({
  file_id: id, original_filename: owner ? 'Owned notes.txt' : 'Shared notes.txt',
  plaintext_size: ciphertext.length, ciphertext_size: ciphertext.length,
  mime_type: 'text/plain', encryption_algorithm: 'AES-256-GCM', status: 'ACTIVE',
  owner, owner_username: owner ? 'sam' : 'alex',
  created_at: '2026-09-10T00:00:00Z', updated_at: '2026-09-10T00:00:00Z',
});
const items = [
  summary('00000000-0000-4000-8000-000000000001', true),
  summary('00000000-0000-4000-8000-000000000002', false),
];

async function readDownload(download) {
  const stream = await download.createReadStream();
  const chunks = [];
  for await (const chunk of stream) chunks.push(chunk);
  return Buffer.concat(chunks);
}

(async () => {
  const server = http.createServer((req, res) => {
    const filename = path.resolve(dist, '.' + new URL(req.url, 'http://localhost').pathname);
    if (!filename.startsWith(dist + path.sep) && filename !== dist) {
      res.writeHead(403).end();
      return;
    }
    const file = fs.existsSync(filename) && fs.statSync(filename).isFile() ? filename : path.join(dist, 'index.html');
    res.setHeader('Content-Type', ({ '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.webp': 'image/webp' })[path.extname(file)] || 'text/html');
    res.end(fs.readFileSync(file));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({ headless: true, ...(process.argv[3] ? { executablePath: process.argv[3] } : {}) });
    const base = 'http://127.0.0.1:' + server.address().port;
    for (const width of [390, 1280]) {
      const context = await browser.newContext({ viewport: { width, height: 900 }, acceptDownloads: true });
      const requests = [];
      let failureStatus = 0;
      await context.addInitScript(() => {
        localStorage.setItem('access_token', 'local-download-fixture');
        localStorage.setItem('auth_username', 'sam');
        localStorage.setItem('theme', 'light');
      });
      await context.route('**/*', async route => {
        const request = route.request();
        const url = new URL(request.url());
        if (url.pathname.includes('/api/v1/')) {
          const api = url.pathname.split('/api/v1')[1];
          requests.push({ api, method: request.method(), body: request.postData(), auth: request.headers().authorization });
          if (api === '/auth/me') {
            await route.fulfill({ json: envelope({ user: { user_id: 'fixture-sam', username: 'sam', email: 'sam@example.invalid', roles: ['USER'] } }) });
          } else if (api === '/files') {
            await route.fulfill({ json: envelope({ items, page: 1, page_size: 100, total: items.length }) });
          } else if (api.endsWith('/download')) {
            if (failureStatus) {
              await route.fulfill({ status: failureStatus, json: { message: failureStatus === 404 ? 'File unavailable' : 'File integrity verification failed' } });
            } else {
              await route.fulfill({ contentType: 'application/octet-stream', body: ciphertext });
            }
          } else {
            await route.fulfill({ status: 500, json: { message: 'Unexpected fixture API request' } });
          }
        } else if (url.origin === base) await route.continue();
        else await route.abort();
      });
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      let downloadCount = 0;
      page.on('download', () => downloadCount++);
      await page.goto(base + '/files');
      const encryptedButton = page.getByRole('button', { name: 'Download encrypted', exact: true });
      for (const file of items) {
        if (!file.owner) await page.getByRole('button', { name: /Shared with me/ }).click();
        const pending = page.waitForEvent('download');
        await encryptedButton.click();
        const download = await pending;
        assert.equal(download.suggestedFilename(), file.original_filename + '.ciphertext');
        assert.deepEqual(await readDownload(download), ciphertext);
        await page.getByText(`Encrypted download started for ${file.original_filename}. The file remains encrypted.`, { exact: true }).waitFor();
        assert.equal(await page.getByRole('heading', { name: 'Unlock your files' }).count(), 0);
        const box = await encryptedButton.boundingBox();
        assert.ok(box && box.x >= 0 && box.x + box.width <= width, 'Encrypted action must remain reachable in the viewport');
      }
      assert.equal(downloadCount, 2);
      for (const status of [404, 409]) {
        failureStatus = status;
        await encryptedButton.click();
        await page.locator('#manage p.text-destructive').filter({ hasText: `Request failed with status code ${status}` }).waitFor();
        assert.equal(downloadCount, 2, 'Failed downloads must not save an error body');
        assert.equal(await encryptedButton.isEnabled(), true);
        assert.equal(await page.getByRole('heading', { name: 'Unlock your files' }).count(), 0);
      }
      const downloads = requests.filter(request => request.api.endsWith('/download'));
      assert.equal(downloads.length, 4);
      for (const request of downloads) {
        assert.equal(request.method, 'POST');
        assert.equal(request.auth, 'Bearer local-download-fixture');
        assert.ok(!request.body, 'Encrypted downloads must not submit key material');
      }
      assert.deepEqual(requests.filter(request => request.api.startsWith('/keys')), []);
      await page.getByRole('button', { name: 'Download and decrypt', exact: true }).click();
      await page.getByRole('heading', { name: 'Unlock your files' }).waitFor();
      assert.equal(requests.filter(request => request.api.endsWith('/download')).length, 4);
      assert.deepEqual(errors, []);
      console.log(`PASS ${width}px: locked owner/recipient ciphertext saves, authorization header, failure handling, original unlock flow`);
      await context.close();
    }
  } finally {
    if (browser) await browser.close();
    server.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
