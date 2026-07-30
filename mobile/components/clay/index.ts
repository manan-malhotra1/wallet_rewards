/**
 * Clay design-language primitives barrel.
 *
 * The claymorphism surface kit: soft low-contrast clay surfaces, big rounded
 * corners, and true puffy depth rendered with `@shopify/react-native-skia` — a
 * clay `Box` painted behind each primitive's content with real inner
 * (highlight + depth) and outer drop shadows (see `ClayShape.tsx`), plus
 * pressed-in states on keys/buttons. The shadow + colour recipe lives in one
 * place (`recipe.ts`).
 */
export { ClaySurface, ClayCard } from './ClaySurface';
export { ClayButton } from './ClayButton';
export { ClayPill } from './ClayPill';
export { ClayKey } from './ClayKey';
export { ClayIconTile } from './ClayIconTile';
export { ClayInset } from './ClayInset';
export * as clay from './recipe';
