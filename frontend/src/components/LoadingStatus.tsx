type LoadingStatusProps = { label: string }

export function LoadingStatus({ label }: LoadingStatusProps) {
  return (
    <span className="loading-status" role="status" aria-live="polite">
      <span className="loading-status__spinner" aria-hidden="true" />
      <span>{label}</span>
    </span>
  )
}
