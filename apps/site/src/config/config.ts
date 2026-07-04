import type {
  LicenseConfig,
  NavBarConfig,
  ProfileConfig,
  SiteConfig,
} from '../types/config'
import { LinkPreset } from '../types/config'
import { AUTO_MODE, DARK_MODE, LIGHT_MODE } from '@constants/constants.ts'


export const siteConfig: SiteConfig = {
  title: "Ainekio",
  subtitle: "Robot familiar field notes",
  enablePostFooterNav: true,
  lang: "en",
  themeColor: {
    hue: 0,
    fixed: false
  },
  transparency: 0.9, // Single value from 0 to 1
  defaultTheme: LIGHT_MODE,
  banner: {
    enable: false,
    src: "/assets/banner/0001.png",
    position: "center",
    credit: {
      enable: true,
      text: "",
      url: ""
    }
  },
  toc: {
    enable: true,
    depth: 3,
    minHeadings: 3,
  },
  rightRail: {
    enable: true,
    showOnHome: true,
    showOnPostsWithoutToc: true,
    stickyTop: "3.5rem",
    widget: {
      type: "updates",
      collection: "updates",
      slug: "site-updates",
      excerptLength: 420,
      pageUrl: "/updates/",
      pageLinkLabel: "Open full release notes",
    },
  },
  favicon: []
}

export const navBarConfig: NavBarConfig = {
  links: [
    LinkPreset.Home,
    {
      name: "Updates",
      url: "/updates/",
    },
    LinkPreset.Archive,
    LinkPreset.About,
  ]
}

export const profileConfig: ProfileConfig = {
  avatar: "/src/content/avatar/avatar.png",
  name: "Ainekio",
  bio: "A small robot companion powered by MetaHuman OS.",
  links: [
    {
      name: "GitHub",
      icon: "fa6-brands:github",
      url: "https://github.com/Greg-Aster/Ainekio-bot"
    }
  ],
  avatarFilename: "ComfyUI_0003.png"
}

export const licenseConfig: LicenseConfig = {
  enable: true,
  name: "CC BY-NC-SA 4.0",
  url: "https://creativecommons.org/licenses/by-nc-sa/4.0/"
}
