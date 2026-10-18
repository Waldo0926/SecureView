import { describe, expect, it } from 'vitest'
import { splitSentences } from './sentences'

describe('splitSentences', () => {
  it('splits English sentences at a full stop followed by a capital', () => {
    expect(splitSentences('Your first secure share in six screenshots. Follow at your own pace.')).toEqual([
      'Your first secure share in six screenshots.',
      'Follow at your own pace.',
    ])
  })

  it('keeps sizes, file extensions and abbreviations inside their sentence', () => {
    expect(splitSentences('Up to 500 MB. Download encrypted saves a .ciphertext file, e.g. this one.')).toEqual([
      'Up to 500 MB.',
      'Download encrypted saves a .ciphertext file, e.g. this one.',
    ])
    expect(splitSentences('Version 1.5 is out.')).toEqual(['Version 1.5 is out.'])
  })

  it('splits Chinese after 。！？ with no space', () => {
    expect(splitSentences('六张截图完成第一次安全分享。按自己的节奏来！')).toEqual(['六张截图完成第一次安全分享。', '按自己的节奏来！'])
  })

  it('returns one sentence for text without a break, and nothing for blank text', () => {
    expect(splitSentences('  Sealed in your browser  ')).toEqual(['Sealed in your browser'])
    expect(splitSentences('   ')).toEqual([])
  })
})
