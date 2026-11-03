async (page) => {
    const base = __DEMO_BASE__;
    const output = __CAPTURE_OUTPUT__;
    const errors = [];
    const failures = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('response', response => {
        if (response.url().startsWith(base) && response.status() >= 400) {
            failures.push(`${response.status()} ${new URL(response.url()).pathname}`);
        }
    });
    await page.context().route('**/*', route => {
        const url = route.request().url();
        if (url.startsWith(base + '/') || url.startsWith('data:') || url.startsWith('blob:')) return route.continue();
        if (url.startsWith('https://fonts.googleapis.com/')) return route.fulfill({ status: 200, contentType: 'text/css', body: '' });
        return route.abort();
    });
    await page.addInitScript(() => {
        localStorage.setItem('vta_theme_preference', JSON.stringify('light'));
        localStorage.setItem('vta_app_shell_sidebar', JSON.stringify({ mode: 'expanded', groups: {} }));
        localStorage.setItem('vta_sidebar_width', '280');
        localStorage.setItem('vta_toc_pinned', 'true');
    });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.emulateMedia({ colorScheme: 'light', reducedMotion: 'reduce' });
    const results = [];
    async function open(path) {
        await page.goto(base + path);
        await page.evaluate(() => document.fonts.ready);
    }
    async function capture(name) {
        await page.evaluate(() => document.activeElement?.blur());
        await page.waitForTimeout(250);
        await page.screenshot({ path: `${output}/${name}.png`, animations: 'disabled' });
        results.push({ file: name, route: new URL(page.url()).pathname });
    }

    await open('/add_task_by_web');
    await page.locator('.workbench-hero h1').waitFor();
    await page.getByText('把阅读变成可以复用的笔记', { exact: true }).first().waitFor();
    await capture('01-import');

    await open('/view/demo-note-0');
    await page.locator('#transcript-summary-text-panel h2').first().waitFor();
    await page.locator('#floating-toc.pinned').waitFor();
    await page.waitForTimeout(450);
    await capture('02-result');

    await open('/collections?collection_id=demo-course');
    await page.getByRole('tab', { name: '章节解读', exact: true }).click();
    await page.locator('#source-summary h2').first().waitFor();
    await page.waitForTimeout(500);
    await capture('03-collections');

    await open('/reading');
    await page.locator('.reading-book-card').first().waitFor();
    await capture('04-reading-library');
    await page.locator('#reading-continue-button').click();
    await page.locator('#reading-flow-content h1').first().waitFor();
    await page.waitForTimeout(450);
    await capture('05-reading');

    await open('/static/focus-studio.html');
    const diary = await page.evaluate(async () => (await (await fetch('/api/journal/entry')).json()).data.body);
    await page.locator('#focus-editor').fill(diary);
    await page.waitForTimeout(850);
    await capture('06-writing');

    await open('/static/history.html');
    await page.locator('.history-record-row').first().waitFor();
    await page.locator('.tendedero-card').first().waitFor();
    await capture('07-history');

    await open('/briefings');
    await page.frameLocator('#briefings-frame').locator('article').first().waitFor({ timeout: 5000 });
    await capture('08-briefings');

    await open('/study/demo-note-1');
    await page.locator('.transcript-row').first().waitFor();
    const video = page.locator('video');
    await video.evaluate(element => new Promise(resolve => {
        if (element.readyState >= 2) resolve();
        else element.addEventListener('loadeddata', resolve, { once: true });
    }));
    await page.locator('.transcript-segment').nth(2).click();
    await page.waitForFunction(() => { const v = document.querySelector('video'); return !v.seeking && v.currentTime >= 2.9 && v.readyState >= 2; });
    await capture('09-player');

    if (errors.length || failures.length) throw new Error(JSON.stringify({ errors, failures }));
    return { screenshots: results, javascriptErrors: 0, failedLocalRequests: 0 };
}
