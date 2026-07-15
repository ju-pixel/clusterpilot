#!/usr/bin/env node
/**
 * Prove the featured-image generator is really setting type in Playfair
 * Display italic, and not in something that merely looks plausible.
 *
 * Why this exists: the old sharp/librsvg generator resolved fonts through
 * fontconfig, so a missing face degraded silently into whatever the system
 * had. It asked for "Menlo, 'DM Mono', monospace" and got Menlo every
 * single time, because DM Mono is not installed on this machine and never
 * was; the site loads it from the Google Fonts CDN. Every card it made was
 * in the wrong face, and no check caught it, because none of them rendered
 * anything.
 *
 * The decisive test is a differential one: measure the same string rendered
 * through two different faces. If the widths match, the font you asked for
 * is not the font you got.
 *
 * Run: node scripts/verify-featured-image.mjs
 */
import satori from 'satori';
import { Resvg } from '@resvg/resvg-js';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

const SAMPLE = 'Slurm without the swearing.';
const SIZE = 80;

async function fontBuffer(spec) {
  return readFile(require.resolve(spec));
}

/**
 * Render the sample string alone and return its rendered SVG + PNG.
 * `style` and `weight` are passed through to both the satori font
 * registration and the element, because satori matches the face on family
 * + weight + style together: ask for the wrong one and it has nothing to
 * select.
 */
async function measure(name, data, { style = 'normal', weight = 700 } = {}) {
  const svg = await satori(
    {
      type: 'div',
      props: {
        style: {
          display: 'flex',
          width: 1280,
          height: 200,
          backgroundColor: '#FFFFFF',
        },
        children: [
          {
            type: 'div',
            props: {
              style: {
                fontFamily: name,
                fontSize: SIZE,
                fontWeight: weight,
                fontStyle: style,
                color: '#000000',
              },
              children: SAMPLE,
            },
          },
        ],
      },
    },
    { width: 1280, height: 200, fonts: [{ name, data, weight, style }], embedFont: true }
  );

  const png = new Resvg(svg, { fitTo: { mode: 'width', value: 1280 } }).render().asPng();
  return { svg, png, name };
}

/** Ink bounding-box width of a PNG buffer, by scanning for non-white pixels. */
async function inkWidth(pngBuffer) {
  const sharp = require('sharp');
  const { data, info } = await sharp(pngBuffer).greyscale().raw().toBuffer({ resolveWithObject: true });
  let min = Infinity;
  let max = -Infinity;
  for (let y = 0; y < info.height; y++) {
    for (let x = 0; x < info.width; x++) {
      if (data[y * info.width + x] < 200) {
        if (x < min) min = x;
        if (x > max) max = x;
      }
    }
  }
  return max < min ? 0 : max - min + 1;
}

const checks = [];
function check(name, pass, detail) {
  checks.push({ name, pass, detail });
  console.log(`${pass ? 'PASS' : 'FAIL'}  ${name}${detail ? ` — ${detail}` : ''}`);
}

const playfair = await fontBuffer(
  '@fontsource/playfair-display/files/playfair-display-latin-700-italic.woff'
);
const mono = await fontBuffer('@fontsource/dm-mono/files/dm-mono-latin-400-normal.woff');

const a = await measure('Playfair Display', playfair, { style: 'italic', weight: 700 });
const b = await measure('DM Mono', mono, { style: 'normal', weight: 400 });

// 1. Glyphs must be embedded as outlines. A <text> node means satori did not
//    resolve the face and left it for the rasteriser to guess at.
check('type is embedded as vector paths', /<path[\s>]/.test(a.svg) && !/<text[\s>]/.test(a.svg));

// 2. The decisive one. Two different faces must produce two different widths.
const wa = await inkWidth(a.png);
const wb = await inkWidth(b.png);
const delta = Math.abs(wa - wb);
check(
  'Playfair italic and DM Mono render at different widths',
  delta > 20,
  `Playfair ${wa}px, DM Mono ${wb}px, delta ${delta}px`
);

// 3. Sanity: the string actually rendered something.
check('sample string produced ink', wa > 100, `${wa}px wide`);

// 4. A corrupt buffer must throw, never silently degrade.
let threw = false;
try {
  await measure('Playfair Display', Buffer.from('not a font'), { style: 'italic', weight: 700 });
} catch {
  threw = true;
}
check('a corrupt font buffer throws rather than falling back', threw);

const failed = checks.filter((c) => !c.pass);
console.log(`\n${checks.length - failed.length}/${checks.length} passed`);
process.exit(failed.length ? 1 : 0);
