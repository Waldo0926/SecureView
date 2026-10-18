/**
 * The measured results quoted on the home page and on the sign-in pages. One list, so the numbers
 * cannot drift apart; they come from our own test runs on the live site (see the project reports).
 * The two load-test figures are from the 2026-10-09 run through the public URL
 * (docs/performance/REPORT-2026-10-09.md); update them together with docs/TESTING_SUMMARY.md.
 * The ZAP figure is the passive baseline scan of 2026-10-04, repeated on 2026-10-12 with the same
 * result (docs/security/scans-2026-10-12/README.md).
 */
export const proof = [
  { value: '0 / 7,444', label: 'downloads failed their integrity check' },
  { value: '0', label: 'server errors with 100 concurrent users on the live server' },
  { value: '0 FAIL', label: 'in an OWASP ZAP scan of this site' },
  { value: '500 MB', label: 'per file and round-tripped byte-exact in testing' },
]
