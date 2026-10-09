export function canSelectCandidate(job, candidate) {
  return candidate.is_target ? candidate.selectable : candidate.eligible !== false && job.state === 'AWAITING_SELECTION'
}

export function matchesCandidateFilters(candidate, filters) {
  if (filters.source_site_id || filters.source_promotion) {
    if (candidate.is_target) return false
    if (filters.source_site_id && String(candidate.site_id) !== String(filters.source_site_id)) return false
    if (filters.source_promotion && candidate.promotion !== filters.source_promotion) return false
  }
  return true
}

export function chooseCandidate(job, currentId, filters) {
  const options = [...(job.candidates || []), ...(job.target_candidate ? [job.target_candidate] : [])]
  if (job.selected_candidate_id) return job.selected_candidate_id
  // 用户手动改选后，轮询不覆盖；应用新筛选时由页面清空旧选择。
  const current = options.find(candidate => candidate.candidate_id === currentId)
  if (current && canSelectCandidate(job, current)) return currentId
  return options.find(candidate => canSelectCandidate(job, candidate) && matchesCandidateFilters(candidate, filters))?.candidate_id
}
