/**
 * Shared class for the action buttons sitting on the user-detail brand hero.
 *
 * The `outline` Button variant sets no text colour, so on the hero it inherits
 * `text-primary-foreground` — cream on a white `bg-background` in light mode,
 * i.e. an invisible label. These buttons therefore drop the opaque surface for
 * a translucent one tinted against the hero, which reads in both themes.
 */
export const heroActionButtonClass =
  "gap-1.5 border-primary-foreground/30 bg-primary-foreground/10 text-primary-foreground hover:bg-primary-foreground/20 hover:text-primary-foreground";
