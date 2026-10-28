"""Guardrails and ethics: the one place that decides when a taxpayer's words need a human.

Owner: Juee (Guardrails and ethics). Policy: data/policy.md, sections #advice, #exploitation,
#uncertainty and #scope.

Intake calls `classify_reply(text)` on every turn before it accepts an answer. The result is one of
the shared escalation reasons in src/schemas.py, or None when the reply is an ordinary answer:

    exploitation_concern          someone else may be steering the return or the refund   (brief 4.4 #6)
    advice_request                the person wants tax advice, planning or optimisation   (brief 4.4 #4)
    1099r_taxable_not_determined  a 1099-R with box 2b checked                            (brief 4.4 #3)
    out_of_scope                  income, forms or returns SilverFile does not handle     (brief 4.4 #1)
    uncertain                     the person is not sure; a volunteer should help         (brief 4.3)

Design choices (each one is tested in tests/test_guardrails.py):

* Rules are named regular expressions, not bare keywords. A bare keyword list flagged ordinary answers:
  "My 1099-R is from a Roth IRA" (in scope) looked like advice because it contains "roth", and
  "Should I type the date with dashes?" looked like advice because it starts "should I".
* Advice needs a decision word AND a tax topic ("should I ... file / claim / deduct / convert ...").
  Questions about how to answer the form are not advice; Intake simply asks again.
* Safety first: exploitation outranks everything else, because elder financial abuse often travels
  through refunds. A false alarm costs a staff member a minute; a miss can cost the client their refund.
* A third party who states a legal authority (power of attorney, guardian, conservator) is not flagged
  for answering on someone's behalf. Refund-routing warning signs are still flagged either way.
* A clear denial ("I do not have foreign income") is not a disclosure.
* The checks never calculate tax or decide eligibility. They only notice words and hand off to a human.

`explain(text)` returns the reason and the name of the rule that matched; tests and the dashboard use it.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# --- Exploitation and third-party pressure (policy.md#exploitation) ---------------------------------

_PERSON = r"(?:son|daughter|boy|girl|kids?|nephew|niece|grandson|granddaughter|grandchild|grandkid|brother|sister|cousin|" \
          r"friend|neighbou?r|caregiver|carer|aide|helper|boyfriend|girlfriend|partner|tenant|landlord|" \
          r"pastor|lawyer|accountant|banker|man|woman|guy|lady|someone|somebody|he|she|they)"

EXPLOITATION_RULES: list[tuple[str, str]] = [
    # The refund is going somewhere the taxpayer does not control or cannot describe.
    ("refund_to_someone_else",
     r"\b(?:send|put|deposit|pay|route|transfer|give|wire)\b[^.?!]{0,40}\b(?:refund|money|check)\b[^.?!]{0,40}"
     r"\b(?:his|her|their|my " + _PERSON + r"'?s?|(?:a|the) " + _PERSON + r"'?s?)\b[^.?!]{0,20}\b(?:account|card|name)\b"),
    ("refund_to_his_her_account", r"\brefund\b[^.?!]{0,30}\bto (?:his|her|their)\b"),
    ("refund_to_relative", r"\brefund\b[^.?!]{0,30}\bto my " + _PERSON + r"\b"),
    ("refund_away_from_taxpayer", r"\brefund\b[^.?!]{0,50}\b(?:instead of|rather than|not (?:to|into)) (?:his|hers|theirs|her|their|him|them)\b"),
    ("not_my_account", r"\b(?:it'?s|that'?s|this is|is)? ?not my (?:own )?(?:bank )?account\b"),
    ("unknown_account",
     r"\b(?:don'?t|do not|doesn'?t|never) (?:know|recogni[sz]e|remember)\b[^.?!]{0,30}\b(?:whose )?"
     r"(?:account|routing number|account number|bank)\b"),
    ("whose_account", r"\bwhose account\b"),
    ("account_belongs_to_other", r"\baccount (?:belongs to|is in) (?:my|his|her|their|a|the) " + _PERSON),
    ("handles_my_money", r"\bmy " + _PERSON + r"\b[^.?!]{0,30}\b(?:handles|controls|manages|takes care of|keeps|looks after|"
                         r"runs|has taken over)\b[^.?!]{0,20}\b(?:my |the |all )?(?:money|finances|bank|accounts?|checks?|refund)"),
    # Someone is telling the taxpayer what to say or do.
    ("told_what_to_say", r"\b(?:told|tells|said|says|wants|made) me (?:to say|to put|to tell you|to answer|to write|i have to|i must)\b"),
    ("said_i_have_to", r"\bsaid i (?:have|need) to\b"),
    ("not_allowed", r"\b(?:won'?t|will not|doesn'?t|does not) let me\b|\b(?:i'?m|i am) not allowed to\b"),
    ("pressure_or_threat", r"\b(?:or else|i'?ll get in trouble|threatened|scared of (?:him|her|them)|afraid of (?:him|her|them)|"
                           r"i (?:owe|promised) (?:him|her|them) the refund)\b"),
    ("scam_contact", r"\b(?:irs|someone|somebody|a man|the man|a woman|the woman|a lady)\b[^.?!]{0,25}\b(?:called|phoned|"
                     r"rang|texted|emailed)\b[^.?!]{0,60}\b(?:refund|gift cards?|pay|account|owe)\b"),
    # Someone else is answering for the taxpayer.
    ("answering_for", r"\b(?:i'?m|i am|this is)\b[^.?!]{0,20}\b(?:answering|filling (?:this|it) (?:in|out)|doing (?:this|it)|typing (?:this|it)|speaking)"
                      r" (?:for|on behalf of)\b"),
    ("doing_it_for_parent", r"\b(?:i'?m|i am) (?:doing|typing|filling in|answering)\b[^.?!]{0,20}\bfor my "
                            r"(?:mother|mom|mum|father|dad|aunt|uncle|grand\w+)\b"),
    ("on_behalf", r"\bon (?:his|her|their|my (?:mother|mom|father|dad|aunt|uncle|grand\w+)'?s?) behalf\b"),
    ("cant_come_to_phone", r"\b(?:he|she|they) (?:can'?t|cannot|isn'?t able to|is not able to) "
                           r"(?:come to the phone|talk|answer|do this)\b"),
]

# A stated legal authority means a third party is allowed to answer (policy.md#exploitation).
STATED_AUTHORITY = re.compile(
    r"\b(?:power of attorney|poa|legal guardian|guardianship|conservator|court[- ]appointed|authori[sz]ed representative)\b",
    re.I,
)
# Third-party rules that a stated authority switches off. Refund-routing rules stay on.
_AUTHORITY_EXEMPT = {"answering_for", "doing_it_for_parent", "on_behalf", "cant_come_to_phone"}

# --- Advice, planning or optimisation (policy.md#advice) ------------------------------------------

# Words that ask for a decision or a recommendation.
_DECISION = r"(?:should (?:i|we)|would (?:i|we|it)|is it (?:better|smarter|worth|wise|a good idea)|which (?:is|would be) better|" \
            r"what(?:'s| is| would be) (?:the )?best|do you (?:recommend|suggest)|would you|how should (?:i|we)|" \
            r"ought (?:i|we)|is (?:\w+ ){0,3}going to|what do you think|do (?:i|we) (?:have|need) to|" \
            r"which (?:status|one|option|way) (?:gets|gives|would)|tell me how)"
# Tax decisions SilverFile must not advise on.
_TAX_TOPIC = r"(?:file|claim|deduct|write off|itemi[sz]e|convert|roth|withdraw|take (?:out|money)|contribute|" \
             r"pay less|owe less|lower|reduce|minimi[sz]e|save|avoid|bigger refund|larger refund|biggest|least|" \
             r"more back|most back|jointly|joint|separately|separate|standard deduction|dependent|report|declare|" \
             r"hide|qcd|charit)"

ADVICE_RULES: list[tuple[str, str]] = [
    ("decision_about_tax", rf"\b{_DECISION}\b[^.?!]{{0,60}}\b{_TAX_TOPIC}"),
    ("pay_less_tax", r"\b(?:pay|owe) (?:less|lower|fewer|the least)\b"),
    ("lower_my_tax", r"\b(?:lower|reduce|cut|minimi[sz]e|save on|avoid)\b[^.?!]{0,15}\b(?:my |our |the )?(?:tax|taxes|tax bill)\b"),
    ("bigger_refund", r"\b(?:bigger|biggest|larger|largest|maximum|max|more) refund\b|\bmaximi[sz]e (?:my |our |the )?refund\b|"
                      r"\bget (?:more|the most|the most money) back\b"),
    ("can_i_deduct", r"\bcan (?:i|we) (?:deduct|write off|claim)\b"),
    ("roth_conversion", r"\b(?:convert|conversion)\b[^.?!]{0,30}\broth\b|\broth\b[^.?!]{0,20}\bconver"),
    ("tax_strategy", r"\b(?:tax (?:advice|planning|strategy|strategies|loophole)|tax[- ]efficient|optimi[sz]e)\b"),
    ("what_would_you_do", r"\bwhat would you do\b|\bif you were me\b"),
]

# --- 1099-R box 2b (policy.md#scope) --------------------------------------------------------------

R1099_2B = re.compile(
    r"taxable amount not determined|\b1099[- ]?r\b[^.?!]{0,40}\bbox\s*2b\s+(?:is\s+)?(?:checked|ticked|marked)\b|"
    r"\bbox\s*2b\b[^.?!]{0,30}\b1099[- ]?r\b[^.?!]{0,15}\b(?:checked|ticked|marked)\b",
    re.I,
)

# --- Out-of-scope disclosures (policy.md#scope) ---------------------------------------------------

SCOPE_RULES: list[tuple[str, str]] = [
    ("foreign", r"foreign (?:income|pension|(?:bank )?accounts?)|overseas (?:income|account)|fbar|"
                r"(?:pension|income|account|benefits?|wages|salary) (?:from|in) (?:canada|mexico|the uk|england|ireland|"
                r"germany|france|italy|india|china|japan|another country|abroad|overseas)"),
    ("digital_assets", r"digital assets?|crypto(?:currency)?|bitcoin|ethereum|nfts?\b"),
    ("self_employment", r"1099[- ]?nec|self[- ]employ(?:ed|ment)(?: income)?|business income|schedule c\b|"
                        r"freelanc\w+|side business|my own business|independent contractor|gig work|1099[- ]?k|"
                        r"(?:drive|deliver|work) for (?:uber|lyft|doordash|instacart|grubhub)|sell on (?:etsy|ebay)"),
    # "Rent out" in any form is letting property; a tenant who rents an apartment does not match.
    ("rental", r"rental (?:income|property)|schedule e\b|rent(?:s|ed|ing)? out\b|rent from (?:a|my|our)|airbnb|"
               r"rent(?:ing)? (?:the|a|an|my|our) [\w ]{0,25}\bto (?:a|an|my|some)\b"),
    ("capital_gains", r"capital gains?|schedule d\b|sold (?:some |my |our |a )?(?:stocks?|shares|house|home|property|investments?)|1099[- ]?b\b"),
    ("itemized", r"itemi[sz]ed deductions?|itemi[sz]e|schedule a\b|instead of (?:the )?standard deduction"),
    ("amended_or_prior", r"amended (?:tax )?returns?|amend my|prior[- ]year (?:tax )?returns?|"
                         r"last year'?s return|(?:20(?:1\d|2[0-4])) (?:tax )?return"),
    ("state_return", r"state (?:tax )?returns?|new york (?:state )?return"),
]
_SCOPE = re.compile(r"\b(?:" + "|".join(f"(?P<{name}>{pattern})" for name, pattern in SCOPE_RULES) + r")", re.I)
# "I do not have foreign income", "no rental income", "without any crypto"
_DENIAL = re.compile(
    r"\b(?:no|not|never|without|none of|(?:do|does|did) not|(?:don|doesn|didn)'?t|haven'?t|have not)"
    r"(?: \w+){0,3}\s*$",
    re.I,
)

# --- Honest uncertainty (policy.md#uncertainty) ---------------------------------------------------

UNCERTAIN = re.compile(
    r"\b(?:not sure|unsure|(?:i )?(?:don'?t|do not) know|no idea|can'?t remember|cannot remember|"
    r"don'?t remember|do not remember|can'?t recall|don'?t recall|not certain|(?:i'?m|i am) confused|don'?t understand|do not understand|no clue)\b",
    re.I,
)

# --- Public API -----------------------------------------------------------------------------------


class Match(NamedTuple):
    reason: str | None
    rule: str | None


_EXPLOITATION = [(name, re.compile(p, re.I)) for name, p in EXPLOITATION_RULES]
_ADVICE = [(name, re.compile(p, re.I)) for name, p in ADVICE_RULES]


def _normalise(text: object) -> str:
    # Curly quotes from phones and word processors would otherwise defeat "don't".
    return str(text).replace("’", "'").replace("‘", "'").strip()


def scope_disclosure(text: object) -> str | None:
    """Name of the out-of-scope topic the person says they HAVE, ignoring clear denials."""
    text = _normalise(text)
    for match in _SCOPE.finditer(text):
        clause_start = max(text.rfind(c, 0, match.start()) for c in ".;,!?")  # look back within the clause
        before = text[clause_start + 1: match.start()]
        if not _DENIAL.search(before):
            return match.lastgroup
    return None


def explain(text: object) -> Match:
    """Which escalation reason applies to this reply, and which named rule matched."""
    text = _normalise(text)
    authority = bool(STATED_AUTHORITY.search(text))
    for name, pattern in _EXPLOITATION:
        if authority and name in _AUTHORITY_EXEMPT:
            continue
        if pattern.search(text):
            return Match("exploitation_concern", name)
    for name, pattern in _ADVICE:
        if pattern.search(text):
            return Match("advice_request", name)
    if R1099_2B.search(text):
        return Match("1099r_taxable_not_determined", "box_2b")
    topic = scope_disclosure(text)
    if topic:
        return Match("out_of_scope", topic)
    if UNCERTAIN.search(text):
        return Match("uncertain", "not_sure")
    return Match(None, None)


def classify_reply(text: object) -> str | None:
    """The escalation reason for a taxpayer's reply, or None for an ordinary answer."""
    return explain(text).reason
