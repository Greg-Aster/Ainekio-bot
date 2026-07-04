<script lang="ts">
import SharedLightDarkSwitch from '@ainekio/blog-core/components/LightDarkSwitch.svelte'
import I18nKey from '@i18n/i18nKey'
import { i18n } from '@i18n/translation'
import { siteConfig } from '@/config/config.ts'
</script>

<SharedLightDarkSwitch
  defaultTheme={siteConfig.defaultTheme}
  lightModeLabel={i18n(I18nKey.lightMode)}
  darkModeLabel={i18n(I18nKey.darkMode)}
  systemModeLabel={i18n(I18nKey.systemMode)}
/>
