/**
 * Babel configuration for the Sasai mobile app.
 *
 * The Tamagui plugin extracts inline styles at build time, and the
 * worklets transform (Reanimated v4 / SDK 54) must remain LAST in the
 * plugin list — moved from `react-native-reanimated/plugin` into the
 * standalone `react-native-worklets/plugin` package.
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
      'react-native-worklets/plugin',
    ],
  };
};
