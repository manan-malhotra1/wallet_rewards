/**
 * PinChallengeSheet — bottom sheet for step-up PIN entry.
 *
 * Slides up when the backend returns 401 `step_up_required` mid-flow.
 * Reuses the auth flow's PinInput so the keypad UX is identical across
 * /auth/pin and step-up moments. On submit, the parent runs the request
 * with the PIN attached; on wrong PIN (InvalidStepUpPin) the parent bumps
 * `attemptKey` to force a remount and clear the keypad.
 */
import { useState } from 'react';
import { Sheet, Text, YStack } from 'tamagui';

import { PinInput } from '@/components/forms/PinInput';

interface Props {
  /** Whether the sheet is visible. */
  open: boolean;
  /** Called when the user dismisses the sheet without entering a PIN. */
  onCancel: () => void;
  /** Called with the entered 4-digit PIN. */
  onSubmit: (pin: string) => void;
  /** Inline error text (e.g., "Incorrect PIN — try again"). Null = none. */
  error: string | null;
  /** Bump this to force-remount the keypad (clears the entered digits). */
  attemptKey: number;
}

function KeypadBody({
  attemptKey,
  errored,
  onSubmit,
}: {
  attemptKey: number;
  errored: boolean;
  onSubmit: (pin: string) => void;
}) {
  // Local state, remounted whenever `attemptKey` changes (via parent `key`).
  const [pin, setPin] = useState('');
  return (
    <PinInput
      value={pin}
      onChange={setPin}
      onComplete={(full) => onSubmit(full)}
      errored={errored}
      length={4}
      // attemptKey is consumed by the parent's <Fragment key=> to remount.
      // The prop is here purely for type-completeness.
      label={undefined}
    />
  );
}

/** Step-up PIN entry sheet. */
export function PinChallengeSheet({
  open,
  onCancel,
  onSubmit,
  error,
  attemptKey,
}: Props) {
  return (
    <Sheet
      modal
      open={open}
      onOpenChange={(o: boolean) => {
        if (!o) onCancel();
      }}
      snapPoints={[55]}
      dismissOnSnapToBottom
      animation="medium"
    >
      <Sheet.Overlay animation="quick" />
      <Sheet.Handle />
      <Sheet.Frame padding="$6" gap="$4" alignItems="center" backgroundColor="$surfaceLt">
        <YStack gap="$2" alignItems="center" marginTop="$2">
          <Text fontFamily="Inter-Bold" fontSize={22} color="$sasaiNavy">
            Confirm with PIN
          </Text>
          <Text fontFamily="Inter-Regular" fontSize={14} color="$muted" textAlign="center">
            This transfer needs your PIN to continue.
          </Text>
        </YStack>
        <KeypadBody key={attemptKey} attemptKey={attemptKey} errored={!!error} onSubmit={onSubmit} />
        {error && (
          <Text fontFamily="Inter-Medium" fontSize={13} color="$error" textAlign="center">
            {error}
          </Text>
        )}
      </Sheet.Frame>
    </Sheet>
  );
}
