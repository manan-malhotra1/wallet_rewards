/**
 * /home — the Pay tab. Sasai Pay redesign (multi-currency).
 *
 * Top: navy gradient hero with avatar + greeting, points pill, bell.
 * Below it, a SWIPEABLE horizontal carousel of clay balance cards — one
 * per financial wallet (e.g. ZAR + INR) — with page-dot indicators. The
 * active card's currency drives every quick action (Send / Airtime /
 * Cash out) so downstream screens debit the right wallet.
 * Quick actions row, a "send money home" promo, and recent activity all
 * sit inside a vertical ScrollView so content below the fold is reachable.
 *
 * Pulls /me/wallet for the name, per-wallet balances, and the PTS pill.
 * Loading + error states fall back to muted greetings rather than
 * blocking the screen — the rest of the UI still renders.
 */
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, useWindowDimensions } from 'react-native';
import { useRouter } from 'expo-router';
import { useQuery } from '@tanstack/react-query';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Text, View, XStack, YStack } from 'tamagui';
import { Ionicons } from '@expo/vector-icons';

import { ActivityRow } from '@/components/ui/ActivityRow';
import { BottomTabBar } from '@/components/ui/BottomTabBar';
import { SideDrawer } from '@/components/ui/SideDrawer';
import { GradientHeader } from '@/components/brand/GradientHeader';
import { ClaySurface, ClayIconTile } from '@/components/clay';
import { signOut } from '@/lib/auth';
import { SessionExpired } from '@/lib/api/errors';
import {
  activityCategory,
  getMyServices,
  getMyWallet,
  transactionTitle,
  type MyService,
  type WalletAccount,
} from '@/lib/api/wallet';
import { currencySymbol, formatMoney } from '@/lib/format';
import { qk } from '@/lib/query';
import { clearAll, getLastPhone } from '@/lib/storage';

/** Ionicons glyph name — a typed union so only valid glyphs compile. */
type IconName = React.ComponentProps<typeof Ionicons>['name'];

/** A rendered quick-action tile. `route` carries the active wallet currency. */
interface Tile {
  icon: IconName;
  label: string;
  route: (currency: string) => string;
}

/**
 * Known money-service code → tile mapping. The pay tiles are driven by the
 * per-user `/me/services` list; each returned service `code` is looked up here
 * for its icon, label, and currency-aware route. Codes NOT in this map (e.g.
 * `change_pin`, which belongs in the drawer) are filtered out — they are not
 * money actions and never render as pay tiles. `cash_in` / `redemption` route
 * to `/home` as placeholders until their flow screens ship, but the tile still
 * shows so an agent sees "Cash in" instead of "Send".
 */
const SERVICE_TILE: Record<string, Tile> = {
  p2p: { icon: 'paper-plane', label: 'Send', route: (c) => `/p2p/recipient?currency=${c}` },
  airtime_recharge: {
    icon: 'phone-portrait',
    label: 'Airtime',
    route: (c) => `/airtime?currency=${c}`,
  },
  cashout: { icon: 'cash-outline', label: 'Cash out', route: (c) => `/cashout?currency=${c}` },
  cash_in: { icon: 'enter-outline', label: 'Cash in', route: (c) => `/cashin?currency=${c}` },
  redemption: { icon: 'gift-outline', label: 'Rewards', route: () => '/home' }, // placeholder
};

/**
 * Static consumer tiles shown while `/me/services` is loading so the pay row is
 * never empty. Once the query resolves the real per-user tiles replace these
 * (an agent then sees "Cash in" instead of "Send").
 */
const FALLBACK_TILES: ReadonlyArray<Tile> = [
  SERVICE_TILE.p2p,
  SERVICE_TILE.airtime_recharge,
  SERVICE_TILE.cashout,
];

/**
 * Map the per-user services to renderable tiles: keep only codes we have a
 * money-tile for (drops `change_pin` and any non-money/settings code), and
 * prefer the backend `display_name` as the label when present.
 */
function tilesFromServices(services: MyService[]): Tile[] {
  return services
    .filter((s) => s.code in SERVICE_TILE)
    .map((s) => {
      const base = SERVICE_TILE[s.code];
      return { ...base, label: s.display_name?.trim() || base.label };
    });
}

/** Format a decimal-string amount as { whole, cents } for the big display —
 *  the cents render in a smaller muted tint. Symbol is applied separately so
 *  the two type sizes line up. */
