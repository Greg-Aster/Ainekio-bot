// Configuration for PostCard components and friend post integration

    // Base PostCard configuration
    export interface PostCardConfig {
      // Layout options
      layout: {
        imagePosition: 'right' | 'top'; // Position of the image
        imageSizePercentage: number; // Size as percentage (e.g., 28 for 28%)
        cardBorderRadius: string; // Border radius for the card
        showEnterButton: boolean; // Whether to show the enter button
      };
      // Styling options
      styling: {
        titleSize: string; // Title font size class
        descriptionLines: number; // Number of lines to show in description
        animationEnabled: boolean; // Whether to enable load animations
      };
      // Content display options
      content: {
        showCategory: boolean;
        showTags: boolean;
        showUpdateDate: boolean;
        showWordCount: boolean;
        showReadTime: boolean;
        hideTagsOnMobile: boolean;
      };
    }

    // Friend post specific configuration
    export interface FriendPostConfig {
      // Friend styling options
      friendStyling: {
        indicatorType: 'border' | 'badge' | 'background'; // How to visually indicate friend posts
        indicatorColor: string; // Color for the indicator
        showFriendAvatar: boolean; // Whether to show friend's avatar
        avatarSize: string; // Size of the avatar
      };
    // Attribution options
      attribution: {
        showAttribution: boolean; // Whether to show attribution
        attributionText: string; // Text template for attribution
        linkToFriendSite: boolean; // Whether to link to friend's site
      };
      // Integration behavior
      behavior: {
        sortingMethod: 'date' | 'source'; // How to sort mixed posts
        mergeWithLocalPosts: boolean; // Whether to merge with local posts or show separately
      };
    }

    // Combined configuration
    export interface PostCardConfigs {
      localPosts: PostCardConfig;
      friendPosts: PostCardConfig & FriendPostConfig;
    }

    // Export the configuration
    export const postCardConfig: PostCardConfigs = {
  localPosts: {
    layout: {
      imagePosition: "right",
      imageSizePercentage: 28,
      cardBorderRadius: "rounded-[var(--radius-large)]",
      showEnterButton: true
    },
    styling: {
      titleSize: "text-lg md:text-3xl",
      descriptionLines: 2,
      animationEnabled: true
    },
    content: {
      showCategory: true,
      showTags: true,
      showUpdateDate: true,
      showWordCount: false,
      showReadTime: false,
      hideTagsOnMobile: true
    }
  },
  friendPosts: {
    layout: {
      imagePosition: "right",
      imageSizePercentage: 28,
      cardBorderRadius: "rounded-[var(--radius-large)]",
      showEnterButton: true
    },
    styling: {
      titleSize: "text-lg md:text-3xl",
      descriptionLines: 2,
      animationEnabled: true
    },
    content: {
      showCategory: true,
      showTags: true,
      showUpdateDate: true,
      showWordCount: true,
      showReadTime: true,
      hideTagsOnMobile: true
    },
    friendStyling: {
      indicatorType: "border",
      indicatorColor: "var(--primary)",
      showFriendAvatar: true,
      avatarSize: "w-5 h-5"
    },
    attribution: {
      showAttribution: false,
      attributionText: "Shared from [friendName]",
      linkToFriendSite: true
    },
    behavior: {
      sortingMethod: "date",
      mergeWithLocalPosts: true
    }
  }
}
