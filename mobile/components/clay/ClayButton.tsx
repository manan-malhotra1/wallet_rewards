/**
 * ClayButton — the clay CTA primitive.
 *
 *   - `primary`  — a navy gradient face, white label, strong clay lift.
 *   - `neutral`  — a raised clay face, ink label, soft clay lift.
 *
 * The clay depth is a Skia `Box` painted behind the content (`ClayShape`): a
 * raised inner highlight/depth + an outer drop at rest, swapping to the
 * recessed `pressed` variant (no outer drop) while pressed, plus a 1px nudge
 * down. The primary face is a Skia linear gradient so the inner shadows read on
 * top of it. Logic stays with the caller — this is presentation. Public props
 * are unchanged.
 */
import { ActivityIndicator, Pressable } from 'react-native';
import { Text, View } from 'tamagui';

import { ClayShape, useClaySize, useClayTokens } from './ClayShape';

interface ClayButtonProps {
  /** Tap handler. Ignored while `disabled` or `loading`. */
  onPress?: () => void;
  disabled?: boolean;
  /** Swap the label for a spinner (keeps the button sized + tinted). */
  loading?: boolean;
  variant?: 'primary' | 'neutral';
  height?: number;
  radius?: number;
  /** Stretch to the parent width. Defaults to true. */
  fullWidth?: boolean;
  accessibilityLabel?: string;
  /** A string renders as the styled label; nodes render as-is (icon rows). */
  children: React.ReactNode;
}

/** Clay call-to-action button with a pressed-in state. */
export function ClayButton({
  onPress,
  disabled = false,
  loading = false,
  variant = 'primary',
  height = 54,
  radius = 16,
  fullWidth = true,
  accessibilityLabel,
  children,
}: ClayButtonProps) {
  const isPrimary = variant === 'primary';
  const inert = disabled || loading;
  const [size, onLayout] = useClaySize();
  const tokens = useClayTokens();
  const navyGradient = tokens.gradients.navy;
  // Primary uses the navy gradient (dark base); neutral uses the clay off-white.
  const fallbackFill = isPrimary ? navyGradient[1] : tokens.surface.raised;
  return (
    <Pressable
      onPress={inert ? undefined : onPress}
      disabled={inert}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      style={{ width: fullWidth ? '100%' : undefined, opacity: disabled ? 0.5 : 1 }}
    >
      {({ pressed }) => (
        <View
          onLayout={onLayout}
          height={height}
          borderRadius={radius}
          alignItems="center"
          justifyContent="center"
          backgroundColor={size ? 'transparent' : fallbackFill}
          style={{ transform: [{ translateY: pressed ? 1 : 0 }] }}
        >
          {size ? (
            <ClayShape
              width={size.w}
              height={size.h}
              radius={radius}
              fill={fallbackFill}
              variant={pressed ? 'pressed' : 'raised'}
              drop={isPrimary ? 'strong' : 'soft'}
              gradient={isPrimary ? navyGradient : undefined}
            />
          ) : null}
          {loading ? (
            <ActivityIndicator color={isPrimary ? '#ffffff' : '#00508F'} />
          ) : typeof children === 'string' ? (
            <Text
              fontFamily="PlusJakartaSans-Bold"
              fontSize={16}
              color={isPrimary ? '#ffffff' : '#00508F'}
            >
              {children}
            </Text>
          ) : (
            children
          )}
        </View>
      )}
    </Pressable>
  );
}
