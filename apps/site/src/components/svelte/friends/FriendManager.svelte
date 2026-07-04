<script>
import SharedFriendManager from '@ainekio/blog-core/components/svelte/friends/FriendManager.svelte'

export let savedFriends = []
</script>

<SharedFriendManager {savedFriends} />
