// Presentation aliases for historical entries; their stored numbers stay intact.
export function transactionNumber(value) {
  return String(value ?? '')
    .replace(/(-R\d+)-TX([123])(?=[ab]?(?:-|$))/g, '$1-T$2')
    .replace(/-CLM(\d+)(?=-P\d+-R\d+-T[12](?:-|$))/g, '-C$1')
}

export function transactionLabel(value) {
  const label = String(value ?? '')
  const prefix = 'Reversal of '
  return label.startsWith(prefix) ? prefix + transactionNumber(label.slice(prefix.length)) : label
}
