// Install the checkout's build as ManimLive.app on this Mac, without
// GitHub: the deploy's app job (.github/workflows/deploy.yml) done here.
//
//   npm run install:local                       # into /Applications/ManimLive.app
//   npm run install:local -- ~/Scratch/M.app    # anywhere else
//
// The deploy's three steps, in its order. The Lyon helper built into the
// package by uv sync, as the deploy builds it, but --inexact and with the
// development group: the checkout's .venv keeps pytest, the gl extra and
// whatever else it holds (a change to tools/lyon_fill wants `uv sync
// --reinstall-package maniml` first, for the checkout and for this alike).
// The bundle packaged by the pinned shell with the package as it stands in
// the checkout, for this Mac's processor, into a site folder of its own
// under the temp folder (app/ManimLive-<arch>.zip and app/latest.json, as
// maniml.tayweid.io serves them). Then the install line (site/install)
// against that folder, which completes the app with Electron cloned from
// the ManimLive it replaces or another Claerbout app on the same Electron,
// else downloaded once, and refuses while that ManimLive is open. The
// engine's packages are not in the bundle: the app installs
// app/engine-requirements.txt on its first launch, as it does from the site.
//
// `npm run app` runs the checkout; this installs the checkout's build as
// the app. The build id is the checkout's commit, cut to seven characters
// as the deploy cuts GITHUB_SHA, with -dirty when the tree has changes not
// committed (the package goes in as it stands). It is what the installed
// app's Check for Updates… compares with the site's app/latest.json, so the
// site's next build replaces this one when you take it.
import { execFileSync, spawnSync } from 'node:child_process';
import { accessSync, constants, mkdtempSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const configPath = path.join('app', 'maniml.json');
const { name, envPrefix } = JSON.parse(readFileSync(path.join(repo, configPath), 'utf8'));

function fail(message) {
  console.error(`install:local: ${message}`);
  process.exit(1);
}
if (process.platform !== 'darwin') fail(`${name}.app is for macOS`);

// Where the install line would put it: Applications, or the home folder's
// when that is not writable. A relative target is the folder npm was
// typed in, not the package's.
function writable(dir) {
  try {
    accessSync(dir, constants.W_OK);
    return true;
  } catch {
    return false;
  }
}
const targets = process.argv.slice(2);
if (targets.length > 1) fail(`one target at most: npm run install:local -- /path/to/${name}.app`);
const app = targets[0]
  ? path.resolve(process.env.INIT_CWD ?? process.cwd(), targets[0])
  : writable('/Applications') ? `/Applications/${name}.app` : path.join(os.homedir(), 'Applications', `${name}.app`);
if (!app.endsWith('.app')) fail(`the target must end in .app (got ${app})`);

// The install line's own test for an open app (macOS may report a path
// under /private without that prefix), asked before the build too, so a
// refusal does not come a minute in.
function isOpen() {
  const plain = app.replace(/^\/private/, '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return spawnSync('pgrep', ['-f', `^(/private)?${plain}/Contents/MacOS/`]).status === 0;
}
const quit = `${name} is open (${app}). Quit it (${name} menu → Quit ${name}), then run npm run install:local again.`;
if (isOpen()) fail(quit);

const git = (...args) => execFileSync('git', args, { cwd: repo, encoding: 'utf8' }).trim();
const build = git('rev-parse', 'HEAD').slice(0, 7) + (git('status', '--porcelain') ? '-dirty' : '');
const arch = process.arch;

function step(command, args, env = {}) {
  console.log(`install:local: ${[command, ...args].join(' ')}`);
  const result = spawnSync(command, args, { cwd: repo, stdio: 'inherit', env: { ...process.env, ...env } });
  if (result.error) console.error(`install:local: ${result.error.message}`);
  return result.status === 0;
}

// The site folder goes when this does, however it ends.
const site = mkdtempSync(path.join(os.tmpdir(), `${name.toLowerCase()}-site-`));
process.on('exit', () => rmSync(site, { recursive: true, force: true }));

console.log(`install:local: ${name} build ${build} for ${arch}, into ${app}`);
if (!step('uv', ['sync', '--locked', '--inexact'])) fail('uv did not build the package (above).');
// The bundle carries the one helper the package holds; the engine refuses
// a package with two (triangle_geometry._packaged_library).
const helpers = readdirSync(path.join(repo, 'maniml', 'web')).filter((file) => /^maniml_lyon_fill.*\.(so|dylib)$/.test(file));
if (helpers.length !== 1) fail(`maniml/web holds ${helpers.length} Lyon helpers (${helpers.join(', ') || 'none'}); it needs exactly one.`);
const packager = path.join('node_modules', 'claerbout', 'package.mjs');
if (!step(process.execPath, [packager, '--config', configPath, '--arch', arch, '--zip', path.join(site, 'app')], { CLAERBOUT_BUILD: build })) {
  fail('the app did not package (above).');
}
if (!step('bash', ['site/install'], { [`${envPrefix}_SITE`]: site, [`${envPrefix}_APP`]: app })) {
  fail(isOpen() ? quit : 'the install line stopped (above).');
}
const stamp = JSON.parse(readFileSync(path.join(app, 'Contents', 'Resources', 'app', 'package.json'), 'utf8'));
console.log(`install:local: installed ${app}, build ${stamp.build} (${stamp.built}).`);
