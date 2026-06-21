/**
 * /p2p/success — confirmation screen after a successful transfer.
 *
 * Shows the amount + masked recipient + earned-PTS pill if the rules
 * engine fired for this transfer. CTAs: Done (back to home, stack
 * replaced) and Send another (back to the recipient picker).
 */
import { useLocalSearchParams, useRouter } from 'expo-router';
import { Button, Text, View, XStack, YStack } from 'tamagui';
import { SafeAreaView } from 'react-native-safe-area-context';

import { formatZAR, maskPhone } from '@/lib/format';

/** P2P success/confirmation screen. */
export default function SuccessScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ phone: string; amount: string; earned: string }>();
  const phone = typeof params.phone === 'string' ? params.phone : '';
  const amount = typeof params.amount === 'string' ? params.amount : '0';
  const earned = parseInt(typeof params.earned === 'string' ? params.earned : '0', 10) || 0;

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: '#FFFFFF' }}>
      <YStack flex={1} padding="$5" alignItems="center" justifyContent="center" gap="$4">
        {/* Checkmark — kept as a styled circle + glyph to avoid pulling in an icon lib. */}
        <View
          width={96}
          height={96}
          borderRadius={48}
          backgroundColor="$sasaiTeal"
          alignItems="center"
          justifyContent="center"
        >
          <Text color="white" fontSize={56} fontFamily="Inter-Bold" lineHeight={62}>
            ✓
          </Text>
        </View>

        <Text fontFamily="Inter-Bold" fontSize={26} color="$ink" textAlign="center">
          {formatZAR(amount)} sent
        </Text>
        <Text fontFamily="Inter-Regular" fontSize={15} color="$muted" textAlign="center">
          to {maskPhone(phone)}
        </Text>

        {earned > 0 ? (
          <XStack
            backgroundColor="rgba(72,194,207,0.18)"
            paddingHorizontal="$3"
            paddingVertical="$2"
            borderRadius={20}
            gap="$2"
            alignItems="center"
            marginTop="$2"
          >
            <Text fontFamily="Inter-SemiBold" fontSize={13} color="$sasaiNavy">
              +{earned} PTS earned
            </Text>
          </XStack>
        ) : null}

        <View flex={1} />

        <YStack width="100%" gap="$2">
          <Button
            size="$5"
            theme="active"
            backgroundColor="$sasaiNavy"
            color="white"
            onPress={() => router.replace('/home')}
            accessibilityLabel="Done"
          >
            Done
          </Button>
          <Button
            size="$5"
            backgroundColor="transparent"
            color="$sasaiNavy"
            onPress={() => router.replace('/p2p/recipient')}
            accessibilityLabel="Send another"
          >
            Send another
          </Button>
        </YStack>
      </YStack>
    </SafeAreaView>
  );
}
