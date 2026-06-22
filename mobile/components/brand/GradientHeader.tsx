/**
 * GradientHeader — the signature Sasai Pay navy hero treatment.
 *
 * Used as the top portion of nearly every primary screen (login, home,
 * transactions, rewards, P2P recipient/amount/PIN, plus success/failure
 * receipts with status-tinted gradients).
 *
 * Layout:
 *   - Linear gradient background (default navy; status variant for receipts)
 *   - One decorative swoosh circle bleeding off the top-right corner
 *   - SafeArea-aware top padding (children render below the system bar)
 *   - Children render with horizontal padding already applied
 */
import { ReactNode } from 'react';
import { LinearGradient } from 'expo-linear-gradient';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { View } from 'tamagui';

type Variant = 'navy' | 'success' | 'failed';

const STOPS: Record<Variant, readonly [string, string]> = {
  navy: ['#00538f', '#013a6b'],
  success: ['#0a8a5f', '#067a52'],
  failed: ['#c0392b', '#a52e22'],
};

interface Props {
  /** Children rendered inside the gradient. Horizontal padding is applied
   *  here; the consumer provides vertical rhythm. */
  children: ReactNode;
  /** Hero color treatment. Defaults to the signature navy. */
  variant?: Variant;
  /** Bottom padding inside the gradient (above any overlapping content). */
  paddingBottom?: number;
  /** Hide the decorative swoosh circle (set true for very tight headers). */
  hideSwoosh?: boolean;
}

/** Navy/success/failed gradient hero with a decorative swoosh circle. */
export function GradientHeader({
  children,
  variant = 'navy',
  paddingBottom = 22,
  hideSwoosh = false,
}: Props) {
  const insets = useSafeAreaInsets();
  return (
    <LinearGradient
      colors={STOPS[variant]}
      start={{ x: 0, y: 0 }}
      end={{ x: 0.55, y: 1 }}
      style={{
        paddingTop: insets.top + 6,
        paddingBottom,
        paddingHorizontal: 22,
        overflow: 'hidden',
        position: 'relative',
      }}
    >
      {!hideSwoosh && (
        // Translucent ring "swoosh" — pure decoration. Positioned top-right,
        // bleeds off-screen. The ring is teal-tinted on navy and white-tinted
        // on the status variants (which already have heavy color).
        <View
          position="absolute"
          width={220}
          height={220}
          borderRadius={110}
          borderWidth={32}
          borderColor={
            variant === 'navy'
              ? 'rgba(80,192,208,0.14)'
              : 'rgba(255,255,255,0.10)'
          }
          top={-90}
          right={-80}
          pointerEvents="none"
        />
      )}
      <View position="relative" zIndex={2}>
        {children}
      </View>
    </LinearGradient>
  );
}
