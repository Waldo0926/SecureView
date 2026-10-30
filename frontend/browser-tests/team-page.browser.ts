/**
 * The Contact us page: supervisor, team and feedback form render, every photo
 * actually loads (the site's CSP only allows images from its own origin, so a hot-linked
 * photo would silently fail), the Monash profile link is right, and a phone does not scroll
 * sideways. Needs no account.
 */
import { expect, test } from '@playwright/test'

const PROFILE = 'https://research.monash.edu/en/persons/asad-malik/'

test('the team page shows the supervisor, the four members and the feedback form', async ({ page }) => {
  await page.goto('/team')

  await expect(page.getByRole('heading', { name: 'Contact us' })).toBeVisible()
  await expect(page.getByTestId('team-feedback').getByRole('button', { name: 'Write the email' })).toBeVisible()

  const supervisor = page.getByTestId('team-supervisor')
  await expect(supervisor.getByRole('heading', { name: 'Dr. Asad Malik' })).toBeVisible()
  await expect(supervisor).toContainText('Cybersecurity Group Leader')
  await expect(supervisor).toContainText('School of Information Technology, Monash University Malaysia')
  await expect(supervisor).toContainText('Guides SecureView on scope')
  await expect(supervisor).toContainText('Research interests')
  for (const interest of ['Cybersecurity', 'Multimedia forensics', 'DeepFake detection', 'Trustworthy AI']) {
    await expect(supervisor).toContainText(interest)
  }
  const link = supervisor.getByTestId('supervisor-profile-link')
  await expect(link).toHaveAttribute('href', PROFILE)
  await expect(link).toHaveAttribute('rel', /noopener/)

  const photo = supervisor.getByAltText('Portrait of Dr. Asad Malik')
  await photo.scrollIntoViewIfNeeded()
  await expect
    .poll(() => photo.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0))
    .toBe(true)

  const members = page.getByTestId('team-member')
  await expect(members).toHaveCount(4)
  await expect(page.getByRole('heading', { name: /The people behind\s+SecureView/ })).toBeVisible()

  // The four member tiles are the same size, not a ragged mosaic.
  const sizes = await members.evaluateAll((tiles) =>
    tiles.map((tile) => {
      const box = tile.getBoundingClientRect()
      return [Math.round(box.width), Math.round(box.height)]
    }),
  )
  for (const size of sizes) expect(size).toEqual(sizes[0])

  // The detail is on the tile itself, and the way to the large profile is stated, not discovered.
  await expect(members.first()).toContainText('Click or tap to enlarge')
  await expect(members.first()).toContainText('Runs the backlog and the release process')
  await members.first().click({ position: { x: 20, y: 20 } })
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)

  // The enlarged supervisor profile is a real enlargement: a portrait far bigger than the one on
  // the tile, beside the whole introduction (role, title, affiliation, interests, profile link).
  const tilePhoto = await supervisor.getByAltText('Portrait of Dr. Asad Malik').boundingBox()
  await supervisor.click({ position: { x: 20, y: 20 } })
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('heading', { name: 'Dr. Asad Malik' })).toBeVisible()
  await expect(dialog).toContainText('Lecturer and Cybersecurity Group Leader')
  await expect(dialog).toContainText('School of Information Technology, Monash University Malaysia')
  await expect(dialog).toContainText('Trustworthy AI')
  await expect(dialog.getByRole('link', { name: 'View Monash profile' })).toHaveAttribute('href', PROFILE)
  const bigPhoto = await dialog.getByAltText('Portrait of Dr. Asad Malik').boundingBox()
  expect(bigPhoto!.width).toBeGreaterThan(tilePhoto!.width * 1.8)
  expect(bigPhoto!.height).toBeGreaterThan(tilePhoto!.height * 1.8)
  await page.keyboard.press('Escape')
  for (const [name, role, github, email] of [
    ['Shuoxun Wen', 'Project Lead', 'https://github.com/Waldo0926', 'swen0027@student.monash.edu'],
    ['Jason Huang', 'Backend and APIs', 'https://github.com/jsonrar', 'jhua0176@student.monash.edu'],
    ['Junyan Li', 'Frontend and Interface', 'https://github.com/jlii0421', 'jlii0421@student.monash.edu'],
    ['Tai Chen', 'Cryptography', 'https://github.com/Charter888', 'tche0186@student.monash.edu'],
  ]) {
    const card = members.filter({ has: page.getByRole('heading', { name }) })
    await expect(card).toContainText(role)
    await expect(card.getByTestId('member-github')).toHaveAttribute('href', github)
    await expect(card.getByTestId('member-github')).toHaveAttribute('rel', /noopener/)
    await expect(card.getByTestId('member-email')).toHaveAttribute('href', `mailto:${email}`)
    const memberPhoto = card.getByAltText(`Portrait of ${name}`)
    await memberPhoto.scrollIntoViewIfNeeded()
    await expect
      .poll(() => memberPhoto.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0))
      .toBe(true)
  }
})

test('the team page does not scroll sideways on a phone', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 })
  await page.goto('/team')
  await expect(page.getByTestId('team-members')).toBeVisible()

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow, 'page is wider than the screen by this many pixels').toBeLessThanOrEqual(0)
})
