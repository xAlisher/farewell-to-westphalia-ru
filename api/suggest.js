// Vercel serverless function: creates a GitHub issue from the reader
// suggestion form on farewelltowestphalia.net.
// Env: GITHUB_TOKEN — fine-grained PAT, Issues: Read and write,
// scoped ONLY to xAlisher/farewell-to-westphalia-ru.

const REPO = 'xAlisher/farewell-to-westphalia-ru';
const ALLOWED_ORIGINS = [
  'https://farewelltowestphalia.net',
  'https://www.farewelltowestphalia.net',
];
const MAX_BODY = 8000;

export default async function handler(req, res) {
  const origin = req.headers.origin || '';
  if (ALLOWED_ORIGINS.includes(origin)) {
    res.setHeader('Access-Control-Allow-Origin', origin);
    res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  }
  if (req.method === 'OPTIONS') return res.status(204).end();
  if (req.method !== 'POST') return res.status(405).json({ error: 'POST only' });
  if (!ALLOWED_ORIGINS.includes(origin)) {
    return res.status(403).json({ error: 'origin not allowed' });
  }

  const { title, body, page } = req.body || {};
  if (!title || !body || typeof title !== 'string' || typeof body !== 'string') {
    return res.status(400).json({ error: 'title and body required' });
  }
  if (title.length > 300 || body.length > MAX_BODY) {
    return res.status(400).json({ error: 'too long' });
  }
  if (page && !String(page).startsWith('https://farewelltowestphalia.net')) {
    return res.status(400).json({ error: 'bad page' });
  }

  const gh = await fetch(`https://api.github.com/repos/${REPO}/issues`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
      Accept: 'application/vnd.github+json',
      'Content-Type': 'application/json',
      'User-Agent': 'ftw-suggest',
    },
    body: JSON.stringify({
      title: title.slice(0, 250),
      body,
      labels: ['reader-suggestion'],
    }),
  });
  if (!gh.ok) {
    return res.status(502).json({ error: 'github ' + gh.status });
  }
  const issue = await gh.json();
  return res.status(200).json({ url: issue.html_url, number: issue.number });
}
