/**
 * StepIndicator — three-stripe progress bar used at the top of multi-step
 * flows (P2P recipient → amount → PIN). Active stripes are teal; inactive
 * stripes are a translucent white that matches the navy gradient header.
 */
import { XStack, View, Text, YStack } from 'tamagui';

import { useColors } from '@/lib/colors';

interface Props {
  /** Current step (1-indexed). 1 = recipient, 2 = amount, 3 = PIN. */
  step: 1 | 2 | 3;
  /** Total steps. Defaults to 3. */
  total?: number;
  /** Caption rendered below the bars, e.g., "Step 1 of 3 · Who are you paying?". */
  caption: string;
}

/** Step indicator bar + caption for the P2P flow header. */
export function StepIndicator({ step, total = 3, caption }: Props) {
  const colors = useColors();
  return (
    <YStack gap={8} marginTop={18}>
      <XStack gap={6} alignItems="center">
        {Array.from({ length: total }).map((_, i) => {
          const done = i < step;
          return (
            <View
              // eslint-disable-next-line react/no-array-index-key
              key={i}
              flex={1}
              height={6}
              borderRadius={4}
              backgroundColor={done ? colors.teal : 'rgba(255,255,255,0.22)'}
              // A hairline light top rim gives the active dot a puffy clay edge.
              borderTopWidth={done ? 1 : 0}
              borderTopColor="rgba(255,255,255,0.55)"
            />
          );
        })}
      </XStack>
      <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={12} color="#9fd9e2">
        {caption}
      </Text>
    </YStack>
  );
}
