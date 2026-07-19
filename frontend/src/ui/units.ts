// Unit code → symbol, from VDI/VDE/NAMUR 2658 Blatt 3 Table 10 ("frequently used
// units"). The Unit channel is an INT enumeration (§7.6); the full list lives in the
// external reference [1], but Table 10 covers the common ones. Unknown codes fall back
// to the raw number so nothing is invented.

const UNIT_SYMBOLS: Record<number, string> = {
  1000: 'K',
  1001: '°C',
  1002: '°F',
  1005: '°',
  1006: "'",
  1007: "''",
  1010: 'm',
  1013: 'mm',
  1018: 'ft',
  1023: 'm²',
  1038: 'ℓ',
  1041: 'hl',
  1054: 's',
  1058: 'min',
  1059: 'h',
  1060: 'd',
  1061: 'm/s',
  1077: 'Hz',
  1081: 'kHz',
  1082: '1/s',
  1083: '1/min',
  1088: 'kg',
  1092: 't',
  1100: 'g/cm³',
  1105: 'g/ℓ',
  1120: 'N',
  1123: 'mN',
  1130: 'Pa',
  1133: 'kPa',
  1137: 'bar',
  1138: 'mbar',
  1149: 'mmH₂O',
  1175: 'W·h',
  1179: 'kW·h',
  1181: 'kcal',
  1190: 'kW',
  1209: 'A',
  1211: 'mA',
  1221: 'A·h',
  1240: 'V',
  1342: '%',
  1349: 'm³/h',
  1353: 'ℓ/h',
  1384: 'mol',
  1422: 'pH',
}

// The code 0xFF / 0 conventions and unmapped codes: return null so the UI shows no unit
// rather than a wrong one. `1342` (%) etc. resolve to their symbol.
export function unitSymbol(code: number | undefined): string | null {
  if (code === undefined || code === 0) return null
  return UNIT_SYMBOLS[code] ?? `#${code}`
}
