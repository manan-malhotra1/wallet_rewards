/**
 * Clay design-language primitives barrel.
 *
 * The claymorphism surface kit: soft low-contrast clay surfaces, big rounded
 * corners, a puffy dual-shadow look (navy drop below-right + white sheen
 * above-left), and pressed-in states on keys/buttons. Screens compose these so
 * the shadow + gradient recipe lives in one place (`recipe.ts`).
 */
export { ClaySurface, ClayCard } from './ClaySurface';
export { ClayButton } from './ClayButton';
export { ClayPill } from './ClayPill';
export { ClayKey } from './ClayKey';
export { ClayIconTile } from './ClayIconTile';
export { ClayInset } from './ClayInset';
export * as clay from './recipe';
