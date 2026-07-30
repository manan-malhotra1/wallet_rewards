/**
 * ClayIconTile — a raised clay action tile (home quick actions, icon chips).
 *
 * A small rounded clay square that lifts off the page via a Skia clay `Box`
 * behind its content (raised inner shadows + soft outer drop). Optionally
 * tappable: when `onPress` is given it renders inside a Pressable and reads
 * pushed-in on press (the Skia `pressed` variant — recessed, no outer drop).
 * Children are the icon/emoji; any label sits outside the tile at the call
 * site. Public props are unchanged.
 */
import { Pressable } from 'react-native';
import { View } from 'tamagui';

import { ClayShape, useClaySize } from './ClayShape';
import { claySurface } from './recipe';

interface ClayIconTileProps {
  onPress?: () => void;
  size?: number;
  radius?: number;
  fill?: string;
  accessibilityLabel?: string;
  children: React.ReactNode;
}

/** Inner face — shared by the static and pressable renders. */
function TileFace({
  size,
  radius,
  fill,
  pressed,
  children,
}: {
  size: number;
  radius: number;
  fill: string;
  pressed: boolean;
  children: React.ReactNode;
}) {
  // Size is fixed and known up-front, so the Skia canvas can render on the
  // first pass — no `onLayout` round-trip needed for this primitive.
  return (
    <View
      width={size}
      height={size}
      borderRadius={radius}
      alignItems="center"
      justifyContent="center"
      backgroundColor="transparent"
    >
      <ClayShape
        width={size}
        height={size}
        radius={radius}
        fill={fill}
        variant={pressed ? 'pressed' : 'raised'}
        drop="soft"
      />
      {children}
    </View>
  );
}

/** Raised clay icon tile. Tappable when `onPress` is provided. */
export function ClayIconTile({
  onPress,
  size = 54,
  radius = 18,
  fill = claySurface.raised,
  accessibilityLabel,
  children,
}: ClayIconTileProps) {
  if (!onPress) {
    return (
      <TileFace size={size} radius={radius} fill={fill} pressed={false}>
        {children}
      </TileFace>
    );
  }
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
    >
      {({ pressed }) => (
        <TileFace size={size} radius={radius} fill={fill} pressed={pressed}>
          {children}
        </TileFace>
      )}
    </Pressable>
  );
}