function splitAmount(amount: string): { whole: string; cents: string } {
  const n = parseFloat(amount);
  if (!Number.isFinite(n)) return { whole: '0', cents: '.00' };
  const [w, c] = n.toFixed(2).split('.');
  const withSep = w.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return { whole: withSep, cents: `.${c ?? '00'}` };
}

/** Pending = total balance minus available; only shown when positive. */
function pendingAmount(account: WalletAccount): string {
  const total = parseFloat(account.balance ?? '0');
  const avail = parseFloat(account.available_balance ?? '0');
  const diff = total - avail;
  return Number.isFinite(diff) && diff > 0 ? diff.toFixed(2) : '0.00';
}

/** Initials for the avatar circle — first two letters of the first name. */
function initials(name: string | null | undefined): string {
  if (!name) return '··';
  const parts = name.trim().split(/\s+/);
  const first = parts[0]?.[0] ?? '';
  const second = parts[1]?.[0] ?? parts[0]?.[1] ?? '';
  return (first + second).toUpperCase();
}

/**
 * A single clay balance card for one financial wallet. Renders the wallet's
 * currency chip, its available balance (masked via the shared eye toggle),
 * and the Available / Pending sub-row. Money is always formatted through the
 * account's own currency — never assume ZAR.
 */
function BalanceCard({
  account,
  width,
  masked,
  onToggleMask,
}: {
  account: WalletAccount;
  width: number;
  masked: boolean;
  onToggleMask: () => void;
}) {
  const symbol = currencySymbol(account.currency).trim();
  const balance = splitAmount(account.available_balance ?? '0');
  const pending = pendingAmount(account);

  return (
    <ClaySurface depth="raised" radius={24} padding={20} width={width}>
      <XStack justifyContent="space-between" alignItems="center">
        <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={12.5} color="#6a7888">
          Available balance
        </Text>
        <View
          backgroundColor="#e6f6f8"
          paddingHorizontal={10}
          paddingVertical={4}
          borderRadius={20}
        >
          <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={12} color="#2EB6C8">
            {account.currency} wallet
          </Text>
        </View>
      </XStack>
      <XStack alignItems="flex-end" gap={8} marginTop={8}>
        <Text
          fontFamily="PlusJakartaSans-ExtraBold"
          fontSize={34}
          color="#0c1b2a"
          letterSpacing={-0.5}
        >
          {symbol} {masked ? '••••' : balance.whole}
        </Text>
        {!masked && (
          <Text
            fontFamily="PlusJakartaSans-Bold"
            fontSize={20}
            color="#94a2b1"
            marginBottom={4}
          >
            {balance.cents}
          </Text>
        )}
        <Pressable
          onPress={onToggleMask}
          style={{ marginLeft: 'auto', paddingBottom: 6 }}
          accessibilityLabel="Toggle balance visibility"
        >
          <Ionicons name={masked ? 'eye-off' : 'eye'} size={20} color="#94a2b1" />
        </Pressable>
      </XStack>
      <XStack
        gap={18}
        marginTop={14}
        paddingTop={14}
        borderTopWidth={1}
        borderTopColor="rgba(1,46,84,0.06)"
        alignItems="center"
      >
        <YStack flex={1}>
          <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={11} color="#8a98a6">
            Available
          </Text>
          <Text fontFamily="PlusJakartaSans-Bold" fontSize={14} color="#0c1b2a" marginTop={2}>
            {formatMoney(account.available_balance ?? '0', account.currency)}
          </Text>
        </YStack>
        <YStack flex={1}>
          <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={11} color="#8a98a6">
            Pending
          </Text>
          <Text fontFamily="PlusJakartaSans-Bold" fontSize={14} color="#0c1b2a" marginTop={2}>
            {formatMoney(pending, account.currency)}
          </Text>
        </YStack>
      </XStack>
    </ClaySurface>
  );
}

