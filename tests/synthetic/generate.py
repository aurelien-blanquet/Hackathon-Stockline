"""Synthetic benchmark generator. Owned by Pod C (test runner).

    python -m tests.synthetic.generate               # 15 curated messy calls -> cases.jsonl
    python -m tests.synthetic.generate --random 50   # + 50 templated calls (volume / regression)
    python -m tests.synthetic.generate --asr-noise   # also apply phonetic ASR confusions

Each case = transcript (as an ASR would output it) + ground truth in SELL units.
expected_sku may be "A|B" when either is acceptable (with the expected alert).
Expected quantities are compared with a 10% tolerance (weight estimates).
After 19:15: replace / extend with cases built from Stockline's real data (CLAUDE.md §7).
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

HERE = Path(__file__).parent
CALL_DATE = "2026-11-23"   # Monday — "mardi dernier" = 2026-11-17

SEED_CASES = [
    dict(id="c01_simple", customer_id="C001", features=["baseline", "units"],
         transcript="Bonjour c'est Karim du Bistrot du Marché. Alors pour demain il me faut douze kilos de tomates grappe, cinq bottes de persil plat et deux colis de courgettes. Merci.",
         expected=[("FL-TOM-GRP", 12), ("FL-PER-PLA", 5), ("FL-COU-VER", 10)], alerts=[]),
    dict(id="c02_correction", customer_id="C003", features=["mid_sentence_correction"],
         transcript="Oui bonjour Brasserie des Halles. Mets-moi trois sacs de patates, euh non pardon deux sacs, et vingt kilos d'oignons jaunes.",
         expected=[("FL-POM-TER", 50), ("FL-OIG-JAU", 20)], alerts=[]),
    dict(id="c03_phonetic_fish", customer_id="C001", features=["asr_error", "phonetic"],
         transcript="Alors du poisson. Il me faut six kilos de barre de ligne, et trois kilos de lieux jaunes en filet.",
         expected=[("MR-BAR-LIG", 6), ("MR-LIE-JAU", 3)], alerts=[]),
    dict(id="c04_faux_filet_asr", customer_id="C001", features=["asr_error", "phonetic"],
         transcript="Pour la viande huit kilos de faut filet et cinq kilos de bavette.",
         expected=[("VI-FAU-FIL", 8), ("VI-BAV", 5)], alerts=[]),
    dict(id="c05_history_plus", customer_id="C002", features=["history_reference", "increment", "out_of_stock"],
         transcript="Salut c'est Marco. Tu me mets comme mardi dernier, pareil, mais rajoute deux bottes de basilic en plus.",
         expected=[("CR-MOZ", 48), ("FL-TOM-CER", 24), ("FL-BAS", 12), ("EP-HUI-OLI", 2), ("EP-FAR", 2)],
         alerts=["HISTORY_USED", "OUT_OF_STOCK"]),
    dict(id="c06_conditional", customer_id="C003", features=["conditional", "generic_product_name"],
         transcript="Deux caisses de tomates si elles sont belles, sinon laisse tomber, et vingt-quatre salades batavia.",
         expected=[("FL-TOM-RON", 14), ("FL-SAL-BAT", 24)], alerts=["CONDITIONAL_LINE"]),
    dict(id="c07_unknown_sku", customer_id="C001", features=["unknown_sku"],
         transcript="Et puis tu m'mets quatre kilos de topinambours et deux kilos de champignons de Paris.",
         expected=[(None, 4), ("FL-CHA", 2)], alerts=["UNKNOWN_SKU"]),
    dict(id="c08_out_of_stock", customer_id="C002", features=["out_of_stock", "substitution", "slang"],
         transcript="Trois colis de mozza di bufala et un plateau de tomates cerises.",
         expected=[("CR-MOZ", 36), ("FL-TOM-CER", 12)], alerts=["OUT_OF_STOCK"]),
    dict(id="c09_noise_interruption", customer_id="C003", features=["background_noise", "interruption", "restatement"],
         transcript="[bruit chambre froide] Allô ? Ouais alors note, cinq kilos de cabillaud... attends Momo pose ça dans la chambre froide... oui pardon, cinq kilos de cabillaud et huit poulets fermiers.",
         expected=[("MR-CAB-DOS", 5), ("VI-POU-FER", 8)], alerts=[]),
    dict(id="c10_quantity_anomaly", customer_id="C003", features=["quantity_anomaly"],
         transcript="Il me faut cinquante kilos d'entrecôte et quatre plateaux d'oeufs.",
         expected=[("VI-ENT", 50), ("CR-OEU", 4)], alerts=["QUANTITY_ANOMALY"]),
    dict(id="c11_fractions", customer_id="C001", features=["fractions", "number_words"],
         transcript="Un kilo et demi d'échalotes, trois bottes de ciboulette et un demi colis de citrons.",
         expected=[("FL-ECH", 1.5), ("FL-CIB", 3), ("FL-CIT-JAU", 2.5)], alerts=[]),
    dict(id="c12_usual_minus", customer_id="C002", features=["history_reference", "removal"],
         transcript="Comme d'habitude mais enlève l'huile d'olive cette fois.",
         expected=[("CR-MOZ", 36), ("FL-TOM-CER", 24), ("FL-BAS", 8), ("EP-FAR", 1)],
         alerts=["HISTORY_USED", "OUT_OF_STOCK"]),
    dict(id="c13_pieces_to_kg", customer_id="C001", features=["variable_weight", "piece_to_kg"],
         transcript="Deux bars de ligne entiers et dix pavés de saumon.",
         expected=[("MR-BAR-LIG", 2.4), ("MR-SAU-PAV", 1.5)], alerts=["WEIGHT_ESTIMATE"]),
    dict(id="c14_price_question_pronoun", customer_id="C003", features=["price_question", "pronoun_en"],
         transcript="C'est combien le dos de cabillaud en ce moment ? Bon mets m'en trois kilos. Et vingt kilos de patates.",
         expected=[("MR-CAB-DOS", 3), ("FL-POM-TER", 20)], alerts=["PRICE_REQUEST"]),
    dict(id="c15_palette_ambiguous", customer_id="C003", features=["quantity_anomaly", "ambiguous_sku", "product_before_qty"],
         transcript="Mets-moi une palette de pommes de terre, et des poivrons, deux colis.",
         expected=[("FL-POM-TER", 1000), ("FL-POI-ROU|FL-POI-JAU", 10)], alerts=["QUANTITY_ANOMALY", "AMBIGUOUS_SKU"]),
]

# ───────── templated generator for volume ─────────
OPENERS = ["Allô oui bonjour", "Salut c'est moi", "Oui c'est pour la commande", "Bonjour, alors",
           "[bruit hotte cuisine] Allô ?", "Ouais bonjour, vite fait"]
CLOSERS = ["Merci, à demain.", "C'est tout.", "Voilà, bonne nuit.", "Ah et livre avant six heures stp."]
NUM_FR = {1: "un", 2: "deux", 3: "trois", 4: "quatre", 5: "cinq", 6: "six", 8: "huit", 10: "dix", 12: "douze", 20: "vingt"}
TEMPLATES = [  # (sku, spoken unit word, unit factor -> sell unit, product phrase)
    ("FL-TOM-GRP", "cagettes", 6, "tomates grappe"), ("FL-COU-VER", "kilos", 1, "courgettes"),
    ("FL-PER-PLA", "bottes", 1, "persil"), ("FL-CAR", "sacs", 10, "carottes"),
    ("MR-SAU-PAV", "kilos", 1, "saumon"), ("VI-BAV", "kilos", 1, "bavette"),
    ("CR-CRE-35", "colis", 6, "crème liquide"), ("CR-BEU-DOU", "colis", 40, "beurre"),
    ("FL-AVO", "plateaux", 20, "avocats"), ("FL-OIG-JAU", "filets", 5, "oignons"),
]


def random_case(i: int, rng: random.Random) -> dict:
    picks = rng.sample(TEMPLATES, k=rng.randint(2, 4))
    parts, expected = [], []
    for sku, unit, f, phrase in picks:
        q = rng.choice(list(NUM_FR))
        de = "d'" if phrase[0] in "aeiouéè" else "de "
        parts.append(f"{NUM_FR[q]} {unit} {de}{phrase}")
        expected.append((sku, q * f))
    body = ", ".join(parts[:-1]) + " et " + parts[-1]
    return dict(id=f"r{i:03d}", customer_id=rng.choice(["C001", "C002", "C003"]), features=["templated"],
                transcript=f"{rng.choice(OPENERS)}. Il me faut {body}. {rng.choice(CLOSERS)}",
                expected=expected, alerts=[])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--random", type=int, default=0)
    ap.add_argument("--asr-noise", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=str(HERE / "cases.jsonl"))
    a = ap.parse_args()
    rng = random.Random(a.seed)
    cases = list(SEED_CASES) + [random_case(i, rng) for i in range(a.random)]
    if a.asr_noise:
        from pod_a_voice.stt import add_asr_noise
        cases = [{**c, "transcript": add_asr_noise(c["transcript"], 0.5, a.seed + n)} for n, c in enumerate(cases)]
    with open(a.out, "w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps({**c, "call_date": CALL_DATE,
                                "expected": [{"sku": s, "qty": q} for s, q in c["expected"]]},
                               ensure_ascii=False) + "\n")
    print(f"wrote {len(cases)} cases -> {a.out}")


if __name__ == "__main__":
    main()
