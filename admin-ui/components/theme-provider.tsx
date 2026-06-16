/**
 * <ThemeProvider> — wraps next-themes so the `.dark` class toggles on
 * <html>. Required by globals.css for the dark token override.
 */
"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";
import * as React from "react";

export function ThemeProvider({
  children,
  ...props
}: React.ComponentProps<typeof NextThemesProvider>) {
  return <NextThemesProvider {...props}>{children}</NextThemesProvider>;
}
