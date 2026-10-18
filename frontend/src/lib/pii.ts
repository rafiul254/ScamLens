/**
 * Client-side PII redaction.
 *
 * ScamLens redacts in two places on purpose:
 *   1. here, in the browser, so a phone number or OTP never leaves the device, and
 *   2. on the server, defensively, before the text reaches the LLM.
 *
 * It mirrors backend/app/services/pii.py: same categories, same placeholder
 * format ([PHONE_1]), and it normalises Bangla/Devanagari/Urdu numerals first.
 */

const DIGIT_MAP: Record<string, string> = {}
const digitSets = [
  [0x0660, 0x0669],
  [0x06f0, 0x06f9],
  [0x0966, 0x096f],
  [0x09e6, 0x09ef],
  [0x0a66, 0x0a6f],
  [0x0be6, 0x0bef],
]
for (const [start, end] of digitSets) {
  for (let i = 0; i < 10; i++) DIGIT_MAP[String.fromCodePoint(start + i)] = String(i)
}

export function normalizeDigits(text: string): string {
  let out = ''
  for (const ch of text) out += DIGIT_MAP[ch] ?? ch
  return out
}

export type PiiKind = 'phone' | 'email' | 'otp' | 'card' | 'account' | 'nid' | 'password'

export interface PiiEntity {
  kind: PiiKind
  value: string
  start: number
  end: number
  placeholder: string
  masked: string
}

const PHONE = /(?<![\d])(\+\s?\d{1,3}[\s.-]?\d{2,5}[\s.-]?\d{3,5}(?:[\s.-]?\d{2,4})?|0\d{2}[\s.-]?\d{6,8}|0\d{9,10}|03\d{2}[\s.-]?\d{7})(?![\d])/g
const EMAIL = /(?<![\w.])([\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{2,63}){1,3})/g
const OTP = /(?:otp|o\.t\.p|one[\s-]?time[\s-]?(?:password|code|pin)|verification code|security code|login code|code is|pin code|একবার|ওটিপি|পিন|কোড|ओटीपी|कोड|पिन|او\s?ٹی\s?پی|کوڈ|پن)[^0-9]{0,24}(?:is|:|hain|hai|হলো|है|ہے)?[^0-9]{0,8}(\d{4,8})(?![\d])/gi
const NID = /(?:nid|national id|aadhaar|aadhar|আইডি|এনআইডি|आधार|شناختی کارڈ)[^0-9]{0,16}(\d{10,17})(?![\d])/gi
const PASSWORD = /(?:password|passcode|pin|পাসওয়ার্ড|পিন|पासवर्ड|पिन|پاس\s?ورڈ)[\s:=\u2014-]{0,4}(?:is\s+)?([0-9A-Za-z@#$%!]{4,20})(?![0-9A-Za-z])/gi
const CARD = /(?<![\d])((?:\d[ -]?){13,19})(?![\d])/g
const ACCOUNT = /(?<![\d])(\d{8,18})(?![\d])/g

function luhn(digits: string): boolean {
  let sum = 0
  let alt = false
  for (let i = digits.length - 1; i >= 0; i--) {
    let d = Number(digits[i])
    if (alt) {
      d *= 2
      if (d > 9) d -= 9
    }
    sum += d
    alt = !alt
  }
  return sum % 10 === 0
}

function mask(value: string): string {
  if (value.length <= 4) return '*'.repeat(value.length)
  return `${value.slice(0, 2)}${'*'.repeat(Math.max(0, value.length - 4))}${value.slice(-2)}`
}

export function detectPii(input: string): PiiEntity[] {
  const norm = normalizeDigits(input)
  const found: Array<{ kind: PiiKind; value: string; start: number; end: number }> = []

  const collect = (re: RegExp, kind: PiiKind, group = 1) => {
    re.lastIndex = 0
    let m: RegExpExecArray | null
    while ((m = re.exec(norm)) !== null) {
      if (!m[group]) continue
      const start = m.index + m[0].indexOf(m[group])
      found.push({ kind, value: m[group], start, end: start + m[group].length })
    }
  }

  collect(EMAIL, 'email')
  collect(CARD, 'card')
  collect(OTP, 'otp')
  collect(NID, 'nid')
  collect(PASSWORD, 'password')
  collect(PHONE, 'phone')
  collect(ACCOUNT, 'account')

  const priority: Record<PiiKind, number> = { card: 0, otp: 1, nid: 2, email: 3, password: 4, phone: 5, account: 6 }
  found.sort((a, b) => a.start - b.start || priority[a.kind] - priority[b.kind] || b.end - b.start)

  const kept: typeof found = []
  let lastEnd = -1
  for (const ent of found) {
    if (ent.start >= lastEnd) {
      if (ent.kind === 'card' && !luhn(ent.value.replace(/\D/g, ''))) continue
      kept.push(ent)
      lastEnd = ent.end
    }
  }

  const counters: Record<string, number> = {}
  const label: Record<PiiKind, string> = {
    phone: 'PHONE', email: 'EMAIL', otp: 'OTP', card: 'CARD', account: 'ACCOUNT', nid: 'NID', password: 'PASSWORD',
  }
  return kept.map((e) => {
    counters[e.kind] = (counters[e.kind] ?? 0) + 1
    return { ...e, placeholder: `[${label[e.kind]}_${counters[e.kind]}]`, masked: mask(e.value) }
  })
}

export interface RedactionResult {
  text: string
  entities: PiiEntity[]
}

export function redactPii(input: string): RedactionResult {
  const entities = detectPii(input)
  let cursor = 0
  let out = ''
  for (const e of entities) {
    out += input.slice(cursor, e.start) + e.placeholder
    cursor = e.end
  }
  out += input.slice(cursor)
  return { text: out, entities }
}

export const PII_BADGE_TEXT: Record<string, string> = {
  en: 'PII protected — phone numbers, OTPs and account numbers were hidden before the AI saw them.',
  bn: 'তথ্য সুরক্ষিত — ফোন নাম্বার, ওটিপি ও অ্যাকাউন্ট নাম্বার এআই দেখার আগেই মুছে দেওয়া হয়েছে।',
  hi: 'जानकारी सुरक्षित — फोन नंबर, ओटीपी और अकाउंट नंबर एआई के देखने से पहले छिपा दिए गए।',
  ur: 'معلومات محفوظ — فون نمبر، او ٹی پی اور اکاؤنٹ نمبر اے آئی کے دیکھنے سے پہلے چھپا دیے گئے۔',
}
