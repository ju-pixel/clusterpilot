#!/usr/bin/env node
/**
 * Generate a 1280x720 featured image for a blog post: a short serif phrase
 * in sentence case, set in Playfair Display italic, composed against a
 * motif, on one of three alternating grounds.
 *
 * This script takes a PHRASE, not a title. A card reads "Slurm without the
 * swearing." or "The queue was the bug."; it never carries the post title.
 * The drafting agent writes the phrase.
 *
 * Grounds (ClusterPilot's warm dark restyle tokens, tasks/todo.md B.1):
 *   charcoal  #14110B ground / #F2EBDD ink / #FFC46B accent
 *   panel     #26211A ground / #F2EBDD ink / #FFC46B accent
 *   amber     #e8a020 ground / #14110B ink / #14110B accent
 *
 * Type is Playfair Display 700 italic: the CP-only flourish from B.4, the
 * one thing the card does that the Fieldnotes house style does not.
 *
 * Rendering: satori measures real glyphs and lays out with flexbox, then
 * embeds the type as vector paths; resvg rasterises. Fonts are read as
 * BUFFERS from node_modules. Nothing is resolved through fontconfig, so
 * there is no system font to install and no silent fallback to a generic
 * serif. This matters: the previous sharp/librsvg version asked for
 * "Menlo, 'DM Mono', monospace" and always got Menlo, because DM Mono is
 * not installed on any machine here (the site loads it from the CDN). Every
 * card it ever made was silently in the wrong face.
 *
 * Usage:
 *   node scripts/generate-featured-image.mjs \
 *     --phrase "Slurm without the swearing." \
 *     --motif prompt --ground charcoal \
 *     --out public/images/blog/2026-07-14-slug.png
 *
 *   node scripts/generate-featured-image.mjs --list-motifs
 */
import satori from 'satori';
import { Resvg } from '@resvg/resvg-js';
import { mkdir, writeFile, readFile } from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { MOTIFS, ruleDevice } from './thumbnail-motifs.mjs';

const require = createRequire(import.meta.url);

const WIDTH = 1280;
const HEIGHT = 720;

/**
 * Grounds for clusterpilot.sh, from the Section B.1 restyle tokens.
 *
 * `accent` and `accentFill` are deliberately different on the dark grounds
 * and B.1 is the reason: #e8a020 is the brand amber but is a FILL colour
 * only, while #FFC46B is amber-as-text (~9:1 on charcoal) and carries the
 * thin strokes and small marks. #FFB866 is dropped by B.1 and must not
 * reappear here.
 *
 * `blocks` are the chain's four fills. Two constraints, both learned by
 * rendering the cards and looking at them:
 *   1. All four must be distinguishable FROM EACH OTHER, not merely from
 *      the ground. The chain means "four different linked things"; four
 *      near-identical darks render as one shape stamped four times and the
 *      motif says nothing.
 *   2. blocks[2] must differ from accentFill, because `hop` uses exactly
 *      those two for its pair of rectangles. Set them equal and hop's
 *      "big thing here, different thing there" collapses into one colour.
 */
const GROUNDS = {
  charcoal: {
    ground: '#14110B',
    ink: '#F2EBDD',
    accent: '#FFC46B',
    accentFill: '#e8a020',
    blocks: ['#F2EBDD', '#e8a020', '#6FD8E8', '#7BD88F'],
  },
  panel: {
    ground: '#26211A',
    ink: '#F2EBDD',
    accent: '#FFC46B',
    accentFill: '#e8a020',
    blocks: ['#F2EBDD', '#e8a020', '#6FD8E8', '#7BD88F'],
  },
  amber: {
    ground: '#e8a020',
    ink: '#14110B',
    accent: '#14110B',
    accentFill: '#14110B',
    blocks: ['#14110B', '#6FD8E8', '#F2EBDD', '#7BD88F'],
  },
};

function parseArgs(argv) {
  const args = { ground: 'charcoal', motif: 'prompt' };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--phrase') args.phrase = argv[++i];
    else if (a === '--motif') args.motif = argv[++i];
    else if (a === '--ground') args.ground = argv[++i];
    else if (a === '--out') args.out = argv[++i];
    else if (a === '--list-motifs') args.list = true;
    else throw new Error(`Unknown argument: ${a}`);
  }
  if (args.list) return args;
  if (!args.phrase || !args.out) {
    console.error('Required: --phrase "..." --out path.png');
    console.error(`Motifs: ${Object.keys(MOTIFS).join(', ')}`);
    console.error(`Grounds: ${Object.keys(GROUNDS).join(', ')}`);
    process.exit(1);
  }
  if (!MOTIFS[args.motif]) {
    console.error(`Unknown motif "${args.motif}". Have: ${Object.keys(MOTIFS).join(', ')}`);
    process.exit(1);
  }
  if (!GROUNDS[args.ground]) {
    console.error(`Unknown ground "${args.ground}". Have: ${Object.keys(GROUNDS).join(', ')}`);
    process.exit(1);
  }
  return args;
}

/**
 * Load Playfair Display 700 italic as a buffer. Fails loudly: a missing
 * font must never degrade into a fallback face, because that failure is
 * invisible in the output until someone looks at a published card.
 */
