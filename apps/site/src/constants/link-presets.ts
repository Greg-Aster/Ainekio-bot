import { LinkPreset, type NavBarLink } from '@/types/config'
import I18nKey from '@i18n/i18nKey'
import { i18n } from '@i18n/translation'

export const LinkPresets: { [key in LinkPreset]: NavBarLink } = {
  [LinkPreset.Home]: {
    name: i18n(I18nKey.home),
    url: '/',
  },
  [LinkPreset.About]: {
    name: i18n(I18nKey.about),
    url: '/about/',
  },
  [LinkPreset.Archive]: {
    name: i18n(I18nKey.archive),
    url: '/archive/',
  },
  [LinkPreset.Community]: {
    name: i18n(I18nKey.community),
    url: '/community/',
  },
  [LinkPreset.Projects]: {
    name: 'Projects',
    url: '/projects/',
  },
  [LinkPreset.Configs]: {
    name: i18n(I18nKey.configs),
    url: '/configs/',
  },
  [LinkPreset.Friends]: {
    name: i18n(I18nKey.friends),
    url: '/friends/',
  },
  [LinkPreset.NewPost]: {
    name: i18n(I18nKey.newPost),
    url: '/new-post/',
  },
}
