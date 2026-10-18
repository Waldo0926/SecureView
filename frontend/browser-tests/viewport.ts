/**
 * What "fits a phone" means, as checks a test can make.
 *
 * Shared by the mobile browser tests (`mobile-*.browser.ts`). Nothing here is opinion about
 * design: a page that scrolls sideways, a control that sits partly off the screen, or a tap
 * target too small to hit is a defect on a phone whatever it looks like.
 */
import { expect, type Locator, type Page } from '@playwright/test'

/** Phone widths the product is checked at: a common modern phone and the narrowest still in use. */
export const PHONE_WIDTHS = [360, 320] as const

/** A touch target below this is hard to hit; WCAG 2.2 AA asks for 24, platform guidance for 44. */
export const MIN_TARGET_PX = 40

export async function expectNoSidewaysScroll(page: Page, where: string) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow, `${where}: the page is wider than the screen by this many pixels`).toBeLessThanOrEqual(0)
}

/**
 * Visible elements that stick out past the screen's left or right edge, outside any element
 * that scrolls on purpose. An empty list is what a page that fits looks like.
 */
export async function elementsOffScreen(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const width = document.documentElement.clientWidth
    // True when something between the element and the page keeps it from being seen or reached
    // outside the screen: a box that scrolls sideways on purpose, or one that clips (a marquee
    // track, a hidden slide) while itself sitting inside the screen.
    const scrolls = (element: Element) => {
      for (let parent = element.parentElement; parent && parent !== document.documentElement; parent = parent.parentElement) {
        if (parent === document.body) break
        const overflowX = getComputedStyle(parent).overflowX
        const box = parent.getBoundingClientRect()
        const inside = box.left >= -1 && box.right <= width + 1
        if ((overflowX === 'auto' || overflowX === 'scroll') && parent.scrollWidth > parent.clientWidth) return true
        if ((overflowX === 'hidden' || overflowX === 'clip') && inside) return true
      }
      return false
    }
    const found: string[] = []
    for (const element of document.querySelectorAll('body *')) {
      const box = element.getBoundingClientRect()
      const style = getComputedStyle(element)
      if (box.width === 0 || box.height === 0 || style.display === 'none' || style.visibility === 'hidden') continue
      if (box.width > 4000) continue // a decorative marquee track, clipped by its container
      if ((box.right > width + 1 || box.left < -1) && !scrolls(element)) {
        const label = (element.getAttribute('aria-label') || element.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 30)
        found.push(`${element.tagName.toLowerCase()} "${label}" ${Math.round(box.left)}..${Math.round(box.right)}`)
      }
    }
    return found
  })
}

export async function expectFitsScreen(page: Page, where: string) {
  await expectNoSidewaysScroll(page, where)
  const off = await elementsOffScreen(page)
  expect(off, `${where}: elements past the screen edge`).toEqual([])
}

/** The control lies wholly inside the screen and is big enough to tap. */
export async function expectReachable(page: Page, control: Locator, label: string) {
  await control.scrollIntoViewIfNeeded()
  const box = await control.boundingBox()
  expect(box, `${label} has a box`).not.toBeNull()
  const width = await page.evaluate(() => document.documentElement.clientWidth)
  expect(box!.x, `${label} starts inside the screen`).toBeGreaterThanOrEqual(0)
  expect(box!.x + box!.width, `${label} ends inside the screen`).toBeLessThanOrEqual(width + 0.5)
  expect(box!.width, `${label} is wide enough to tap`).toBeGreaterThanOrEqual(MIN_TARGET_PX - 0.5)
  expect(box!.height, `${label} is tall enough to tap`).toBeGreaterThanOrEqual(MIN_TARGET_PX - 0.5)
}

/** A dialog stays within the screen in both directions, so none of it is cut off. */
export async function expectDialogFits(page: Page, dialog: Locator, where: string) {
  const box = await dialog.boundingBox()
  expect(box, `${where}: dialog has a box`).not.toBeNull()
  const viewport = page.viewportSize()!
  expect(box!.x, `${where}: dialog left edge`).toBeGreaterThanOrEqual(0)
  expect(box!.x + box!.width, `${where}: dialog right edge`).toBeLessThanOrEqual(viewport.width + 0.5)
  expect(box!.y, `${where}: dialog top edge`).toBeGreaterThanOrEqual(0)
  expect(box!.y + box!.height, `${where}: dialog bottom edge`).toBeLessThanOrEqual(viewport.height + 0.5)
}
