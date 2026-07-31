/**
 * ClayShape — the shared Skia clay-depth renderer that sits BEHIND a
 * primitive's content.
 *
 * Every clay primitive (surface, card, button, pill, key, icon tile, inset)
 * composes this. It paints an absolutely-positioned Skia `Canvas` containing a
 * single rounded `Box` with the clay shadows: a near-white INNER highlight + a
 * navy INNER depth shadow (the puffy/carved look) and, for raised pieces, a
 * soft navy OUTER drop (the lift off the page). The primitive's own content
 * then paints on top of this canvas on a TRANSPARENT background, so the inner
 * shadows and fill remain visible (an opaque content layer would hide them).
 *
 * Skia caveats a reviewer should know:
 *   1. Sizing — a Skia `Canvas` has no intrinsic size and clips its drawing to
 *      its own bounds. The primitive measures itself via `onLayout`; until then
 *      it shows a plain rounded fill (no flash). We then oversize the canvas by
 *      `CLAY_SHADOW_PAD` on every side and draw the box inset by that pad, so
 *      the OUTER drop shadow isn't clipped.
 *   2. Inner-shadow signs — see the convention note in `recipe.ts`: positive
 *      `dx,dy` puts an inner shadow on the TOP-LEFT interior (CSS-inset parity).
 *   3. The oversized canvas overflows into sibling controls, so it MUST be
 *      inert to touch. It is wrapped in a plain RN `<View pointerEvents="none">`
 *      because Android does not reliably honour `pointerEvents` on the Skia
 *      `<Canvas>` itself — without the wrapper, an overflowing shadow steals
 *      taps from the neighbour it covers (e.g. keypad `1` firing `5`).
 */
import { useCallback, useState } from 'react';
import { type LayoutChangeEvent, View } from 'react-native';
import { Box, BoxShadow, Canvas, LinearGradient, rect, rrect, vec } from '@shopify/react-native-skia';

import {
  CLAY_SHADOW_PAD as PAD,
  claySkiaDrop,
  claySkiaInner,
  type ClaySkiaShadow,
} from './recipe';

/** Measured pixel size of a laid-out primitive. */
export interface ClaySize {
  w: number;
  h: number;
}

/**
 * Track a primitive's own pixel size for the Skia canvas.
 *
 * Returns the measured `size` (null until first layout) and an `onLayout`
 * handler to spread onto the primitive's outer view. Re-measures only when the
 * rounded size actually changes, to avoid render loops.
 *
 * Returns:
 *   [size, onLayout] — `size` is null pre-measurement; render a plain fill then.
 */
export function useClaySize(): [ClaySize | null, (e: LayoutChangeEvent) => void] {
  const [size, setSize] = useState<ClaySize | null>(null);
  const onLayout = useCallback((e: LayoutChangeEvent) => {
    const { width, height } = e.nativeEvent.layout;
    const w = Math.round(width);
    const h = Math.round(height);
    setSize((prev) => (prev && prev.w === w && prev.h === h ? prev : { w, h }));
  }, []);
  return [size, onLayout];
}

interface ClayShapeProps {
  /** Measured content-box width in px. */
  width: number;
  /** Measured content-box height in px. */
  height: number;
  /** Corner radius in px (matches the primitive's `borderRadius`). */
  radius: number;
  /** Solid surface fill. Ignored when `gradient` is supplied. */
  fill: string;
  /** Depth look. `raised` = puffy; `pressed`/`inset` = recessed. */
  variant: 'raised' | 'pressed' | 'inset';
  /**
   * Render the OUTER drop shadow (raised lift). Defaults to true for `raised`
   * and is forced off for `pressed`/`inset` (a recessed piece has no drop).
   */
  outer?: boolean;
  /** OUTER drop intensity tier. Defaults to `raised`. */
  drop?: 'soft' | 'raised' | 'strong';
  /** Optional 2+ stop gradient face (navy CTA, teal pill) rendered in Skia. */
  gradient?: readonly string[];
}

/** Map a `ClaySkiaShadow` spec onto a Skia `<BoxShadow>`. */
function shadow(spec: ClaySkiaShadow, key: string) {
  return (
    <BoxShadow
      key={key}
      inner={spec.inner}
      dx={spec.dx}
      dy={spec.dy}
      blur={spec.blur}
      color={spec.color}
    />
  );
}

/**
 * The Skia clay-depth canvas for one primitive. Render it as the first child of
 * a measured, transparent-background wrapper; the primitive's content follows
 * and paints on top.
 *
 * Renders null for a zero/negative size (pre-measurement guard).
 */
export function ClayShape({
  width,
  height,
  radius,
  fill,
  variant,
  outer,
  drop = 'raised',
  gradient,
}: ClayShapeProps) {
  if (width <= 0 || height <= 0) return null;

  // Draw the box inset by PAD inside an oversized canvas so the outer drop
  // shadow has room and isn't clipped by the canvas bounds.
  const box = rrect(rect(PAD, PAD, width, height), radius, radius);
  const inner = claySkiaInner[variant];
  // Only raised pieces lift; pressed/inset never carry an outer drop.
  const showOuter = variant === 'raised' && outer !== false;

  // Wrap the Skia Canvas in a plain RN View with `pointerEvents="none"`.
  // WHY: the canvas is oversized by PAD on every side to fit the outer drop
  // shadow, so it overflows well into sibling controls (e.g. a keypad key's
  // canvas covers its neighbours). On Android, react-native-skia's <Canvas>
  // does NOT reliably honour its own `pointerEvents` prop, so that overflow
  // steals taps meant for the neighbour and fires the wrong key. A RN <View>
  // DOES honour `pointerEvents="none"` on Android, removing the whole
  // decorative subtree from hit-testing. iOS was already correct; this keeps
  // it correct and fixes Android. Visual output is unchanged.
  return (
    <View
      pointerEvents="none"
      style={{
        position: 'absolute',
        top: -PAD,
        left: -PAD,
        width: width + PAD * 2,
        height: height + PAD * 2,
      }}
    >
      <Canvas pointerEvents="none" style={{ flex: 1 }}>
        <Box box={box} color={fill}>
          {gradient ? (
            <LinearGradient
              start={vec(PAD, PAD)}
              end={vec(PAD + width, PAD + height)}
              colors={[...gradient]}
            />
          ) : null}
          {showOuter ? shadow(claySkiaDrop[drop], 'drop') : null}
          {shadow(inner.depth, 'depth')}
          {shadow(inner.highlight, 'highlight')}
        </Box>
      </Canvas>
    </View>
  );
}
