import { describe, expect, it } from 'vitest'
import { detectPii, redactPii } from '../lib/pii'

describe('client-side PII redaction', () => {
  it('redacts a Bangladeshi phone number', () => {
    const { text, entities } = redactPii('Call me on 01712345678 today')
    expect(text).toContain('[PHONE_1]')
    expect(text).not.toContain('01712345678')
    expect(entities[0].kind).toBe('phone')
  })

  it('redacts Bangla-digit and international numbers', () => {
    const { text } = redactPii('আমার নাম্বার ০১৭১১২২৩৩৪৪ এবং +880 1812 345678')
    expect(text).not.toContain('০১৭১১২২৩৩৪৪')
    expect(text).not.toContain('+880 1812 345678')
    expect(text.match(/\[PHONE_\d\]/g)?.length).toBe(2)
  })

  it('redacts OTP codes mentioned with a keyword', () => {
    const { entities, text } = redactPii('Your OTP is 483920, please share it')
    expect(entities.some((e) => e.kind === 'otp')).toBe(true)
    expect(text).not.toContain('483920')
  })

  it('redacts emails', () => {
    const { text } = redactPii('mail me at victim.name+spam@example.co.uk')
    expect(text).toContain('[EMAIL_1]')
  })

  it('numbers placeholders per type', () => {
    const { text } = redactPii('01712345678 or 01812345678')
    expect(text).toContain('[PHONE_1]')
    expect(text).toContain('[PHONE_2]')
  })

  it('leaves ordinary text untouched', () => {
    const clean = 'Bhai kal office e dekha hobe, 5 tay'
    expect(detectPii(clean)).toHaveLength(0)
    expect(redactPii(clean).text).toBe(clean)
  })

  it('does not treat a 4-digit PIN as a card number', () => {
    const entities = detectPii('my pin 4821 still works')
    expect(entities.some((e) => e.kind === 'card')).toBe(false)
  })
})
