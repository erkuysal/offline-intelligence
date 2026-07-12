import { expect, test as base } from '@playwright/test'

export const test = base.extend({
  page: async ({ page }, use, testInfo) => {
    const browserErrors: string[] = []
    page.on('console', message => {
      if (message.type() === 'error') browserErrors.push(`console: ${message.text()}`)
    })
    page.on('pageerror', error => browserErrors.push(`page: ${error.message}`))
    page.on('requestfailed', request => {
      browserErrors.push(
        `network: ${request.method()} ${request.url()} (${request.failure()?.errorText ?? 'unknown'})`,
      )
    })

    await use(page)

    const allowedPatterns = testInfo.annotations
      .filter(annotation => annotation.type === 'allow-browser-error' && annotation.description)
      .map(annotation => new RegExp(annotation.description!))
    const unexpectedErrors = browserErrors.filter(
      error => !allowedPatterns.some(pattern => pattern.test(error)),
    )
    expect(unexpectedErrors, 'Unexpected browser errors or failed network requests').toEqual([])
  },
})

export { expect }
