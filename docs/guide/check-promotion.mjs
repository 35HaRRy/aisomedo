import { readFileSync, existsSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const files = ['README.md', 'docs/cv.md', 'docs/linkedin.md', ...['windows-local-setup', 'getting-started', 'publishing-a-reel', 'settings-and-recovery', 'screenshots'].map(name => `docs/guide/${name}.md`)];
for (const file of files) {
  assert(existsSync(resolve(root, file)), `Missing document: ${file}`);
  const text = readFileSync(resolve(root, file), 'utf8');
  for (const [, target] of text.matchAll(/!?\[[^\]]*\]\(([^)]+)\)/g)) {
    if (/^(https?:|mailto:|#)/.test(target)) continue;
    const path = decodeURIComponent(target.split('#')[0]);
    assert(existsSync(resolve(root, dirname(file), path)), `${file}: broken link ${target}`);
  }
  assert(!/```(?:python|sql)\b/i.test(text), `${file}: inline Python/SQL is not part of quick start`);
}
const readme = readFileSync(resolve(root, 'README.md'), 'utf8');
assert.match([...readme.matchAll(/^## (.+)$/gm)].at(-1)?.[1] ?? '', /Android/);
const cv = readFileSync(resolve(root, 'docs/cv.md'), 'utf8');
for (const heading of ['Architect & Leadership & Soft skills', 'Frontend skills', 'Backend skills', 'DevOps skills']) assert(cv.includes(`## ${heading}`), `Missing CV heading: ${heading}`);
const linkedin = readFileSync(resolve(root, 'docs/linkedin.md'), 'utf8');
assert(linkedin.includes('## Türkçe') && linkedin.includes('## English') && linkedin.includes('#Aisomedo') && linkedin.includes('!['));
console.log(`PASS: ${files.length} promotion documents, local links, screenshots, and required sections`);
