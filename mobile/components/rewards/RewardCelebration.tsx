/**
 * RewardCelebration — a full-screen celebratory overlay shown on /home when the
 * user has an unseen earned reward.
 *
 * A dimmed modal with a clay card: a teal "burst" behind a gift Ionicon, a
 * "You earned …!" headline, and a dismiss button. The entrance is a scale +
 * fade-in built with React Native's `Animated` + `Modal`, matching the app's
 * existing overlay approach (see components/ui/SideDrawer.tsx) rather than
 * pulling in an animation library.
 *
 * Points render as "{value} points"; cashback as money in its own currency.
 * Dismissing is the caller's cue to mark the reward seen so it doesn't re-fire.
 */
import { useEffect, useRef } from 'react';
import { Animated, Modal, Pressable } from 'react-native';
import { Text, View, YStack } from 'tamagui';
import { Ionicons } from '@expo/vector-icons';

import { ClayButton } from '@/components/clay';
import { useColors } from '@/lib/colors';
import { formatMoney } from '@/lib/format';
import { type RecentReward } from '@/lib/api/rewards';

interface Props {
  /** The earned reward to celebrate. */
  reward: RecentReward;
  /** Called when the user dismisses — caller marks the reward seen. */
  onDismiss: () => void;
}

/**
 * Celebration copy for a reward: "You earned 200 points!" or, for cashback,
 * "You earned R 25.00!".
 */
function celebrationText(reward: RecentReward): string {
  if (reward.reward_type === 'cashback' && reward.currency) {
    return `You earned ${formatMoney(reward.value, reward.currency)}!`;
  }
  const points = parseFloat(reward.value);
  const count = Number.isFinite(points) ? Math.round(points) : 0;
  return `You earned ${count.toLocaleString('en-ZA')} points!`;
}

/** Reward-earned celebration overlay. */
export function RewardCelebration({ reward, onDismiss }: Props) {
  const colors = useColors();
  // Scale + fade the card in on mount — a single shared progress value drives
  // both so the entrance reads as one motion.
  const progress = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.spring(progress, {
      toValue: 1,
      friction: 7,
      tension: 60,
      useNativeDriver: true,
    }).start();
  }, [progress]);

  const scale = progress.interpolate({ inputRange: [0, 1], outputRange: [0.8, 1] });

  return (
    <Modal transparent visible animationType="fade" onRequestClose={onDismiss} statusBarTranslucent>
      {/* Dim overlay — tap outside the card to dismiss. */}
      <Pressable
        onPress={onDismiss}
        accessibilityRole="button"
        accessibilityLabel="Dismiss"
        style={{
          flex: 1,
          backgroundColor: 'rgba(12,27,42,0.55)',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 28,
        }}
      >
        {/* Stop taps on the card from bubbling to the dismiss overlay. */}
        <Pressable onPress={() => {}} style={{ width: '100%', maxWidth: 340 }}>
          <Animated.View style={{ opacity: progress, transform: [{ scale }] }}>
            <View
              backgroundColor={colors.clayRaised}
              borderRadius={28}
              paddingHorizontal={24}
              paddingVertical={30}
              alignItems="center"
            >
              {/* Gift icon on a teal burst. */}
              <View alignItems="center" justifyContent="center" marginBottom={18}>
                <View
                  width={96}
                  height={96}
                  borderRadius={48}
                  backgroundColor={colors.chipTealBg}
                  alignItems="center"
                  justifyContent="center"
                />
                <View
                  position="absolute"
                  width={70}
                  height={70}
                  borderRadius={35}
                  backgroundColor={colors.teal}
                  alignItems="center"
                  justifyContent="center"
                >
                  <Ionicons name="gift" size={36} color={colors.textOnDark} />
                </View>
              </View>

              <Text fontFamily="PlusJakartaSans-Bold" fontSize={13} color={colors.teal}>
                Reward unlocked
              </Text>
              <Text
                fontFamily="PlusJakartaSans-ExtraBold"
                fontSize={22}
                color={colors.text}
                textAlign="center"
                marginTop={6}
                letterSpacing={-0.3}
              >
                {celebrationText(reward)}
              </Text>
              {reward.rule_name ? (
                <Text
                  fontFamily="PlusJakartaSans-Medium"
                  fontSize={12.5}
                  color={colors.textMuted}
                  textAlign="center"
                  marginTop={8}
                >
                  {reward.rule_name}
                </Text>
              ) : null}

              <YStack width="100%" marginTop={22}>
                <ClayButton onPress={onDismiss} height={50} accessibilityLabel="Awesome, dismiss">
                  Awesome
                </ClayButton>
              </YStack>
            </View>
          </Animated.View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
