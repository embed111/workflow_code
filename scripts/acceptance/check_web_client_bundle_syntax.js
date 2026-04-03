#!/usr/bin/env node
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const childProcess = require('child_process');

function main() {
  const repoRoot = path.resolve(__dirname, '..', '..');
  const webClientRoot = path.join(repoRoot, 'src', 'workflow_app', 'web_client');
  const manifestPath = path.join(webClientRoot, 'bundle_manifest.json');
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  if (!Array.isArray(manifest) || !manifest.length) {
    throw new Error('bundle_manifest.json is empty');
  }

  const bundle = manifest
    .map((name) => {
      const filePath = path.join(webClientRoot, String(name || ''));
      return fs.readFileSync(filePath, 'utf8');
    })
    .join('\n');

  const outDir = process.env.TEST_TMP_DIR || os.tmpdir();
  fs.mkdirSync(outDir, { recursive: true });
  const outPath = path.join(outDir, 'workflow-web-client.bundle.check.js');
  fs.writeFileSync(outPath, bundle, 'utf8');

  childProcess.execFileSync(process.execPath, ['--check', outPath], {
    stdio: 'inherit',
  });

  process.stdout.write(
    JSON.stringify(
      {
        ok: true,
        manifest_path: manifestPath,
        bundle_path: outPath,
        file_count: manifest.length,
      },
      null,
      2
    ) + '\n'
  );
}

main();
