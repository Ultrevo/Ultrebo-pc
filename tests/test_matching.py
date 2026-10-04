# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
import cv2

from conftest import with_pattern
from ultrebo.imagematch import TemplateCache, find_template, to_gray
from ultrebo.ocr import group_into_lines, split_line
from ultrebo.textmatch import OcrWord, find, normalize, similarity


def test_finds_pattern_at_the_right_place(blank, pattern):
    frame = with_pattern(blank, pattern, x=200, y=120)
    match = find_template(to_gray(frame), to_gray(pattern), 0.8)
    assert match is not None
    assert abs(match.x - (200 + 30)) <= 2 and abs(match.y - (120 + 20)) <= 2


def test_no_match_when_pattern_absent(blank, pattern):
    assert find_template(to_gray(blank), to_gray(pattern), 0.8) is None


def test_template_larger_than_frame_is_not_a_crash(pattern):
    small = to_gray(pattern)[:10, :10]
    assert find_template(small, to_gray(pattern), 0.5) is None


def test_small_templates_match_at_full_size(blank):
    patch = blank[50:70, 60:80].copy()
    frame = blank.copy()
    match = find_template(to_gray(frame), to_gray(patch), 0.9)
    assert match is not None and abs(match.x - 70) <= 2 and abs(match.y - 60) <= 2


def test_template_cache_loads_and_reloads(tmp_path, pattern):
    cache = TemplateCache(tmp_path)
    assert cache.load("missing.png") is None
    cv2.imwrite(str(tmp_path / "p.png"), pattern)
    first = cache.load("p.png")
    assert first is not None and first.shape == pattern.shape[:2]
    assert cache.load("p.png") is first


def word(text, left, top=100, right=None, bottom=140):
    return OcrWord(text, left, top, right if right is not None else left + 60, bottom)


SCREEN = [
    [word("Wave", 10), word("12", 80)],
    [word("Are", 300), word("you", 370), word("still", 440), word("there?", 510)],
    [word("I'm", 300, 400, 360, 440), word("here", 370, 400, 430, 440)],
]


def test_text_found_and_centred():
    m = find(SCREEN, "I'm here", 0.85)
    assert m is not None and (m.x, m.y) == ((300 + 430) // 2, (400 + 440) // 2)


def test_text_ignores_case_punctuation_spacing():
    assert find(SCREEN, "IM HERE", 0.9) is not None
    assert find(SCREEN, "are you still there", 0.9) is not None


def test_text_tolerates_small_misreads():
    misread = [[word("I'm", 0), word("hera", 70)]]
    assert find(misread, "I'm here", 0.8) is not None
    assert find(misread, "I'm here", 0.95) is None


def test_text_missing_or_blank():
    assert find(SCREEN, "game over", 0.85) is None
    assert find(SCREEN, "   ", 0.5) is None
    assert find([], "wave", 0.5) is None


def test_text_split_and_joined_words_still_match():
    assert find([[word("I'mhere", 0)]], "I'm here", 0.9) is not None
    assert find([[word("I'm", 0), word("he", 70), word("re", 100)]], "I'm here", 0.9) is not None


def test_normalize_and_similarity():
    assert normalize("I'm  Here!") == "imhere"
    assert similarity("abc", "abc") == 1.0 and similarity("", "") == 1.0
    assert 0.6 < similarity("imhere", "imhera") < 0.9


def test_split_line_estimates_word_boxes():
    words = split_line("I'm here", 100, 50, 260, 90)
    assert [w.text for w in words] == ["I'm", "here"]
    assert words[0].left == 100 and words[1].right == 260 and words[0].right <= words[1].left


def test_boxes_side_by_side_are_joined_into_one_line():
    boxes = [("here", 299, 78, 473, 149), ("I'm", 171, 80, 289, 140)]
    [line] = group_into_lines(boxes)
    assert [w.text for w in line] == ["I'm", "here"]
    assert find([line], "I'm here", 0.85) is not None


def test_distant_or_stacked_boxes_stay_separate():
    far = [("Wave", 10, 10, 90, 40), ("Score", 900, 12, 980, 42)]
    assert len(group_into_lines(far)) == 2
    stacked = [("Press", 100, 100, 200, 130), ("here", 100, 150, 180, 180)]
    assert len(group_into_lines(stacked)) == 2
