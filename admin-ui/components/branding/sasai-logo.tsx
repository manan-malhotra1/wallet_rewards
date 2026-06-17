/**
 * <SasaiLogo> — renders the official Sasai logo from `public/sasai-logo.png`.
 *
 * The asset lives in `admin-ui/public/sasai-logo.png` and is served at
 * `/sasai-logo.png` by Next.js. Drop a higher-DPI replacement at the
 * same path to swap brands.
 *
 * Width auto-scales from the supplied `height` so the aspect ratio is
 * preserved regardless of the source file's exact dimensions — no
 * truncation.
 */
import * as React from "react";

interface SasaiLogoProps {
  /** Height in pixels. Width scales to keep the image's aspect ratio. */
  height?: number;
  className?: string;
}

export function SasaiLogo({
  height = 32,
  className,
}: SasaiLogoProps): React.ReactElement {
  // Plain <img> instead of next/image to avoid forcing an explicit
  // width — the file's natural aspect ratio carries the proportions.
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src="/sasai-logo.png"
      alt="Sasai"
      style={{ height, width: "auto", display: "block" }}
      className={className}
    />
  );
}
