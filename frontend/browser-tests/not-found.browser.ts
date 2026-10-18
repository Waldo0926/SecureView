/**
 * An unknown URL: the visitor sees a not-found page with a way back, not a blank screen.
 *
 * Needs no account and no key material, so it is a cheap guard on the router's catch-all
 * (docs/THREAT_MODEL.md F-20 recorded the blank page as an observed defect).
 */
import { expect, test } from '@playwright/test'

test('an unknown URL shows the not-found page and a link home', async ({ page }) => {
  await page.goto('/definitely-not-a-page')

  await expect(page.getByTestId('not-found')).toBeVisible()
  await expect(page.getByRole('heading', { name: /can't find that page/i })).toBeVisible()
  await expect(page.getByText('/definitely-not-a-page')).toBeVisible()

  await page.getByRole('link', { name: 'Back to home' }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByTestId('not-found')).toHaveCount(0)
})