async function loadFont() {
  let file;
  try {
    file = require.resolve(
      '@fontsource/playfair-display/files/playfair-display-latin-700-italic.woff'
    );
  } catch {
    throw new Error(
      'Playfair Display .woff not found in node_modules. Run `npm install`.\n' +
        'Do NOT "fix" this by installing the font on this machine: the same ' +
        'repo is built on the Linux workstation, where it would silently ' +
        'fall back to a generic serif. That silent fallback is exactly how ' +
        'the old generator ended up rendering every card in Menlo.'
    );
  }
  const data = await readFile(file);
  if (data.length < 1000) throw new Error(`Font file looks truncated: ${file}`);
  return data;
}

function fontSizeFor(phrase) {
  const n = phrase.length;
  if (n <= 18) return 92;
  if (n <= 26) return 80;
  if (n <= 36) return 68;
  return 58;
}

/**
 * Wrap an SVG fragment as a data URI. `pad` expands the viewBox on all
 * sides: strokes are centred on their paths and motifs deliberately draw
 * at negative coordinates (offset hairlines, terminal dots), so a viewBox
 * anchored at 0,0 crops them without any error.
 */
function svgLayer({ inner, width, height, pad = 0 }) {
  const w = width + pad * 2;
  const h = height + pad * 2;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="${-pad} ${-pad} ${w} ${h}">${inner}</svg>`;
  return { src: `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`, w, h };
}

function compose({ phrase, motif, palette }) {
  const { ground, ink } = palette;
  const m = MOTIFS[motif](palette);
  const fontSize = fontSizeFor(phrase);

  const motifLayer = svgLayer({ inner: m.svg, width: m.w, height: m.h, pad: m.pad ?? 0 });
  const motifImg = {
    type: 'img',
    props: { src: motifLayer.src, width: motifLayer.w, height: motifLayer.h },
  };
  // fontStyle must be set explicitly: satori matches the face on family +
  // weight + style, and the only face loaded is the italic one. Ask for
  // normal and satori has nothing to select.
  const text = (extra = {}) => ({
    type: 'div',
    props: {
      style: {
        fontFamily: 'Playfair Display',
        fontSize,
        fontWeight: 700,
        fontStyle: 'italic',
        color: ink,
        lineHeight: 1.15,
        letterSpacing: '-0.01em',
        ...extra,
      },
      children: phrase,
    },
  });

  const ruleEdge = m.place === 'beside' ? 'bottom' : 'top';
  const ruleLayer = svgLayer({ inner: ruleDevice({ ink }), width: WIDTH, height: 60 });
  const rule = {
    type: 'img',
    props: {
      src: ruleLayer.src,
      width: ruleLayer.w,
      height: ruleLayer.h,
      style: {
        position: 'absolute',
        left: 0,
        ...(ruleEdge === 'top' ? { top: 0 } : { bottom: 0 }),
      },
    },
  };

  let body;
  if (m.place === 'below') {
    body = {
      type: 'div',
      props: {
        style: {
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 68,
          width: '100%',
          height: '100%',
        },
        children: [motifImg, text({ textAlign: 'center', maxWidth: 940 })],
      },
    };
  } else if (m.place === 'beside') {
    // The prompt card sits the line high, at roughly 30% of the frame, with
    // the negative space falling below it. Centring loses the point. The
    // column anchors the row's top; the row centres motif against text.
    body = {
      type: 'div',
      props: {
        style: {
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'flex-start',
          width: '100%',
          height: '100%',
          padding: '156px 110px 0 110px',
        },
        children: [
          {
            type: 'div',
            props: {
              style: { display: 'flex', flexDirection: 'row', alignItems: 'center', gap: 44 },
              children: [motifImg, text({ maxWidth: 820 })],
            },
          },
        ],
      },
    };
  } else {
    body = {
      type: 'div',
      props: {
        style: {
          display: 'flex',
          flexDirection: 'column',
          width: '100%',
          height: '100%',
          padding: '96px 100px',
          position: 'relative',
        },
        children: [
          text({ maxWidth: 660 }),
          {
            type: 'div',
            props: {
              style: { position: 'absolute', left: 100, bottom: 58, display: 'flex' },
              children: [motifImg],
            },
          },
        ],
      },
    };
  }

  return {
    type: 'div',
    props: {
      style: {
        display: 'flex',
        width: WIDTH,
        height: HEIGHT,
        backgroundColor: ground,
        position: 'relative',
      },
      children: [rule, body],
    },
  };
}

const args = parseArgs(process.argv);

if (args.list) {
  console.log(`Motifs:  ${Object.keys(MOTIFS).join(', ')}`);
  console.log(`Grounds: ${Object.keys(GROUNDS).join(', ')}`);
  process.exit(0);
}

const fontData = await loadFont();
const palette = GROUNDS[args.ground];

const svg = await satori(compose({ phrase: args.phrase, motif: args.motif, palette }), {
  width: WIDTH,
  height: HEIGHT,
  fonts: [{ name: 'Playfair Display', data: fontData, weight: 700, style: 'italic' }],
  embedFont: true,
});

// satori embeds the face as vector paths. If it ever emits a <text> node the
// glyphs were not resolved, which is the silent-fallback failure this script
// exists to prevent. Refuse to write it.
if (/<text[\s>]/.test(svg)) {
  throw new Error('satori emitted <text>, so the font did not resolve to outlines. Refusing to write.');
}

const png = new Resvg(svg, { fitTo: { mode: 'width', value: WIDTH } }).render().asPng();

await mkdir(path.dirname(args.out), { recursive: true });
await writeFile(args.out, png);
console.log(`wrote ${args.out} (${(png.length / 1024).toFixed(1)} KB) [${args.ground}/${args.motif}]`);