/** Pay tab — home. */
export default function HomeScreen() {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const [masked, setMasked] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [phone, setPhone] = useState<string | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const { data, isLoading, error } = useQuery({
    queryKey: qk.wallet(),
    queryFn: getMyWallet,
  });
  // Per-user money services drive the quick-action tiles. While this loads we
  // fall back to the static consumer set so the pay row is never empty.
  const { data: services } = useQuery({
    queryKey: qk.services(),
    queryFn: getMyServices,
  });

  // Pull the phone the user last logged in with from secure storage so
  // the drawer can show it. The wallet endpoint doesn't echo phone back
  // (it's only on the session); cached `lastPhone` is the authoritative
  // client-side source.
  useEffect(() => {
    let cancelled = false;
    getLastPhone().then((p) => {
      if (!cancelled) setPhone(p);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error instanceof SessionExpired) {
    clearAll().finally(() => router.replace('/auth/phone'));
  }

  /**
   * Sign out: best-effort invalidate the bearer server-side, clear all
   * cached tokens locally, then route back to /auth/phone. The drawer
   * stays open with a "Signing out…" label while the API call runs
   * (typically <200 ms); we close it on the navigation transition.
   */
  async function handleSignOut() {
    if (signingOut) return;
    setSigningOut(true);
    try {
      await signOut();
    } finally {
      setSigningOut(false);
      setDrawerOpen(false);
      router.replace('/auth/phone');
    }
  }

  const firstName = data?.first_name ?? 'there';
  // Funded wallet first: order the carousel by available balance (desc) so it
  // opens on the wallet that actually has money rather than an empty ₹0 card.
  const walletAccounts = (data?.accounts ?? [])
    .filter((a) => a.account_type === 'financial_wallet')
    .sort(
      (a, b) => parseFloat(b.available_balance ?? '0') - parseFloat(a.available_balance ?? '0'),
    );
  const points = data?.accounts.find((a) => a.currency === 'PTS');

  // Carousel geometry: cards are full-width minus the horizontal gutters, and
  // snap one-per-page. onMomentumScrollEnd derives the active index from the
  // scroll offset so the active currency + page dots track the visible card.
  const H_PADDING = 18;
  const CARD_GAP = 12;
  const cardWidth = width - H_PADDING * 2;
  const snapInterval = cardWidth + CARD_GAP;

  const activeCurrency =
    walletAccounts[activeIndex]?.currency ?? walletAccounts[0]?.currency ?? 'ZAR';

  // Quick-action tiles: real per-user tiles once services resolve, else the
  // static consumer fallback so the row renders immediately.
  const tiles = services ? tilesFromServices(services) : FALLBACK_TILES;

  // Recent activity is scoped to the visible card's currency so swiping to the
  // INR card shows INR activity, ZAR shows ZAR. PTS (reward/redemption) rows are
  // kept regardless — points aren't a spendable currency tied to any one card.
  const recentForCurrency = (data?.recent_transactions ?? []).filter(
    (t) => t.currency === activeCurrency || t.currency === 'PTS',
  );

  return (
    <View flex={1} backgroundColor="#ccd8e8">
      <SafeAreaView style={{ flex: 1 }} edges={['bottom']}>
        <YStack flex={1}>
          {/* Header — navy gradient with user info + points + bell, plus
              extra bottom padding so the balance card overlaps by 58px. */}
          <GradientHeader paddingBottom={40}>
            <XStack alignItems="center" justifyContent="space-between" paddingTop={6}>
              <Pressable
                onPress={() => setDrawerOpen(true)}
                accessibilityRole="button"
                accessibilityLabel="Open menu"
                style={({ pressed }) => ({ opacity: pressed ? 0.7 : 1 })}
                hitSlop={8}
              >
                <XStack alignItems="center" gap={11}>
                  <View
                    width={42}
                    height={42}
                    borderRadius={21}
                    backgroundColor="#50C0D0"
                    alignItems="center"
                    justifyContent="center"
                  >
                    <Text fontFamily="PlusJakartaSans-Bold" fontSize={14} color="#013a6b">
                      {initials(firstName)}
                    </Text>
                  </View>
                  <YStack>
                    <Text
                      fontFamily="PlusJakartaSans-Medium"
                      fontSize={12}
                      color="rgba(255,255,255,0.7)"
                    >
                      Welcome back
                    </Text>
                    <Text fontFamily="PlusJakartaSans-Bold" fontSize={15} color="#ffffff">
                      {firstName}
                    </Text>
                  </YStack>
                </XStack>
              </Pressable>
              <XStack alignItems="center" gap={10}>
                <XStack
                  alignItems="center"
                  gap={7}
                  backgroundColor="rgba(255,255,255,0.14)"
                  borderColor="rgba(80,192,208,0.5)"
                  borderWidth={1}
                  borderRadius={22}
                  paddingHorizontal={12}
                  paddingVertical={6}
                >
                  <View
                    width={26}
                    height={26}
                    borderRadius={13}
                    backgroundColor="#50C0D0"
                    alignItems="center"
                    justifyContent="center"
                  >
                    <Ionicons name="star" size={14} color="#ffffff" />
                  </View>
                  <YStack>
                    <Text
                      fontFamily="PlusJakartaSans-ExtraBold"
                      fontSize={13}
                      color="#ffffff"
                      lineHeight={14}
                    >
                      {points ? parseInt(points.available_balance, 10).toLocaleString('en-ZA') : '0'}
                    </Text>
                    <Text
                      fontFamily="PlusJakartaSans-SemiBold"
                      fontSize={8.5}
                      color="#9fd9e2"
                      letterSpacing={0.4}
                      lineHeight={10}
                    >
                      POINTS
                    </Text>
                  </YStack>
                </XStack>
                <View
                  width={40}
                  height={40}
                  borderRadius={12}
                  backgroundColor="rgba(255,255,255,0.12)"
                  alignItems="center"
                  justifyContent="center"
                  position="relative"
                >
                  <Ionicons name="notifications" size={20} color="#ffffff" />
                  <View
                    position="absolute"
                    top={9}
                    right={10}
                    width={8}
                    height={8}
                    borderRadius={4}
                    backgroundColor="#ff5a5a"
                    borderWidth={1.5}
                    borderColor="#013a6b"
                  />
                </View>
              </XStack>
            </XStack>
          </GradientHeader>

          {/* Everything below the fixed header scrolls vertically so recent
              activity is reachable above the bottom tab bar. */}
          <ScrollView
            showsVerticalScrollIndicator={false}
            contentContainerStyle={{ paddingBottom: 120 }}
          >
            {/* Balance carousel — one card per financial wallet. The wrapper's
                negative top margin lifts the cards into the gradient so they
                "float" on the navy, matching the single-card design. A nested
                horizontal ScrollView is fine inside the vertical one — RN routes
                each axis to the matching gesture. */}
            <View marginTop={-20}>
              <ScrollView
                horizontal
                showsHorizontalScrollIndicator={false}
                snapToInterval={snapInterval}
                decelerationRate="fast"
                disableIntervalMomentum
                contentContainerStyle={{ paddingHorizontal: H_PADDING, paddingVertical: 4 }}
                onMomentumScrollEnd={(e) => {
                  const x = e.nativeEvent.contentOffset.x;
                  const next = Math.round(x / snapInterval);
                  if (next !== activeIndex) setActiveIndex(next);
                }}
              >
                {walletAccounts.map((account, i) => (
                  <View
                    key={account.id}
                    marginRight={i === walletAccounts.length - 1 ? 0 : CARD_GAP}
                  >
                    <BalanceCard
                      account={account}
                      width={cardWidth}
                      masked={masked}
                      onToggleMask={() => setMasked((m) => !m)}
                    />
                  </View>
                ))}
              </ScrollView>

              {/* Page dots — only meaningful with more than one wallet. */}
              {walletAccounts.length > 1 ? (
                <XStack justifyContent="center" alignItems="center" gap={6} marginTop={12}>
                  {walletAccounts.map((account, i) => {
                    const active = i === activeIndex;
                    return (
                      <View
                        key={account.id}
                        width={active ? 18 : 6}
                        height={6}
                        borderRadius={3}
                        backgroundColor={active ? '#00508F' : 'rgba(1,46,84,0.18)'}
                      />
                    );
                  })}
                </XStack>
              ) : null}
            </View>

            {/* Quick actions. Tiles carry the active wallet currency forward. */}
            <XStack justifyContent="space-between" paddingHorizontal={22} paddingTop={22}>
              {tiles.map((tile) => (
                <Pressable
                  key={tile.label}
                  onPress={() => router.push(tile.route(activeCurrency) as never)}
                  accessibilityRole="button"
                  accessibilityLabel={tile.label}
                  style={({ pressed }) => ({ opacity: pressed ? 0.85 : 1, width: 60 })}
                >
                  <YStack alignItems="center" gap={8}>
                    <ClayIconTile size={54} radius={18}>
                      <Ionicons name={tile.icon} size={24} color="#00508F" />
                    </ClayIconTile>
                    <Text
                      fontFamily="PlusJakartaSans-SemiBold"
                      fontSize={11}
                      color="#3a4756"
                      numberOfLines={1}
                    >
                      {tile.label}
                    </Text>
                  </YStack>
                </Pressable>
              ))}
            </XStack>

            {/* Promo banner — Sasai's "send money home" call-out. */}
            <View
              marginTop={14}
              marginHorizontal={18}
              backgroundColor="#00538f"
              borderRadius={24}
              padding={18}
              overflow="hidden"
              position="relative"
              shadowColor="#012e54"
              shadowOpacity={0.24}
              shadowRadius={20}
              shadowOffset={{ width: 0, height: 12 }}
              style={{ elevation: 10 }}
            >
              {/* Decorative ring at the bottom-right. */}
              <View
                position="absolute"
                width={140}
                height={140}
                borderRadius={70}
                borderWidth={24}
                borderColor="rgba(80,192,208,0.22)"
                bottom={-70}
                right={-40}
                pointerEvents="none"
              />
              <Text fontFamily="PlusJakartaSans-ExtraBold" fontSize={16} color="#ffffff">
                Send money home, faster
              </Text>
              <Text
                fontFamily="PlusJakartaSans-Medium"
                fontSize={12.5}
                color="rgba(255,255,255,0.82)"
                marginTop={4}
                maxWidth={200}
                lineHeight={18}
              >
                Transfer to any bank or mobile wallet across Africa.
              </Text>
              <Pressable
                onPress={() => router.push(`/p2p/recipient?currency=${activeCurrency}` as never)}
                style={{ marginTop: 14 }}
              >
                <View
                  alignSelf="flex-start"
                  backgroundColor="#ffffff"
                  paddingHorizontal={16}
                  paddingVertical={8}
                  borderRadius={11}
                >
                  <Text fontFamily="PlusJakartaSans-Bold" fontSize={13} color="#00508F">
                    Send now →
                  </Text>
                </View>
              </Pressable>
            </View>

            {/* Recent activity. */}
            <XStack
              justifyContent="space-between"
              alignItems="center"
              paddingHorizontal={22}
              paddingTop={22}
              paddingBottom={10}
            >
              <Text fontFamily="PlusJakartaSans-ExtraBold" fontSize={15} color="#0c1b2a">
                Recent activity
              </Text>
              <Pressable onPress={() => router.push('/transactions' as never)}>
                <Text fontFamily="PlusJakartaSans-SemiBold" fontSize={12.5} color="#00508F">
                  See all
                </Text>
              </Pressable>
            </XStack>
            <ClaySurface
              depth="soft"
              radius={20}
              marginHorizontal={18}
              paddingHorizontal={14}
            >
              {isLoading ? (
                <View paddingVertical={24} alignItems="center">
                  <ActivityIndicator color="#00508F" />
                </View>
              ) : recentForCurrency.length === 0 ? (
                <View paddingVertical={20} alignItems="center">
                  <Text fontFamily="PlusJakartaSans-Medium" fontSize={13} color="#8a98a6">
                    No activity yet.
                  </Text>
                </View>
              ) : (
                /* Last 3 transactions for the active card's currency (plus PTS),
                   each formatted in its own currency. */
                recentForCurrency
                  .slice(0, 3)
                  .map((t, i, arr) => {
                    const positive = t.direction === 'in';
                    const sign = positive ? '+' : '−';
                    const absAmount = Math.abs(parseFloat(t.amount));
                    const amtText =
                      t.currency === 'PTS'
                        ? `${sign}${absAmount.toFixed(0)} PTS`
                        : `${sign}${formatMoney(absAmount, t.currency)}`;
                    const when = new Date(t.created_at);
                    const now = new Date();
                    const sameDay =
                      now.getFullYear() === when.getFullYear() &&
                      now.getMonth() === when.getMonth() &&
                      now.getDate() === when.getDate();
                    const time = when.toLocaleTimeString('en-GB', {
                      hour: '2-digit',
                      minute: '2-digit',
                    });
                    const subtitle = sameDay
                      ? `Today · ${time}`
                      : `${when.toLocaleDateString('en-GB', {
                          day: '2-digit',
                          month: 'short',
                        })} · ${time}`;
                    return (
                      <ActivityRow
                        key={t.id}
                        category={activityCategory(t)}
                        title={transactionTitle(t)}
                        subtitle={subtitle}
                        amount={amtText}
                        positive={positive}
                        noBorder={i === arr.length - 1}
                      />
                    );
                  })
              )}
            </ClaySurface>
          </ScrollView>
        </YStack>
      </SafeAreaView>
      <BottomTabBar active="pay" />
      <SideDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onSignOut={handleSignOut}
        name={firstName === 'there' ? null : firstName}
        phone={phone}
        initials={initials(firstName)}
        signingOut={signingOut}
      />
    </View>
  );
}
