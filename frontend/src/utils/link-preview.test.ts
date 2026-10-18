import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

// LinkedIn and other link-preview crawlers read the served index.html without running the
// SPA, so the Open Graph tags must be in the static file, with an absolute PNG image URL.
const frontendRoot = path.resolve(__dirname, '../..')
const html = readFileSync(path.join(frontendRoot, 'index.html'), 'utf8')

const og = (property: string): string | undefined =>
  html.match(new RegExp(`<meta property="og:${property}" content="([^"]*)"`))?.[1]

describe('link preview tags', () => {
  it('declares the Open Graph fields LinkedIn requires', () => {
    expect(og('title')).toBeTruthy()
    expect(og('description')).toBeTruthy()
    expect(og('url')).toBe('https://secureview.tech/')
    expect(og('type')).toBe('website')
  })

  it('points og:image at an absolute PNG that ships in public/', () => {
    const image = og('image')
    expect(image).toMatch(/^https:\/\/secureview\.tech\/.+\.png(\?v=\d+)?$/)

    const file = readFileSync(path.join(frontendRoot, 'public', new URL(image!).pathname))
    // PNG signature, then the IHDR width and height (big-endian) at bytes 16-23.
    expect(file.subarray(1, 4).toString('ascii')).toBe('PNG')
    expect([file.readUInt32BE(16), file.readUInt32BE(20)]).toEqual([
      Number(og('image:width')),
      Number(og('image:height')),
    ])
  })
})
