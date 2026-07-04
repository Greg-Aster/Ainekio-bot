<script>
    export let addonsConfig;
    
    // Initialize addons config structure if it doesn't exist
    if (!addonsConfig) {
      addonsConfig = {
        enabled: false,
        availableAddons: [],
        installedAddons: []
      };
    }
    
    // Function to toggle addons system
    function toggleAddons() {
      addonsConfig.enabled = !addonsConfig.enabled;
    }
  </script>
  
  <div class="space-y-6">
    <div class="card-base p-6">
      <h2 class="text-xl font-semibold mb-4">Add-ons System</h2>
      
      <div class="flex items-center justify-between">
        <div>
          <h3 class="font-medium">Enable Add-ons</h3>
          <p class="text-sm text-neutral-500 dark:text-neutral-400">
            Allow installation and management of third-party add-ons
          </p>
        </div>
        <label class="switch">
          <input type="checkbox" bind:checked={addonsConfig.enabled} on:change={toggleAddons}>
          <span class="slider round"></span>
        </label>
      </div>
    </div>
  
    {#if addonsConfig.enabled}
      <div class="card-base p-6">
        <h2 class="text-xl font-semibold mb-4">Installed Add-ons</h2>
        
        {#if addonsConfig.installedAddons.length > 0}
          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {#each addonsConfig.installedAddons as addon}
              <div class="border rounded-lg p-4 flex flex-col">
                <div class="flex justify-between items-start mb-2">
                  <h3 class="font-medium">{addon.name}</h3>
                  <span class="text-xs px-2 py-1 rounded bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200">
                    v{addon.version}
                  </span>
                </div>
                <p class="text-sm text-neutral-600 dark:text-neutral-400 mb-3">{addon.description}</p>
                <div class="mt-auto flex justify-between items-center">
                  <span class="text-xs text-neutral-500 dark:text-neutral-400">
                    {addon.author}
                  </span>
                  <button class="text-xs text-red-600 hover:text-red-800 dark:hover:text-red-400">
                    Uninstall
                  </button>
                </div>
              </div>
            {/each}
          </div>
        {:else}
          <div class="text-center py-8 text-neutral-500 dark:text-neutral-400">
            <p>No add-ons installed yet.</p>
          </div>
        {/if}
      </div>
  
      <div class="card-base p-6">
        <h2 class="text-xl font-semibold mb-4">Available Add-ons</h2>
        
        {#if addonsConfig.availableAddons.length > 0}
          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {#each addonsConfig.availableAddons as addon}
              <div class="border rounded-lg p-4 flex flex-col">
                <div class="flex justify-between items-start mb-2">
                  <h3 class="font-medium">{addon.name}</h3>
                  <span class="text-xs px-2 py-1 rounded bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200">
                    v{addon.version}
                  </span>
                </div>
                <p class="text-sm text-neutral-600 dark:text-neutral-400 mb-3">{addon.description}</p>
                <div class="mt-auto flex justify-between items-center">
                  <span class="text-xs text-neutral-500 dark:text-neutral-400">
                    {addon.author}
                  </span>
                  <button class="text-xs px-3 py-1 rounded bg-[var(--primary)] text-white hover:opacity-90">
                    Install
                  </button>
                </div>
              </div>
            {/each}
          </div>
        {:else}
          <div class="text-center py-8 text-neutral-500 dark:text-neutral-400">
            <p>No add-ons available at this time.</p>
          </div>
        {/if}
      </div>
    {/if}
  </div>
  
  <style>
    /* Switch styling */
    .switch {
      position: relative;
      display: inline-block;
      width: 60px;
      height: 34px;
    }
    
    .switch input {
      opacity: 0;
      width: 0;
      height: 0;
    }
    
    .slider {
      position: absolute;
      cursor: pointer;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background-color: #ccc;
      transition: .4s;
    }
    
    .slider:before {
      position: absolute;
      content: "";
      height: 26px;
      width: 26px;
      left: 4px;
      bottom: 4px;
      background-color: white;
      transition: .4s;
    }
    
    input:checked + .slider {
      background-color: var(--primary);
    }
    
    input:focus + .slider {
      box-shadow: 0 0 1px var(--primary);
    }
    
    input:checked + .slider:before {
      transform: translateX(26px);
    }
    
    .slider.round {
      border-radius: 34px;
    }
    
    .slider.round:before {
      border-radius: 50%;
    }
  </style>