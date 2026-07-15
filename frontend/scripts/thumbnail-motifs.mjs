/**
 * Motif library for blog featured images.
 *
 * Each motif is a self-contained SVG fragment drawn in its own coordinate
 * space. Motifs never set the ground colour; they receive the resolved
 * palette so the same motif works on charcoal, panel and amber.
 *
 * The vocabulary is the terminal one ClusterPilot already speaks: the
 * prompt chevron, rounded blocks joined by arrows, a hop from here to
 * there, a plot line ending in a dot, a hairline rule with a terminal dot
 * along one edge.
 *
 * Every motif declares `pad`. Strokes are centred on their path and
 * offset hairlines are drawn at negative coordinates, so a viewBox
 * starting at 0,0 silently clips them. The generator expands the viewBox
 * by `pad` on all sides. If you add a motif that draws outside 0..w/0..h,
 * raise its pad to match or it will render cropped.
 *
 * `place` is the layout preset the generator composes with:
 *   'below'    motif centred above, phrase beneath it
 *   'beside'   motif left, phrase to its right, both sitting high
 *   'diagonal' phrase upper left, motif spanning the lower half
 */

/**
 * Palette contract. Every motif reads its colours from the resolved
 * palette; nothing is hardcoded, because the three sites do not share an
 * accent set. ClusterPilot's restyle (tasks/todo.md B.1) explicitly drops
 * #FFB866, so a motif that bakes in juliafrank's amber cannot port.
 *
 *   ground      the card background
 *   ink         type and hairlines
 *   accent      thin strokes and small marks (must read as text on ground)
 *   accentFill  large filled areas (may be lower contrast than accent)
 *   blocks      four fills for the chain, ordered light to accent
 *
 * The accent/accentFill split is a real contrast rule from B.1, not a
 * stylistic one: #e8a020 is a fill colour and #FFC46B is amber-as-text
 * (~9:1). A hairline drawn in the fill amber fails on charcoal.
 */

/** The terminal prompt: a chevron and its underscore. */
function prompt({ accent }) {
  return {
    place: 'beside',
    w: 132,
    h: 92,
    pad: 10,
    svg: `
      <path d="M 12 16 L 52 46 L 12 76" stroke="${accent}" stroke-width="13"
            fill="none" stroke-linecap="round" stroke-linejoin="round"/>
      <rect x="64" y="64" width="58" height="12" rx="6" fill="${accent}"/>
    `,
  };
}

/** Four rounded blocks joined by arrows, each with an offset hairline. */
function chain({ ink, blocks }) {
  const fills = blocks;
  const step = 168;
  const size = 112;
  const rects = fills
    .map((fill, i) => {
      const x = i * step;
      return `
        <rect x="${x - 11}" y="-11" width="${size}" height="${size}" rx="3"
              fill="none" stroke="${fill}" stroke-width="2" opacity="0.85"/>
        <rect x="${x}" y="0" width="${size}" height="${size}" rx="3" fill="${fill}"/>
      `;
    })
    .join('');
  const arrows = [0, 1, 2, 3]
    .map((i) => {
      const x = i * step + size + 8;
      const y = size / 2;
      return `<g opacity="0.9">${arrow([x, y], [x + 38, y], {
        colour: ink,
        width: 2.5,
        head: 11,
        spread: 5,
      })}</g>`;
    })
    .join('');
  return { place: 'below', w: 3 * step + size + 46, h: size, pad: 14, svg: rects + arrows };
}

/**
 * An arrow from `a` to `b` with a filled triangular head.
 *
 * The head is a filled triangle, not a stroked V. A stroked V is only
 * legible on a steep arrow: on a shallow one its upper barb lands nearly
 * parallel to the shaft and reads as a stray whisker. A triangle is
 * correct at every angle.
 */
export function arrow(a, b, { colour, width = 6, head = 30, spread = 12 }) {
  const [ax, ay] = a;
  const [bx, by] = b;
  const dx = bx - ax;
  const dy = by - ay;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len;
  const uy = dy / len;
  const px = -uy;
  const py = ux;
  // Stop the shaft at the head's base so it never pokes through the tip.
  const sx = bx - ux * head;
  const sy = by - uy * head;
  const p1 = [sx + px * spread, sy + py * spread];
  const p2 = [sx - px * spread, sy - py * spread];
  return `
    <path d="M ${ax} ${ay} L ${sx.toFixed(1)} ${sy.toFixed(1)}" stroke="${colour}"
          stroke-width="${width}" fill="none" stroke-linecap="round"/>
    <polygon points="${bx},${by} ${p1[0].toFixed(1)},${p1[1].toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}"
             fill="${colour}"/>
  `;
}

/**
 * A big block low left and a small one high right, joined by a long
 * diagonal arrow. Spans the frame: the phrase sits over the empty upper
 * left, so the arrow is free to cross the whole card.
 */
function hop({ ink, accentFill, blocks }) {
  return {
    place: 'diagonal',
    w: 1060,
    h: 500,
    pad: 12,
    svg: `
      <rect x="0" y="330" width="286" height="170" rx="28" fill="${accentFill}"/>
      <rect x="912" y="0" width="148" height="100" rx="20" fill="${blocks[2]}"/>
      ${arrow([300, 402], [906, 112], { colour: ink })}
    `,
  };
}

/**
 * A plot line stepping up through marked points, ending in a filled dot.
 * Point centres are punched out in the ground colour so the line does not
 * read through them, which is why this motif needs the real ground rather
 * than a guess derived from the ink.
 */
function plot({ accent, ground }) {
  const pts = [
    [0, 150],
    [96, 108],
    [192, 126],
    [288, 58],
    [384, 74],
    [480, 12],
  ];
  const d = pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'} ${x} ${y}`).join(' ');
  const dots = pts
    .slice(1, -1)
    .map(
      ([x, y]) =>
        `<circle cx="${x}" cy="${y}" r="6" fill="${ground}" stroke="${accent}" stroke-width="3"/>`
    )
    .join('');
  const [lx, ly] = pts[pts.length - 1];
  return {
    place: 'below',
    w: 480,
    h: 162,
    pad: 16,
    svg: `
      <path d="${d}" stroke="${accent}" stroke-width="4" fill="none"
            stroke-linecap="round" stroke-linejoin="round"/>
      ${dots}
      <circle cx="${lx}" cy="${ly}" r="11" fill="${accent}"/>
    `,
  };
}

export const MOTIFS = { prompt, chain, hop, plot };

/**
 * The hairline rule with a terminal dot that runs along one edge of the
 * card. Drawn into its own full-width layer.
 */
export function ruleDevice({ ink, width = 1280, height = 60 }) {
  const y = height / 2;
  const stop = Math.round(width * 0.66);
  return `
    <line x1="0" y1="${y}" x2="${stop}" y2="${y}" stroke="${ink}"
          stroke-width="2.5" opacity="0.9"/>
    <circle cx="${stop}" cy="${y}" r="8" fill="${ink}"/>
  `;
}
