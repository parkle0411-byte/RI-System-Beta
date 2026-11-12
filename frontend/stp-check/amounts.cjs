const assert = require('assert')
;(async () => {
  const {formatStpAmount, sumStpAmounts} = await import('../src/alpha/stp.js')
  assert.equal(sumStpAmounts([0.1, 0.2001]), '0.3001')
  assert.equal(sumStpAmounts([1000.005, 0.005]), '1,000.01')
  assert.equal(formatStpAmount(0.000000000000000000001), '0.000000000000000000001')
  assert.equal(formatStpAmount(1234567.1234), '1,234,567.1234')
  console.log('STP decimal precision checks passed')
})().catch(error=>{ console.error(error); process.exit(1) })
