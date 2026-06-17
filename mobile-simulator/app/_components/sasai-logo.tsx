/**
 * <SasaiLogo> — renders the official Sasai logo from
 * `mobile-simulator/public/sasai-logo.png`. Width auto-scales from the
 * supplied `height` so the file's aspect ratio is preserved.
 */
import * as React from "react";

interface SasaiLogoProps {
  height?: number;
  className?: string;
}

export function SasaiLogo({
  height = 32,
  className,
}: SasaiLogoProps): React.ReactElement {
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
