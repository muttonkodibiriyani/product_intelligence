"""Regenerates ``fixtures/ounass_offer_content_sample.json``: 200 synthetic offers' content with
the shape of 200 real Ounass offers, for test_content_memory. No retailer text is kept.

Run from the repo root: ``uv run python packages/pi_api/tests/make_offer_content_sample.py``.
The output is fixed by ``SEED`` and ``PROFILE``.

``PROFILE`` has one line per real offer, read off the sample it replaces (taken at a fixed
stride from the Ounass snapshot the budget was calibrated on): ``description length | its
non-ASCII characters, as hex code points | sku stem length | sku suffix ("242", or the length of
another) | image stem ("=" the sku stem, else "length:characters shared with the sku stem") |
image views | upper-case NOCOLOR | ts length | has a gtin``. Each synthetic offer keeps those,
so its description has the real one's length, UTF-8 size and CPython width (1 or 2 bytes per
character), and its packed content repeats what the real one repeats: the stem across family,
sku and every image path, one ``ts`` per offer, one host and path prefix. Every real offer is
its own family with one variant, no shade and no ingredients, so there is nothing shared between
offers to keep.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

SEED = 20261007
OUT = Path(__file__).parent / "fixtures" / "ounass_offer_content_sample.json"
HOST = "https://img.example.invalid/small_light(p=zoom,of=webp,q=65)/pub/media/catalog/product"
#: Generic product-copy words, drawn with flattened Zipf weights (rank ** -0.6): at that
#: exponent the sample compresses like the real 200 (zlib 2.14x against 2.10x).
VOCABULARY = """
the a and of with to for in your on its that is this as an by from skin while each into it
formula finish colour scent notes base heart top long lasting light rich soft smooth fresh warm
creamy silky lightweight hydrating nourishing gentle bold radiant velvety matte dewy glow tone
texture blend balance touch layer hint trace accord mood ritual moment day night everyday care
cleanse protect restore refine renew enrich soothe brighten smooth define lift hold build wear
apply sweep press glide melt absorb leave reveal enhance comfort seal lock deliver offer create
oil water butter extract flower leaf root seed fruit wood musk amber cedar rose iris jasmine
vanilla citrus bergamot pepper spice leather moss vetiver sandal cocoa tea mint fig peach plum
pear berry neroli violet saffron oud tonka powder petal bloom garden forest ocean mineral clay
lip eye cheek face body hair nail brow lash hand neck shade pigment tint stain gloss balm serum
cream mist spray brush sponge stick palette compact pencil liner wand tube jar bottle cap pump
designed crafted inspired made infused enriched formulated tested loved chosen kept found
modern classic timeless iconic signature refined elegant playful natural pure clean vivid
subtle intense delicate deep bright clear sheer full fine even all new more most every
"""
WORDS = VOCABULARY.split()


def text(rng: random.Random, length: int, special: str) -> str:
    """Prose-like text of exactly ``length`` characters holding the characters of ``special``."""
    weights = [1 / (rank + 1) ** 0.6 for rank in range(len(WORDS))]
    sentences: list[str] = []
    size = 0
    while size <= length:
        words = rng.choices(WORDS, weights, k=rng.randint(7, 22))
        if rng.random() < 0.4:
            words[rng.randint(2, len(words) - 2)] += ","
        sentence = " ".join(words).capitalize() + "."
        sentences.append(sentence)
        size += len(sentence) + 1
    chars = list(" ".join(sentences)[: length - 1] + ".")
    for spot, char in zip(rng.sample(range(1, length - 1), len(special)), special, strict=True):
        chars[spot] = char
    return "".join(chars)


def digits(rng: random.Random, n: int) -> str:
    return "".join(rng.choice("0123456789") for _ in range(n))


def gtin14(rng: random.Random) -> str:
    """A GTIN-14 with a correct check digit (weights 3, 1 from the right of the body)."""
    body = "0" + digits(rng, 12)
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return body + str(-total % 10)


def offer(rng: random.Random, line: str) -> dict[str, Any]:
    length, codes, stem_len, suffix, image, views, upper, ts_len, gtin = line.split("|")
    stem = rng.choice("123456789") + digits(rng, int(stem_len) - 1)
    sku = f"{stem}_{suffix if suffix == '242' else digits(rng, int(suffix))}"
    if image == "=":
        image_stem = stem
    else:
        image_len, shared = map(int, image.split(":"))
        image_stem = stem[:shared] + digits(rng, image_len - shared)
    ts = f"{digits(rng, 10)}.{digits(rng, int(ts_len) - 11)}"
    colour = "NOCOLOR" if upper == "1" else "nocolor"
    folder = f"{image_stem[0]}/{image_stem[1]}"
    return {
        "captured": ["description", "images", "gtin"],
        "description": text(rng, int(length), "".join(chr(int(c, 16)) for c in codes.split())),
        "ingredients": None,
        "images": [
            f"{HOST}/{folder}/{image_stem}_{colour}_{view}.jpg?ts={ts}" for view in views.split()
        ],
        "variants": [{"sku": sku, "shade": None, "gtin": gtin14(rng) if gtin == "1" else None}],
        "family": sku,
    }


def sample() -> list[dict[str, Any]]:
    rng = random.Random(SEED)  # noqa: S311 - fixture data, not security
    return [offer(rng, line) for line in PROFILE.strip().splitlines()]


def main() -> None:
    OUT.write_text(json.dumps(sample(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


PROFILE = """
495|e9 2014|10|242|9:0|in fr bk cu|0|15|1
467|2019|9|242|=|in|0|15|1
196||9|242|=|in fr cu|0|15|1
392||9|242|=|in|0|15|1
255||9|4|=|in|1|15|1
277||9|242|=|in|0|15|1
377||9|242|9:4|in fr bk cu e1|0|15|1
484|2019|9|242|9:4|in|0|15|1
606||9|242|=|in|0|15|1
424|e9 e9|9|242|9:6|in|0|15|1
278||9|242|=|in fr|0|15|1
444|2013|9|3|9:7|in fr cu|0|15|1
284||9|242|=|in fr bk|0|15|1
358||9|242|=|in fr|0|13|1
360||9|242|=|in|0|15|1
452||9|5|9:8|in fr bk cu|0|14|1
328||9|242|9:7|in e1|0|15|1
245||9|3|=|in fr|1|15|1
306|2122|9|242|=|in|0|15|1
323|2122 2122|9|242|=|in|0|15|1
405|2019|9|242|=|in|0|15|1
326||9|242|=|in|1|15|1
442|2019|9|242|=|in|0|15|1
373|2019|9|242|9:7|in|0|14|1
461||9|242|=|in fr|1|14|1
226||9|242|=|in|1|15|1
369|e9|9|242|=|in fr|0|15|1
390|2019|9|2|=|in fr bk cu e1|0|15|1
327|2019 e9|9|242|=|in fr bk cu e1 e2 ou|0|15|1
250||9|242|9:7|in|0|15|1
458|2019|9|242|=|in fr bk cu e1 e2|0|15|1
322|2019|9|242|=|in fr cu pk|0|15|1
374||9|242|=|in|0|15|1
293||9|242|=|in|0|15|1
412|2013 2013|9|242|=|in|0|15|1
358|2122|9|242|=|in|0|15|1
186||9|242|=|in|0|15|1
406|2019|9|242|9:6|in e1|0|15|1
340||9|242|=|in|0|15|1
323||9|242|=|in|0|15|1
448||9|5|9:2|in fr bk|0|15|1
353||9|242|9:6|in|0|15|1
316||9|242|9:6|in e1|0|15|1
202||9|242|=|in|0|15|1
217||9|242|=|in fr|0|15|1
553|2019|9|242|=|in|0|15|1
385|2019|9|242|9:7|in fr|0|15|1
548||9|242|=|in e1 e2 pk|0|15|1
338||9|242|=|in fr bk cu|0|15|1
321||9|242|9:7|in fr|0|14|1
462|e0 e8|9|4|9:2|in fr bk cu e1 e2 pk|0|15|1
397|ae 2013|9|242|=|in|0|15|1
427||9|242|=|in e1|0|15|1
268|e9|9|242|9:6|in|0|14|1
286||9|242|=|in fr|0|15|1
355|ef ef|9|242|=|in fr|0|15|1
285||9|242|=|in fr bk e1|0|14|1
377|2122|9|242|9:7|in fr|0|15|1
617|2122 2122|9|242|9:6|in e1|0|15|1
336||9|5|9:6|in fr bk cu e1 e2|0|15|1
514|e8|9|242|=|in fr e1|0|15|1
605|2019|9|242|=|in|0|15|1
299||9|242|=|in fr bk cu e1 pk|0|15|1
279||9|242|=|in fr|0|15|0
245||9|242|9:7|in e1|0|15|1
265|f3|9|242|=|in|0|15|0
342||9|2|9:8|in fr bk cu pk|0|15|1
282||9|242|=|in|0|15|1
270||9|1|=|in fr|0|15|1
285|2019 e9|9|242|=|in|0|15|1
222||9|242|=|in|0|15|1
432||9|242|=|in fr bk cu e1 e2 pk|0|15|1
561||9|1|9:3|in|0|14|1
272|2019|9|242|=|in fr bk|0|15|1
277||9|242|9:7|in fr e1 e2 pk|0|15|1
338||9|242|9:8|in|0|15|1
255|ae|9|242|=|in fr|0|15|1
445|e9 2013 e9 e9|9|4|9:7|in fr e1 e2 pk|0|15|1
290||9|242|=|in|0|15|1
289||9|2|9:8|in fr e1|0|14|1
443||9|242|9:7|in fr e1|0|15|1
275|b7 b7|9|4|9:6|in e1|0|15|1
486|b7 b7 2013 2013 2013|9|242|=|in fr|0|15|1
719|e9 2019 2019|9|242|=|in|0|15|1
414||9|242|=|in fr|0|15|1
401||9|242|9:7|in bk|0|15|1
313||9|242|=|in|0|14|1
262||9|2|=|in|0|15|1
372|2019|9|4|9:7|in fr cu|0|15|1
398|2019 2019|9|242|9:7|in|0|15|1
393||9|242|=|in|0|15|1
439||9|242|=|in fr|0|15|1
346|f4 f4|9|242|=|in|0|15|1
482|e9|9|242|=|in fr|0|15|1
648|2019 2013 2013 2013|9|5|9:8|in cu|0|15|1
359|e9 e9|9|242|=|in|0|15|1
313|e8 e8|9|1|=|in fr bk cu e1 pk|0|15|1
327||9|242|=|in fr bk e1|0|15|1
309|2013 2013 2122|9|242|=|in pk|0|15|1
311||9|242|9:7|in fr bk cu e1 pk|0|15|1
411|b7 b7|9|1|9:6|in fr|0|15|1
710||9|242|=|in|0|15|1
308||9|242|=|in|0|15|1
634||9|242|=|in fr bk|0|15|1
441|f4 e9|9|242|9:8|in fr bk cu e1 e2 ou pk ar|0|15|1
245||9|242|=|in fr e1 e2|0|15|1
609|2019 2019|9|242|9:7|in fr|0|15|1
272|2019 2019|9|242|9:5|in|0|15|1
364||9|242|9:8|in fr bk e1 e2 pk|0|14|1
345|e9|9|5|9:3|in|0|15|1
368||9|242|=|in fr e1 e2|0|15|1
329|b7 b7 b7 b7|9|242|=|in fr bk cu e1 e2 pk|0|15|1
372|201c|9|242|9:7|in fr bk cu e1 pk|0|13|1
402|e8 e9 e8 e9|9|242|=|in fr e1 e2 pk|0|15|1
389|b2|9|5|9:6|in fr bk cu e1 e2 pk|0|15|1
313||9|242|=|in fr|0|15|1
327||9|5|9:6|in fr|0|15|1
322||9|242|9:6|in fr bk cu e1 e2 pk|0|15|1
350|2019 2019|9|242|=|in fr|0|14|1
398|e8 2122|9|242|=|in fr bk|0|15|1
434|2019 2019 e9 2019|9|242|=|in fr bk|0|15|1
321||9|242|=|in fr|0|15|1
333|2019 2019|9|242|=|in fr bk cu pk|0|15|1
412|2019|9|242|=|in fr|0|15|1
364||9|242|=|in fr bk cu|0|15|1
202|2122|9|242|9:8|in fr bk cu e1 pk|0|15|1
586||9|242|=|in fr bk cu e1 e2 pk|0|15|1
452|e9 e9 2013|9|242|9:8|in fr bk cu e1 e2 pk|0|15|1
493||9|242|=|in|0|15|1
497||9|5|9:5|in fr bk cu e1 e2|0|15|1
380|2019 2013|9|242|9:7|in fr|0|15|1
444|2019 2019 200b|9|5|=|in fr bk cu e1 e2|0|14|1
502||9|2|=|in fr bk cu e1 e2|0|14|1
851||9|242|=|in fr bk cu e1 pk|0|15|1
617||9|242|=|in|0|15|1
332|2019 2019|9|242|=|in fr bk cu e1|0|15|1
542|2013 2019|9|242|=|in|0|15|1
318|e8 e8|9|242|9:8|in fr bk cu e1 e2 ou pk ar|0|15|1
313||9|242|=|in fr bk cu|0|15|1
500|e8 e9 e8 e9|9|242|=|in fr bk cu|0|15|1
411||9|242|=|in fr|0|15|1
418||9|242|9:7|in fr bk cu e1 e2 ou pk ar|0|15|1
507|2019 2019|9|242|=|in fr|0|15|1
300|ae|9|242|=|in fr|0|15|1
320||9|242|=|in|0|14|1
489||9|242|=|in fr|0|15|1
338||9|5|9:7|in fr bk cu|0|15|1
354|2019|9|242|9:7|in fr bk cu e1 e2 ou|0|15|1
442||9|242|=|in fr|0|15|1
373||9|242|=|in fr|0|15|1
289||9|2|=|in fr bk cu|0|15|1
308|e8 2019|9|242|=|in fr bk|0|15|1
315||9|242|=|in fr bk|0|15|0
399|2013|9|242|9:6|in fr|0|15|1
190||9|242|=|in bk cu e1 e2|0|15|1
369||9|242|=|in cu|0|15|1
309|2019|9|242|=|in fr bk e1 pk|0|15|1
356||9|242|9:8|in fr|0|15|1
396||9|242|=|in|0|15|1
389||9|242|=|in|0|15|1
268|2019|9|242|9:6|in fr bk cu e1|0|15|1
547|2014 2014|9|242|=|in|0|15|1
460||9|5|9:8|in fr bk cu e1 e2 ou pk|0|15|1
367|2019|9|242|=|in fr bk cu e2|0|15|1
520|e7|9|242|9:8|in fr bk|0|15|1
301||9|5|9:2|in fr bk cu e1 e2 ou pk|0|15|1
380|2019|9|5|9:7|in fr bk cu|0|15|1
231||9|242|=|in fr|0|15|1
448|f4|9|242|=|in fr bk cu e1 e2|0|15|1
270|2013|9|242|=|in fr bk|0|15|1
376|e9|9|242|=|in fr bk|0|15|1
288||9|2|=|in fr bk cu e1 e2 ou|0|14|1
668|2122 2122|9|5|9:7|in fr bk cu|0|15|1
379||9|2|9:7|in fr bk cu e1|0|15|1
402||9|242|9:7|in fr bk cu e1 e2 ou pk ar|0|14|1
475||9|5|9:8|in fr bk cu e1|0|13|1
393|2019|9|242|9:7|in fr bk cu e1 e2 ou|0|15|1
288|2019|9|242|9:2|in fr bk cu e1 e2 pk|0|15|1
353||9|242|=|in fr bk cu e1 pk|0|15|1
96||9|242|=|in fr bk|0|15|1
459||9|242|9:7|in fr bk cu e1 e2 ou pk|0|14|1
305||9|242|9:8|in fr|0|15|1
363||9|5|9:8|in fr bk cu e1 e2 pk|0|15|1
312|2014|9|242|=|in fr bk|0|15|1
289|2019|9|242|=|in fr e1|0|15|1
260|200b|9|242|=|in fr bk cu|0|15|1
406|2014 2014|9|242|=|in bk cu e1 e2 ou pk ar|0|15|1
420||9|242|=|in fr bk|0|15|0
193|2011 2019|9|242|=|in fr bk cu|0|15|1
405||9|242|=|in fr bk cu e1 e2 ou pk|0|15|1
467||9|242|=|in fr bk cu e1 e2 ou pk|0|15|1
512||9|242|=|in fr bk cu e1 e2|0|15|1
279|2019|9|5|9:6|in fr bk cu e1 e2 ou pk ar|0|15|1
308|2019|9|242|=|in fr bk cu|0|15|1
271|2019 2019 2014|9|242|=|in|0|15|1
316||9|5|=|in fr bk cu e1 e2|0|15|1
344||9|242|9:6|in fr|0|15|1
503||9|242|=|in fr bk cu e1 e2 ou pk ar|0|15|1
325|2019|9|5|9:7|in fr bk cu e1 e2 ou|0|15|1
250|2019|9|242|9:5|in|0|15|1
"""

if __name__ == "__main__":
    main()
