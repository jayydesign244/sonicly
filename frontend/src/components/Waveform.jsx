function generateBars(seed, count) {
  const bars = []
  let s = Math.abs(seed) || 42
  for (let i = 0; i < count; i++) {
    s = (s * 1103515245 + 12345) & 0x7fffffff
    const envelope = Math.pow(Math.sin((i / count) * Math.PI), 0.6)
    const noise = (s % 1000) / 1000
    // Add a secondary wave for more organic look
    const secondary = Math.abs(Math.sin(i * 0.4 + seed * 0.1)) * 0.3
    const h = Math.max(0.05, (noise * 0.6 + secondary + 0.1) * envelope)
    bars.push(Math.min(h, 0.95))
  }
  return bars
}

export default function Waveform({
  seed = 42,
  color = '#6366f1',
  ghostColor = '#e5e7eb',
  height = 56,
  bars = 72,
  showGhost = false,
  muted = false,
  className = '',
}) {
  const barData = generateBars(seed, bars)
  const barW = 3
  const gap = 2
  const totalW = bars * (barW + gap)

  return (
    <div className={`w-full overflow-hidden ${className}`} style={{ height }}>
      <svg
        width="100%"
        height={height}
        viewBox={`0 0 ${totalW} ${height}`}
        preserveAspectRatio="none"
      >
        {barData.map((h, i) => {
          const barH = Math.max(4, h * height)
          const x = i * (barW + gap)
          const y = (height - barH) / 2
          return (
            <g key={i}>
              {showGhost && (
                <rect
                  x={x}
                  y={(height - Math.max(4, barData[i] * height * 0.7)) / 2}
                  width={barW}
                  height={Math.max(4, barData[i] * height * 0.7)}
                  fill={ghostColor}
                  rx={barW / 2}
                  opacity={0.5}
                />
              )}
              <rect
                x={x}
                y={y}
                width={barW}
                height={barH}
                fill={muted ? ghostColor : color}
                rx={barW / 2}
                opacity={muted ? 0.6 : 1}
              />
            </g>
          )
        })}
      </svg>
    </div>
  )
}
