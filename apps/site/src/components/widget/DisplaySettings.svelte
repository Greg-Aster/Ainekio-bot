<script lang="ts">
import SharedDisplaySettings from '@ainekio/blog-core/components/widget/DisplaySettings.svelte'
import I18nKey from '@i18n/i18nKey'
import { i18n } from '@i18n/translation'
</script>

<SharedDisplaySettings
  themeColorLabel={i18n(I18nKey.themeColor)}
  resetButtonLabel="Reset to Default"
/>
