/**
 * ClayIconTile — a raised clay action tile (home quick actions, icon chips).
 *
 * A small rounded clay square that lifts off the page, with the top-left white
 * sheen. Optionally tappable: when `onPress` is given it renders inside a
 * Pressable and reads pushed-in on press. Children are the icon/emoji; any
 * label sits outside the tile at the call site.
 */
import { Pressable } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { View } from 'tamagui';

import {
  claySurface,
  clayRimLight,
  elevation,
  highlightColors,
  highlightEnd,
  highlightLocations,
  highlightStart,
  insetShadeColors,
  insetShadeLocations,
  overlayFill,
  shadowPressed,
  shadowSoft,
} from './recipe';

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
  return (
    <View
      width={size}
      height={size}
      borderRadius={radius}
      alignItems="center"
      justifyContent="center"
      backgroundColor={fill}
      borderWidth={1}
      borderColor={pressed ? claySurface.inset : clayRimLight}
      {...(pressed ? shadowPressed : shadowSoft)}
      style={{
        elevation: pressed ? elevation.pressed : elevation.soft,
        transform: [{ translateY: pressed ? 1 : 0 }],
      }}
    >
      {pressed ? (
        <LinearGradient
          colors={insetShadeColors}
          locations={insetShadeLocations}
          start={{ x: 0, y: 0 }}
          end={{ x: 0, y: 1 }}
          pointerEvents="none"
          style={overlayFill(radius)}
        />
      ) : (
        <LinearGradient
          colors={highlightColors}
          locations={highlightLocations}
          start={highlightStart}
          end={highlightEnd}
          pointerEvents="none"
          style={overlayFill(radius)}
        />
      )}
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
