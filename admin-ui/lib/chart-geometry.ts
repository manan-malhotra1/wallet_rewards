/**
 * Pure SVG geometry for the dashboard's hand-rolled charts.
 *
 * The analytics dashboard draws its own SVG rather than going through a chart
 * library, so the plot maths lives here: DOM-free, dependency-free, and under
 * the `admin-ui/lib/` coverage gate. Every builder takes an explicit
 * {@link PlotRect} so a series can be drawn inset from the SVG edge (leaving
 * room for the y-axis gutter) without post-processing the path string.
 *
 * Coordinates are SVG user units with y growing downwards, which is why every
 * `y` here is `rect.y + rect.height - <scaled value>`.
 */

/** The rectangle a series is drawn inside, in SVG user units. */
export interface PlotRect {
  /** Left edge — the y-axis gutter width. */
  x: number;
  /** Top edge. */
  y: number;
  /** Drawable width. */
  width: number;
  /** Drawable height. */
  height: number;
}

/** One horizontal gridline: where to draw it and the value it represents. */
export interface GridLine {
  /** y coordinate of the line. */
  y: number;
  /** The domain value at this line, for the axis label. */
  value: number;
}

/** One x-axis tick: where to draw it and its label. */
export interface XTick {
  /** x coordinate of the tick's centre. */
  x: number;
  /** The bucket label to render. */
  label: string;
}

/** Round coordinates to 2dp — keeps path strings short and diff-stable. */
function fixed(n: number): string {
  return n.toFixed(2);
}

/**
 * The x coordinate of point `index` of `count` evenly spaced points.
 *
 * A single point is centred rather than pinned to the left edge, so a
 * one-bucket range doesn't draw a line hugging the axis.
 */
export function xAt(index: number, count: number, rect: PlotRect): number {
  if (count <= 1) return rect.x + rect.width / 2;
  return rect.x + (index / (count - 1)) * rect.width;
}

/**
 * The y coordinate of `value` scaled into `rect` over the domain `[min, max]`.
 *
 * A zero-width domain (max === min) pins to the bottom instead of dividing by
 * zero, which is what a flat all-equal series should look like.
 */
export function yAt(value: number, min: number, max: number, rect: PlotRect): number {
  if (max === min) return rect.y + rect.height;
  return rect.y + rect.height - ((value - min) / (max - min)) * rect.height;
}

/**
 * A smooth (cubic Bézier) line path through `values`.
 *
 * Control points sit one third of the way between neighbours on the x axis
 * with the neighbour's own y, which yields the same relaxed curve as a
 * monotone spline without overshooting past a data point — important for money
 * series, where a curve dipping below zero between two positive buckets would
 * misrepresent the data.
 *
 * @returns an SVG path, or `""` for an empty series (safe to pass to `d`).
 */
export function smoothPath(
  values: number[],
  rect: PlotRect,
  max: number,
  min = 0,
): string {
  const count = values.length;
  if (count === 0) return "";
  const px = (i: number) => xAt(i, count, rect);
  const py = (v: number) => yAt(v, min, max, rect);

  let path = `M${fixed(px(0))} ${fixed(py(values[0]))}`;
  if (count === 1) return path;
  for (let i = 1; i < count; i++) {
    const x0 = px(i - 1);
    const x1 = px(i);
    const dx = (x1 - x0) / 3;
    path +=
      ` C${fixed(x0 + dx)} ${fixed(py(values[i - 1]))}` +
      `,${fixed(x1 - dx)} ${fixed(py(values[i]))}` +
      `,${fixed(x1)} ${fixed(py(values[i]))}`;
  }
  return path;
}

/**
 * Close a line path into a filled area by dropping to the baseline.
 *
 * Takes the output of {@link smoothPath} so the fill traces exactly the same
 * curve as the stroke — deriving it separately is how the two drift apart.
 */
export function areaPath(line: string, rect: PlotRect): string {
  if (!line) return "";
  const bottom = rect.y + rect.height;
  return `${line} L${fixed(rect.x + rect.width)} ${fixed(bottom)} L${fixed(rect.x)} ${fixed(bottom)} Z`;
}

/** Cartesian coordinates of an angle on a circle, measuring 0° from 12 o'clock. */
function polar(cx: number, cy: number, r: number, degrees: number): [number, number] {
  const radians = ((degrees - 90) * Math.PI) / 180;
  return [cx + r * Math.cos(radians), cy + r * Math.sin(radians)];
}

/**
 * A donut ring segment: outer arc clockwise, inner arc back.
 *
 * @param outer - outer radius
 * @param inner - inner radius (the hole)
 * @param startDeg - start angle, 0° at 12 o'clock, growing clockwise
 * @param endDeg - end angle; a span over 180° sets the large-arc flag
 */
export function ringPath(
  cx: number,
  cy: number,
  outer: number,
  inner: number,
  startDeg: number,
  endDeg: number,
): string {
  const large = endDeg - startDeg > 180 ? 1 : 0;
  const [x0, y0] = polar(cx, cy, outer, startDeg);
  const [x1, y1] = polar(cx, cy, outer, endDeg);
  const [x2, y2] = polar(cx, cy, inner, endDeg);
  const [x3, y3] = polar(cx, cy, inner, startDeg);
  return (
    `M${fixed(x0)} ${fixed(y0)} A${outer} ${outer} 0 ${large} 1 ${fixed(x1)} ${fixed(y1)}` +
    ` L${fixed(x2)} ${fixed(y2)} A${inner} ${inner} 0 ${large} 0 ${fixed(x3)} ${fixed(y3)} Z`
  );
}

