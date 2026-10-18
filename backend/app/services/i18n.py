"""Language detection + localised template strings.

Used by the deterministic local agent (when Gemini is unavailable) and for
grammar-safe localisation of things the model should not invent (verdict labels,
action lists). The LLM path generates much richer prose in the detected language;
these templates guarantee the app still speaks the user's language with no API key.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SUPPORTED = ("bn", "en", "hi", "ur")

SCRIPT_RANGES = {
    "bn": [(0x0980, 0x09FF)],
    "hi": [(0x0900, 0x097F)],
    "ur": [(0x0600, 0x06FF), (0x0750, 0x077F)],
}

# Romanised markers (Banglish / Hinglish / Roman Urdu) so transliterated scams are
# not silently treated as pure English.
ROMAN_MARKERS = {
    "bn": ["taka", "tk", "bhai", "apa", "dada", "kemon", "korbo", "korte", "paisa", "poisa",
           "amar", "apnar", "bkash", "nagad", "jiten", "pathao", "pathan", "din", "hobe"],
    "hi": ["hai", "kya", "aap", "aapka", "paisa", "rupaye", "rupees", "karo", "kar", "bhejo",
           "jaldi", "inam", "jeeta", "ka", "ki", "mera", "nahi", "turant"],
    "ur": ["aap", "aapka", "rupay", "bhejein", "inam", "jeeta", "foran", "nahi", "mera",
           "karein", "hoga", "milay", "sab", "koi"],
}


@dataclass
class LanguageGuess:
    language: str
    confidence: float
    mixed: bool = False
    romanised_hint: str | None = None

    def to_dict(self) -> dict:
        return {
            "language": self.language,
            "confidence": round(self.confidence, 3),
            "mixed": self.mixed,
            "romanised_hint": self.romanised_hint,
        }


def detect_language(text: str) -> LanguageGuess:
    """Script-first detection with a romanised fallback. Deterministic, offline."""
    if not text or not text.strip():
        return LanguageGuess("unknown", 0.0)
    counts = {lang: 0 for lang in SUPPORTED}
    letters = 0
    for ch in text:
        if ch.isalpha():
            letters += 1
            for lang, ranges in SCRIPT_RANGES.items():
                if any(lo <= ord(ch) <= hi for lo, hi in ranges):
                    counts[lang] += 1
                    break

    best = max(counts, key=lambda k: counts[k])
    if counts[best] > 0 and letters > 0:
        share = counts[best] / letters
        # Mixed-script messages: keep the dominant script but flag it.
        non_zero = [l for l, c in counts.items() if c > 0]
        return LanguageGuess(best, min(0.99, 0.55 + share * 0.5), mixed=len(non_zero) > 1)

    lowered = text.lower()
    tokens = set(re.findall(r"[a-z']+", lowered))
    scores = {lang: len(tokens & set(words)) for lang, words in ROMAN_MARKERS.items()}
    best_roman = max(scores, key=lambda k: scores[k])
    if scores[best_roman] >= 2:
        return LanguageGuess(best_roman, 0.5, romanised_hint=best_roman)
    return LanguageGuess("en", 0.45)


# --------------------------------------------------------------------------- #
# Localised strings for the deterministic path
# --------------------------------------------------------------------------- #
VERDICT_LABEL = {
    "en": {"SAFE": "Looks safe", "SUSPICIOUS": "Be careful", "SCAM": "This is a scam"},
    "bn": {"SAFE": "নিরাপদ মনে হচ্ছে", "SUSPICIOUS": "সাবধান হোন", "SCAM": "এটি প্রতারণা"},
    "hi": {"SAFE": "सुरक्षित लगता है", "SUSPICIOUS": "सावधान रहें", "SCAM": "यह धोखा है"},
    "ur": {"SAFE": "محفوظ لگتا ہے", "SUSPICIOUS": "محتاط رہیں", "SCAM": "یہ فراڈ ہے"},
}

# Sentence terminators: Bangla and Hindi use the danda, Urdu its own full stop.
SENTENCE_END = {"en": ".", "bn": "\u0964", "hi": "\u0964", "ur": "\u06d4"}

OPENERS = {
    "en": {
        "SCAM": "This message shows clear signs of a scam",
        "SUSPICIOUS": "This message has some warning signs",
        "SAFE": "We did not find strong scam signs, but stay careful",
    },
    "bn": {
        "SCAM": "এই মেসেজে স্পষ্ট প্রতারণার লক্ষণ আছে",
        "SUSPICIOUS": "এই মেসেজে কিছু সতর্কতার লক্ষণ আছে",
        "SAFE": "শক্তিশালী প্রতারণার লক্ষণ পাওয়া যায়নি, তবে সাবধানে থাকুন",
    },
    "hi": {
        "SCAM": "इस संदेश में साफ़ धोखाधड़ी के संकेत हैं",
        "SUSPICIOUS": "इस संदेश में कुछ चेतावनी संकेत हैं",
        "SAFE": "धोखे के मजबूत संकेत नहीं मिले, फिर भी सावधान रहें",
    },
    "ur": {
        "SCAM": "اس پیغام میں فراڈ کی واضح علامات ہیں",
        "SUSPICIOUS": "اس پیغام میں کچھ خطرے کے اشارے ہیں",
        "SAFE": "فراڈ کی مضبوط علامات نہیں ملیں، پھر بھی محتاط رہیں",
    },
}

PATTERN_SENTENCE = {
    "en": "This looks like: {pattern}.",
    "bn": "এটি এমন প্রতারণার ধরন: {pattern}।",
    "hi": "यह इस तरह की ठगी लगती है: {pattern}।",
    "ur": "یہ اس قسم کا فراڈ لگتا ہے: {pattern}۔",
}

NEXT_STEP_LABEL = {
    "en": "What to do now:",
    "bn": "এখন কী করবেন:",
    "hi": "अब क्या करें:",
    "ur": "اب کیا کریں:",
}

SIGNAL_LABELS = {
    "en": {"ml": "message pattern model", "url": "link risk analysis", "pattern": "known scam playbook", "llm": "AI reasoning"},
    "bn": {"ml": "মেসেজ বিশ্লেষণ মডেল", "url": "লিংক ঝুঁকি বিশ্লেষণ", "pattern": "পরিচিত প্রতারণার ধরন", "llm": "এআই বিশ্লেষণ"},
    "hi": {"ml": "संदेश विश्लेषण मॉडल", "url": "लिंक जोखिम विश्लेषण", "pattern": "ज्ञात ठगी पैटर्न", "llm": "एआई विश्लेषण"},
    "ur": {"ml": "پیغام تجزیہ ماڈل", "url": "لنک رسک تجزیہ", "pattern": "معروف فراڈ پیٹرن", "llm": "اے آئی تجزیہ"},
}

BASE_ACTIONS = {
    "SCAM": {
        "en": ["Stop replying to this sender right now.", "Do not pay, do not share any OTP, PIN or password.",
               "Block the number or account and delete the message.",
               "If you already sent money, call your bank/MFS helpline and ask them to freeze the transaction, then report to the police cyber cell."],
        "bn": ["এই প্রেরকের সাথে যোগাযোগ বন্ধ করুন।", "কোনো টাকা দেবেন না, ওটিপি, পিন বা পাসওয়ার্ড শেয়ার করবেন না।",
               "নাম্বার বা অ্যাকাউন্ট ব্লক করে মেসেজটা ডিলিট করুন।",
               "যদি টাকা পাঠিয়ে থাকেন, সাথে সাথে ব্যাংক/বিকাশ হেল্পলাইনে কল করে লেনদেন আটকাতে বলুন, তারপর পুলিশের সাইবার সেলে জানান।"],
        "hi": ["इस भेजने वाले को जवाब देना तुरंत बंद करें।", "कोई पैसा न भेजें, ओटीपी, पिन या पासवर्ड साझा न करें।",
               "नंबर या अकाउंट ब्लॉक करें और संदेश हटा दें।",
               "अगर पैसे भेज दिए हैं, तो बैंक/मोबाइल वॉलेट हेल्पलाइन पर कॉल कर ट्रांजैक्शन रोकने को कहें, फिर साइबर सेल में शिकायत दर्ज करें।"],
        "ur": ["اس بھیجنے والے کو جواب دینا فوراً بند کریں۔", "کوئی رقم نہ بھیجیں، او ٹی پی، پن یا پاس ورڈ شیئر نہ کریں۔",
               "نمبر یا اکاؤنٹ بلاک کریں اور پیغام ڈیلیٹ کر دیں۔",
               "اگر رقم بھیج دی ہے تو بینک/موبائل والٹ ہیلپ لائن پر کال کر کے ٹرانزیکشن روکنے کو کہیں، پھر سائبر سیل میں رپورٹ کریں۔"],
    },
    "SUSPICIOUS": {
        "en": ["Do not click any link or call any number in this message.",
               "Check the sender through an official app, website or the number printed on your card.",
               "Ask a younger family member to look at it with you before you act.",
               "Save this message as evidence in case you want to report it."],
        "bn": ["মেসেজের কোনো লিংকে ক্লিক করবেন না, কোনো নাম্বারে কল করবেন না।",
               "প্রেরকের পরিচয় যাচাই করুন অফিসিয়াল অ্যাপ, ওয়েবসাইট বা কার্ডে লেখা নাম্বার দিয়ে।",
               "কিছু করার আগে পরিবারের কারো সাথে মিলে দেখে নিন।",
               "প্রমাণ হিসেবে মেসেজটা সেভ করে রাখুন, পরে রিপোর্ট করতে পারেন।"],
        "hi": ["संदेश के किसी लिंक पर क्लिक न करें, किसी नंबर पर कॉल न करें।",
               "भेजने वाले की जांच ऑफिशियल ऐप, वेबसाइट या कार्ड पर छपे नंबर से करें।",
               "कुछ करने से पहले परिवार के किसी सदस्य से साथ देखें।",
               "सबूत के तौर पर संदेश सुरक्षित रखें, बाद में शिकायत कर सकते हैं।"],
        "ur": ["پیغام کے کسی لنک پر کلک نہ کریں، کسی نمبر پر کال نہ کریں۔",
               "بھیجنے والے کی تصدیق آفیشل ایپ، ویب سائٹ یا کارڈ پر لکھے نمبر سے کریں۔",
               "کچھ کرنے سے پہلے گھر کے کسی فرد کے ساتھ دیکھیں۔",
               "ثبوت کے طور پر پیغام محفوظ رکھیں، بعد میں شکایت کر سکتے ہیں۔"],
    },
    "SAFE": {
        "en": ["Nothing urgent to do — just keep the habit of checking.", "Never share OTP, PIN or password with anyone.",
               "When in doubt, open the official app yourself instead of using links."],
        "bn": ["জরুরি কিছু করার নেই — অভ্যাস হিসেবে যাচাই চালিয়ে যান।", "ওটিপি, পিন বা পাসওয়ার্ড কখনো কাউকে দেবেন না।",
               "সন্দেহ হলে লিংক নয়, নিজে অফিসিয়াল অ্যাপ খুলুন।"],
        "hi": ["कुछ ज़रूरी नहीं है — जांच करने की आदत बनाए रखें।", "ओटीपी, पिन या पासवर्ड किसी को न बताएं।",
               "संदेह हो तो लिंक नहीं, खुद ऑफिशियल ऐप खोलें।"],
        "ur": ["کوئی فوری کام نہیں — تصدیق کی عادت جاری رکھیں۔", "او ٹی پی، پن یا پاس ورڈ کسی کو نہ بتائیں۔",
               "شک ہو تو لنک نہیں، خود آفیشل ایپ کھولیں۔"],
    },
}

CATEGORY_ACTION = {
    "credential_theft": {
        "en": "Change the password of that account from the official app and switch on two-step verification.",
        "bn": "অফিসিয়াল অ্যাপ থেকে ওই অ্যাকাউন্টের পাসওয়ার্ড বদলান এবং টু-স্টেপ ভেরিফিকেশন চালু করুন।",
        "hi": "उस अकाउंट का पासवर्ड ऑफिशियल ऐप से बदलें और टू-स्टेप वेरिफिकेशन चालू करें।",
        "ur": "اس اکاؤنٹ کا پاس ورڈ آفیشل ایپ سے تبدیل کریں اور ٹو اسٹیپ تصدیق آن کریں۔",
    },
    "remote_access": {
        "en": "If a remote-access or screen-sharing app was installed, uninstall it now and change your banking passwords.",
        "bn": "রিমোট অ্যাকসেস বা স্ক্রিন শেয়ার অ্যাপ ইনস্টল হয়ে থাকলে এখনই আনইনস্টল করুন এবং ব্যাংকিং পাসওয়ার্ড বদলান।",
        "hi": "अगर रिमोट एक्सेस या स्क्रीन शेयरिंग ऐप इंस्टॉल हुआ है, तुरंत हटाएं और बैंकिंग पासवर्ड बदलें।",
        "ur": "اگر ریموٹ رسائی یا اسکرین شیئرنگ ایپ انسٹال ہوئی ہے تو فوراً ہٹائیں اور بینکنگ پاس ورڈ تبدیل کریں۔",
    },
    "investment": {
        "en": "Verify the company on the securities regulator's licensed list before investing anything.",
        "bn": "টাকা লাগানোর আগে কোম্পানিটি সিকিউরিটিজ নিয়ন্ত্রকের অনুমোদিত তালিকায় আছে কি না দেখুন।",
        "hi": "निवेश से पहले कंपनी को सेबी/नियामक की लाइसेंस्ड सूची में जांचें।",
        "ur": "سرمایہ کاری سے پہلے کمپنی کو ریگولیٹر کی لائسنس یافتہ فہرست میں دیکھیں۔",
    },
    "blackmail": {
        "en": "You have not done anything wrong. Do not pay, save the evidence, block the sender and inform the police cyber cell.",
        "bn": "আপনি কোনো ভুল করেননি। টাকা দেবেন না, প্রমাণ রাখুন, ব্লক করুন এবং পুলিশের সাইবার সেলে জানান।",
        "hi": "आपने कोई गलती नहीं की। पैसे न दें, सबूत रखें, ब्लॉक करें और साइबर सेल को बताएं।",
        "ur": "آپ نے کوئی غلطی نہیں کی۔ پیسے نہ دیں، ثبوت رکھیں، بلاک کریں اور سائبر سیل کو بتائیں۔",
    },
    "phishing": {
        "en": "Open the official app or type the official website address yourself — never through the link.",
        "bn": "অফিসিয়াল অ্যাপ খুলুন বা নিজে ওয়েবসাইটের ঠিকানা টাইপ করুন — লিংক দিয়ে নয়।",
        "hi": "ऑफिशियल ऐप खोलें या वेबसाइट का पता खुद टाइप करें — लिंक से नहीं।",
        "ur": "آفیشل ایپ کھولیں یا ویب سائٹ کا پتہ خود ٹائپ کریں — لنک سے نہیں۔",
    },
    "advance_fee": {
        "en": "Never pay a fee to receive money, a job or a prize. Genuine offers cost nothing up front.",
        "bn": "টাকা, চাকরি বা পুরস্কার পেতে কোনো ফি দেবেন না। আসল সুযোগে আগে টাকা লাগে না।",
        "hi": "पैसा, नौकरी या इनाम पाने के लिए कोई फीस न दें। असली ऑफर में पहले पैसा नहीं लगता।",
        "ur": "رقم، نوکری یا انعام کے لیے کوئی فیس نہ دیں۔ اصلی پیشکش میں پہلے پیسے نہیں لگتے۔",
    },
    "impersonation": {
        "en": "Call the real person on their saved number before believing anything in this message.",
        "bn": "মেসেজ বিশ্বাস করার আগে আসল ব্যক্তিকে তার সেভ করা নাম্বারে কল করুন।",
        "hi": "संदेश पर भरोसा करने से पहले असली व्यक्ति को उसके सेव किए नंबर पर कॉल करें।",
        "ur": "پیغام پر یقین کرنے سے پہلے اصل فرد کو اس کے محفوظ نمبر پر کال کریں۔",
    },
    "greed": {
        "en": "If it sounds too good to be true, it is. Do not pay to claim a prize.",
        "bn": "যা সত্য হতে পারে না, সেটাই প্রতারণা। পুরস্কার নিতে টাকা দেবেন না।",
        "hi": "जो बात सच नहीं हो सकती, वही ठगी है। इनाम के लिए पैसे न दें।",
        "ur": "جو بات سچ نہ ہو سکے، وہی فراڈ ہے۔ انعام کے لیے پیسے نہ دیں۔",
    },
    "authority": {
        "en": "No real police or customs officer asks for money on a call or a link. Verify at the nearest station.",
        "bn": "আসল পুলিশ বা কাস্টম অফিসার ফোনে বা লিংকে টাকা চায় না। নিকটস্থ থানায় যাচাই করুন।",
        "hi": "असली पुलिस या कस्टम अफसर कॉल या लिंक पर पैसे नहीं मांगते। नज़दीकी थाने में जांचें।",
        "ur": "اصل پولیس یا کسٹم افسر کال یا لنک پر پیسے نہیں مانگتے۔ قریبی تھانے میں تصدیق کریں۔",
    },
}

FAMILY_ALERT = {
    "en": "⚠️ Scam alert from ScamLens: someone is sending messages like \"{preview}\". Please do not click any link, do not share OTP/PIN, and never pay to receive a prize. If you already replied, tell me right away.",
    "bn": "⚠️ ScamLens সতর্কবার্তা: এখন এমন মেসেজ ঘুরছে — \"{preview}\"। অনুগ্রহ করে কোনো লিংকে ক্লিক করবেন না, ওটিপি/পিন কারো সাথে শেয়ার করবেন না, আর পুরস্কার পেতে টাকা দেবেন না। যদি উত্তর দিয়ে থাকেন, সাথে সাথে আমাকে জানান।",
    "hi": "⚠️ ScamLens चेतावनी: ऐसे संदेश भेजे जा रहे हैं — \"{preview}\"। कृपया किसी लिंक पर क्लिक न करें, ओटीपी/पिन साझा न करें, और इनाम पाने के लिए पैसे न भेजें। अगर आपने जवाब दिया है, मुझे तुरंत बताएं।",
    "ur": "⚠️ ScamLens انتباہ: ایسے پیغامات بھیجے جا رہے ہیں — \"{preview}\"۔ براہ کرم کسی لنک پر کلک نہ کریں، او ٹی پی/پن شیئر نہ کریں، اور انعام کے لیے پیسے نہ بھیجیں۔ اگر آپ نے جواب دیا ہے تو فوراً مجھے بتائیں۔",
}

LESSON_LABELS = {
    "en": {
        "title": "60-second lesson", "learn": "What you will learn",
        "flags": "Red flags to remember", "quiz": "Quick check",
        "tip": "Golden rule",
    },
    "bn": {
        "title": "৬০ সেকেন্ডের পাঠ", "learn": "যা শিখবেন",
        "flags": "মনে রাখার লক্ষণ", "quiz": "দ্রুত যাচাই",
        "tip": "সোনার নিয়ম",
    },
    "hi": {
        "title": "60 सेकंड का पाठ", "learn": "आप क्या सीखेंगे",
        "flags": "याद रखने योग्य संकेत", "quiz": "छोटा सवाल",
        "tip": "सुनहरा नियम",
    },
    "ur": {
        "title": "60 سیکنڈ کا سبق", "learn": "آپ کیا سیکھیں گے",
        "flags": "یاد رکھنے کے اشارے", "quiz": "چھوٹا سوال",
        "tip": "سنہری اصول",
    },
}

PII_BADGE = {
    "en": "PII protected — phone numbers, OTPs and account numbers were hidden before the AI saw them.",
    "bn": "তথ্য সুরক্ষিত — ফোন নাম্বার, ওটিপি ও অ্যাকাউন্ট নাম্বার এআই দেখার আগেই মুছে দেওয়া হয়েছে।",
    "hi": "जानकारी सुरक्षित — फोन नंबर, ओटीपी और अकाउंट नंबर एआई के देखने से पहले छिपा दिए गए।",
    "ur": "معلومات محفوظ — فون نمبر، او ٹی پی اور اکاؤنٹ نمبر اے آئی کے دیکھنے سے پہلے چھپا دیے گئے۔",
}

LOCKED_PATTERNS_NOTE = {
    "en": "Pattern details are shown in English when the AI assistant is offline.",
    "bn": "এআই সহকারী অফলাইন থাকলে প্রতারণার বিস্তারিত ইংরেজিতে দেখানো হয়।",
    "hi": "एआई सहायक ऑफलाइन होने पर पैटर्न विवरण अंग्रेज़ी में दिखाया जाता है।",
    "ur": "اے آئی اسسٹنٹ آف لائن ہونے پر پیٹرن کی تفصیل انگریزی میں دکھائی جاتی ہے۔",
}


def text(mapping: dict, lang: str, *keys: str, default: str = "") -> str:
    """Look up a localised string in either shape used across this module.

    * ``{key: {lang: value}}``  -> text(BASE_ACTIONS-like, "bn", "SCAM")
    * ``{lang: {key: value}}``  -> text(OPENERS, "bn", "SCAM")
    * ``{lang: value}``         -> text(PATTERN_SENTENCE, "bn")

    Written after a real bug: OPENERS and LESSON_LABELS are keyed by language first, and the
    old `pick()` call returned "" for them, so every explanation silently lost its opening
    sentence and offline lessons had empty labels. English is the fallback everywhere.
    """
    lang = lang if lang in SUPPORTED else "en"

    def walk(node, ks):
        for k in ks:
            if not isinstance(node, dict):
                return None
            node = node.get(k)
        return node

    for order in ((*keys,), (lang, *keys), (lang,), ("en", *keys), ("en",)):
        if not order:
            continue
        node = walk(mapping, order)
        if isinstance(node, str):
            return node
        if isinstance(node, dict):
            value = node.get(lang) or node.get("en")
            if isinstance(value, str):
                return value
    return default


def pick(mapping: dict, lang: str, key: str | None = None, default: str = "") -> str:
    """Pick a localised string.

    Supports both shapes used in this module:
      * {lang: value}                     -> pick(OPENERS["SCAM"], "bn")
      * {key: {lang: value}}              -> pick(LESSON_LABELS, "bn", "title")
      * {key: {verdict: {lang: value}}}   -> pick(BASE_ACTIONS, "bn", "SCAM") -> list
    """
    lang = lang if lang in SUPPORTED else "en"
    node = mapping if key is None else mapping.get(key, {})
    if isinstance(node, dict):
        if lang in node:
            return node[lang]
        if "en" in node:
            return node["en"]
        # one more level (e.g. BASE_ACTIONS[verdict][lang] already unwrapped above)
        for value in node.values():
            if isinstance(value, dict) and lang in value:
                return value[lang]
        return default if default else (next(iter(node.values()), "") if node else "")
    return node if isinstance(node, str) else default


def fmt(template, **kwargs) -> str:
    """Safe .format that never raises on unexpected braces in user text."""
    if not isinstance(template, str):
        return str(template)
    try:
        return template.format(**kwargs)
    except Exception:
        return template


URL_SENTENCE = {
    "en": "The link inside it scores {score}% on our link-risk check.",
    "bn": "এর ভেতরের লিংকটির ঝুঁকি {score}%।",
    "hi": "इसमें दिए लिंक का जोखिम {score}% है।",
    "ur": "اس میں دیے گئے لنک کا خطرہ {score}% ہے۔",
}

ML_SENTENCE = {
    "en": "Our message model scored it {score}%.",
    "bn": "আমাদের মেসেজ মডেলের স্কোর {score}%।",
    "hi": "हमारे संदेश मॉडल का स्कोर {score}% है।",
    "ur": "ہمارے پیغام ماڈل کا سکور {score}% ہے۔",
}

REPORT_PREFIX = {
    "en": "Report it: ",
    "bn": "রিপোর্ট করুন: ",
    "hi": "रिपोर्ट करें: ",
    "ur": "رپورٹ کریں: ",
}
