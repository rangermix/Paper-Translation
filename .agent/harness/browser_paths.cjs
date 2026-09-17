// Repository paths for maintained browser checks; archived evidence stays read-only.
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const repoRoot = path.resolve(__dirname, '../..');
const temporaryRoot = path.join(repoRoot, '.agent/tmp');
const runId = process.env.LIBRARY_BROWSER_RUN_ID ||= `${new Date().toISOString().replace(/[:.]/g, '-')}-${randomUUID().slice(0, 8)}`;

function inputPath(value) {
  let input = String(value).replace(/\\/g, '/');
  const root = repoRoot.replace(/\\/g, '/');
  const oldRoot = `${root}/bilingual-library-personal-pdf-v3/`;
  if (input.startsWith(oldRoot)) input = input.slice(oldRoot.length);
  else if (input.startsWith(`${root}/`)) input = input.slice(root.length + 1);
  else if (input.startsWith('/') || /^[a-zA-Z]:/.test(input)) {
    throw new Error('Browser inputs must belong to the current or former repository root');
  }
  if (input.split('/').includes('..')) throw new Error('Browser input traversal is not allowed');
  for (const [before, after] of [
    ['apps/web/evidence/', '.agent/tmp/frontend/evidence/'],
    ['src/apps/web/evidence/', '.agent/tmp/frontend/evidence/'],
    ['evidence/', '.agent/tmp/evidence/'],
    ['reports/', '.agent/tmp/reports/'],
    ['reference/', 'res/reference/'],
    ['apps/', 'src/apps/'],
    ['packages/', 'src/packages/'],
    ['workers/', 'src/workers/'],
    ['tools/', 'src/tools/'],
  ]) {
    if (input.startsWith(before)) { input = after + input.slice(before.length); break; }
  }
  const resolved = path.resolve(repoRoot, input);
  const relative = path.relative(repoRoot, resolved);
  if (relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) {
    throw new Error('Browser inputs must stay inside the repository');
  }
  return resolved;
}

function outputPath(value) {
  const output = path.resolve(repoRoot, value);
  const relative = path.relative(temporaryRoot, output);
  if (!relative || relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative)) {
    throw new Error('Browser outputs must be inside the repository .agent/tmp directory');
  }
  return output;
}

function outputDirectory(name) {
  const base = process.env.LIBRARY_BROWSER_OUTPUT
    ? outputPath(process.env.LIBRARY_BROWSER_OUTPUT)
    : path.join(temporaryRoot, 'frontend/runs', runId);
  return outputPath(path.join(base, name));
}

module.exports = { repoRoot, temporaryRoot, runId, inputPath, outputPath, outputDirectory };