/**
 * A bar with its outer end rounded, growing up (`height >= 0`) or down.
 *
 * `y` is always the bar's baseline end, so a downward bar (outflow below the
 * zero line) is drawn by passing a negative height and gets its rounding on
 * the bottom edge instead — the two directions stay visually symmetrical.
 *
 * The corner radius is clamped to half the width and the bar's own height so a
 * very short bar degrades to a nub rather than inverting its curves.
 */
export function barPath(x: number, y: number, width: number, height: number, radius: number): string {
  const r = Math.max(0, Math.min(radius, width / 2, Math.abs(height)));
  if (height >= 0) {
    const top = y - height;
    return (
      `M${fixed(x)} ${fixed(y)} L${fixed(x)} ${fixed(top + r)}` +
      ` Q${fixed(x)} ${fixed(top)} ${fixed(x + r)} ${fixed(top)}` +
      ` L${fixed(x + width - r)} ${fixed(top)}` +
      ` Q${fixed(x + width)} ${fixed(top)} ${fixed(x + width)} ${fixed(top + r)}` +
      ` L${fixed(x + width)} ${fixed(y)} Z`
    );
  }
  const bottom = y - height;
  return (
    `M${fixed(x)} ${fixed(y)} L${fixed(x)} ${fixed(bottom - r)}` +
    ` Q${fixed(x)} ${fixed(bottom)} ${fixed(x + r)} ${fixed(bottom)}` +
    ` L${fixed(x + width - r)} ${fixed(bottom)}` +
    ` Q${fixed(x + width)} ${fixed(bottom)} ${fixed(x + width)} ${fixed(bottom - r)}` +
    ` L${fixed(x + width)} ${fixed(y)} Z`
  );
}

/**
 * Round `value` up to a readable axis maximum (1, 2, 2.5, 5 or 10 × a power of
 * ten) so gridline labels land on round numbers instead of the data's max.
 *
 * Non-positive input returns 1: an all-zero series still needs a domain.
 */
export function niceMax(value: number): number {
  if (!Number.isFinite(value) || value <= 0) return 1;
  const magnitude = Math.pow(10, Math.floor(Math.log10(value)));
  const scaled = value / magnitude;
  const step = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 2.5 ? 2.5 : scaled <= 5 ? 5 : 10;
  return step * magnitude;
}

/**
 * `count + 1` evenly spaced gridlines from 0 up to `max` inclusive.
 *
 * Returned bottom-up (0 first) so the caller can label them in domain order.
 */
export function gridLines(max: number, rect: PlotRect, count: number): GridLine[] {
  const lines: GridLine[] = [];
  for (let i = 0; i <= count; i++) {
    lines.push({
      y: rect.y + rect.height - (i / count) * rect.height,
      value: (max / count) * i,
    });
  }
  return lines;
}

/**
 * Thin `labels` down to at most `want` x-axis ticks.
 *
 * Steps by a whole number of buckets so the kept labels stay evenly spaced —
 * a 90-day range shows every 12th day rather than an uneven scatter.
 */
export function xTicks(labels: string[], rect: PlotRect, want: number): XTick[] {
  const count = labels.length;
  if (count === 0) return [];
  const step = Math.max(1, Math.ceil(count / Math.max(1, want)));
  const ticks: XTick[] = [];
  for (let i = 0; i < count; i += step) {
    ticks.push({ x: xAt(i, count, rect), label: labels[i] });
  }
  return ticks;
}

/**
 * The centre x of each band in a banded (bar) chart.
 *
 * Bars occupy a band rather than sitting on a point, so they are centred at
 * `(i + 0.5)` band widths — using the line-chart {@link xAt} spacing instead
 * would push the first and last bars half out of the plot.
 */
export function bandCentres(count: number, rect: PlotRect): number[] {
  if (count <= 0) return [];
  const band = rect.width / count;
  return Array.from({ length: count }, (_, i) => rect.x + (i + 0.5) * band);
}

/** {@link xTicks} for banded charts: same thinning, band-centre positions. */
export function bandTicks(labels: string[], rect: PlotRect, want: number): XTick[] {
  const centres = bandCentres(labels.length, rect);
  const step = Math.max(1, Math.ceil(labels.length / Math.max(1, want)));
  const ticks: XTick[] = [];
  for (let i = 0; i < labels.length; i += step) {
    ticks.push({ x: centres[i], label: labels[i] });
  }
  return ticks;
}

/**
 * The index of the bucket nearest a pointer position, for chart hover.
 *
 * @param offsetX - pointer x within the SVG's client rect, already scaled into
 *   viewBox units by the caller (which is the only part that needs the DOM)
 * @returns a valid index, clamped to the series — never null, so the hover
 *   cursor can't land off the plot
 */
export function nearestIndex(offsetX: number, count: number, rect: PlotRect): number {
  if (count <= 1) return 0;
  const ratio = (offsetX - rect.x) / rect.width;
  return Math.max(0, Math.min(count - 1, Math.round(ratio * (count - 1))));
}
