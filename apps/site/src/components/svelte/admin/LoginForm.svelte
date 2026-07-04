<script>
  import SharedLoginForm from '@ainekio/blog-core/components/svelte/admin/LoginForm.svelte'

  let sharedLoginFormRef

  export function show() {
    sharedLoginFormRef?.show?.()
  }

  export function hide() {
    sharedLoginFormRef?.hide?.()
  }

  export function toggle() {
    sharedLoginFormRef?.toggle?.()
  }
</script>

<SharedLoginForm bind:this={sharedLoginFormRef} on:login on:setup />
