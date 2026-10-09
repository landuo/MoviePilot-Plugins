export function optionalLimit(value, label) {
  if (value === null || value === undefined || (typeof value === 'string' && !value.trim())) return null
  const number = Number(value)
  if (!['number', 'string'].includes(typeof value) || !Number.isSafeInteger(number) || number < 0) {
    throw new Error(`${label}请填写非负整数，留空或 0 表示不限制`)
  }
  return number === 0 ? null : number
}
