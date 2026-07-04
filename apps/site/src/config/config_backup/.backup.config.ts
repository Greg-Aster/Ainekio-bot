import type {
  LicenseConfig,
  NavBarConfig,
  ProfileConfig,
  SiteConfig,
} from '../types/config'
import { LinkPreset } from '../types/config'
import { AUTO_MODE, DARK_MODE, LIGHT_MODE } from '@constants/constants.ts'


export const siteConfig: SiteConfig = {
  title: "Temporal Flow Net",
  subtitle: "A Decentralized Content Platform",
  lang: "en",
  themeColor: {
    hue: 0,
    fixed: false
  },
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
    depth: 3
  },
  favicon: []
}

export const navBarConfig: NavBarConfig = {
  links: [
    0,
    {
      name: "Projects",
      url: "/archive/",
      dropdown: [
        {
          name: "Timeline Example",
          url: "/posts/timeline/"
        },
        {
          name: "Project One",
          url: "/projects/project-one/"
        },
        {
          name: "Project Two",
          url: "/projects/project-two/"
        },
        {
          name: "Project Three",
          url: "/projects/project-three/"
        },
        {
          name: "External Project",
          url: "https://example.com/project",
          external: true
        }
      ]
    },
    3,
    1,
    2
  ]
}

export const profileConfig: ProfileConfig = {
  avatar: "/src/content/avatar/avatar.png",
  name: "Site Owner",
  bio: "Content Creator & Digital Storyteller",
  links: [
    {
      name: "Bluesky",
      icon: "fa6-brands:luesky",
      url: "https://bluesky.com/example"
    },
    {
      name: "Discord",
      icon: "fa6-brands:discord",
      url: "https://discord.gg/example"
    },
    {
      name: "GitHub",
      icon: "fa6-brands:github",
      url: "https://github.com/example"
    }
  ],
  avatarFilename: "ComfyUI_0003.png"
}

export const licenseConfig: LicenseConfig = {
  enable: true,
  name: "CC BY-NC-SA 4.0",
  url: "https://creativecommons.org/licenses/by-nc-sa/4.0/"
}