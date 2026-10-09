export const stateValues = {
  MATCHING: ['匹配中', 'info'],
  SOURCE_SUBMITTING: ['下载提交待确认', 'warning'],
  WAITING_SOURCE_RETRY: ['等待来源重试', 'warning'],
  FAILED_MATCHING: ['匹配重试已停止', 'error'],
  AWAITING_SELECTION: ['等待选择', 'warning'],
  SOURCE_DOWNLOADING: ['来源下载中', 'primary'],
  TARGET_DOWNLOADING: ['原种下载中', 'primary'],
  WAITING_CAPACITY: ['等待下载名额', 'warning'],
  WAITING_IYUU: ['等待 IYUU', 'info'],
  WAITING_IYUU_RETRY: ['等待 IYUU 重试', 'warning'],
  TARGET_RECHECKING: ['目标种校验中', 'info'],
  TARGET_SEEDING: ['保种成功', 'success'],
  TARGET_COMPLETE: ['数据完整待做种', 'info'],
  TARGET_PAUSED: ['目标种已暂停', 'warning'],
  TARGET_ERROR: ['目标种异常', 'error'],
  SKIPPED_NO_IYUU_MATCH: ['无跨站匹配', 'secondary'],
  SKIPPED_NO_HEALTHY_SOURCE: ['无符合筛选来源', 'secondary'],
  FAILED_TARGET_TORRENT: ['目标种失败', 'error'],
  FAILED_SOURCE_DOWNLOAD: ['来源下载失败', 'error'],
  IGNORED: ['已忽略', 'secondary'],
}

export function normalizeFilters(filters) {
  const result = {}
  for (const key of ['state', 'promotion', 'source_promotion', 'source_site_id']) {
    const value = String(filters[key] ?? '').trim()
    if (value) result[key] = value
  }
  for (const key of ['min_seeders', 'max_seeders']) {
    const value = filters[key]
    if (value === null || value === undefined || (typeof value === 'string' && !value.trim())) continue
    const number = Number(value)
    if (!['number', 'string'].includes(typeof value) || !Number.isSafeInteger(number) || number < 0) {
      throw new Error('做种人数请填写非负整数，留空表示不限')
    }
    result[key] = number
  }
  if (result.min_seeders !== undefined && result.max_seeders !== undefined && result.min_seeders > result.max_seeders) {
    throw new Error('最低做种人数不能大于最高做种人数')
  }
  return result
}

export function statusQuery(view, page, pageSize, filters) {
  return new URLSearchParams({ view, page, page_size: pageSize, ...filters }).toString()
}
