const OWNER = 'mefferso';
const REPO = 'tornado_path_calculator';
const WORKFLOW_FILE = 'run-crossings.yml';
const REF = 'main';
const DEFAULT_BBOX = '-91.8,28.5,-87.8,31.5';
const MAX_DATE_RANGE_DAYS = 45;
const MIN_SECONDS_BETWEEN_RUNS = 20;

function doGet() {
  return htmlResponse_(
    'Tornado workflow trigger',
    '<p>This endpoint is alive. Submit requests from the tornado map run form.</p>'
  );
}

function doPost(e) {
  try {
    const props = PropertiesService.getScriptProperties();
    const githubToken = props.getProperty('GITHUB_TOKEN');
    const runKey = props.getProperty('RUN_KEY');

    if (!githubToken) throw new Error('Missing Script Property: GITHUB_TOKEN');
    if (!runKey) throw new Error('Missing Script Property: RUN_KEY');

    const suppliedKey = String(e.parameter.run_key || '').trim();
    if (suppliedKey !== runKey) throw new Error('Invalid run key. Workflow not started.');

    throttle_();

    const startDate = String(e.parameter.start_date || '').trim();
    const endDate = String(e.parameter.end_date || '').trim();
    const bbox = String(e.parameter.bbox || DEFAULT_BBOX).trim();

    validateDate_(startDate, 'start_date');
    validateDate_(endDate, 'end_date');
    validateDateRange_(startDate, endDate);
    validateBbox_(bbox);

    const apiUrl = `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${encodeURIComponent(WORKFLOW_FILE)}/dispatches`;
    const payload = {
      ref: REF,
      inputs: {
        start_date: startDate,
        end_date: endDate,
        bbox: bbox
      }
    };

    const response = UrlFetchApp.fetch(apiUrl, {
      method: 'post',
      contentType: 'application/json',
      payload: JSON.stringify(payload),
      headers: {
        Authorization: `Bearer ${githubToken}`,
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28'
      },
      muteHttpExceptions: true
    });

    const code = response.getResponseCode();
    const body = response.getContentText();

    if (code !== 204) {
      throw new Error(`GitHub API returned HTTP ${code}: ${body}`);
    }

    return htmlResponse_(
      'Workflow started',
      `<p><b>Started successfully.</b></p>
       <p>Date range: ${escapeHtml_(startDate)} through ${escapeHtml_(endDate)}</p>
       <p>BBox: ${escapeHtml_(bbox)}</p>
       <p><a href="https://github.com/${OWNER}/${REPO}/actions" target="_blank">Open GitHub Actions</a></p>
       <p><a href="https://${OWNER}.github.io/${REPO}/" target="_blank">Open map</a></p>
       <p>Give GitHub a couple minutes, then refresh the map.</p>`
    );
  } catch (err) {
    return htmlResponse_(
      'Workflow trigger failed',
      `<p><b>Workflow was not started.</b></p><pre>${escapeHtml_(err.message || String(err))}</pre>`
    );
  }
}

function validateDate_(value, fieldName) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw new Error(`${fieldName} must be YYYY-MM-DD`);
  }
  const d = new Date(value + 'T00:00:00Z');
  if (Number.isNaN(d.getTime())) throw new Error(`${fieldName} is not a valid date`);
}

function validateDateRange_(startDate, endDate) {
  const start = new Date(startDate + 'T00:00:00Z');
  const end = new Date(endDate + 'T00:00:00Z');
  if (end < start) throw new Error('end_date must be the same as or after start_date');
  const days = Math.round((end - start) / 86400000) + 1;
  if (days > MAX_DATE_RANGE_DAYS) {
    throw new Error(`Date range is ${days} days. Max allowed is ${MAX_DATE_RANGE_DAYS} days.`);
  }
}

function validateBbox_(bbox) {
  const parts = bbox.split(',').map(s => Number(s.trim()));
  if (parts.length !== 4 || parts.some(n => !Number.isFinite(n))) {
    throw new Error('bbox must be min_lon,min_lat,max_lon,max_lat');
  }
  const [minLon, minLat, maxLon, maxLat] = parts;
  if (minLon >= maxLon) throw new Error('bbox min_lon must be less than max_lon');
  if (minLat >= maxLat) throw new Error('bbox min_lat must be less than max_lat');
  if (minLon < -180 || maxLon > 180 || minLat < -90 || maxLat > 90) {
    throw new Error('bbox values are outside valid lat/lon ranges');
  }
}

function throttle_() {
  const cache = CacheService.getScriptCache();
  if (cache.get('recent_run')) {
    throw new Error(`Another workflow was triggered recently. Wait ${MIN_SECONDS_BETWEEN_RUNS} seconds and try again.`);
  }
  cache.put('recent_run', '1', MIN_SECONDS_BETWEEN_RUNS);
}

function htmlResponse_(title, bodyHtml) {
  const html = `<!doctype html>
  <html>
    <head>
      <base target="_top">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <style>
        body { font-family: system-ui, -apple-system, Segoe UI, sans-serif; margin: 24px; line-height: 1.4; color: #0f172a; }
        .card { max-width: 720px; border: 1px solid #cbd5e1; border-radius: 14px; padding: 18px 20px; box-shadow: 0 12px 30px rgba(15,23,42,.12); }
        h1 { margin: 0 0 12px; font-size: 22px; }
        pre { white-space: pre-wrap; background: #f8fafc; border: 1px solid #e2e8f0; padding: 12px; border-radius: 10px; }
        a { color: #0369a1; font-weight: 700; }
      </style>
    </head>
    <body><div class="card"><h1>${escapeHtml_(title)}</h1>${bodyHtml}</div></body>
  </html>`;
  return HtmlService.createHtmlOutput(html);
}

function escapeHtml_(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
