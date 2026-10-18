import { describe, expect, it } from 'vitest'

import { riskyFileKind } from './risky-file'

describe('riskyFileKind', () => {
  it('flags programs and scripts, whatever the case', () => {
    expect(riskyFileKind('setup.exe')).toBe('program')
    expect(riskyFileKind('RUN.BAT')).toBe('program')
    expect(riskyFileKind('install.sh')).toBe('program')
  })

  it('judges the last extension, so a disguised program is still caught', () => {
    expect(riskyFileKind('invoice.pdf.exe')).toBe('program')
    expect(riskyFileKind('setup.exe.pdf')).toBeNull()
  })

  it('flags Office files that can carry macros, but not the macro-free formats', () => {
    expect(riskyFileKind('budget.xlsm')).toBe('macro')
    expect(riskyFileKind('report.docm')).toBe('macro')
    expect(riskyFileKind('report.docx')).toBeNull()
  })

  it('leaves ordinary documents and extensionless names alone', () => {
    expect(riskyFileKind('photo.jpg')).toBeNull()
    expect(riskyFileKind('README')).toBeNull()
  })
})
