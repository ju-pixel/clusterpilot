#!/usr/bin/env node
/**
 * Generate a 1280x720 featured image for a blog post in the ClusterPilot
 * thumbnail style: a warm charcoal background (or a supplied screenshot on the
 * right half), a rounded amber banner with the title in bold dark capitals, and
 * an optional accent arrow.
 *
 * Palette (fixed, per the warm dark restyle, tasks/todo.md Section B.1):
 *   #14110B background   #e8a020 banner        #14110B title (dark on amber)
 *   #C9BEA9 secondary     #FFC46B accent arrow  #F2EBDD divider
 *
 * Usage:
 *   node scripts/generate-featured-image.mjs \
 *     --title "Escape without reboot" \
 *     --out public/images/blog/2026-07-14-escape-without-reboot.png \
 *     [--screenshot path/to/screenshot.png] \
 *     [--banner "#e8a020"] [--no-arrow]
 *
 * The screenshot, when given, fills the right half over the warm charcoal base
 * (the split layout). Without one, the card is the plain layout with the site
 * wordmark top left.
 */
import sharp from 'sharp';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const WIDTH = 1280;
const HEIGHT = 720;
const BG = '#14110B';        // warm charcoal
const TITLE = '#14110B';     // dark title text on the amber banner
const ACCENT = '#FFC46B';    // accent arrow
const BANNER = '#e8a020';    // amber banner fill
const SECONDARY = '#C9BEA9'; // wordmark / secondary text
const DIVIDER = '#F2EBDD';   // split-layout divider

const FONT = "Menlo, 'DM Mono', monospace";

function parseArgs(argv) {
  const args = { arrow: true, banner: BANNER };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--title') args.title = argv[++i];
    else if (a === '--out') args.out = argv[++i];
    else if (a === '--screenshot') args.screenshot = argv[++i];
    else if (a === '--banner') args.banner = argv[++i];
    else if (a === '--no-arrow') args.arrow = false;
    else throw new Error(`Unknown argument: ${a}`);
  }
  if (!args.title || !args.out) {
    console.error('Required: --title "..." --out path.png');
    process.exit(1);
  }
  return args;
}

function escapeXml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&apos;');
}

// Split a title into at most two visually balanced lines.
function wrapTitle(title) {
  const words = title.toUpperCase().split(/\s+/);
  const oneLine = words.join(' ');
  if (oneLine.length <= 22 || words.length === 1) return [oneLine];
  let best = null;
  for (let i = 1; i < words.length; i++) {
    const a = words.slice(0, i).join(' ');
    const b = words.slice(i).join(' ');
    const spread = Math.abs(a.length - b.length);
    if (!best || spread < best.spread) best = { lines: [a, b], spread };
  }
  return best.lines;
}

const args = parseArgs(process.argv);
const lines = wrapTitle(args.title);
const longest = Math.max(...lines.map((l) => l.length));

// Menlo Bold is roughly 0.6em wide per character; size the type so the
// longest line fits inside the banner with margins, capped for shorter
// titles so single words do not become billboards.
const maxTextWidth = WIDTH - 2 * 110;
const fontSize = Math.min(84, Math.floor(maxTextWidth / (longest * 0.62)));
const lineHeight = Math.round(fontSize * 1.25);
const padX = 46;
const padY = 34;
const textWidth = Math.ceil(longest * fontSize * 0.62);
const bannerW = Math.min(WIDTH - 100, textWidth + 2 * padX);
const bannerH = lines.length * lineHeight + 2 * padY - (lineHeight - fontSize);
const bannerX = Math.round((WIDTH - bannerW) / 2);
const bannerY = HEIGHT - bannerH - 52;

const textSvg = lines
  .map((line, i) => {
    const y = bannerY + padY + fontSize * 0.85 + i * lineHeight;
    return `<text x="${WIDTH / 2}" y="${y}" text-anchor="middle" font-family="${FONT}" font-weight="700" font-size="${fontSize}" letter-spacing="2" fill="${TITLE}">${escapeXml(line)}</text>`;
  })
  .join('\n  ');

// A hand-drawn style curved arrow pointing into the upper right area.
const arrowSvg = args.arrow
  ? `<g stroke="${ACCENT}" stroke-width="14" fill="none" stroke-linecap="round">
      <path d="M 520 205 C 590 155, 680 150, 745 175"/>
      <path d="M 700 155 L 752 178 L 712 210" fill="none"/>
    </g>`
  : '';

const wordmarkSvg = args.screenshot
  ? ''
  : `<text x="80" y="96" font-family="${FONT}" font-size="24" letter-spacing="4" fill="${SECONDARY}">CLUSTERPILOT.SH</text>`;

const svg = `
<svg xmlns="http://www.w3.org/2000/svg" width="${WIDTH}" height="${HEIGHT}" viewBox="0 0 ${WIDTH} ${HEIGHT}">
  ${wordmarkSvg}
  ${arrowSvg}
  <rect x="${bannerX}" y="${bannerY}" width="${bannerW}" height="${bannerH}" rx="26" fill="${args.banner}"/>
  ${textSvg}
</svg>
`.trim();

let base = sharp({
  create: { width: WIDTH, height: HEIGHT, channels: 3, background: BG },
});

const layers = [];
if (args.screenshot) {
  // Split layout: screenshot cover-fitted to the right half, thin warm divider
  // between the halves.
  const half = Math.floor(WIDTH / 2);
  const shot = await sharp(args.screenshot)
    .resize(half + 8, HEIGHT, { fit: 'cover' })
    .toBuffer();
  layers.push({ input: shot, left: half - 8, top: 0 });
  const divider = Buffer.from(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${WIDTH}" height="${HEIGHT}"><rect x="${half - 10}" y="0" width="3" height="${HEIGHT}" fill="${DIVIDER}"/></svg>`
  );
  layers.push({ input: divider, left: 0, top: 0 });
}
layers.push({ input: Buffer.from(svg), left: 0, top: 0 });

const png = await base
  .composite(layers)
  .png({ compressionLevel: 9 })
  .toBuffer();

await mkdir(path.dirname(args.out), { recursive: true });
await writeFile(args.out, png);
console.log(`wrote ${args.out} (${(png.length / 1024).toFixed(1)} KB)`);
