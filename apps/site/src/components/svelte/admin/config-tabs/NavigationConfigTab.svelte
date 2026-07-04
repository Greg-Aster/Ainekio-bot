<script>
  import SharedNavigationConfigTab from '@ainekio/blog-core/components/svelte/admin/config-tabs/NavigationConfigTab.svelte'

  export let navBarConfig
</script>

<SharedNavigationConfigTab {navBarConfig} on:change />
