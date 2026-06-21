/**
 * Babel configuration for the Sasai mobile app.
 *
 * The Tamagui plugin extracts inline styles at build time, and
 * react-native-reanimated's worklet transform must remain LAST in the
 * plugin list per the Reanimated docs.
 */
module.exports = function (api) {
  api.cache(true);
  return {
    presets: ['babel-preset-expo'],
    plugins: [
      [
        '@tamagui/babel-plugin',
        {
          components: ['tamagui'],
          config: './tamagui.config.ts',
          logTimings: true,
        },
      ],
      'react-native-reanimated/plugin',
    ],
  };
};
